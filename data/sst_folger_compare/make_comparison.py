"""Satellite SST and the two ONC Folger stations in one four-panel figure.

WHAT THIS DRAWS
    One figure, four panels, one shared time axis:

        1. raw daily temperature -- satellite skin, Pinnacle 25 m, Deep 98 m, overlaid
        2. monthly anomalies, satellite
        3. monthly anomalies, Folger Pinnacle
        4. monthly anomalies, Folger Deep

    The point is the vertical read: an event in the raw panel can be traced straight
    down into all three anomaly series, and the three depths compared at a glance.

WHOSE CODE THIS USES
    Nothing here is new plotting. Both libraries are imported read-only and neither
    file is modified:

        ../folger_taylor/onc_folger.py   Taylor Borgfeldt and Claude -- the ONC reader,
                                         the aggregation chain, and every plot function
        ../sst/sst_anomalies.py          a documented fork of the above, adapted for a
                                         satellite series (see its docstring)

    plot_combined() already takes N series and N anomaly panels, so the four-panel
    figure needs no change to it -- her three-panel version is the same call with one
    fewer of each.

    Because sst_anomalies.py is a fork rather than a reimplementation, the arithmetic
    behind all three anomaly panels is identical. That is what makes them comparable.

THE SATELLITE SERIES IS WEEKLY, NOT DAILY
    data/sst_barkley_realtime.nc holds only the rolling 7-day window. The full satellite
    history at Folger exists locally as one file -- data/sst/folger_point_daily.csv,
    380 values over 2,592 days, written by backfill_point_history.py at stride 7.

    So the satellite line in panel 1 is weekly through the record and daily only for
    the last week, while the two ONC lines are true daily means. At fifteen years on one
    axis the difference is barely visible, and monthly means are unbiased either way --
    but each satellite month rests on ~4 values rather than ~30, which is why its
    min_days threshold is 3 and why `n` travels with every monthly row.

    Densifying it means re-running backfill_point_history.py at stride 1: roughly 2,600
    ERDDAP requests against a service whose own guidance asks for pauses between them.
    Deliberately not done here.

BASELINES ARE NOT COMMON
    Each of the three sits on its own full record: satellite 2019-2026, Pinnacle
    2011-2026, Deep 2016-2026. So each panel answers "how unusual was this month *for
    this series*", which is the same question three times, but measured against three
    different periods.

    That differs from folger_timeseries_and_anomalies.png, which rebaselines both
    stations onto the 89 months usable at both. A three-way common baseline would be
    capped by the satellite's 2019 start and would discard eight years of Pinnacle, so
    the trade was made the other way. The consequence is real and belongs in any caption:
    a difference between panels may partly reflect the different baseline periods rather
    than the water. See README.md.

USAGE
    python make_comparison.py                  # writes the figure into this folder
    python make_comparison.py --outdir /tmp/x
    python make_comparison.py --help

Authors: Anais Gentilhomme and Claude (Anthropic), 2026-08-28.
Builds on Taylor Borgfeldt's onc_folger.py; that file is imported, never edited.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent                      # data/
REPO = DATA.parent

# Read-only imports from the two sibling folders. Anchored to this file rather than the
# working directory: the hub launches from /home/jovyan, not the repo.
sys.path.insert(0, str(DATA / "folger_taylor"))
sys.path.insert(0, str(DATA / "sst"))

import onc_folger as onc          # noqa: E402  -- path set above
import sst_anomalies as sa        # noqa: E402

# --------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------

SATELLITE = DATA / "sst" / "folger_point_daily.csv"

STATIONS = [
    # label, ONC "clean, averaged" hourly CSV
    ("Folger Pinnacle (25 m)",
     DATA / "folger" / "FolgerPassage_FolgerPinnacle_variables_SeaWaterTemperature"
                       "_20110203T170000Z_20260811T180000Z-NaN_clean_avg1hour.csv"),
    ("Folger Deep (98 m)",
     DATA / "folger" / "FolgerPassage_FolgerDeep_variables_SeaWaterTemperature"
                       "_20160101T000000Z_20260718T050000Z-NaN_clean_avg1hour.csv"),
]

SATELLITE_LABEL = "Satellite skin SST"

# Taylor's thresholds for the ONC chain, unchanged. The satellite has no hourly step to
# screen, and its months hold ~4 weekly values, so it keeps sst_anomalies' own min_days=3.
MIN_HOURS, MIN_DAYS, SAT_MIN_DAYS, DPI = 18, 15, 3, 200


def satellite_daily(path: Path = SATELLITE) -> pd.DataFrame:
    """The backfilled satellite series as the daily frame the pipeline expects."""
    df = pd.read_csv(path, comment="#", parse_dates=["date"])
    return sa.daily_frame(df["date"], df["sst_c"])


def station_daily(path: Path) -> pd.DataFrame:
    """One ONC export, hourly -> daily, through Taylor's reader unchanged."""
    return onc.to_daily(onc.read_csv(path), min_hours=MIN_HOURS)


def anomaly_frame(daily: pd.DataFrame, min_days: int) -> pd.DataFrame:
    """daily -> monthly -> climatology -> anomalies, on this series' own baseline."""
    monthly = onc.to_monthly(daily, min_days=min_days)
    return onc.anomalies(monthly, onc.climatology(monthly))


def build(outdir: Path) -> Path:
    """Assemble the three series and write the four-panel figure."""
    series, panels = {}, []

    sat_daily = satellite_daily()
    series[SATELLITE_LABEL] = sat_daily
    panels.append((SATELLITE_LABEL, anomaly_frame(sat_daily, SAT_MIN_DAYS)))

    for label, path in STATIONS:
        daily = station_daily(path)
        series[label] = daily
        panels.append((label, anomaly_frame(daily, MIN_DAYS)))

    # Spans differ (satellite 2019-, Pinnacle 2011-, Deep 2016-), so the shared axis is
    # wider than any one series and every panel shows its own record as a gap either
    # side. Left visible rather than cropped, matching plot_combined's own docstring.
    subtitle = (
        "Each series on its own baseline -- not a common one; panels differ in period.  "
        "Satellite is skin temperature, weekly-sampled before the last week; "
        "stations are hourly means at depth."
    )

    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "sst_vs_folger_four_panel.png"
    onc.plot_combined(
        series,
        panels,
        title="Folger Passage temperature -- satellite surface against two depths",
        subtitle=subtitle,
        path=path,
        dpi=DPI,
    )
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir", type=Path, default=HERE,
                    help="where to write the figure (default: this folder)")
    args = ap.parse_args()

    path = build(args.outdir)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
