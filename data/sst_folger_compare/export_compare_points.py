"""Build the clickable point layer behind the four-panel Folger comparison. NO NETWORK.

WHAT IT WRITES
    ../folger_compare_points.geojson -- one Point feature at Folger Passage carrying
    all three series the figure draws, so the app can render the four panels without
    reading a CSV, a netCDF, or anything in this folder.

    Structured as a LIST of series rather than three named fields:

        properties.series = [
            {key: "satellite", label: ..., daily: [...], monthly: [...],
             climatology: [...], anomaly_thresholds: {...}},
            {key: "pinnacle",  ...},
            {key: "deep",      ...},
        ]

    Deliberately a list. The app loops it -- panel 1 overlays every series' `daily`,
    then one anomaly panel per series in order. Adding a fourth depth later is a
    data change, not an app change.

WHAT IT READS
    ../sst/folger_point_daily.csv    satellite, weekly back to 2019
    ../folger/*.csv                  the two ONC hourly exports

    All already in the repo. This script never touches the network.

SUB-SAMPLING
    Every daily series is thinned to weekly, plus the last 7 days at full resolution --
    the same rule export_points.py uses, and applied to the ONC records for the same
    reason: 5,669 daily values per station is an unreadable line at popup width and a
    payload nobody wants to ship. The satellite is weekly-sampled at source anyway, so
    this also puts all three on one footing in panel 1.

    Monthly means are computed from the FULL daily records before thinning. The
    anomaly panels therefore carry their real precision -- only the drawn raw line is
    thinned, never the statistics.

RELATIONSHIP TO sst_barkley_points.geojson
    This is a superset of that file: it carries the satellite's daily, monthly,
    climatology and thresholds unchanged, plus the same four fields for both ONC
    stations. Integrate one or the other, not both -- two markers 2 km apart at the
    same place read as two different stories.

USAGE
    python export_compare_points.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import make_comparison as mc      # noqa: E402  -- sets up the sibling imports
import onc_folger as onc          # noqa: E402

OUTPUT = mc.DATA / "folger_compare_points.geojson"

# Where the marker sits: the midpoint of the two ONC instruments, which are 611 m apart.
# Not the satellite cell centre -- two of the three series are physically measured here,
# and the satellite cell contains this point. The cell's own centre and bounds travel in
# `cell` below so the app can draw the footprint if it wants to.
STATIONS = {
    "pinnacle": {"label": "Folger Pinnacle (25 m)", "depth_m": 23.0,
                 "lat": 48.80829, "lon": -125.28150, "code": "FGPPN"},
    "deep":     {"label": "Folger Deep (98 m)", "depth_m": 96.5,
                 "lat": 48.81376, "lon": -125.28078, "code": "FGPD"},
}
MARKER_LAT = round(sum(s["lat"] for s in STATIONS.values()) / 2, 5)
MARKER_LON = round(sum(s["lon"] for s in STATIONS.values()) / 2, 5)

# The satellite cell, from folger_point_daily.csv's own preamble.
CELL = {"lat": 48.825, "lon": -125.275,
        "lat_range": [48.800, 48.850], "lon_range": [-125.300, -125.250],
        "size_km": [5.6, 3.7]}

DISPLAY_STRIDE_DAYS = 7
DAILY_TAIL_DAYS = 7
PERCENTILES = (90, 95, 99)

# A gap wider than this gets an explicit null in `daily`, so a consumer's line BREAKS
# instead of drawing a straight segment across an outage it has no data for. Pinnacle's
# 2017-2019 outage is 860 days; drawn through, it invents two and a half years of water.
# Three times the display stride: wide enough that ordinary weekly spacing never trips
# it, narrow enough to catch any real absence.
GAP_BREAK_DAYS = 21

# Taylor's validated palette, carried in the file so a consumer never guesses at styling
# and the app cannot drift from the reference figure. Her METHODS.md records the CVD and
# contrast gates these were checked against -- worst adjacent CVD separation dE 16.3,
# worst normal-vision dE 19.6 (OKLab x100; floors 8 and 15). Do not substitute by eye.
SERIES_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")   # onc_folger._SERIES
PALETTE = {
    "ink": "#0b0b0b", "muted": "#898781", "surface": "#fcfcfb",
    "bar": "#b8b6ae", "p90": "#4a3aa7", "p95": "#e87ba4", "p99": "#eda100",
}


def display_series(daily: pd.DataFrame) -> pd.Series:
    """Thin a daily record to weekly, keeping the last week at full resolution.

    Same rule as export_points.py, and thinned by DATE GAP rather than row position --
    keep a value only once `stride` days have passed since the last one kept. That is
    idempotent: the satellite is already 7-day spaced at source and passes through
    untouched, while a true-daily ONC record drops to weekly. Striding by position
    instead would thin the satellite a second time, to one value every 49 days.

    Applied to the drawn line only -- monthly means and anomalies are computed upstream
    of this, from every value.
    """
    v = daily["temperature_C"].dropna().astype(float)
    if v.empty:
        return v

    cutoff = v.index[-1] - pd.Timedelta(days=DAILY_TAIL_DAYS)
    older, recent = v[v.index <= cutoff], v[v.index > cutoff]

    keep, last = [], None
    for when in older.index:
        if last is None or (when - last).days >= DISPLAY_STRIDE_DAYS:
            keep.append(when)
            last = when
    return pd.concat([older.loc[keep], recent])


def series_payload(key: str, label: str, depth_m, daily: pd.DataFrame,
                   min_days: int, color: str) -> dict:
    """One series' four ready-made fields: raw line, monthly, climatology, thresholds.

    The in-progress month is SHOWN but does not COUNT. Two passes over to_monthly:

        base  drop_partial_end=True  -- the complete months. Builds the climatology and
                                       the percentile thresholds.
        full  drop_partial_end=False -- adds the trailing partial month back, for display
                                       only, with its anomaly taken against the baseline
                                       above rather than one it helped set.

    Without the split, ten days of August raise the August climatology that all seven
    other Augusts are then measured against. sst_barkley_points.geojson does exactly
    that -- its August bin has n_years=8 where every other month has 7 -- which shifts
    two of its anomalies by 0.01 C. Small, but the wrong direction.
    """
    base = onc.to_monthly(daily, min_days=min_days)
    full = onc.to_monthly(daily, min_days=min_days, drop_partial_end=False)

    clim = onc.climatology(base)                 # partial month excluded from the baseline
    anom = onc.anomalies(full, clim)             # ...but still given an anomaly against it
    partial_months = set(full.index) - set(base.index)

    # Thresholds from complete months only, for the same reason.
    v = onc.anomalies(base, clim)["anom_C"].dropna()
    thresholds = {str(p): round(float(v.quantile(p / 100)), 2) for p in PERCENTILES}

    drawn = display_series(daily)
    ok = daily["temperature_C"].dropna()

    def num(x, nd=2):
        return None if pd.isna(x) else round(float(x), nd)

    # Walk the drawn points and mark every real outage with a null, so the line breaks.
    line, previous = [], None
    for when, value in drawn.items():
        if previous is not None and (when - previous).days > GAP_BREAK_DAYS:
            marker = previous + pd.Timedelta(days=1)
            line.append({"date": marker.strftime("%Y-%m-%d"), "value_C": None})
        line.append({"date": when.strftime("%Y-%m-%d"), "value_C": num(value)})
        previous = when

    return {
        "key": key,
        "label": label,
        "depth_m": depth_m,
        "color": color,
        "record": f"{ok.index[0]:%Y-%m} to {ok.index[-1]:%Y-%m}",
        "n_days": int(len(ok)),
        "daily": line,
        "monthly": [{"month": m.strftime("%Y-%m"),
                     "mean_C": num(r["temperature_C"]),
                     "n": int(r["n"]),
                     "ok": bool(r["ok"]),
                     "clim_C": num(r["clim_C"]),
                     "anom_C": num(r["anom_C"]),
                     "partial": m in partial_months}
                    for m, r in anom.iterrows()],
        "climatology": [{"calendar_month": int(m),
                         "clim_C": num(r["clim_C"]),
                         "std_C": num(r["std_C"]),
                         "n_years": int(r["n_years"])}
                        for m, r in clim.iterrows()],
        "anomaly_thresholds": thresholds,
    }


def build() -> dict:
    """The FeatureCollection: one Point, three series, and the metadata to caption it."""
    series = [
        series_payload("satellite", mc.SATELLITE_LABEL, None,
                       mc.satellite_daily(), mc.SAT_MIN_DAYS, SERIES_COLORS[0]),
    ]
    for (label, path), (key, meta), color in zip(mc.STATIONS, STATIONS.items(),
                                                 SERIES_COLORS[1:]):
        series.append(series_payload(key, label, meta["depth_m"],
                                     mc.station_daily(path), mc.MIN_DAYS, color))

    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [MARKER_LON, MARKER_LAT]},
            "properties": {
                "id": "folger-compare",
                "name": "Folger Passage",
                "stations": list(STATIONS.values()),
                "cell": CELL,
                "series": series,
            },
        }],
        # Renderers ignore this. It is here so the app never has to hardcode a caption,
        # a colour, or a panel order -- same convention as sst_barkley_layer.geojson.
        "properties": {
            "title": "Folger Passage temperature -- surface against two depths",
            "units": "degree_C",
            "marker": {"lat": MARKER_LAT, "lon": MARKER_LON,
                       "note": "midpoint of the two ONC instruments, 611 m apart"},
            "panels": [
                {"panel": 1, "kind": "daily",
                 "draws": "every series' `daily`, overlaid on one axis",
                 "y_label": "temperature (°C)"},
                {"panel": 2, "kind": "anomaly", "series": "satellite"},
                {"panel": 3, "kind": "anomaly", "series": "pinnacle"},
                {"panel": 4, "kind": "anomaly", "series": "deep"},
            ],
            "palette": PALETTE,
            "anomaly_y_shared": True,
            "anomaly_y_note": ("One symmetric y-limit across all anomaly panels, from the "
                               "largest |anom_C| in any of them. The satellite reads flatter "
                               "than the stations and that difference is real -- do not "
                               "autoscale the panels independently."),
            "series_order": [s["key"] for s in series],
            "baseline_caveat": ("Each series is on its OWN baseline -- satellite 2019-2026, "
                                "Pinnacle 2011-2026, Deep 2016-2026 -- not a common one. A "
                                "difference between panels may partly reflect the different "
                                "baseline periods rather than the water."),
            "depth_caveat": ("Three different quantities that share a location and a unit. The "
                             "satellite is skin temperature of the surface; the stations sit at "
                             "23 m and ~96 m. The satellite is not a proxy for either."),
            "cell_caveat": ("One 5.6 x 3.7 km satellite cell covers both stations. The marker is "
                            "at the instruments' midpoint; the satellite value is a cell average "
                            "centred 2 km away."),
            "source_caveat": ("Satellite is a near-real-time L4 analysis, about two days behind, "
                              "partly modelled. Station data is ONC 'Clean' QC, uncalibrated "
                              "beyond their own screening."),
            "sampling": ("Raw lines are thinned to weekly plus the last 7 days at full "
                         "resolution. Monthly means and anomalies are computed from the FULL "
                         "daily records before thinning -- only the drawn line is sparse."),
            "partial_note": ("A month with partial: true is the in-progress one at export time -- "
                             "it creeps upward all month. RENDER IT DISTINCTLY (hatched, faded, "
                             "outlined) or a third of a month reads as a finished one. It is shown "
                             "but does not count: it is excluded from the climatology and from the "
                             "percentile thresholds, and its anom_C is measured against a baseline "
                             "it played no part in setting."),
            "gap_note": ("`daily` carries entries with value_C: null wherever the record has a "
                         "real outage (a gap over 21 days). DRAW THEM AS BREAKS, not by "
                         "skipping them: Pinnacle is missing 2017-06 to 2019-10, and a line "
                         "joined across that invents two and a half years of water. In "
                         "matplotlib, map null to NaN and the break is automatic."),
            "threshold_caveat": ("The 90/95/99 percentiles are fixed over each whole record, so "
                                 "they are set mostly by autumn-winter variability. ZERO "
                                 "exceedances fall in Jun/Jul/Aug in any of the three series. "
                                 "That is a property of the threshold, not evidence that summer "
                                 "marine heatwaves do not occur here."),
            "supersedes": ("sst_barkley_points.geojson -- this carries the same satellite fields "
                           "plus both stations. Integrate one or the other, not both."),
        },
    }


def main() -> None:
    layer = build()
    OUTPUT.write_text(json.dumps(layer, separators=(",", ":")))

    props = layer["features"][0]["properties"]
    kb = OUTPUT.stat().st_size / 1024
    print(f"wrote {OUTPUT}  ({kb:.0f} kB)")
    for s in props["series"]:
        print(f"  {s['key']:10s} {s['record']}  "
              f"{len(s['daily']):5d} drawn / {s['n_days']:5d} days, "
              f"{len(s['monthly']):3d} months, 90th +{s['anomaly_thresholds']['90']}")


if __name__ == "__main__":
    main()
