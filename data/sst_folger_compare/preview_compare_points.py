"""Draw the four panels from the GeoJSON alone -- the worked example for the app.

This file imports NOTHING from this repository. No onc_folger, no sst_anomalies, no
barkley_sst, no pandas. It opens one .geojson and draws, which is the whole point:
it proves the layer carries everything a consumer needs, and it is the reference to
read rather than reverse-engineering the file.

Whoever wires the popup into the map app should port this function, not invent one.

USAGE
    python preview_compare_points.py            # writes preview_compare_points.png
    python preview_compare_points.py --out x.png
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates          # noqa: E402
import matplotlib.pyplot as plt            # noqa: E402
import matplotlib.transforms as transforms  # noqa: E402

HERE = Path(__file__).resolve().parent
LAYER = HERE.parent / "folger_compare_points.geojson"


def _month(s: str) -> date:
    """'2026-08' -> a date at the first of that month."""
    y, m = s.split("-")
    return date(int(y), int(m), 1)


def draw(feature: dict, meta: dict, path: Path, dpi: int = 200):
    """Panel 1 overlays every series' raw line; then one anomaly panel per series."""
    series = feature["properties"]["series"]
    pal = meta["palette"]
    n = 1 + len(series)

    fig, axes = plt.subplots(n, 1, figsize=(15, 4.4 * n), sharex=True,
                             facecolor=pal["surface"],
                             gridspec_kw={"height_ratios": [1.2] + [1] * len(series)})

    # --- Panel 1: raw lines, all series on one axis, same quantity and unit.
    ax = axes[0]
    ax.set_facecolor(pal["surface"])
    for s in series:
        # Nulls are kept, NOT filtered out. They mark real outages, and mapping them to
        # NaN makes the line break there. Dropping them instead joins the two sides with
        # a straight segment -- Pinnacle's 2017-2019 gap would draw as 860 days of
        # invented water. See the layer's `gap_note`.
        xs = [date.fromisoformat(d["date"]) for d in s["daily"]]
        ys = [float("nan") if d["value_C"] is None else d["value_C"] for d in s["daily"]]
        ax.plot(xs, ys, lw=0.7, color=s["color"], label=s["label"], zorder=3)
    ax.set_ylabel("temperature (°C)", color=pal["muted"], fontsize=9)
    ax.grid(axis="y", color="#e1e0d9", lw=0.8, zorder=0)
    ax.legend(frameon=False, fontsize=9, labelcolor=pal["muted"],
              loc="upper right", ncol=len(series))

    # --- One shared symmetric y-limit for every anomaly panel. The file asks for this
    # explicitly (anomaly_y_shared); autoscaling per panel would make the satellite's
    # genuinely smaller anomalies look the same size as the stations'.
    every = [m["anom_C"] for s in series for m in s["monthly"] if m["anom_C"] is not None]
    lim = max(abs(min(every)), abs(max(every))) * 1.15

    for ax, s in zip(axes[1:], series):
        ax.set_facecolor(pal["surface"])
        thr = {int(p): v for p, v in s["anomaly_thresholds"].items()}
        colors = dict(zip(sorted(thr), (pal["p90"], pal["p95"], pal["p99"])))

        rows = [m for m in s["monthly"] if m["anom_C"] is not None]
        xs = [_month(m["month"]) for m in rows]
        ys = [m["anom_C"] for m in rows]
        fill = []
        for v in ys:                                  # ascending: severest wins
            c = pal["bar"]
            for p in sorted(thr):
                if v > thr[p]:
                    c = colors[p]
            fill.append(c)

        # The in-progress month is drawn hollow -- outline only, hatched. It is a third
        # of a month and creeps upward daily; filled like the rest it reads as a
        # finished one. See the layer's `partial_note`.
        solid = [i for i, m in enumerate(rows) if not m.get("partial")]
        part = [i for i, m in enumerate(rows) if m.get("partial")]
        ax.bar([xs[i] for i in solid], [ys[i] for i in solid], width=24,
               color=[fill[i] for i in solid], zorder=3)
        if part:
            ax.bar([xs[i] for i in part], [ys[i] for i in part], width=24,
                   facecolor="none", edgecolor=[fill[i] for i in part],
                   hatch="////", lw=1.0, zorder=3)
        ax.axhline(0, color=pal["ink"], lw=1.1, zorder=4)

        tf = transforms.blended_transform_factory(ax.transAxes, ax.transData)
        for p in sorted(thr):
            ax.axhline(thr[p], color=colors[p], lw=1.2, ls=(0, (5, 3)), zorder=5)
            ax.text(1.008, thr[p], f"{p}th  {thr[p]:+.2f}", transform=tf,
                    color=colors[p], fontsize=8.5, va="center", ha="left", zorder=6)

        ax.set_ylim(-lim, lim)
        ax.set_ylabel("anomaly (°C)", color=pal["muted"], fontsize=9)
        ax.text(0.002, 0.97, s["label"], transform=ax.transAxes, color=pal["ink"],
                fontsize=10.5, va="top", ha="left", zorder=7,
                bbox=dict(facecolor=pal["surface"], edgecolor="none", pad=2.5))

    for ax in axes:
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.tick_params(colors=pal["muted"], labelsize=9)
        ax.tick_params(axis="x", length=0, pad=6)
        for sp in ("top", "right", "left", "bottom"):
            ax.spines[sp].set_visible(False)
    for ax in axes[:-1]:
        ax.tick_params(axis="x", labelbottom=False)

    fig.suptitle(meta["title"], color=pal["ink"], fontsize=13,
                 x=0.011, y=0.998, ha="left", va="top")
    fig.text(0.011, 0.9765, meta["baseline_caveat"], color=pal["muted"],
             fontsize=9.5, ha="left", va="top")
    fig.subplots_adjust(top=0.955, hspace=0.13)
    fig.savefig(path, dpi=dpi, facecolor=pal["surface"], bbox_inches="tight")
    return fig


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layer", type=Path, default=LAYER)
    ap.add_argument("--out", type=Path, default=HERE / "preview_compare_points.png")
    args = ap.parse_args()

    layer = json.loads(args.layer.read_text())
    draw(layer["features"][0], layer["properties"], args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
