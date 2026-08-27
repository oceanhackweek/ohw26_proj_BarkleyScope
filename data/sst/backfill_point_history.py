"""Download the full SST history for one grid cell. RUN ONCE, BY HAND.

    ############################################################################
    #  DO NOT ADD THIS TO A WORKFLOW.                                          #
    #                                                                          #
    #  It is the only script in data/sst/ that asks NOAA for historical data,   #
    #  it takes minutes rather than seconds, and its output is committed. Once  #
    #  folger_point_daily.csv exists, export_points.py rebuilds everything      #
    #  downstream from it offline, and the daily job needs nothing from here.   #
    #                                                                          #
    #  Re-run it only to extend the record backwards or to add a station.       #
    ############################################################################

WHY A POINT SERIES IS THE EXPENSIVE SHAPE
    The map layer asks for one day over the whole box: one file, 1,536 cells. This asks
    the opposite -- one cell over thousands of days -- and the product stores one global
    file per day. So the server opens a file per timestep to return a single pixel from
    each. The response is tiny; the work behind it is not.

    Measured against the live server on 2026-08-27:

        30 days,  every day      11.1 s
        90 days,  every day      97.5 s   (one 502 retry)
        365 days, every day      FAILED   502 Proxy Error, all 3 attempts
        365 days, every 7th day  35.6 s   succeeded

    Unstrided, the full 7-year record extrapolates to about 47 minutes, and a single year
    already exceeds their proxy's patience. With STRIDE = 7 it is ~370 values in about
    four minutes. That is the whole reason this file samples weekly.

    (NOAA was mid-migration that day and also returning 503s, so a healthy server may do
    better. The stride result holds regardless -- cost tracks files opened, not bytes.)

ON NOT GETTING BLACKLISTED
    ERDDAP's documentation is blunt about what earns a ban: "Don't make multiple
    simultaneous requests or you will be blacklisted!" Every request here is sequential,
    one chunk at a time, with fetch_sst_barkley.PAUSE between them. Nothing is threaded.
    Chunking by year makes MORE requests than a single span would, but each is an
    ordinary size and none overlap -- which is the distinction that matters.

WHAT IT WRITES
    folger_point_daily.csv -- date, sst_c, and the cell's coordinates in a header
    comment. The coordinates are there so export_points.py can refuse to run if the
    archive's grid ever moves under it; a silently relocated series would look fine and
    describe the wrong patch of ocean.

USAGE
    python backfill_point_history.py                 # skips chunks already present
    python backfill_point_history.py --force         # refetch everything
    python backfill_point_history.py --dry-run       # print the requests, fetch nothing
"""

import argparse
import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import barkley_sst as sst                    # noqa: E402
import fetch_sst_barkley as fetch            # noqa: E402


# ---------------------------------------------------------------------------
# What to fetch
# ---------------------------------------------------------------------------

# Both ONC Folger stations, with the depths that make them different instruments --
# and, at this resolution, indistinguishable to a satellite. They are 611 m apart and
# land in the same 5 km cell, which is why there is one series here and not two.
STATIONS = [
    {'name': 'Folger Deep',     'lat': 48.81376, 'lon': -125.28078, 'depth_m': 96.5},
    {'name': 'Folger Pinnacle', 'lat': 48.80829, 'lon': -125.28150, 'depth_m': 23.0},
]

# The point the series describes. Taken as the mean of the stations rather than either
# one, because the cell is what is actually being sampled and neither station has a
# better claim to it. resolve_cell() snaps this to the grid.
TARGET_LAT = float(np.mean([s['lat'] for s in STATIONS]))
TARGET_LON = float(np.mean([s['lon'] for s in STATIONS]))

# Every 7th day. See the measurements above -- this is what makes the fetch feasible,
# and it costs about 0.19 degC of noise on a monthly mean against 0.07 for daily.
STRIDE = 7

# One request per calendar year. A 365-day span at stride 7 was measured at 35.6 s,
# comfortably inside TIMEOUT; the unstrided equivalent timed out.
CHUNK_YEARS = 1

OUTPUT = HERE / 'folger_point_daily.csv'


# ---------------------------------------------------------------------------

def resolve_cell(lat=TARGET_LAT, lon=TARGET_LON, grid=None):
    """Snap a coordinate to the archive's grid. Returns (cell_lat, cell_lon, bounds).

    Resolved from the live grid every time rather than hardcoded, because a cell INDEX
    is only meaningful for one box at one resolution. If either ever changes this
    follows; a stored index would quietly point somewhere else.
    """
    grid = sst.read_grid() if grid is None else grid
    lats, lons = grid['latitude'].values, grid['longitude'].values
    lat_edges, lon_edges = sst.cell_edges(lats), sst.cell_edges(lons)

    i = int(np.searchsorted(lat_edges, lat)) - 1
    j = int(np.searchsorted(lon_edges, lon)) - 1
    if not (0 <= i < len(lats) and 0 <= j < len(lons)):
        raise ValueError(f'({lat}, {lon}) falls outside the archive grid')

    return float(lats[i]), float(lons[j]), {
        'lat_range': [float(lat_edges[i]), float(lat_edges[i + 1])],
        'lon_range': [float(lon_edges[j]), float(lon_edges[j + 1])],
    }


def server_time_range():
    """The dataset's full time axis, so we fetch what exists rather than what we guess."""
    src = fetch.source()
    times = fetch.available_times(src['datasets']['final'])
    return times[0], times[-1]


def chunk_spans(start, end, years=CHUNK_YEARS):
    """Split [start, end] into calendar-year spans, oldest first."""
    spans, cursor = [], start
    while cursor <= end:
        stop = min(cursor + pd.DateOffset(years=years) - pd.Timedelta(days=1), end)
        spans.append((cursor, stop))
        cursor = stop + pd.Timedelta(days=1)
    return spans


def chunk_url(cell_lat, cell_lon, start, end, stride=STRIDE):
    """One griddap request: a strided time range at a single grid point.

    The [(a):stride:(b)] form is what makes this affordable -- it asks the server for
    every Nth timestep, so it opens a seventh of the files. Parentheses mean "by
    coordinate value"; without them the numbers would be read as array indices.
    """
    src = fetch.source()
    return (
        f'{src["server"]}/griddap/{src["datasets"]["final"]}.nc?'
        f'{src["variable"]}'
        f'[({start:%Y-%m-%d}T12:00:00Z):{stride}:({end:%Y-%m-%d}T12:00:00Z)]'
        f'[({cell_lat})][({cell_lon})]'
    )


def fetch_chunk(cell_lat, cell_lon, start, end):
    """Fetch one span and return it as a (date, sst_c) DataFrame."""
    response = fetch.get(chunk_url(cell_lat, cell_lon, start, end))
    with xr.open_dataset(io.BytesIO(response.content)) as ds:
        variable = fetch.source()['variable']
        values = np.asarray(ds[variable].values, dtype=float).ravel()
        dates = pd.to_datetime(ds['time'].values, utc=True)
    return pd.DataFrame({'date': dates.date, 'sst_c': values})


def read_existing(path=OUTPUT):
    """Whatever is already on disk, or an empty frame. Lets a failed run be resumed."""
    if not path.exists():
        return pd.DataFrame(columns=['date', 'sst_c'])
    frame = pd.read_csv(path, comment='#')
    frame['date'] = pd.to_datetime(frame['date']).dt.date
    return frame


def write_csv(frame, cell_lat, cell_lon, bounds, path=OUTPUT):
    """Write the series with the cell it describes recorded in a header comment.

    The coordinates are not decoration. export_points.py compares them against the
    archive's grid on every run and refuses to proceed if they disagree, so a changed
    box becomes a loud failure instead of a plausible graph of the wrong place.
    """
    frame = frame.sort_values('date').drop_duplicates('date', keep='last')
    stations = '; '.join(
        f'{s["name"]} ({s["lat"]},{s["lon"]},{s["depth_m"]}m)' for s in STATIONS)
    header = (
        f'# Daily SST for one grid cell of {fetch.ACTIVE_SOURCE}, written by '
        f'backfill_point_history.py\n'
        f'# cell_lat: {cell_lat}\n'
        f'# cell_lon: {cell_lon}\n'
        f'# lat_range: {bounds["lat_range"][0]},{bounds["lat_range"][1]}\n'
        f'# lon_range: {bounds["lon_range"][0]},{bounds["lon_range"][1]}\n'
        f'# stations: {stations}\n'
        f'# stride_days: {STRIDE}  -- backfill is weekly; see the module docstring\n'
    )
    with open(path, 'w') as fh:
        fh.write(header)
        frame.to_csv(fh, index=False)
    return frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--force', action='store_true',
                        help='refetch every chunk, ignoring what is already on disk')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the requests that would be made, and stop')
    args = parser.parse_args(argv)

    cell_lat, cell_lon, bounds = resolve_cell()
    print(f'cell: ({cell_lat:.4f}, {cell_lon:.4f})  '
          f'lat {bounds["lat_range"][0]:.3f}..{bounds["lat_range"][1]:.3f}  '
          f'lon {bounds["lon_range"][0]:.3f}..{bounds["lon_range"][1]:.3f}')
    for station in STATIONS:
        print(f'  covers {station["name"]:16} ({station["lat"]}, {station["lon"]}) '
              f'{station["depth_m"]} m')

    start, end = server_time_range()
    spans = chunk_spans(start, end)
    print(f'\nserver holds {start:%Y-%m-%d} to {end:%Y-%m-%d} '
          f'-- {len(spans)} chunks at stride {STRIDE}')

    if args.dry_run:
        for a, b in spans:
            print(f'  {a:%Y-%m-%d} .. {b:%Y-%m-%d}')
            print(f'    {chunk_url(cell_lat, cell_lon, a, b)}')
        return 0

    existing = pd.DataFrame(columns=['date', 'sst_c']) if args.force else read_existing()
    have = set(existing['date'])
    collected = [existing] if len(existing) else []

    failures = 0
    for index, (a, b) in enumerate(spans):
        # Resume rather than restart: a span whose dates are already on disk is skipped,
        # so a run that died halfway does not re-ask for what it already got.
        if not args.force and have and all(
                d in have for d in pd.date_range(a, b, freq=f'{STRIDE}D').date):
            print(f'  [{index + 1}/{len(spans)}] {a:%Y-%m-%d}..{b:%Y-%m-%d}  already present')
            continue

        if index:
            time.sleep(fetch.PAUSE)          # sequential and unhurried, by design

        clock = time.perf_counter()
        try:
            chunk = fetch_chunk(cell_lat, cell_lon, a, b)
        except Exception as err:                                  # noqa: BLE001
            # Keep going. One bad span should not discard the years that worked, and
            # the next run resumes from whatever this one managed to save.
            failures += 1
            print(f'  [{index + 1}/{len(spans)}] {a:%Y-%m-%d}..{b:%Y-%m-%d}  '
                  f'FAILED after {time.perf_counter() - clock:.0f}s -- {err}')
            continue

        collected.append(chunk)
        print(f'  [{index + 1}/{len(spans)}] {a:%Y-%m-%d}..{b:%Y-%m-%d}  '
              f'{len(chunk):4d} values in {time.perf_counter() - clock:5.1f}s')

    if not collected:
        print('\nnothing fetched; leaving any existing file alone')
        return 1

    frame = write_csv(pd.concat(collected, ignore_index=True), cell_lat, cell_lon, bounds)
    finite = int(frame['sst_c'].notna().sum())
    print(f'\nwrote {OUTPUT.name}: {len(frame)} rows, {finite} with data, '
          f'{frame["date"].min()} to {frame["date"].max()}')
    if failures:
        print(f'{failures} chunk(s) failed -- re-run to fill them in; '
              f'what succeeded is saved')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
