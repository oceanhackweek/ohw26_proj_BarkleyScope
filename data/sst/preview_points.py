"""Render the point layer's two panels as a PNG, offline.

WHY THIS EXISTS
    export_points.py writes a GeoJSON that some other app is meant to plot. That is a
    slow way to find out whether the numbers are sensible -- you would need the app
    running, the layer wired in, and a browser. This draws the same two panels straight
    from the file, in a second, with nothing but matplotlib.

    It is the point-layer counterpart to preview_panels.py and preview_map.py, and it
    exists for the same reason: a figure answers "did that work?" faster than an app can.

    It also serves as a worked example. Whoever builds the popup can read this to see
    exactly which fields feed which panel, without reverse-engineering the GeoJSON.

WHAT IT DRAWS
    A   raw SST through the whole record -- weekly for the backfilled years, with the
        most recent week marked, since those are the only daily points.
    B   monthly anomaly against the calendar-month climatology, with warm-percentile
        exceedance thresholds.

    Both share an x-axis, so a warm stretch in A sits above its bars in B. The anomaly
    panel is drawn by sst_anomalies._draw_anomaly(), unchanged, so this figure and the
    ones Taylor's module produces carry identical marks.

USAGE
    python preview_points.py
    python preview_points.py --out somewhere.png
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')                     # no display on the hub, and none needed

import matplotlib.pyplot as plt           # noqa: E402
import pandas as pd                       # noqa: E402

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import barkley_sst as sst                 # noqa: E402
import sst_anomalies as sa                # noqa: E402

LAYER = sst.DATA_DIR / 'sst_barkley_points.geojson'
OUTPUT = HERE / 'preview_points.png'

PERCENTILES = (90, 95, 99)


def load(path=LAYER):
    """The point feature and the collection-level metadata."""
    if not path.exists():
        raise FileNotFoundError(
            f'{path.name} is missing -- run export_points.py first.')
    layer = json.loads(path.read_text())
    return layer['features'][0]['properties'], layer['properties']


def frames(feature):
    """The GeoJSON's two series as frames: raw for panel A, anomalies for panel B."""
    daily = pd.DataFrame(feature['daily'])
    daily['date'] = pd.to_datetime(daily['date'], utc=True)

    monthly = pd.DataFrame(feature['monthly'])
    monthly['month'] = pd.to_datetime(monthly['month'] + '-01', utc=True)
    # _draw_anomaly() wants a month-indexed frame with an anom_C column, which is
    # exactly what to_monthly()/anomalies() hand it -- so reassemble that shape rather
    # than teach the renderer a second one.
    anom = monthly.set_index('month')[['anom_C']].astype('float64')
    return daily, monthly, anom


def draw(feature, meta, daily, monthly, anom):
    fig, (ax_a, ax_b) = plt.subplots(2, 1, figsize=(15, 8), sharex=True,
                                     facecolor=sa._SURFACE)

    # --- A: raw SST -------------------------------------------------------
    ax_a.set_facecolor(sa._SURFACE)
    ax_a.plot(daily['date'], daily['sst_C'], lw=1.0, color=sa._BLUE, zorder=3)

    # The daily tail is the only part of the record sampled every day; marking it stops
    # a reader assuming the whole line has that resolution.
    tail = daily[daily['date'] > daily['date'].max() - pd.Timedelta(days=8)]
    ax_a.plot(tail['date'], tail['sst_C'], lw=0, marker='o', ms=4,
              color=sa._ORANGE, zorder=4)

    ax_a.set_ylabel('SST (°C)', color=sa._MUTED, fontsize=9)
    ax_a.text(0.002, 0.97, 'A   raw SST — weekly through the record, last 7 days daily',
              transform=ax_a.transAxes, color=sa._INK, fontsize=10.5, va='top')
    for spine in ('top', 'right', 'left'):
        ax_a.spines[spine].set_visible(False)
    ax_a.spines['bottom'].set_color('#c3c2b7')
    ax_a.tick_params(colors=sa._MUTED, labelsize=9)

    # --- B: anomalies, drawn by Taylor's renderer -------------------------
    thresholds = sa._draw_anomaly(ax_b, anom, percentiles=PERCENTILES)
    sa._time_axis(ax_b, anom)
    ax_b.set_ylabel('anomaly (°C)', color=sa._MUTED, fontsize=9)
    ax_b.text(0.002, 0.97, 'B   monthly anomaly vs calendar-month climatology',
              transform=ax_b.transAxes, color=sa._INK, fontsize=10.5, va='top')

    cell = feature['cell']
    fig.suptitle(f'{feature["name"]} — cell ({cell["lat"]:.3f}, {cell["lon"]:.3f})',
                 color=sa._INK, fontsize=12.5, x=0.011, y=0.985, ha='left')
    fig.text(0.011, 0.952, meta['baseline'], color=sa._MUTED, fontsize=9.5, ha='left')

    # The caveats belong on the figure, not only in the file. A PNG travels further
    # than the GeoJSON it came from, and arrives without its metadata.
    thin = sum(1 for m in feature['monthly'] if m['ok'] and m['n'] < 10)
    fig.text(0.011, -0.02,
             f'{meta["cell_caveat"]}\n{meta["depth_caveat"]}\n'
             f'{thin} of {len(feature["monthly"])} months rest on fewer than 10 samples '
             f'— see n in the layer.',
             color=sa._MUTED, fontsize=8.5, ha='left', va='top')

    fig.subplots_adjust(top=0.90, hspace=0.16)
    return fig, thresholds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    feature, meta = load()
    daily, monthly, anom = frames(feature)
    fig, thresholds = draw(feature, meta, daily, monthly, anom)

    fig.savefig(args.out, dpi=150, facecolor=sa._SURFACE, bbox_inches='tight')
    print(f'wrote {args.out.name}')
    print(f'  A: {len(daily)} points, '
          f'{daily["sst_C"].min():.1f}–{daily["sst_C"].max():.1f} °C')
    print(f'  B: {int(anom["anom_C"].notna().sum())} months, thresholds ' +
          ', '.join(f'{p}th {v:+.2f}' for p, v in thresholds.items()))
    print(f'  {meta["baseline"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
