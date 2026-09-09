"""Pull the latest month of ONC mooring temperature and score every hour of it
against the day-of-year climatology.

Companion to `onc_climatology.py`, which builds the climatology from the archived
downloads, and to `check_latest.py`, which scores a handful of hand-entered spot
readings. The difference here is the shape of the comparison: this pulls a whole
recent window straight from the ONC API, so what gets scored is a curve against
an envelope rather than one point against a band. The scoring itself is
`onc_climatology.classify_series`, unchanged -- nothing about the statistics is
re-implemented here.

    python latest_month.py                       # last 30 days, every ONC site
    python latest_month.py --site node --days 14
    python latest_month.py --offline             # no API: score the archive tail

The API token is read from $ONC_TOKEN, falling back to ~/.onc_token. It is never
printed, logged, or written into any output file.

La Perouse Bank is deliberately absent. It is a DFO/MEDS buoy, not an ONC
station, so it has no ONC location code and cannot be fetched through this API
at all; it stays archive-only until a live source for it is found.

Authors: Dwight Owens and Claude (Anthropic)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

from onc_climatology import (
    GOOD_FLAGS, build_climatology, classify_series, discover_sites, load_series,
    site_label,
)

HERE = Path(__file__).parent
CLIM_DIR = HERE / "climatology"
LOCATION_CACHE = HERE / "onc_locations.json"

# ONC separates the two: `seawatertemperature` is the *property* code, shared by
# every instrument that measures it, while the *sensor category* code is whatever
# that particular device calls the channel ("temperature"). The property is what
# identifies the measurement; the sensor category is what the data call wants.
PROPERTY = "seawatertemperature"
# Several device categories at one location can carry the property (a turbidity
# meter and an oxygen sensor both report their own temperature). CTD is the one
# the archives -- and so the climatology -- were built from, so it is preferred
# and the rest are a fallback rather than a coin toss on dict order.
PREFERRED_CATEGORIES = ("CTD",)
# The climatology is built on hourly averages, so the live pull is resampled to
# the same 1 h basis. Comparing raw sub-minute scalars against an hourly-derived
# sd would inflate every z-score.
RESAMPLE_SECONDS = 3600
MATCH_TOLERANCE_KM = 2.0

# DFO/MEDS buoy, not an ONC station -- see the module docstring.
NOT_ON_ONC = {"laperusebank"}


# --------------------------------------------------------------------------
# Token
# --------------------------------------------------------------------------

def read_token() -> str:
    """The ONC API token, from the environment or ~/.onc_token.

    Deliberately never echoed: callers get the string, and nothing in this
    module puts it into stdout, a figure, or a written file.
    """
    token = os.environ.get("ONC_TOKEN", "").strip()
    if token:
        return token
    path = Path.home() / ".onc_token"
    if path.is_file():
        token = path.read_text().strip()
        if token:
            return token
    raise SystemExit(
        "No ONC API token found.\n"
        "Set ONC_TOKEN, or write the token to ~/.onc_token without it entering\n"
        "your shell history:\n\n"
        "    read -s -p 'ONC token: ' T && printf '%s' \"$T\" > ~/.onc_token \\\n"
        "        && chmod 600 ~/.onc_token && unset T\n"
    )


def client():
    from onc import ONC
    return ONC(read_token())


# --------------------------------------------------------------------------
# Station metadata, read out of the archived files
# --------------------------------------------------------------------------

def station_meta(path: Path) -> dict:
    """Coordinates, depth and (for CSV exports) the ONC station code.

    The two export formats carry different things. The CSV preamble has
    `STNCODE`, which *is* the ONC location code, so those sites need no lookup
    at all. The NetCDF files carry `station_lat`/`station_lon` but no code, so
    those are resolved against the API's own location list by position.
    """
    path = Path(path)
    if path.suffix == ".nc":
        import xarray as xr

        with xr.open_dataset(path) as ds:
            first = lambda v: float(str(v).split(",")[0]) if v not in (None, "") else float("nan")
            return {
                "lat": float(ds.attrs.get("station_lat", "nan")),
                "lon": float(ds.attrs.get("station_lon", "nan")),
                "depth": first(ds.attrs.get("station_depth", "nan").rstrip("m")),
                "code": None,
                "devcat_name": None,
            }

    fields = {}
    with open(path) as fh:
        for line in fh:
            if line.startswith("## END HEADER"):
                break
            if not line.startswith("#") or ":" not in line:
                continue
            key, _, rest = line[1:].partition(":")
            fields[key.strip()] = rest.split("  /")[0].strip().strip('"')
    return {
        "lat": float(fields.get("LATITUDE", "nan")),
        "lon": float(fields.get("LONGITUDE", "nan")),
        "depth": float(fields.get("DEPTH", "nan")),
        "code": fields.get("STNCODE") or None,
        "devcat_name": fields.get("DEVCAT") or None,
    }


def _km_apart(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance, for matching a station against ONC's location list."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# Resolving each site to an ONC locationCode + deviceCategoryCode
# --------------------------------------------------------------------------

def _load_cache() -> dict:
    if LOCATION_CACHE.is_file():
        return json.loads(LOCATION_CACHE.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    LOCATION_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


def resolve_site_location(key: str, path: Path, onc, cache: dict) -> dict:
    """Map a site key to {'locationCode', 'deviceCategoryCode'}, and cache it.

    Nothing here is hardcoded: the station code comes from the file's own
    preamble where there is one, and otherwise from a position match against
    ONC's location list. The device category is whichever one at that location
    actually reports a seawatertemperature sensor -- it is CTD at the canyon
    moorings but not everywhere, so it is asked for rather than assumed.
    """
    if key in cache and "sensorCategoryCode" in cache[key]:
        return cache[key]

    meta = station_meta(path)
    code = meta["code"]

    if code is None:
        if not (np.isfinite(meta["lat"]) and np.isfinite(meta["lon"])):
            raise SystemExit(f"{key}: no station code and no coordinates in {path.name}")
        candidates = onc.getLocations({"deviceCategoryCode": "CTD"}) or []
        scored = [
            (_km_apart(meta["lat"], meta["lon"], c["lat"], c["lon"]), c)
            for c in candidates
            if c.get("lat") is not None and c.get("lon") is not None
        ]
        if not scored:
            raise SystemExit(f"{key}: ONC returned no locations to match against")
        distance, best = min(scored, key=lambda t: t[0])
        if distance > MATCH_TOLERANCE_KM:
            raise SystemExit(
                f"{key}: nearest ONC location {best['locationCode']} is {distance:.1f} km "
                f"from the archived station position; refusing to guess"
            )
        code = best["locationCode"]

    # Ask the location which device categories it has, and keep the first that
    # genuinely offers the temperature sensor.
    def property_sensor(cat_code):
        """The sensor category at `cat_code` carrying the property, if any."""
        sensors = onc.getSensorCategoryCodes({
            "locationCode": code, "deviceCategoryCode": cat_code,
        }) or []
        for s in sensors:
            if s.get("propertyCode") == PROPERTY:
                return s["sensorCategoryCode"]
        return None

    available = [c["deviceCategoryCode"]
                 for c in onc.getDeviceCategories({"locationCode": code}) or []]
    # Try the preferred categories first and stop at the first hit, rather than
    # interrogating every instrument at the location. Besides being fewer calls,
    # it avoids provoking access warnings from categories we will never use --
    # CCIP's hydrophone data is restricted, and asking about it prints a notice
    # about a dataset this tool has no interest in.
    found = None
    for cat_code in list(PREFERRED_CATEGORIES) + sorted(set(available) - set(PREFERRED_CATEGORIES)):
        if cat_code not in available:
            continue
        sensor_cat = property_sensor(cat_code)
        if sensor_cat:
            found = (cat_code, sensor_cat)
            break
    if found is None:
        raise SystemExit(f"{key}: no device category at {code} reports {PROPERTY}")
    devcat, sensor_cat = found

    cache[key] = {"locationCode": code, "deviceCategoryCode": devcat,
                  "sensorCategoryCode": sensor_cat}
    _save_cache(cache)
    return cache[key]


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def fetch_series(key: str, path: Path, days: int, onc, cache: dict,
                 end: pd.Timestamp | None = None) -> pd.Series:
    """The last `days` of hourly temperature for one site, from the ONC API.

    Returns a tz-naive UTC series to match what `onc_climatology.load_series`
    produces from the archives -- the two are compared directly downstream, and
    a tz-aware index would not align with the climatology's day-of-year index.
    """
    where = resolve_site_location(key, path, onc, cache)
    end = pd.Timestamp.utcnow().tz_localize(None) if end is None else pd.Timestamp(end)
    start = end - pd.Timedelta(days=days)

    result = onc.getScalardataByLocation({
        "locationCode": where["locationCode"],
        "deviceCategoryCode": where["deviceCategoryCode"],
        "sensorCategoryCodes": where["sensorCategoryCode"],
        "dateFrom": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "dateTo": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "resamplePeriod": RESAMPLE_SECONDS,
        "rowLimit": 100_000,
    })

    sensors = (result or {}).get("sensorData") or []
    if not sensors:
        return _empty_series(key, where)

    data = sensors[0]["data"]
    series = pd.Series(
        np.asarray(data["values"], dtype=float),
        index=pd.to_datetime(data["sampleTimes"], format="ISO8601", utc=True).tz_localize(None),
    )
    # Same QAQC treatment the climatology was built under, so like is compared
    # with like: keep only good/probably-good/averaged, drop the rest as gaps.
    flags = data.get("qaqcFlags")
    if flags is not None:
        series = series.where(pd.Series(flags, index=series.index).isin(GOOD_FLAGS))
    series = series.dropna().sort_index()
    series.name = "temperature"
    series.index.name = "time"
    series.attrs.update(source="ONC API", **where)
    return series


def _empty_series(key: str, where: dict) -> pd.Series:
    s = pd.Series(dtype=float, index=pd.DatetimeIndex([], name="time"))
    s.name = "temperature"
    s.attrs.update(source="ONC API", **where)
    return s


def archive_tail(path: Path, days: int) -> pd.Series:
    """The last `days` of the archived record -- the offline stand-in for a fetch.

    Lets the whole scoring and plotting path be exercised without a token. The
    archives lag real time by days to weeks, so this is a structural check, not
    a current one.
    """
    obs = load_series(path=path)
    if obs.empty:
        return obs
    tail = obs[obs.index > obs.index[-1] - pd.Timedelta(days=days)]
    tail.attrs.update(obs.attrs)
    tail.attrs["source"] = f"archive tail ({path.name})"
    return tail


# --------------------------------------------------------------------------
# Climatology
# --------------------------------------------------------------------------

def load_climatology(key: str, path: Path) -> pd.DataFrame:
    """The prebuilt day-of-year table if there is one, else build it.

    Reading the CSV takes milliseconds; rebuilding from the archive takes tens
    of seconds per site, because it pools every observation within +/- 7 days
    across the whole record.
    """
    csv = CLIM_DIR / f"{key}_climatology.csv"
    if csv.is_file():
        clim = pd.read_csv(csv).set_index("yearday")
        clim.attrs["source"] = csv.name
        return clim
    clim = build_climatology(load_series(path=path))
    clim.attrs["source"] = "rebuilt from archive"
    return clim


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def score_site(key: str, path: Path, series: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Score a fetched window and reduce it to one summary row."""
    obs = load_series(path=path)
    label = site_label(obs)
    clim = load_climatology(key, path)

    if series.empty:
        empty = pd.DataFrame(
            columns=["temperature", "yearday", "clim_mean", "clim_sd",
                     "anomaly", "z", "band", "label"],
            index=pd.DatetimeIndex([], name="time"),
        ).astype(float)
        return empty, {
            "site": label, "key": key, "depth": obs.attrs.get("depth"),
            "n": 0,
            "mean_temp": float("nan"), "mean_z": float("nan"),
            "max_abs_z": float("nan"),
            "pct_outside_1sd": float("nan"), "pct_outside_2sd": float("nan"),
            # the archive still knows when this site last said anything, which is
            # the number that tells an outage from a fetch bug
            "archived_last": float(obs.iloc[-1]),
            "archived_time": obs.index[-1],
            "source": series.attrs.get("source", ""),
            "verdict": "no data returned",
        }

    scored = classify_series(clim, series)
    usable = scored[np.isfinite(scored["z"])]
    summary = {
        "site": label,
        "key": key,
        "depth": obs.attrs.get("depth"),
        "n": int(len(usable)),
        "first": series.index[0],
        "last": series.index[-1],
        "mean_temp": float(series.mean()),
        "mean_z": float(usable["z"].mean()) if len(usable) else float("nan"),
        "max_abs_z": float(usable["z"].abs().max()) if len(usable) else float("nan"),
        "pct_outside_1sd": float((usable["band"] >= 1).mean() * 100) if len(usable) else float("nan"),
        "pct_outside_2sd": float((usable["band"] == 2).mean() * 100) if len(usable) else float("nan"),
        # the archive's own last value, so a stale or mismatched feed is visible
        "archived_last": float(obs.iloc[-1]),
        "archived_time": obs.index[-1],
        "source": series.attrs.get("source", ""),
    }
    summary["verdict"] = _verdict(summary["mean_z"], summary["pct_outside_1sd"])
    return scored, summary


def _verdict(mean_z: float, pct_outside: float) -> str:
    """A window-level label, deliberately coarser than the per-point one.

    A single hour beyond 2 sd is noise; a month that spends most of its time
    outside 1 sd is not. This keys off the sustained behaviour of the window
    rather than its worst point.
    """
    if not np.isfinite(mean_z):
        return "no climatology"
    warm = "warm" if mean_z > 0 else "cool"
    if abs(mean_z) > 2:
        return f"extreme {warm} anomaly"
    if abs(mean_z) > 1:
        return f"unusually {warm}"
    if pct_outside > 50:
        return f"mixed, over half outside 1 sd"
    return "normal"


def run(keys=None, days: int = 30, offline: bool = False,
        end=None) -> tuple[dict, pd.DataFrame]:
    """Fetch (or read) and score every site. Returns per-site frames + summary."""
    sites = {k: v for k, v in discover_sites().items() if k not in NOT_ON_ONC}
    if keys:
        sites = {k: v for k, v in sites.items() if k in keys}
    if not sites:
        raise SystemExit("no matching sites")

    onc, cache = (None, {}) if offline else (client(), _load_cache())

    frames, rows = {}, []
    for key, path in sites.items():
        series = (archive_tail(path, days) if offline
                  else fetch_series(key, path, days, onc, cache, end=end))
        scored, summary = score_site(key, path, series)
        frames[key] = scored
        rows.append(summary)

    summary = pd.DataFrame(rows).sort_values("depth", na_position="first")
    return frames, summary


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------

# Same palette as check_latest.py, so the two sets of figures read as one family.
BAND_2, BAND_1 = "#cde2fb", "#9ec5f4"
MEAN_C, OBS_C, FLAG_C = "#184f95", "#2a78d6", "#eb6834"
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"


def _style(ax, fig):
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9)


def _finish(fig, out_path):
    """Write the figure and return its path, or hand back the live figure.

    The CLI wants files on disk; the marimo app wants the figure object to
    render inline. Same drawing code either way. The output format follows the
    path's own suffix, so `.svg` and `.png` both work with no other change.
    """
    import matplotlib.pyplot as plt

    if out_path is None:
        return fig
    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


# Matplotlib names its clip paths and glyph definitions per figure, and those
# names are not unique between figures. Several inline SVGs on one page will
# then resolve each other's `url(#...)` references -- in practice a panel picks
# up a neighbour's clip rectangle and loses half its content. Namespacing every
# id per figure is what makes multiple vector figures on a page safe.
_SVG_ID = re.compile(r'id="([^"]+)"')


def as_svg(fig, responsive: bool = True, close: bool = True) -> str:
    """A matplotlib figure as inline SVG markup, safe to place beside others.

    Vector rather than raster because these panels are read closely -- a lag
    scan is a dozen points and a fitted curve, and it should stay sharp when
    the reader zooms. It is also about half the bytes of the equivalent PNG.
    """
    import hashlib
    import io

    import matplotlib.pyplot as plt

    buf = io.StringIO()
    fig.savefig(buf, format="svg", facecolor=fig.get_facecolor())
    if close:
        plt.close(fig)
    svg = buf.getvalue()

    # Drop the XML prolog and any doctype: this is being embedded in an HTML
    # document, not served as a standalone file.
    svg = svg[svg.index("<svg"):]

    prefix = "f" + hashlib.sha1(svg.encode()).hexdigest()[:8] + "-"
    ids = set(_SVG_ID.findall(svg))
    for name in sorted(ids, key=len, reverse=True):
        new = prefix + name
        svg = (svg.replace(f'id="{name}"', f'id="{new}"')
                  .replace(f'url(#{name})', f'url(#{new})')
                  .replace(f'xlink:href="#{name}"', f'xlink:href="#{new}"')
                  .replace(f'href="#{name}"', f'href="#{new}"'))

    if responsive:
        # matplotlib writes an absolute pt width/height alongside a viewBox.
        # Removing the former and letting the latter drive lets the figure
        # scale to the column it lands in.
        svg = re.sub(r'(<svg[^>]*?)\swidth="[^"]*"', r"\1", svg, count=1)
        svg = re.sub(r'(<svg[^>]*?)\sheight="[^"]*"', r"\1", svg, count=1)
        svg = svg.replace("<svg ", '<svg style="width:100%;height:auto" ', 1)
    return svg


def plot_site(key: str, label: str, scored: pd.DataFrame,
              out_path: Path | None = None):
    """The fetched window drawn on top of its own day-of-year envelope.

    The bands are the climatology evaluated at each timestamp's day of year, so
    they slope with the season rather than sitting flat across the window.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if scored.empty:
        return None

    t = scored.index
    obs = scored["temperature"]
    mean, sd = scored["clim_mean"], scored["clim_sd"]
    hi1, lo1 = mean + sd, mean - sd
    hi2, lo2 = mean + 2 * sd, mean - 2 * sd

    fig, ax = plt.subplots(figsize=(11, 4.6), constrained_layout=True)
    _style(ax, fig)

    ax.fill_between(t, lo2, hi2, color=BAND_2, lw=0, label="climatology +/- 2 sd")
    ax.fill_between(t, lo1, hi1, color=BAND_1, lw=0, label="climatology +/- 1 sd")
    ax.plot(t, mean, color=MEAN_C, lw=1.4, label="climatology mean")
    ax.plot(t, obs, color=OBS_C, lw=1.6, label="observed")

    # Sustained excursions are drawn as filled area rather than a marker per
    # hour. At a site that sits outside the band for most of the month -- Upper
    # Slope spends ~70% of it there -- per-point markers cover the very line
    # they are annotating, and the eye reads dot density instead of distance.
    ax.fill_between(t, hi1, obs, where=obs > hi1, color=FLAG_C, alpha=0.55,
                    lw=0, interpolate=True, label="outside 1 sd")
    ax.fill_between(t, lo1, obs, where=obs < lo1, color=FLAG_C, alpha=0.55,
                    lw=0, interpolate=True)

    last = scored.iloc[-1]
    ax.annotate(f"{last['temperature']:.2f} C  ({last['z']:+.2f} sd)",
                xy=(t[-1], last["temperature"]), xytext=(6, 0),
                textcoords="offset points", va="center", fontsize=9,
                color=INK_2, annotation_clip=False)
    # room on the right for that label, which sits outside the last data point
    ax.set_xlim(t[0], t[-1] + (t[-1] - t[0]) * 0.11)

    ax.set_ylabel("Temperature (C)", color=INK_2)
    ax.set_title(f"{label}\nlatest window against its own day-of-year climatology",
                 color=INK, fontsize=12.5, loc="left", pad=38)
    # above the axes, not inside them: the data fills the upper left at the
    # warm sites and an inset legend lands on top of it
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=5,
              frameon=False, fontsize=9, labelcolor=INK_2,
              columnspacing=1.4, handlelength=1.6)
    fig.autofmt_xdate()
    return _finish(fig, out_path)


def plot_summary(summary: pd.DataFrame, out_path: Path | None = None):
    """Cross-site strip: mean anomaly per site, with the window's full range.

    check_latest.py draws one point per site because it scores one reading per
    site. Here each site has a whole window, so the mean sits on a bar showing
    how far the window travelled -- a site can average normal and still have
    spent hours outside 2 sd.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = summary[summary["n"] > 0].sort_values("depth", ascending=False, na_position="last")
    df = df.reset_index(drop=True)
    if df.empty:
        return None
    y = np.arange(len(df))

    fig, ax = plt.subplots(figsize=(11, 0.82 * len(df) + 2.4), constrained_layout=True)
    _style(ax, fig)
    ax.grid(True, axis="y", lw=0)

    ax.axvspan(-2, 2, color=BAND_2, lw=0)
    ax.axvspan(-1, 1, color=BAND_1, lw=0)
    ax.axvline(0, color=MEAN_C, lw=1.4)

    lo, hi = float(df["min_z"].min()), float(df["max_z"].max())
    # every label starts at the same x, so the numbers form a column instead of
    # stepping in and out with each site's range
    label_x = max(hi, 2.0) + 0.25

    texts = []
    for i, row in df.iterrows():
        colour = OBS_C if abs(row["mean_z"]) <= 1 else FLAG_C
        ax.plot([row["min_z"], row["max_z"]], [i, i], color=colour, lw=2,
                solid_capstyle="round", alpha=0.45, zorder=3)
        ax.plot(row["mean_z"], i, "o", ms=11, color=colour, mec=SURFACE, mew=2, zorder=4)
        texts.append(ax.text(
            label_x, i,
            f"{row['mean_temp']:.2f} C   mean {row['mean_z']:+.2f} sd   "
            f"{row['pct_outside_1sd']:.0f}% outside 1 sd",
            va="center", ha="left", fontsize=9, color=INK_2))

    ax.set_yticks(y, list(df["site"]), fontsize=10)
    ax.set_ylim(-0.7, len(df) - 0.3)
    ax.set_xlabel("Anomaly from the day-of-year climatology (standard deviations)",
                  color=INK_2)

    left = min(-2.4, lo - 0.5)
    # ticks stop where the data stops; the space to their right is the label
    # column, and gridlines running through it imply a range that has no data
    ax.set_xticks(np.arange(np.ceil(left), np.floor(max(hi, 2.0)) + 1, 1.0))
    ax.set_xlim(left, label_x + 1.0)
    # The labels are placed in data coordinates but their width is fixed in
    # pixels, so the right limit that clears them can only be found by drawing
    # and measuring. Two passes converge; a fixed pad guesses wrong whenever the
    # site names or the anomalies change length.
    for _ in range(3):
        fig.canvas.draw()
        inv = ax.transData.inverted()
        right = max(inv.transform((t.get_window_extent().x1, 0))[0] for t in texts)
        ax.set_xlim(left, right + 0.25)

    # A live pull ends at the same instant everywhere, but the offline path ends
    # at each archive's own last record, and those differ by weeks. Saying "X to
    # Y" across sites would then describe a window no site actually has.
    ragged = (df["last"].max() - df["last"].min()) > pd.Timedelta("2D")
    span = (f"per-site windows, ending {df['last'].min():%Y-%m-%d} "
            f"to {df['last'].max():%Y-%m-%d}" if ragged
            else f"{df['first'].min():%Y-%m-%d} to {df['last'].max():%Y-%m-%d}")
    ax.set_title(
        "Latest window vs day-of-year climatology, ONC Barkley moorings\n"
        f"{span}\n"
        "dot is the window mean, bar its full range",
        color=INK, fontsize=12.5, loc="left", pad=10)
    return _finish(fig, out_path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--site", action="append", help="site key; repeatable (default: all)")
    p.add_argument("--days", type=int, default=30, help="window length (default 30)")
    p.add_argument("--offline", action="store_true",
                   help="skip the API and score the tail of the archived files")
    p.add_argument("--outdir", type=Path, default=CLIM_DIR / "latest_month")
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("--format", choices=("svg", "png"), default="svg",
                   help="figure format (default svg: vector, and about half the "
                        "bytes of the equivalent png)")
    args = p.parse_args(argv)

    frames, summary = run(keys=args.site, days=args.days, offline=args.offline)

    # range columns the summary plot needs, derived here so `run` stays plot-free
    for col, fn in (("min_z", "min"), ("max_z", "max")):
        summary[col] = [
            getattr(frames[k]["z"].dropna(), fn)()
            if "z" in frames[k] and frames[k]["z"].notna().any() else np.nan
            for k in summary["key"]
        ]

    cols = ["site", "n", "mean_temp", "mean_z", "max_abs_z",
            "pct_outside_1sd", "pct_outside_2sd", "verdict"]
    print(summary[cols].round(2).to_string(index=False))

    args.outdir.mkdir(parents=True, exist_ok=True)
    # round only the numeric columns; .round() on the timestamp columns warns
    numeric = summary.select_dtypes("number").columns
    summary.astype({c: float for c in numeric}).round({c: 4 for c in numeric}).to_csv(
        args.outdir / "latest_month_summary.csv", index=False)
    for key, scored in frames.items():
        if not scored.empty:
            scored.round(4).to_csv(args.outdir / f"{key}_latest_month.csv")

    if not args.no_plots:
        plot_summary(summary, args.outdir / f"latest_month_summary.{args.format}")
        for _, row in summary.iterrows():
            plot_site(row["key"], row["site"], frames[row["key"]],
                      args.outdir / f"{row['key']}_latest_month.{args.format}")
    print(f"\nwritten  {args.outdir}/")

    # A live feed that disagrees with the archive usually means the archive has
    # not caught up, but it can also mean the wrong sensor or depth was resolved.
    stale = summary[(summary["n"] > 0) &
                    (summary["last"] - summary["archived_time"] > pd.Timedelta("2D"))]
    if len(stale) and not args.offline:
        print("\nfetched data is newer than the archived file (expected for a live pull):")
        for _, r in stale.iterrows():
            print(f"  {r['site']:<32} live to {r['last']:%Y-%m-%d %H:%M}"
                  f"  vs archive {r['archived_time']:%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()
