"""Build the clickable point layer: raw SST plus monthly anomalies. NO NETWORK.

    This is the counterpart to backfill_point_history.py and the opposite of it in
    every operational sense. That one talks to NOAA, takes minutes, and runs once by
    hand. This one reads two files already on disk, takes a second, and runs on every
    workflow refresh. If you are wiring something into CI, it is this.

WHAT IT READS
    folger_point_daily.csv        the committed history, weekly back to 2019
    ../sst_barkley_realtime.nc    the rolling archive, daily for the last week

    The archive already contains this cell -- the daily job downloads the whole box --
    so extending the series forward costs nothing. The expensive backfill bought the
    years before that, once.

WHAT IT WRITES
    ../sst_barkley_points.geojson   one Point feature carrying two series:

      "daily"     for Plot A. The raw measured field, no baseline: the record
                  sub-sampled to weekly, plus the last 7 days at daily resolution.
                  Sub-sampled because 2,591 points is an unreadable plot, and because
                  the backfilled years only exist weekly anyway.

      "monthly"   for Plot B. Monthly means with clim_C and anom_C alongside, so the
                  anomaly panel can be drawn without recomputing anything.

WHY THE CELL IS CHECKED EVERY RUN
    The CSV records the cell it describes. If the study box or the product's resolution
    ever changes, the archive's grid moves and that cell is no longer the same patch of
    ocean -- but nothing would look broken. The series would keep plotting, describing
    somewhere else. So a mismatch is a hard failure here, not a warning.

USAGE
    python export_points.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import barkley_sst as sst                                  # noqa: E402
import sst_anomalies as sa                                 # noqa: E402
from backfill_point_history import STATIONS, resolve_cell  # noqa: E402

HISTORY = HERE / 'folger_point_daily.csv'
OUTPUT = sst.DATA_DIR / 'sst_barkley_points.geojson'

NAME = 'Folger Passage'

# Plot A shows the record weekly, with the most recent week at full resolution. Seven
# days because that is what the archive holds; if N_DAYS ever changes this follows it.
DISPLAY_STRIDE_DAYS = 7
DAILY_TAIL_DAYS = 7

# Percentile thresholds for Plot B, matching sst_anomalies.plot_anomalies() so a reader
# who opens the figures and the map sees the same marks.
PERCENTILES = (90, 95, 99)


def read_history(path=HISTORY):
    """The committed daily series, plus the cell it was fetched for."""
    if not path.exists():
        raise FileNotFoundError(
            f'{path.name} is missing. It is produced once by backfill_point_history.py '
            'and committed; it is not rebuilt automatically because doing so costs '
            'minutes of NOAA time.')

    meta, header_lines = {}, []
    with open(path) as fh:
        for line in fh:
            if not line.startswith('#'):
                break
            header_lines.append(line)          # kept verbatim for save_history()
            key, _, value = line[1:].partition(':')
            meta[key.strip()] = value.strip()

    frame = pd.read_csv(path, comment='#')
    frame['date'] = pd.to_datetime(frame['date'], utc=True)
    return frame.sort_values('date'), meta, header_lines


def assert_same_cell(meta, cell_lat, cell_lon):
    """Refuse to build a series for a cell the archive no longer describes."""
    was = (float(meta['cell_lat']), float(meta['cell_lon']))
    now = (cell_lat, cell_lon)
    if not np.allclose(was, now, atol=1e-6):
        raise SystemExit(
            f'cell mismatch: {HISTORY.name} holds ({was[0]:.4f}, {was[1]:.4f}) but the '
            f'archive grid now resolves ({now[0]:.4f}, {now[1]:.4f}).\n'
            'The box or resolution has changed, so the stored history describes a '
            'different patch of ocean. Re-run backfill_point_history.py --force.')


def extend_from_archive(history, cell_lat, cell_lon):
    """Append any days the archive has that the history does not. No network.

    The result is written back to the CSV by save_history(), and that is not optional.
    The archive is a rolling seven-day window, so a day it holds today is gone from it
    next week. If the extension only lived in memory, every day between the end of the
    backfill and the current window would be seen once and then lost -- leaving a hole
    that grows by a day per run, silently, with nothing raising an error about it.
    """
    grid = sst.read_grid()
    variable = sst.variable_name(grid)
    lats, lons = grid['latitude'].values, grid['longitude'].values
    i = int(np.argmin(np.abs(lats - cell_lat)))
    j = int(np.argmin(np.abs(lons - cell_lon)))

    rows = [
        {'date': pd.Timestamp(day, tz='UTC'),
         'sst_c': float(grid[variable].values[k, i, j])}
        for k, day in enumerate(sst.dates(grid))
    ]
    fresh = pd.DataFrame(rows)
    fresh = fresh[np.isfinite(fresh['sst_c'])]

    combined = pd.concat([history, fresh], ignore_index=True)
    # Archive wins on a shared date: it is the same product, but a value revised
    # upstream since the backfill should not be pinned to the older copy.
    combined = (combined.sort_values('date')
                        .drop_duplicates('date', keep='last')
                        .reset_index(drop=True))
    added = len(combined) - len(history)
    return combined, added


def save_history(series, header_lines, path=HISTORY):
    """Write the extended series back, preserving the backfill's header verbatim.

    The header records which cell the series describes and how the backfill sampled it,
    and assert_same_cell() reads it on every run. Rewriting the file without it would
    disarm that check, so the original lines are carried through unchanged rather than
    regenerated -- this function has no business deciding what the cell is.
    """
    out = series.copy()
    out['date'] = pd.to_datetime(out['date'], utc=True).dt.strftime('%Y-%m-%d')
    with open(path, 'w') as handle:
        handle.writelines(header_lines)
        out.to_csv(handle, index=False)
    return len(out)


def display_series(series, stride=DISPLAY_STRIDE_DAYS, tail=DAILY_TAIL_DAYS):
    """Plot A's data: the record at weekly spacing, with the last week left daily.

    The backfilled years are already weekly, so the stride only thins the recent daily
    stretch -- which grows by a day per run and would otherwise slowly crowd the plot.
    """
    series = series.sort_values('date')
    cutoff = series['date'].max() - pd.Timedelta(days=tail)
    older, recent = series[series['date'] <= cutoff], series[series['date'] > cutoff]

    keep, last = [], None
    for _, row in older.iterrows():
        if last is None or (row['date'] - last).days >= stride:
            keep.append(row)
            last = row['date']

    out = pd.concat([pd.DataFrame(keep), recent], ignore_index=True)
    return out.sort_values('date').reset_index(drop=True)


def build(series, cell_lat, cell_lon, bounds):
    """The FeatureCollection, self-describing enough that a consumer imports nothing."""
    daily = sa.daily_frame(series['date'], series['sst_c'])
    monthly = sa.to_monthly(daily, drop_partial_end=False)
    anom = sa.anomalies(monthly)
    clim = sa.climatology(monthly)

    # The month the record stops inside is incomplete by definition, and this file is
    # rebuilt every run, so it creeps upward all month. Flagged rather than dropped:
    # a reader should see the current month, but not mistake it for a finished one.
    last_day = series['date'].max()
    # .replace(day=1) rather than .to_period('M').start_time: to_period drops the
    # timezone on a tz-aware value and warns about it, which is the same trap
    # sst_anomalies.to_monthly() documents avoiding a few lines from here.
    in_progress = last_day.normalize().replace(day=1)

    thresholds = {p: float(anom['anom_C'].dropna().quantile(p / 100)) for p in PERCENTILES}

    display = display_series(series)

    return {
        'type': 'FeatureCollection',
        'features': [{
            'type': 'Feature',
            # GeoJSON is [lon, lat] -- the reverse of how it is said aloud.
            'geometry': {'type': 'Point', 'coordinates': [cell_lon, cell_lat]},
            'properties': {
                'id': 'folger-passage',
                'name': NAME,
                'stations': STATIONS,
                'cell': {'lat': cell_lat, 'lon': cell_lon, **bounds},
                'daily': [
                    {'date': d.strftime('%Y-%m-%d'), 'sst_C': round(float(v), 2)}
                    for d, v in zip(display['date'], display['sst_c'])
                    if np.isfinite(v)
                ],
                'monthly': [
                    {'month': m.strftime('%Y-%m'),
                     'mean_C': None if pd.isna(r['temperature_C']) else round(float(r['temperature_C']), 2),
                     'n': int(r['n']),
                     'ok': bool(r['ok']),
                     'clim_C': None if pd.isna(r['clim_C']) else round(float(r['clim_C']), 2),
                     'anom_C': None if pd.isna(r['anom_C']) else round(float(r['anom_C']), 2),
                     'partial': bool(m == in_progress)}
                    for m, r in anom.iterrows()
                ],
                'climatology': [
                    {'calendar_month': int(m),
                     'clim_C': None if pd.isna(r['clim_C']) else round(float(r['clim_C']), 2),
                     'std_C': None if pd.isna(r['std_C']) else round(float(r['std_C']), 2),
                     'n_years': int(0 if pd.isna(r['n_years']) else r['n_years'])}
                    for m, r in clim.iterrows()
                ],
                'anomaly_thresholds': {str(p): round(v, 2) for p, v in thresholds.items()},
            },
        }],
        'properties': {
            'title': f'Satellite SST history at {NAME}',
            'units': 'degree_C',
            'record': [series['date'].min().strftime('%Y-%m-%d'),
                       last_day.strftime('%Y-%m-%d')],
            # A calendar month with no usable data at all comes back NaN from
            # climatology(), so fill before casting rather than letting int() raise.
            'baseline': (f'{series["date"].min():%Y-%m-%d} to {last_day:%Y-%m-%d}, '
                         f'{int(clim["n_years"].fillna(0).min())}-'
                         f'{int(clim["n_years"].fillna(0).max())} '
                         'years per calendar month'),
            'baseline_caveat': (
                'A climatology over 6-8 years, not the 30 the WMO standard assumes. '
                'Treat anomalies as indicative of this record, not of the climate.'),
            'sampling': (
                'Backfilled years are sampled weekly (~4 values per month); days from '
                'the rolling archive are daily (~30). Means are unbiased either way, '
                'but precision differs -- read n alongside each month.'),
            'cell_caveat': (
                f'One {abs(bounds["lat_range"][1] - bounds["lat_range"][0]) * 111:.1f} x '
                f'{abs(bounds["lon_range"][1] - bounds["lon_range"][0]) * 111 * 0.66:.1f} km '
                'cell covers both Folger stations, which are 611 m apart. The marker '
                'sits at the cell centre, on neither instrument.'),
            'depth_caveat': (
                'A skin-temperature analysis of the surface. The stations sit at 23 m '
                'and ~96 m; this is not a proxy for what they record.'),
            'source_caveat': sst.SOURCE_CAVEAT,
            'plot_a': 'daily -- raw SST, weekly through the record, last 7 days daily',
            'plot_b': 'monthly -- anom_C against clim_C, thresholds in anomaly_thresholds',
        },
    }


def main():
    cell_lat, cell_lon, bounds = resolve_cell()
    history, meta, header_lines = read_history()
    assert_same_cell(meta, cell_lat, cell_lon)

    series, added = extend_from_archive(history, cell_lat, cell_lon)

    # Persist before building. The archive's window rolls, so a day not written here is
    # a day gone for good -- see the note on extend_from_archive().
    save_history(series, header_lines)

    layer = build(series, cell_lat, cell_lon, bounds)
    OUTPUT.write_text(json.dumps(layer, separators=(',', ':')))

    props = layer['features'][0]['properties']
    meta_props = layer['properties']
    print(f'wrote {OUTPUT.name}  ({OUTPUT.stat().st_size / 1024:.0f} kB)')
    print(f'  cell ({cell_lat:.4f}, {cell_lon:.4f}) -- {NAME}')
    print(f'  history {meta_props["record"][0]} to {meta_props["record"][1]} '
          f'({len(series)} values, {added} new from the archive)')
    print(f'  plot A: {len(props["daily"])} points')
    print(f'  plot B: {len(props["monthly"])} months, '
          f'{sum(1 for m in props["monthly"] if m["ok"])} usable')
    print(f'  baseline: {meta_props["baseline"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
