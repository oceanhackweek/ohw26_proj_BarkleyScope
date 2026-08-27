"""Fetch a rolling window of satellite sea surface temperature over Barkley Sound.

WHAT THIS IS
    Companion to PartII_API_Access.ipynb. That notebook pulls *point* measurements
    from Ocean Networks Canada's instruments -- a CTD on the seafloor at Folger
    Pinnacle, say, reporting one temperature at one place. This script pulls the
    *gridded* counterpart: a satellite analysis giving a temperature for every cell
    of a lat/lon grid across the whole region, once per day.

    The two are complementary. ONC tells you what the water is actually doing at a
    handful of points; the satellite tells you the spatial pattern but never quite
    measures the water itself (see RESOLUTION CAVEAT below).

HOW IT GETS THE DATA
    Through ERDDAP, the same style of data server the ONC notebook talks to, but
    NOAA's rather than ONC's. ERDDAP exposes two flavours of dataset:

      tabledap  -- rows of observations (stations, buoys, ship tracks)
      griddap   -- n-dimensional arrays on a regular grid  <-- what we use here

    A griddap request is just a URL. You name the variable, then constrain each of
    its dimensions in square brackets, and the server returns only that subset --
    so we never download the global field just to keep a corner of it.

WHAT IT PRODUCES
    One netCDF file holding the last N_DAYS of data over the bounding box, with a
    'source' coordinate recording where each day came from. The file is rewritten
    whole on each run rather than appended to; at this size that is far simpler
    than append machinery and has no meaningful cost.

OPERATIONAL BEHAVIOUR
    Written to run daily from cron:
      - Idempotent. If the output already holds the target days it exits without
        touching the network, so running it hourly is harmless.
      - Fails safe. On any network error it exits non-zero and leaves the previous
        output untouched, so a consumer keeps serving stale-but-valid data rather
        than being handed an empty or half-written file.

CHOOSING THE PRODUCT
    The default is the NOAA Geo-polar blend at ~5 km, chosen by measurement rather
    than by specification -- see compare_resolutions.py and same_day_check.py.

    Two results worth not rediscovering. OISST at 0.25 degrees puts exactly TWO ocean
    cells inside Barkley Sound; a cell there is larger than the sound, so Bamfield,
    Cape Beale and Folger Pinnacle all collapse into the same pair. And MUR at ~1 km,
    despite 21x as many pixels, carries about a seventh of the blend's spatial
    variability there -- it is a gap-filled analysis that interpolates near coastlines,
    so its detail is smooth fiction. The blend sits where resolution still tracks
    signal.

USAGE
    python fetch_sst_barkley.py              # top up if stale, else do nothing
    python fetch_sst_barkley.py --force      # refetch regardless
    python fetch_sst_barkley.py --verbose    # log every request URL
"""

import argparse
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests          # plain HTTP: the griddap URLs are simple enough to build
import xarray as xr      # reads the returned netCDF into labelled arrays

# NOTE ON erddapy: the erddapy library exists to build these URLs for you, and is
# installed here, but version 3.3.0 in this environment has an internal rename that
# breaks dependent packages. The URL construction we need is a few lines of f-string,
# so we do it directly and carry no dependency on that library's API stability.


# ===========================================================================
# CONFIGURATION -- this is the part you edit
# ===========================================================================

# --- Which product to pull -------------------------------------------------
#
# Every ERDDAP dataset has its own quirks, and those quirks reach into the query
# itself -- the number of axes, the longitude convention, the variable's name. So
# rather than scatter them through the code, each product is described once here
# and the query builder adapts. Switching products means changing ACTIVE_SOURCE
# and nothing else.
#
# Keys in each preset:
#
#   server      Base URL of the ERDDAP server. Products live on different servers;
#               NOAA runs several and they do not carry the same holdings.
#
#   datasets    {label: dataset_id}. Some products publish twice: a quick
#               'prelim' release, then a quality-controlled 'final' one weeks
#               later. List both and 'final' wins for any date carried by both.
#               Single-release products just list one entry.
#
#   variable    Name of the SST variable *inside* the dataset. Not standardised --
#               OISST calls it 'sst', the L4 analyses call it 'analysed_sst'.
#
#   depth_axis  True if the grid carries a size-1 vertical axis. This matters
#               because a griddap query must constrain every dimension in order:
#               get the count wrong and the request is rejected. OISST has a
#               vestigial depth axis (always 0.0 m); the L4 products do not.
#
#   lon_360     True if longitudes run 0-360 instead of -180/180. Barkley Sound is
#               -125 in one convention and 235 in the other. Query the wrong one
#               and you get a valid, empty response from the far side of the globe.
#
#   resolution  Nominal grid spacing in degrees. Reference only -- nothing reads
#               it -- but it is the number that decides whether a product can see
#               the feature you care about.

SOURCES = {
    # VERIFIED against the live server: returns real data over this box.
    # 0.25 deg. Too coarse for the sound itself (see RESOLUTION CAVEAT above),
    # but it renders the shelf upwelling gradient clearly.
    # Two-stage publication: 'final' runs ~16 days behind, 'prelim' ~5 days.
    'oisst': {
        'server': 'https://www.ncei.noaa.gov/erddap',
        'datasets': {
            'final': 'ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon',
            'prelim': 'ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon',
        },
        'variable': 'sst',
        'depth_axis': True,
        'lon_360': True,
        'resolution': 0.25,
    },

    # VERIFIED 2026-08-26 and the product this project uses. NOAA Geo-polar blended,
    # ~5 km, ~2 days behind. 1,220 ocean cells over the box, 57 of them inside Barkley
    # Sound, against OISST's 2.
    #
    # An earlier trial reported this returning empty. It was not empty -- the request
    # was refused. coastwatch.pfeg.noaa.gov redirects to coastwatch.noaa.gov, which
    # answers the default python-requests user-agent with 403. See HEADERS below.
    #
    # NOAA is migrating this ERDDAP, and the redirect renames the dataset as it goes:
    #     coastwatch.pfeg.noaa.gov/.../nesdisBLENDEDsstDNDaily   (what we request)
    #  -> coastwatch.noaa.gov/.../noaacwBLENDEDsstDNDaily        (where it lands)
    # Observed 2026-08-27, when the new host returned 503 for several hours while the
    # old host still served metadata. Retries and the fail-safe cover an outage like
    # that. What they cannot cover is the old id being retired: if this preset starts
    # failing permanently, try server 'https://coastwatch.noaa.gov/erddap' with dataset
    # 'noaacwBLENDEDsstDNDaily' before assuming the product is gone.
    #
    # Chosen over the finer mur1km deliberately; see that entry.
    'blended5km': {
        'server': 'https://coastwatch.pfeg.noaa.gov/erddap',
        'datasets': {'final': 'nesdisBLENDEDsstDNDaily'},
        'variable': 'analysed_sst',
        'depth_axis': False,
        'lon_360': False,
        'resolution': 0.05,
    },

    # VERIFIED to work, and deliberately NOT used. MUR L4, ~1 km, ~1 day behind, 1,220
    # ocean cells inside the sound -- 21x the blend's.
    #
    # Those extra pixels are interpolation, not signal. Measured over the sound on the
    # same day (2026-08-24), MUR's spatial standard deviation is 0.159 C against the
    # blend's 1.087 C, and its whole range across the sound is 0.67 C. MUR is a
    # gap-filled analysis: near a coastline it fills rather than measures, so it renders
    # as a smooth, confident, nearly uniform field. Finer is not better here.
    #
    # Re-run same_day_check.py before reconsidering this.
    'mur1km': {
        'server': 'https://coastwatch.pfeg.noaa.gov/erddap',
        'datasets': {'final': 'jplMURSST41'},
        'variable': 'analysed_sst',
        'depth_axis': False,
        'lon_360': False,
        'resolution': 0.01,
    },
}

# Pick one of the keys above.
ACTIVE_SOURCE = 'blended5km'


# --- Region ----------------------------------------------------------------
# Barkley Sound and the Juan de Fuca approaches: the envelope of the two corner
# pairs defining the map area. Always written in -180/180 here regardless of what
# the active product uses; to_query_lon() converts on the way out, so this stays
# readable and you never have to think in 0-360.
MIN_LON, MAX_LON = -126.8, -124.5
MIN_LAT, MAX_LAT = 47.85, 49.36

# --- Retention -------------------------------------------------------------
# How many time steps to keep. These are the most recent *available* steps, not
# calendar days. The distinction matters: satellite products publish days behind
# real time, so asking for "today minus 7" would return a mostly or entirely
# empty file. Asking for "the 7 newest that exist" always yields 7 maps.
N_DAYS = 7

# --- Output ----------------------------------------------------------------
# Written to the shared data/ directory, one level up from this script, so the map
# app's config resolves every dataset it needs from a single location -- the same
# place cproof_glider_realtime.nc lives.
#
# The preset name is recorded INSIDE the file (source_preset) rather than in the
# filename. A product switch changes the grid, and the staleness check below compares
# dates rather than geometry, so a stale file from another product would look current.
# read_grid() in barkley_sst.py checks source_preset for exactly that reason.
OUT = Path(__file__).resolve().parent.parent / 'sst_barkley_realtime.nc'

# --- Network behaviour -----------------------------------------------------
TIMEOUT = 120    # seconds per request; generous, ERDDAP can be slow under load
RETRIES = 3      # attempts before giving up, with exponential backoff between

# Pause between successive day-requests. ERDDAP's own admin documentation asks that a
# script making a series of requests "be considerate of other users by putting a small
# pause (2 seconds?) in the script between requests", and its blacklist exists for
# clients that ignore that. Seven requests are hardly a large number, but this runs
# unattended from GitHub Actions -- shared runner IPs, where we are pooled with every
# other Actions user hitting the same server -- so the cost of being conspicuous is not
# ours alone to bear. Fourteen seconds on a refresh day is not worth arguing about.
PAUSE = 2.0

# NOAA CoastWatch -- where coastwatch.pfeg.noaa.gov now redirects -- rejects the default
# python-requests user-agent outright with 403 Forbidden. That failure is easy to
# misread as "this product has no data over our box", because a 403 arrives looking much
# like any other bad response. A descriptive agent gets past it and, more to the point,
# identifies this client to the people running a free public server.
HEADERS = {
    'User-Agent': 'BarkleyScope/1.0 (OceanHackWeek 2026; '
                  '+https://github.com/oceanhackweek/ohw26_proj_BarkleyScope)',
}

log = logging.getLogger('oisst')


# ===========================================================================
# HELPERS
# ===========================================================================

def source():
    """Return the active preset from SOURCES.

    Looked up on each call rather than captured in a module-level constant, so a
    test (or an interactive session) can reassign ACTIVE_SOURCE and have every
    function follow immediately.
    """
    try:
        return SOURCES[ACTIVE_SOURCE]
    except KeyError:
        # A typo here would otherwise surface as a confusing failure much later.
        raise SystemExit(
            f'ACTIVE_SOURCE={ACTIVE_SOURCE!r} is not in SOURCES '
            f'(choose from {", ".join(sorted(SOURCES))})'
        )


def to_query_lon(lon):
    """Convert a -180/180 longitude to whatever convention the active product uses.

    Python's % on a negative float returns a positive result (-125.5 % 360 == 234.5),
    which is exactly the mapping we want.
    """
    return lon % 360 if source()['lon_360'] else lon


def to_180(lon):
    """Convert a 0-360 longitude back to -180/180 for downstream consumers.

    Mapping tools almost universally expect -180/180, so whatever we queried in,
    the output file is normalised to this convention.
    """
    return ((lon + 180) % 360) - 180


def get(url, **kwargs):
    """HTTP GET with retries, so one transient blip doesn't fail the nightly run.

    Backs off 2s then 4s between attempts. Raises the underlying requests
    exception if every attempt fails -- callers decide what that means.
    """
    kwargs.setdefault('headers', HEADERS)
    for attempt in range(1, RETRIES + 1):
        try:
            response = requests.get(url, timeout=TIMEOUT, **kwargs)
            response.raise_for_status()      # turn 4xx/5xx into an exception
            return response
        except requests.RequestException as err:
            if attempt == RETRIES:
                raise
            wait = 2 ** attempt
            log.warning('attempt %d/%d failed (%s), retrying in %ds',
                        attempt, RETRIES, err, wait)
            time.sleep(wait)


def available_times(dataset_id):
    """Return a dataset's time axis as a sorted list of pandas Timestamps.

    We ask the server what days exist rather than assuming. Publication is not
    reliably daily -- products skip days, run late, and the preliminary ones roll
    off the back as they age.

    Requesting a coordinate variable with no constraints returns just that axis,
    a few kB, which is far cheaper than probing with data requests to discover
    what has been published.
    """
    url = f'{source()["server"]}/griddap/{dataset_id}.csv?time'
    lines = get(url).text.splitlines()

    # ERDDAP's CSV carries two header rows, not one: the column name, then the
    # units. Hence [2:] rather than the usual [1:].
    times = [pd.Timestamp(line) for line in lines[2:] if line.strip()]

    log.debug('%s: %d steps, %s to %s',
              dataset_id, len(times), times[0], times[-1])
    return sorted(times)


def candidate_steps():
    """List (timestamp, label) newest first, preferring final over preliminary.

    Where a product publishes twice, the same date can exist in both datasets with
    different values -- preliminary first, quality-controlled later. We want the
    better one whenever it exists.

    Worth knowing: under a 7-day retention window the final product will never
    actually appear, because a date ages out of the window roughly nine days
    before its final version is published. The preference costs almost nothing and
    keeps the script correct if the publication lag shrinks or N_DAYS grows.
    """
    by_date = {}
    datasets = source()['datasets']

    # Iterate with 'final' last so its entry overwrites any preliminary one for
    # the same date. sorted() puts False before True, so the key expression
    # `name == 'final'` sorts every other label ahead of 'final'.
    for label in sorted(datasets, key=lambda name: name == 'final'):
        try:
            for timestamp in available_times(datasets[label]):
                by_date[timestamp.date()] = (timestamp, label)
        except requests.RequestException as err:
            # One dataset being unreachable should not sink the run if another
            # answers -- degraded output beats no output for a daily job.
            log.warning('could not read time axis for %s: %s', datasets[label], err)

    if not by_date:
        raise RuntimeError('no dataset returned a time axis')

    return [by_date[date] for date in sorted(by_date, reverse=True)]


def fetch_step(label, timestamp):
    """Download one time step over the bounding box and return it as a Dataset.

    ON THE QUERY SYNTAX
        griddap constrains each dimension in square brackets, in the dataset's own
        dimension order. The critical subtlety is what goes inside:

            [0:10]       -- by array index: the first eleven cells
            [(48.5)]     -- by coordinate VALUE: the cell nearest latitude 48.5
            [(a):(b)]    -- by coordinate range

        The parentheses are what distinguish the two, and getting it wrong fails
        silently in the worst way: [(2026-08-20T12:00:00Z)] asks for that instant,
        while [2026] would be read as index 2026 and return an unrelated day.

    ONE REQUEST PER DAY, NOT ONE PER RANGE
        A single request could fetch the whole date range at once. We deliberately
        don't, for two reasons: days may come from different datasets (prelim vs
        final), and each day must be inspected individually so an unfilled one can
        be skipped and replaced by the next one back. At this size the extra
        round-trips cost far less than the added logic to slice a range apart.
    """
    src = source()
    stamp = timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Every dimension must be constrained, in order. OISST carries a vestigial
    # depth axis; the L4 products have only (time, lat, lon). Emitting the wrong
    # number of brackets gets the request rejected outright.
    depth_constraint = '[(0.0)]' if src['depth_axis'] else ''

    query = (
        f'{src["variable"]}'
        f'[({stamp})]'                                              # time
        f'{depth_constraint}'                                       # depth, maybe
        f'[({MIN_LAT}):({MAX_LAT})]'                                # latitude
        f'[({to_query_lon(MIN_LON)}):({to_query_lon(MAX_LON)})]'    # longitude
    )
    url = f'{src["server"]}/griddap/{src["datasets"][label]}.nc?{query}'
    log.debug('GET %s', url)

    content = get(url).content

    # ERDDAP returns netCDF-3, which xarray cannot open from an in-memory buffer
    # with the default engine. Write it to a temp file, read it, then load() to
    # pull the values into memory so the file can be deleted immediately -- without
    # load() the array stays lazily bound to a file we are about to unlink.
    with tempfile.NamedTemporaryFile(suffix='.nc', delete=False) as handle:
        handle.write(content)
        temp_path = handle.name
    try:
        with xr.open_dataset(temp_path) as raw:
            ds = raw.load()
    finally:
        os.unlink(temp_path)       # runs even if opening raised

    # Drop the size-1 vertical dimension so downstream code sees a clean
    # (time, lat, lon) array. Matched by SIZE rather than by name deliberately:
    # the dataset id advertises "zlev" but the served variable calls it "depth",
    # and a name-based match would quietly fail to strip it.
    for dim, size in list(ds.sizes.items()):
        if size == 1 and dim not in ('time', 'latitude', 'longitude'):
            ds = ds.squeeze(dim, drop=True)

    # Stash the URL so assemble() can record exactly what was requested. Carried
    # as a data variable because that survives the concat; dropped afterwards.
    ds['queryUrl'] = url
    return ds


def is_filled(ds):
    """True if this step carries any actual data.

    A time step can appear on the axis before its values are written -- the
    newest preliminary step is sometimes an entirely empty grid. It is a real
    response, not an error, so nothing else catches it. Writing it would give a
    consumer a blank top frame: the most recent map, and therefore the one most
    likely to be looked at, showing nothing.

    Note this tests for ANY finite value, not all of them. A normal step over this
    box is legitimately ~23% NaN, because those cells are land.
    """
    values = ds[source()['variable']].values
    return bool(np.isfinite(values).any())


def collect(steps):
    """Fetch newest-first until N_DAYS filled steps are in hand.

    Walking newest-first and stopping at N_DAYS means an unfilled or missing day
    is absorbed by reaching one day further back, rather than leaving a hole or
    returning a short file.
    """
    collected = []
    for index, (timestamp, label) in enumerate(steps):
        if len(collected) == N_DAYS:
            break

        # Not before the first request, and not after the last: the pause is there to
        # space requests out, not to pad the run.
        if index:
            time.sleep(PAUSE)

        ds = fetch_step(label, timestamp)

        if not is_filled(ds):
            log.info('skipping %s (%s): all cells empty', timestamp.date(), label)
            continue

        # Record which dataset this day came from, as a coordinate along time.
        # This rides with the data rather than sitting in a sidecar file, so a
        # consumer can caption each day accurately -- 'preliminary' values carry a
        # real caveat and should be labelled as such wherever they are displayed.
        ds = ds.assign_coords(source=('time', [label]))

        log.info('fetched %s (%s)', timestamp.date(), label)
        collected.append(ds)

    # Short is not fatal -- a consumer can show five days as easily as seven --
    # but it is worth surfacing, since it usually means a product is publishing
    # late or has stopped.
    if len(collected) < N_DAYS:
        log.warning('only %d of %d requested steps were available',
                    len(collected), N_DAYS)
    if not collected:
        raise RuntimeError('no usable time steps found')

    return collected


def assemble(collected):
    """Concatenate the daily steps into one Dataset and attach provenance."""
    # Lift the per-step query URLs out before concatenating, then drop them: they
    # belong in the file's metadata, not as a data variable alongside the SST.
    urls = [str(ds['queryUrl'].values) for ds in collected]
    collected = [ds.drop_vars('queryUrl') for ds in collected]

    src = source()

    # Steps arrive newest-first (collect walks backwards); sort so the file's time
    # axis is ascending, which is what every downstream tool assumes.
    ds = xr.concat(collected, dim='time').sortby('time')

    # Normalise longitudes to -180/180 whatever we queried in, so the output
    # contract stays identical across products and a consumer never has to branch
    # on which source produced the file. Re-sort afterwards: the conversion can
    # leave the axis non-monotonic if a box straddles the antimeridian.
    if src['lon_360']:
        ds = ds.assign_coords(longitude=to_180(ds['longitude']))
        ds = ds.sortby('longitude')
        ds['longitude'].attrs.update(
            units='degrees_east',
            long_name='Longitude',
            comment='converted from the 0-360 axis served by ERDDAP',
        )

    # Provenance. Anyone opening this file months from now should be able to see
    # what it is, where it came from, and reconstruct the exact requests.
    ds.attrs['source_preset'] = ACTIVE_SOURCE
    ds.attrs['history'] = (
        f'{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}: '
        f'fetched by fetch_sst_barkley.py from {src["server"]}'
    )
    ds.attrs['queryUrls'] = '\n'.join(urls)

    # Recompute the geospatial bounds from the converted axis; the values
    # inherited from the server describe the 0-360 version and would be wrong.
    ds.attrs['geospatial_lon_min'] = float(ds['longitude'].min())
    ds.attrs['geospatial_lon_max'] = float(ds['longitude'].max())
    return ds


def write_atomic(ds, path):
    """Write via a temp file and rename, so a reader never sees a partial file.

    ON THE ENCODING
        Values are stored as int16 with a scale factor rather than as float32.
        The reader multiplies by scale_factor on the way out, so 1583 becomes
        15.83 degrees C. This halves the size versus float32 and costs nothing
        real: 0.01 C is far finer than the accuracy of any SST analysis.

        Range check: int16 spans -32768..32767, so at 0.01 C the representable
        range is +/- 327 C. Sea temperatures use a sliver of it.

        _FillValue is the sentinel for land and missing data, and must sit outside
        the range of genuine values -- -32768 decodes to -327.68 C, which no
        real measurement will ever collide with.

    ON THE ATOMICITY
        A consumer may read this file at any moment, including midway through a
        write. os.replace() is atomic on POSIX: the path points at either the old
        complete file or the new complete file, never at a partial one. Writing
        directly to `path` would expose a window where it is truncated garbage.
    """
    encoding = {
        source()['variable']: {
            'zlib': True,            # netCDF-4 internal compression
            'complevel': 4,          # 1..9; 4 is the usual sweet spot
            'dtype': 'int16',
            'scale_factor': 0.01,    # stored value * 0.01 = degrees C
            'add_offset': 0.0,
            '_FillValue': -32768,
        },
    }
    temp_path = path.with_suffix('.tmp')
    ds.to_netcdf(temp_path, encoding=encoding)
    os.replace(temp_path, path)


def current_state(path):
    """Return {date: source_label} for the existing output, or None if unusable.

    This is what makes the script idempotent. Comparing what is on disk against
    what the server currently offers lets a scheduled run exit immediately when
    there is nothing new, so it can be scheduled generously without hammering
    the server or burning bandwidth on identical data.

    A corrupt or unreadable file returns None rather than raising -- the right
    response to "I cannot read what I wrote last time" is to fetch it again.
    """
    if not path.exists():
        return None
    try:
        with xr.open_dataset(path) as ds:
            times = pd.to_datetime(ds['time'].values)
            sources = [str(value) for value in ds['source'].values]
            return dict(zip((t.date() for t in times), sources))
    except (OSError, KeyError, ValueError) as err:
        log.warning('could not read existing %s (%s); refetching', path.name, err)
        return None


# ===========================================================================
# ENTRY POINT
# ===========================================================================

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--force', action='store_true',
                        help='refetch even if the output is already current')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='log each request')
    args = parser.parse_args(argv)

    # Configure THIS logger, not the root one. logging.basicConfig() would set the
    # root level and every imported library inherits it -- turning on --verbose
    # would then bury our seven useful lines under matplotlib's font cache, zarr's
    # codec registry and urllib3's connection pool.
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    log.propagate = False

    # Step 1: ask the server what exists. Cheap, and needed either way -- both to
    # decide whether we are stale and to know what to fetch.
    try:
        steps = candidate_steps()
    except (requests.RequestException, RuntimeError) as err:
        log.error('could not determine what is published: %s', err)
        return 1

    # Step 2: compare against what we already have. Comparing the {date: source}
    # mapping rather than just dates means a day being upgraded from preliminary
    # to final correctly counts as a change worth refetching.
    wanted = {timestamp.date(): label for timestamp, label in steps[:N_DAYS]}
    existing = current_state(OUT)

    if existing is not None and existing == wanted and not args.force:
        log.info('%s is already current (%d steps, %s to %s); nothing to do',
                 OUT.name, len(existing), min(existing), max(existing))
        return 0

    # Step 3: fetch. Note what does NOT happen on failure -- no partial write, no
    # deletion of the previous output. A failed run leaves yesterday's good file
    # exactly where it was.
    try:
        collected = collect(steps)
    except (requests.RequestException, RuntimeError) as err:
        log.error('fetch failed: %s', err)
        if OUT.exists():
            log.error('leaving the previous %s in place', OUT.name)
        return 1

    # Step 4: assemble and write. Only now is the old file replaced.
    ds = assemble(collected)
    write_atomic(ds, OUT)

    times = pd.to_datetime(ds['time'].values)
    log.info('wrote %s: %d steps, %s to %s, %.1f kB',
             OUT.name, ds.sizes['time'], times.min().date(), times.max().date(),
             OUT.stat().st_size / 1024)
    return 0


if __name__ == '__main__':
    # Exit code carries the outcome to cron: 0 means fine (fetched or already
    # current), 1 means the run failed and the previous output is still in place.
    sys.exit(main())
