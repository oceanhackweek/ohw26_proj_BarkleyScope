"""Day-of-year temperature climatologies for the ONC Barkley Sound / Barkley Canyon moorings.

Builds a seasonal (day-of-year) climatology from an hourly-averaged
SeaWaterTemperature record, then scores a new measurement against it:

    within 1 sigma  -> normal
    1-2 sigma       -> unusually warm / unusually cool
    beyond 2 sigma  -> extreme warm / extreme cool

The climatology for each day of year is pooled from a centred +/- WINDOW_DAYS
window across every year in the record, so each estimate rests on thousands of
hourly values from ~10 years instead of the handful a single calendar day offers.

Sites are discovered from the ONC data products under `data/folger` and
`data/barkley`; station name and depth are read out of each file's own metadata.

Usage as a script:

    python folger_climatology.py --list                    # what sites are available
    python folger_climatology.py --site pinnacle           # build + report
    python folger_climatology.py --site axis --check 2026-08-26T22:00 3.65
    python folger_climatology.py --all --outdir climatology/

Usage as a library:

    from folger_climatology import load_series, build_climatology, classify
    obs  = load_series("upperslope")
    clim = build_climatology(obs)
    classify(clim, "2026-08-26T19:00", 6.05, obs=obs)
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Data locations
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRS = [REPO_ROOT / "data" / "folger", REPO_ROOT / "data" / "barkley",
             REPO_ROOT / "data" / "buoys"]

WINDOW_DAYS = 7      # +/- days pooled into each day-of-year estimate
MIN_YEARS = 3        # a day-of-year needs this many contributing years
SMOOTH_DAYS = 5      # light circular smoothing applied to mean and sd curves
PERCENTILES = (5, 10, 25, 50, 75, 90, 95)

# ONC qaqcFlags: 0=no QC, 1=pass, 2=probably good, 3=probably bad,
# 4=bad, 7=averaged value, 8=interpolated, 9=missing.
GOOD_FLAGS = (1, 2, 7)

# QC for the DFO/MEDS moored-buoy exports, which arrive as raw sub-hourly
# records. Their Q_FLAG column cannot be trusted -- at La Peruse Bank, flag 1
# ("appears correct") covers values from -33 to +79 C while flag 4
# ("erroneous") covers a perfectly ordinary 7.3-18.6 C -- so the flags are
# ignored and the series is screened on the values themselves instead:
#   1. a gross plausibility range,
#   2. a spike test against a centred rolling median (this is what catches the
#      second, bad telemetry stream that shows up interleaved at a different
#      minute offset in 2008, 2009 and 2017),
#   3. hourly averaging, then a robust day-of-year test that removes what is
#      left: sustained excursions a local median cannot see.
BUOY_RANGE = (2.0, 25.0)          # C, gross plausibility limits
BUOY_SPIKE_WINDOW = "13h"         # centred window for the rolling median
BUOY_SPIKE_FLOOR = 1.5            # C, minimum residual before a point can be cut
BUOY_ROBUST_SDS = 5.0             # robust sds from the day-of-year median


def discover_sites(data_dirs=None) -> dict[str, Path]:
    """Map a short site key to the best available file for that station.

    ONC download names look like `<Location>_<Station>_variables_...`; the
    station part becomes the key. A .nc is preferred over a .csv for the same
    station because it carries the QAQC flags as a variable.
    """
    found: dict[str, Path] = {}
    for directory in data_dirs or DATA_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix not in (".nc", ".csv"):
                continue
            kind = _sniff(path)
            if kind is None:
                continue
            # ONC names are <Location>_<Station>_variables_...; the buoy exports
            # are <Station>_<Variable>_<years>.csv
            station = path.name.split("_")[1 if kind != "buoy" else 0]
            key = re.sub(r"[^a-z0-9]", "", station.lower())
            for prefix in ("barkleycanyon", "folgerpassage", "barkley", "folger"):
                if key.startswith(prefix) and key != prefix:
                    key = key[len(prefix):]
                    break
            if key not in found or (path.suffix == ".nc" and found[key].suffix == ".csv"):
                found[key] = path
    return found


def resolve_site(name: str, sites: dict[str, Path] | None = None) -> str:
    """Accept a site key, or any unambiguous fragment of one."""
    sites = sites or discover_sites()
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    if key in sites:
        return key
    matches = [k for k in sites if key in k]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"unknown site {name!r}; known sites: {', '.join(sorted(sites))}")
    raise SystemExit(f"ambiguous site {name!r}; matches {', '.join(sorted(matches))}")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def _sniff(path: Path) -> str | None:
    """Identify the file format: 'onc_nc', 'onc_csv', 'buoy', or None if unknown."""
    if path.suffix == ".nc":
        return "onc_nc" if "_variables_" in path.name else None
    with open(path, errors="replace") as fh:
        first = fh.readline()
    if first.startswith("##") or first.startswith("#"):
        return "onc_csv"
    if first.startswith("STN_ID"):
        return "buoy"
    return None


def _csv_header(path: Path) -> tuple[int, dict[str, str]]:
    """Return the number of lines to skip and the ONC `#KEY: value` header fields."""
    fields: dict[str, str] = {}
    with open(path, errors="replace") as fh:
        for i, line in enumerate(fh):
            if line.startswith("## END HEADER"):
                return i + 1, fields
            m = re.match(r"#([A-Z0-9]+):\s+(.*?)\s+/", line)
            if m:
                fields[m.group(1)] = m.group(2).strip().strip('"')
    raise ValueError(f"no '## END HEADER' line in {path}")


def _first_float(text) -> float:
    m = re.search(r"-?\d+(\.\d+)?", str(text))
    return float(m.group()) if m else float("nan")


def _prettify(station: str) -> str:
    """'BarkleyCanyonMid-East' / 'Barkley Canyon Axis' -> 'Barkley Canyon Mid-East'."""
    station = station.strip()
    if not station:
        return ""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", station)
    return re.sub(r"\s+", " ", spaced).strip()


def _despike(series: pd.Series, window: str, floor: float, n_sds: float) -> pd.Series:
    """Drop points that sit far from a centred rolling median of their neighbours.

    The cut is the larger of `floor` and `n_sds` robust sds, so a quiet stretch
    does not get its own noise clipped away and a genuinely variable one is not
    over-trimmed.
    """
    median = series.rolling(window, center=True, min_periods=5).median()
    resid = series - median
    mad = resid.abs().rolling(window, center=True, min_periods=5).median()
    limit = np.maximum(floor, n_sds * 1.4826 * mad)
    return series[resid.abs() <= limit]


def _drop_doy_outliers(series: pd.Series, window_days: int, n_sds: float) -> pd.Series:
    """Drop points far from the robust day-of-year centre of the whole record.

    Median and MAD rather than mean and sd, so the outliers being looked for do
    not inflate the yardstick used to find them.
    """
    yd = yearday(series.index)
    by_day = {day: grp for day, grp in pd.Series(series.to_numpy()).groupby(yd)}
    centre, scale = {}, {}
    for day in range(1, 366):
        parts = [by_day[d].to_numpy() for d in _window_days(day, window_days) if d in by_day]
        if not parts:
            continue
        vals = np.concatenate(parts)
        centre[day] = np.median(vals)
        scale[day] = 1.4826 * np.median(np.abs(vals - centre[day]))
    mid = np.array([centre.get(d, np.nan) for d in yd])
    sd = np.array([scale.get(d, np.nan) for d in yd])
    keep = ~(np.abs(series.to_numpy() - mid) > n_sds * sd)   # NaN scale -> keep
    return series[keep]


def load_buoy_series(path: Path, window_days: int = WINDOW_DAYS) -> pd.Series:
    """Read a DFO/MEDS moored-buoy CSV, screen it, and return hourly averages.

    See the BUOY_* constants for why the file's own Q_FLAG column is not used.
    """
    raw = pd.read_csv(path, usecols=["STN_ID", "DATE", "LATITUDE", "LONGITUDE",
                                     "DEPTH", "SeaWaterTemperature"])
    time = pd.to_datetime(raw["DATE"], format="%m/%d/%Y %H:%M")
    series = pd.Series(raw["SeaWaterTemperature"].to_numpy(), index=time).sort_index()
    series = series[~series.index.duplicated()]

    n_raw = len(series)
    in_range = series[series.between(*BUOY_RANGE)]
    despiked = _despike(in_range, BUOY_SPIKE_WINDOW, BUOY_SPIKE_FLOOR, BUOY_ROBUST_SDS)
    hourly = despiked.resample("1h").mean().dropna()
    clean = _drop_doy_outliers(hourly, window_days, BUOY_ROBUST_SDS)

    clean.attrs["qc"] = {
        "raw_records": n_raw,
        "out_of_range": n_raw - len(in_range),
        "spikes": len(in_range) - len(despiked),
        "hourly_bins": len(hourly),
        "day_of_year_outliers": len(hourly) - len(clean),
        "kept": len(clean),
    }
    clean.attrs["station_id"] = str(raw["STN_ID"].iloc[0])
    # DEPTH in these files is the water depth under the buoy, not a sensor
    # depth -- the temperature is a surface measurement.
    clean.attrs["water_depth"] = float(raw["DEPTH"].median())
    clean.attrs["lat"] = float(raw["LATITUDE"].median())
    clean.attrs["lon"] = -abs(float(raw["LONGITUDE"].median()))
    return clean


def load_series(site: str = "pinnacle", path: str | Path | None = None) -> pd.Series:
    """Return the hourly-averaged temperature record as a clean pandas Series.

    Bad and missing values are dropped, so the series has gaps rather than NaNs.
    Station name and depth are attached as `series.attrs`.
    """
    if path is None:
        sites = discover_sites()
        path = sites[resolve_site(site, sites)]
    path = Path(path)
    kind = _sniff(path)

    if kind == "buoy":
        temp = load_buoy_series(path)
        temp.name = "temperature"
        temp.index.name = "time"
        temp.attrs.update(
            station=_prettify(path.name.split("_")[0]),
            depth=float("nan"),      # surface measurement, not a fixed sensor depth
            surface=True,
            source=path.name,
        )
        return temp

    if path.suffix == ".nc":
        import xarray as xr

        ds = xr.open_dataset(path)
        temp = ds["seawatertemperature"].to_series()
        flags = ds.get("seawatertemperature_qaqcFlags")
        if flags is not None:
            temp = temp.where(flags.to_series().isin(GOOD_FLAGS))
        depth = _first_float(ds.attrs.get("station_depth", ""))
    else:
        # ONC CSV. Column 0 is time, 1 the (clean average) value, 2 its QC flag;
        # Min/Max+Avg products carry six more columns we do not need here.
        skip, fields = _csv_header(path)
        raw = pd.read_csv(
            path, skiprows=skip, header=None, usecols=[0, 1, 2],
            names=["time", "temperature", "flag"],
            skipinitialspace=True, na_values=["NaN"],
        )
        raw["time"] = pd.to_datetime(raw["time"], format="mixed", utc=True).dt.tz_localize(None)
        raw = raw.set_index("time")
        temp = raw["temperature"].where(raw["flag"].isin(GOOD_FLAGS))
        depth = _first_float(fields.get("DEPTH", ""))

    temp = temp.dropna().sort_index()
    temp.name = "temperature"
    temp.index.name = "time"
    # The station name comes from the filename rather than the file metadata:
    # the ONC CSV header's STNNAME is a hyphen-joined hierarchy, and station
    # names that contain a hyphen themselves (Mid-East) cannot be split out of it.
    temp.attrs.update(
        station=_prettify(path.name.split("_")[1]),
        depth=depth,
        source=path.name,
    )
    return temp


def site_label(obs: pd.Series) -> str:
    if obs.attrs.get("surface"):
        station_id = obs.attrs.get("station_id")
        return f"{obs.attrs['station']}{f' ({station_id})' if station_id else ''}, sea surface"
    depth = obs.attrs.get("depth")
    if depth and np.isfinite(depth):
        return f"{obs.attrs['station']}, {depth:.0f} m"
    return obs.attrs.get("station", "unknown site")


# --------------------------------------------------------------------------
# Day-of-year bookkeeping
# --------------------------------------------------------------------------

def yearday(index: pd.DatetimeIndex | pd.Timestamp) -> np.ndarray | int:
    """Day of year on a fixed 365-day cycle (Feb 29 folded onto Feb 28 = 59).

    Without this, day-of-year 60 means Mar 1 in three years out of four and
    Feb 29 in the fourth, and everything after February is off by a day in
    leap years.
    """
    scalar = isinstance(index, pd.Timestamp)
    idx = pd.DatetimeIndex([index]) if scalar else pd.DatetimeIndex(index)
    doy = np.asarray(idx.dayofyear)
    leap = np.asarray(idx.is_leap_year)
    yd = np.where(leap & (doy >= 60), doy - 1, doy)
    return int(yd[0]) if scalar else yd


def _window_days(day: int, half_width: int) -> np.ndarray:
    """Yeardays within +/- half_width of `day`, wrapping around New Year."""
    return (np.arange(day - half_width, day + half_width + 1) - 1) % 365 + 1


def window_values(obs: pd.Series, day: int, window_days: int = WINDOW_DAYS) -> np.ndarray:
    """Every observation in the record that falls within the day-of-year window."""
    days = _window_days(day, window_days)
    return obs.to_numpy()[np.isin(yearday(obs.index), days)]


def _circular_smooth(values: np.ndarray, days: int) -> np.ndarray:
    """Centred moving average that wraps at the year boundary."""
    if days <= 1:
        return values
    pad = days // 2
    padded = np.concatenate([values[-pad:], values, values[:pad]])
    return np.convolve(padded, np.ones(days) / days, mode="valid")


# --------------------------------------------------------------------------
# Climatology
# --------------------------------------------------------------------------

def build_climatology(
    obs: pd.Series,
    window_days: int = WINDOW_DAYS,
    min_years: int = MIN_YEARS,
    smooth_days: int = SMOOTH_DAYS,
) -> pd.DataFrame:
    """Pooled day-of-year climatology, indexed by yearday 1..365.

    Columns
    -------
    mean, sd      : pooled mean and standard deviation of the hourly values
    n, n_years    : sample count and number of distinct years in the window
    p05..p95      : percentiles, a distribution-free cross-check on the sd bands
    lo1/hi1, lo2/hi2 : the +/-1 and +/-2 sigma bounds used for classification
    """
    frame = pd.DataFrame({
        "temperature": obs.to_numpy(),
        "yd": yearday(obs.index),
        "year": obs.index.year,
    })
    by_day = {day: grp for day, grp in frame.groupby("yd")}

    rows = []
    for day in range(1, 366):
        parts = [by_day[d] for d in _window_days(day, window_days) if d in by_day]
        window = pd.concat(parts, ignore_index=True) if parts else frame.iloc[:0]
        vals = window["temperature"].to_numpy()
        rows.append({
            "yearday": day,
            "mean": vals.mean() if len(vals) else np.nan,
            # ddof=1: these are a sample of the possible conditions on this date
            "sd": vals.std(ddof=1) if len(vals) > 1 else np.nan,
            "n": len(vals),
            "n_years": window["year"].nunique(),
            **{
                f"p{q:02d}": np.percentile(vals, q) if len(vals) else np.nan
                for q in PERCENTILES
            },
        })

    clim = pd.DataFrame(rows).set_index("yearday")
    stat_cols = ["mean", "sd"] + [f"p{q:02d}" for q in PERCENTILES]
    clim.loc[clim["n_years"] < min_years, stat_cols] = np.nan

    if smooth_days > 1 and clim["mean"].notna().all():
        clim["mean"] = _circular_smooth(clim["mean"].to_numpy(), smooth_days)
        clim["sd"] = _circular_smooth(clim["sd"].to_numpy(), smooth_days)

    for k in (1, 2):
        clim[f"lo{k}"] = clim["mean"] - k * clim["sd"]
        clim[f"hi{k}"] = clim["mean"] + k * clim["sd"]

    clim.attrs["window_days"] = window_days
    clim.attrs["period"] = (str(obs.index.min()), str(obs.index.max()))
    clim.attrs["site"] = site_label(obs)
    return clim


# --------------------------------------------------------------------------
# Scoring a new measurement
# --------------------------------------------------------------------------

def _label(z: float) -> str:
    a = abs(z)
    side = "warm" if z > 0 else "cool"
    if a <= 1:
        return "normal"
    if a <= 2:
        return f"unusually {side} (outside 1 sigma)"
    return f"extreme {side} (outside 2 sigma)"


def classify(clim: pd.DataFrame, when, value: float, obs: pd.Series | None = None) -> dict:
    """Score one measurement against the climatology.

    Returns the day-of-year climatology it was compared against, the anomaly,
    the z-score, which sigma band it falls in, and a plain-language label.
    Pass `obs` as well to get the exact percentile rank of the value among
    every historical observation in the same day-of-year window.
    """
    when = pd.Timestamp(when)
    day = yearday(when)
    row = clim.loc[day]
    if not np.isfinite(row["sd"]) or row["sd"] == 0:
        raise ValueError(f"no usable climatology for yearday {day}")

    anomaly = value - row["mean"]
    z = anomaly / row["sd"]
    result = {
        "time": when,
        "yearday": day,
        "temperature": value,
        "clim_mean": row["mean"],
        "clim_sd": row["sd"],
        "anomaly": anomaly,
        "z": z,
        "band": 0 if abs(z) <= 1 else (1 if abs(z) <= 2 else 2),
        "label": _label(z),
        "normal_range_1sd": (row["lo1"], row["hi1"]),
        "normal_range_2sd": (row["lo2"], row["hi2"]),
    }
    if obs is not None:
        vals = window_values(obs, day, clim.attrs.get("window_days", WINDOW_DAYS))
        result["percentile"] = float((vals < value).mean() * 100)
        result["n_compared"] = int(vals.size)
        result["window_min"] = float(vals.min())
        result["window_max"] = float(vals.max())
    return result


def classify_series(clim: pd.DataFrame, obs: pd.Series) -> pd.DataFrame:
    """Vectorised `classify` for a whole series of new measurements."""
    day = yearday(obs.index)
    mean = clim["mean"].reindex(day).to_numpy()
    sd = clim["sd"].reindex(day).to_numpy()
    anomaly = obs.to_numpy() - mean
    z = anomaly / sd
    band = np.where(np.abs(z) <= 1, 0, np.where(np.abs(z) <= 2, 1, 2))
    return pd.DataFrame(
        {
            "temperature": obs.to_numpy(),
            "yearday": day,
            "clim_mean": mean,
            "clim_sd": sd,
            "anomaly": anomaly,
            "z": z,
            "band": band,
            "label": [_label(v) if np.isfinite(v) else "no climatology" for v in z],
        },
        index=obs.index,
    )


# --------------------------------------------------------------------------
# Reporting and plotting
# --------------------------------------------------------------------------

def _date_of(day: int) -> str:
    return (pd.Timestamp("2025-01-01") + pd.Timedelta(days=day - 1)).strftime("%d %b")


def report(obs: pd.Series, clim: pd.DataFrame) -> str:
    scored = classify_series(clim, obs)
    counts = scored["band"].value_counts(normalize=True).sort_index() * 100
    n_years = obs.index.year.nunique()

    return "\n".join([
        f"{site_label(obs)} -- sea water temperature, hourly averages",
        f"  record        {obs.index.min():%Y-%m-%d} to {obs.index.max():%Y-%m-%d}"
        f"  ({len(obs):,} good hourly values, {n_years} calendar years)",
        f"  range         {obs.min():.2f} to {obs.max():.2f} C, overall mean {obs.mean():.2f} C",
        f"  seasonal      coldest {clim['mean'].min():.2f} C around {_date_of(clim['mean'].idxmin())},"
        f" warmest {clim['mean'].max():.2f} C around {_date_of(clim['mean'].idxmax())}"
        f" (amplitude {clim['mean'].max() - clim['mean'].min():.2f} C)",
        f"  variability   day-of-year sd ranges {clim['sd'].min():.2f}-{clim['sd'].max():.2f} C"
        f" (median {clim['sd'].median():.2f} C)",
        f"  support       {clim['n'].min():,}-{clim['n'].max():,} hourly values per day-of-year"
        f" from {clim['n_years'].min()}-{clim['n_years'].max()} years",
        *([f"  screening     {qc['raw_records']:,} raw records ->"
           f" {qc['out_of_range']:,} out of range,"
           f" {qc['spikes']:,} spikes,"
           f" {qc['day_of_year_outliers']:,} day-of-year outliers removed"]
          if (qc := obs.attrs.get("qc")) else []),
        "",
        "  Where the record itself falls relative to this climatology:",
        f"    within 1 sigma   {counts.get(0, 0):5.1f} %   (Gaussian expectation 68.3 %)",
        f"    1 to 2 sigma     {counts.get(1, 0):5.1f} %   (Gaussian expectation 27.2 %)",
        f"    beyond 2 sigma   {counts.get(2, 0):5.1f} %   (Gaussian expectation  4.6 %)",
    ])


def plot_climatology(obs: pd.Series, clim: pd.DataFrame, out_path: Path,
                     overlay_year: int | None = None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    if overlay_year is None:
        # the last year in the record is often a stub (a buoy pulled in April),
        # which would draw a line across a third of the axis and stop
        days = obs.groupby(obs.index.year).apply(lambda s: s.index.normalize().nunique())
        complete = days[days >= 200]
        overlay_year = int(complete.index.max() if len(complete) else obs.index.year.max())

    band_2, band_1 = "#cde2fb", "#9ec5f4"   # blue 100 / 200
    mean_c, obs_c = "#184f95", "#eb6834"    # blue 600 / orange
    ink, ink_2, grid = "#0b0b0b", "#52514e", "#e6e5e1"

    x = pd.to_datetime("2025-01-01") + pd.to_timedelta(clim.index - 1, unit="D")

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(11, 7.5), height_ratios=[3, 2], constrained_layout=True
    )
    fig.patch.set_facecolor("#fcfcfb")

    # --- panel 1: seasonal cycle with sigma envelopes -----------------------
    ax.fill_between(x, clim["lo2"], clim["hi2"], color=band_2, lw=0,
                    label="+/- 2 sd (climatological range)")
    ax.fill_between(x, clim["lo1"], clim["hi1"], color=band_1, lw=0,
                    label="+/- 1 sd (normal)")
    ax.plot(x, clim["mean"], color=mean_c, lw=2, label="climatological mean")

    year_obs = obs[obs.index.year == overlay_year]
    if len(year_obs):
        yx = pd.to_datetime("2025-01-01") + pd.to_timedelta(yearday(year_obs.index) - 1, unit="D")
        ax.plot(yx, year_obs.to_numpy(), color=obs_c, lw=1.1, alpha=0.9,
                label=f"{overlay_year} observations")

    ax.set_ylabel("Temperature (C)", color=ink_2)
    ax.set_title(
        f"{site_label(obs)} -- day-of-year temperature climatology, "
        f"{obs.index.min():%Y}-{obs.index.max():%Y}",
        color=ink, fontsize=13, loc="left", pad=10,
    )
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.set_xlim(x[0], x[-1])
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=ink_2, ncols=2)

    # --- panel 2: anomalies over the whole record ---------------------------
    scored = classify_series(clim, obs)
    # in sigma units, not degrees: the sd varies with season, so a fixed band
    # in degrees would mean different things at different times of year
    monthly = scored["z"].resample("MS").mean()
    ax2.axhspan(-1, 1, color=band_1, lw=0)
    ax2.axhspan(-2, -1, color=band_2, lw=0)
    ax2.axhspan(1, 2, color=band_2, lw=0)
    ax2.axhline(0, color=mean_c, lw=1.2)
    ax2.plot(monthly.index, monthly.to_numpy(), color=obs_c, lw=1.6)
    ax2.set_ylabel("Anomaly (standard deviations)", color=ink_2)
    ax2.set_title(
        "Monthly-mean anomaly in units of the day-of-year sd; shading marks the 1 and 2 sd bands",
        color=ink_2, fontsize=10, loc="left", pad=6,
    )
    lim = float(np.nanmax(np.abs(monthly.to_numpy()))) * 1.15
    ax2.set_ylim(-max(lim, 2.4), max(lim, 2.4))

    for a in (ax, ax2):
        a.set_facecolor("#fcfcfb")
        a.grid(True, color=grid, lw=0.8)
        a.set_axisbelow(True)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            a.spines[side].set_color(grid)
        a.tick_params(colors=ink_2, labelsize=9)

    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


def print_check(clim: pd.DataFrame, obs: pd.Series, when, value: float) -> dict:
    r = classify(clim, when, value, obs=obs)
    print(f"{site_label(obs)}   {r['time']:%Y-%m-%d %H:%M}   {r['temperature']:.2f} C")
    print(f"  climatology  {r['clim_mean']:.2f} +/- {r['clim_sd']:.2f} C (day {r['yearday']},"
          f" {_date_of(r['yearday'])})")
    print(f"  normal 1 sd  {r['normal_range_1sd'][0]:.2f} to {r['normal_range_1sd'][1]:.2f} C")
    print(f"  2 sd range   {r['normal_range_2sd'][0]:.2f} to {r['normal_range_2sd'][1]:.2f} C")
    print(f"  anomaly      {r['anomaly']:+.2f} C   z = {r['z']:+.2f}")
    print(f"  percentile   {r['percentile']:.1f} of {r['n_compared']:,} historical hourly values"
          f" within +/-{clim.attrs['window_days']} days of this date"
          f" (observed {r['window_min']:.2f}-{r['window_max']:.2f} C)")
    print(f"  verdict      {r['label'].upper()}")
    return r


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--site", default="pinnacle", help="site key or unambiguous fragment")
    p.add_argument("--all", action="store_true", help="run every discovered site")
    p.add_argument("--list", action="store_true", help="list discovered sites and exit")
    p.add_argument("--window", type=int, default=WINDOW_DAYS,
                   help="half-width in days of the day-of-year pooling window")
    p.add_argument("--check", nargs=2, metavar=("TIME", "VALUE"),
                   help="score a single measurement, e.g. --check 2026-08-26T22:00 3.65")
    p.add_argument("--outdir", type=Path, default=None,
                   help="write <site>_climatology.csv and .png here")
    args = p.parse_args(argv)

    sites = discover_sites()
    if args.list:
        for key, path in sorted(sites.items()):
            print(f"  {key:<12} {path.parent.name}/{path.name}")
        return

    keys = sorted(sites) if args.all else [resolve_site(args.site, sites)]
    for i, key in enumerate(keys):
        obs = load_series(path=sites[key])
        clim = build_climatology(obs, window_days=args.window)
        if i:
            print()
        if args.check and not args.all:
            print_check(clim, obs, args.check[0], float(args.check[1]))
        else:
            print(report(obs, clim))
        if args.outdir:
            args.outdir.mkdir(parents=True, exist_ok=True)
            clim.round(4).to_csv(args.outdir / f"{key}_climatology.csv")
            plot_climatology(obs, clim, args.outdir / f"{key}_climatology.png")
            print(f"  written       {args.outdir}/{key}_climatology.{{csv,png}}")


if __name__ == "__main__":
    main()
