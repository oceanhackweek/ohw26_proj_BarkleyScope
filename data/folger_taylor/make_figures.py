"""Regenerate every Folger Passage temperature figure and table from the raw ONC CSVs.

This is the *driver*: ``onc_folger`` supplies the tools, this script supplies the
recipe -- which files, in what order, with what titles, written where. Running it
reproduces the contents of this folder from nothing but the source CSVs.

    python make_figures.py                  # everything, into this folder
    python make_figures.py --station deep    # one station only
    python make_figures.py --outdir /tmp/x   # write somewhere else

To use it on your own data, edit ``STATIONS`` below and nothing else. Each entry
needs a display label and a path to an ONC "clean, averaged" scalar CSV; depth,
station code, and instrument are read from the file's own preamble. The analysis
assumes hourly temperature -- see ``onc_folger.read_csv``.

Authors: Taylor Borgfeldt and Claude (Anthropic)
Last modified: 2026-08-27
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")          # write files, never open a window
import pandas as pd

import onc_folger as onc

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "folger"        # where the raw ONC exports live

# ---- edit this block to point at your own data -----------------------------
STATIONS = {
    "pinnacle": {
        "label": "Folger Pinnacle",
        "file": SOURCE / ("FolgerPassage_FolgerPinnacle_variables_SeaWaterTemperature"
                          "_20110203T170000Z_20260811T180000Z-NaN_clean_avg1hour.csv"),
    },
    "deep": {
        "label": "Folger Deep",
        "file": SOURCE / ("FolgerPassage_FolgerDeep_variables_SeaWaterTemperature"
                          "_20160101T000000Z_20260718T050000Z-NaN_clean_avg1hour.csv"),
    },
}
COMPARE = ("pinnacle", "deep")   # anomaly panels, middle then bottom; None to skip
# ---------------------------------------------------------------------------

MIN_HOURS, MIN_DAYS, DPI = 18, 15, 200


def run_station(key: str, cfg: dict, outdir: Path, show_report: bool = True) -> dict:
    """One station: load, aggregate, plot coverage and anomalies, write tables."""
    path = cfg["file"]
    if not path.exists():
        raise SystemExit(f"missing source file: {path}")

    print(f"\n{'=' * 78}\n{cfg['label']}  <-  {path.name}\n{'=' * 78}")
    df = onc.inspect(path, min_days=7.0) if show_report else onc.read_csv(path)

    meta = onc.read_header(path)
    site = f"{cfg['label']} ({meta.get('STNCODE', '?')}, {meta.get('DEPTH', '?')} m)"

    daily = onc.to_daily(df, min_hours=MIN_HOURS)
    monthly = onc.to_monthly(daily, min_days=MIN_DAYS)
    clim = onc.climatology(monthly)
    anom = onc.anomalies(monthly, clim)
    usable = monthly[monthly["ok"]]

    onc.plot_coverage(
        monthly, min_days=MIN_DAYS,
        title=f"{site} — valid days per month, hourly→daily(≥{MIN_HOURS}h)→monthly",
        path=outdir / f"{key}_coverage.png")

    baseline = (
        f"Monthly anomaly vs {usable.index[0]:%Y-%m}–{usable.index[-1]:%Y-%m} baseline"
        f"  ·  {len(usable)} usable months"
        f" (n={int(clim['n_years'].min())}–{int(clim['n_years'].max())} yr per calendar month)"
        f"  ·  hourly→daily(≥{MIN_HOURS} h)→monthly(≥{MIN_DAYS} d)")
    _, _, thr = onc.plot_anomalies(
        anom, baseline=baseline, station=f"{site} — sea water temperature anomaly",
        path=outdir / f"{key}_anomaly.png", dpi=DPI)

    table = anom[["temperature_C", "clim_C", "anom_C", "n", "ok"]].copy()
    table.columns = ["monthly_mean_C", "climatology_C", "anomaly_C",
                     "valid_days", f"meets_{MIN_DAYS}day_rule"]
    for pct, value in thr.items():
        table[f"exceeds_p{pct}"] = table["anomaly_C"] > value
    table.index.name = "month"
    table.round(4).to_csv(outdir / f"{key}_monthly_anomaly.csv")
    clim.round(4).to_csv(outdir / f"{key}_climatology.csv")

    print(f"  usable months {len(usable)}/{len(monthly)}   "
          f"thresholds " + "  ".join(f"p{p}={v:+.2f}" for p, v in thr.items()))
    print(f"  wrote {key}_coverage.png, {key}_anomaly.png, "
          f"{key}_monthly_anomaly.csv, {key}_climatology.csv")
    return {"daily": daily, "monthly": monthly, "anom": anom, "site": site}


def run_comparison(results: dict, outdir: Path) -> None:
    """One figure: daily means on top, then one anomaly panel per station.

    The anomaly panels use the common baseline -- both stations restricted to the
    months usable at BOTH -- so a difference between them is a difference between
    the sites and not between their sampling. The daily panel keeps each station's
    full record, so it is wider than the anomaly panels below it.
    """
    mid, bottom = COMPARE
    if mid not in results or bottom not in results:
        print(f"\nskipping combined figure: needs both {mid!r} and {bottom!r}")
        return

    print(f"\n{'=' * 78}\nCombined figure: daily series + {mid} and {bottom} anomalies"
          f"\n{'=' * 78}")
    anom_mid, anom_bottom, n_common = onc.common_baseline(
        results[mid]["monthly"], results[bottom]["monthly"])

    subtitle = (
        "Top: daily means over each station's full record."
        f"  ·  Below: monthly anomalies on a common baseline — "
        f"{anom_mid.index[0]:%Y-%m}–{anom_mid.index[-1]:%Y-%m}, "
        f"the {n_common} months usable at both sites")

    onc.plot_combined(
        {results[k]["site"]: results[k]["daily"] for k in results},
        [(results[mid]["site"], anom_mid), (results[bottom]["site"], anom_bottom)],
        title="Folger Passage sea water temperature — daily means and monthly anomalies",
        subtitle=subtitle,
        path=outdir / "folger_timeseries_and_anomalies.png", dpi=DPI)

    joint = pd.DataFrame({f"{mid}_anom_C": anom_mid["anom_C"],
                          f"{bottom}_anom_C": anom_bottom["anom_C"]}).dropna()
    joint.round(4).to_csv(outdir / "common_baseline_anomalies.csv")
    r = joint.iloc[:, 0].corr(joint.iloc[:, 1])
    print(f"  {len(joint)} common months   anomaly correlation r = {r:+.3f}")
    print("  wrote folger_timeseries_and_anomalies.png, common_baseline_anomalies.csv")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--station", choices=sorted(STATIONS), action="append",
                    help="run only this station (repeatable); default is all")
    ap.add_argument("--outdir", type=Path, default=HERE,
                    help="where figures and tables are written (default: this folder)")
    ap.add_argument("--no-report", action="store_true",
                    help="skip the printed inspection report for each file")
    ap.add_argument("--no-comparison", action="store_true",
                    help="skip the combined daily + anomaly figure")
    args = ap.parse_args(argv)

    args.outdir.mkdir(parents=True, exist_ok=True)
    keys = args.station or list(STATIONS)

    results = {k: run_station(k, STATIONS[k], args.outdir, show_report=not args.no_report)
               for k in keys}
    if not args.no_comparison and COMPARE:
        run_comparison(results, args.outdir)
    print(f"\ndone -> {args.outdir}")


if __name__ == "__main__":
    main()
