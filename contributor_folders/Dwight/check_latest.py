"""Score the latest reading from each Barkley Canyon / Barkley Sound mooring
against its own day-of-year climatology, and draw the comparison.

    python check_latest.py                 # table + summary figure
    python check_latest.py --edit          # print the block to update by hand

READINGS holds what is being checked; edit it when new values come in.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from onc_climatology import (
    build_climatology, classify, discover_sites, load_series, site_label,
)

# site key -> (timestamp of the reading, temperature in C)
READINGS = {
    # La Peruse Bank is a surface buoy whose archive stops in 2022; the reading
    # is still scored against its 1988-2022 day-of-year climatology.
    "laperusebank": ("2026-08-26T12:00", 14.00),
    "upperslope": ("2026-08-26T18:30", 6.05),
    "node":       ("2026-08-26T21:30", 5.05),
    "hydrates":   ("2026-08-26T21:30", 4.00),
    "mideast":    ("2026-07-27T23:30", 3.94),
    "axis":       ("2026-08-26T21:30", 3.65),
}

OUT_DIR = Path(__file__).parent / "climatology"


def score_all(readings=READINGS) -> pd.DataFrame:
    sites = discover_sites()
    rows = []
    for key, (when, value) in readings.items():
        obs = load_series(path=sites[key])
        clim = build_climatology(obs)
        r = classify(clim, when, value, obs=obs)
        rows.append({
            "site": site_label(obs),
            "key": key,
            "depth": obs.attrs["depth"],
            "time": r["time"],
            "reading": value,
            "clim_mean": r["clim_mean"],
            "sd": r["clim_sd"],
            "lo1": r["normal_range_1sd"][0], "hi1": r["normal_range_1sd"][1],
            "lo2": r["normal_range_2sd"][0], "hi2": r["normal_range_2sd"][1],
            "anomaly": r["anomaly"],
            "z": r["z"],
            "percentile": r["percentile"],
            "verdict": r["label"],
            # what the archive itself last recorded, for comparison with the
            # value being checked (live dashboard readings can be newer)
            "archived_last": float(obs.iloc[-1]),
            "archived_time": obs.index[-1],
        })
    return pd.DataFrame(rows).sort_values("depth", na_position="first")


def _ordinal(n: float) -> str:
    n = int(round(n))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def plot_summary(scored: pd.DataFrame, out_path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    band_2, band_1 = "#cde2fb", "#9ec5f4"
    zero_c, normal_c, flagged_c = "#184f95", "#2a78d6", "#eb6834"
    ink, ink_2, grid = "#0b0b0b", "#52514e", "#e6e5e1"

    # deepest at the bottom, the surface buoy at the top
    df = scored.sort_values("depth", ascending=False, na_position="last").reset_index(drop=True)
    y = np.arange(len(df))

    fig, ax = plt.subplots(figsize=(10, 0.9 * len(df) + 2.6), constrained_layout=True)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")

    ax.axvspan(-2, 2, color=band_2, lw=0)
    ax.axvspan(-1, 1, color=band_1, lw=0)
    ax.axvline(0, color=zero_c, lw=1.4)

    for i, row in df.iterrows():
        colour = normal_c if abs(row["z"]) <= 1 else flagged_c
        ax.plot([0, row["z"]], [i, i], color=colour, lw=2, solid_capstyle="round", zorder=3)
        # 2px surface ring so the marker stays legible against the bands
        ax.plot(row["z"], i, "o", ms=11, color=colour, mec="#fcfcfb", mew=2, zorder=4)
        ax.text(row["z"] + (0.12 if row["z"] >= 0 else -0.12), i,
                f"{row['reading']:.2f} C  ({row['z']:+.2f} sd, {_ordinal(row['percentile'])} pct)"
                + ("" if abs(row["z"]) <= 1 else "  -- outside 1 sd"),
                va="center", ha="left" if row["z"] >= 0 else "right",
                fontsize=9, color=ink_2)

    ax.set_yticks(y, [f"{r['site']}" for _, r in df.iterrows()], fontsize=10)
    ax.set_ylim(-0.7, len(df) - 0.3)
    # asymmetric limits: the direct labels sit outside each marker and need room
    ax.set_xlim(-max(2.4, -float(df["z"].min()) + 1.6),
                max(2.4, float(df["z"].max()) + 2.6))
    ax.set_xlabel("Anomaly from the day-of-year climatology (standard deviations)", color=ink_2)
    ax.set_title(
        "Latest reading vs day-of-year climatology, ONC Barkley moorings\n"
        "shaded: +/- 1 sd (normal) and +/- 2 sd; each site scored against its own record",
        color=ink, fontsize=12.5, loc="left", pad=10,
    )
    ax.grid(True, axis="x", color=grid, lw=0.8)
    ax.set_axisbelow(False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(grid)
    ax.tick_params(colors=ink_2, labelsize=9)

    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--outdir", type=Path, default=OUT_DIR)
    args = p.parse_args(argv)

    scored = score_all()
    cols = ["site", "reading", "clim_mean", "sd", "lo1", "hi1", "z", "percentile", "verdict"]
    print(scored[cols].round(2).to_string(index=False))

    args.outdir.mkdir(parents=True, exist_ok=True)
    scored.round(4).to_csv(args.outdir / "latest_vs_climatology.csv", index=False)
    out = plot_summary(scored, args.outdir / "latest_vs_climatology.png")
    print(f"\nwritten  {args.outdir}/latest_vs_climatology.{{csv,png}}")

    # a surface buoy whose archive ended years ago is not "drift", so only
    # compare readings against an archive that is still current
    recent = scored["archived_time"] > scored["time"] - pd.Timedelta("7D")
    drift = scored[recent & ((scored["reading"] - scored["archived_last"]).abs() > 0.1)]
    if len(drift):
        print("\nreadings that differ from the last archived value by more than 0.1 C:")
        for _, r in drift.iterrows():
            print(f"  {r['site']:<32} checked {r['reading']:.2f} C"
                  f" vs archive {r['archived_last']:.2f} C at {r['archived_time']:%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()
