"""Compare the three SST products over the Barkley box, at the pixel level.

WHY THIS EXISTS
    fetch_sst_barkley.py ships three presets in SOURCES, but only 'oisst' has ever
    been confirmed against the live server. The other two are the candidates for
    actually resolving Barkley Sound, and the choice between them is not a detail:
    the winner becomes the dataset committed to data/, which the map app's config
    points at. Picking wrong means redoing the dataset.

    Two things need answering, and neither can be answered from a spec sheet:

      1. Does the product carry data over THIS box? A trial query against
         'blended5km' previously came back empty. An empty ERDDAP response is a
         valid response, not an error, so nothing raises -- you have to look.

      2. How many pixels land inside the sound itself? This is the question the
         handoff calls blocking. At 0.25 degrees the answer is two, and every site
         of interest collapses into them.

WHAT IT DOES
    For each preset: reads the time axis, reports the publication lag, then walks
    newest-first until it finds a step that actually carries data, and saves that
    step next to this script so every downstream step is offline.

    Nothing here re-implements query building -- it drives fetch_sst_barkley's own
    functions by reassigning ACTIVE_SOURCE, which that module's source() explicitly
    supports ("so a test can reassign ACTIVE_SOURCE and have every function follow").

USAGE
    python compare_resolutions.py            # all three presets
    python compare_resolutions.py mur1km     # just one
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')            # argopy/erddapy import noise, see HANDOFF

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_sst_barkley as f              # noqa: E402

# Barkley Sound proper -- not the wider fetch box, which deliberately reaches out onto
# the shelf for context. These bounds enclose the sound's mouth and interior, and the
# three sites the project actually cares about:
SOUND = {'lon': (-125.55, -124.95), 'lat': (48.72, 49.05)}
SITES = {
    'Bamfield':        (48.835, -125.135),
    'Cape Beale':      (48.786, -125.213),
    'Folger Pinnacle': (48.814, -125.281),
}

# How far back to walk before giving up on finding a populated step. The newest step
# of a preliminary product is routinely present-but-empty; five is comfortably enough.
MAX_PROBES = 5


def probe(preset):
    """Fetch the newest populated step for one preset. Returns a dict of findings."""
    f.ACTIVE_SOURCE = preset                 # every f.* function follows this
    src = f.SOURCES[preset]
    out = {'preset': preset, 'resolution': src['resolution'], 'error': None}

    try:
        steps = f.candidate_steps()
    except Exception as err:
        out['error'] = f'could not read time axis: {err}'
        return out

    newest, label = steps[0]
    # ERDDAP time axes parse as tz-aware (the values end in 'Z'); drop the zone so this
    # subtracts cleanly against a naive 'today' rather than raising.
    naive = newest.tz_localize(None) if newest.tz is not None else newest
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    out['newest'] = naive.date()
    out['lag_days'] = (today - naive.normalize()).days
    out['label'] = label
    out['n_steps'] = len(steps)

    # Walk back until something carries data. An empty newest step is normal, not a fault.
    for timestamp, label in steps[:MAX_PROBES]:
        try:
            ds = f.fetch_step(label, timestamp)
        except Exception as err:
            out['error'] = f'fetch failed for {timestamp.date()}: {err}'
            return out
        if f.is_filled(ds):
            out['used'] = timestamp.date()
            out['probes'] = steps.index((timestamp, label)) + 1
            break
        out.setdefault('empty_steps', []).append(str(timestamp.date()))
    else:
        out['error'] = f'no populated step in the newest {MAX_PROBES}'
        return out

    ds = ds.drop_vars('queryUrl')
    if src['lon_360']:
        ds = ds.assign_coords(longitude=f.to_180(ds['longitude'])).sortby('longitude')

    values = ds[src['variable']].values
    lat, lon = ds['latitude'].values, ds['longitude'].values
    ocean = np.isfinite(values).squeeze()

    out['shape'] = (len(lat), len(lon))
    out['n_cells'] = ocean.size
    out['n_ocean'] = int(ocean.sum())
    out['n_land'] = int(ocean.size - ocean.sum())

    # The number that decides everything: ocean pixels inside the sound itself.
    in_lat = (lat >= SOUND['lat'][0]) & (lat <= SOUND['lat'][1])
    in_lon = (lon >= SOUND['lon'][0]) & (lon <= SOUND['lon'][1])
    sound_ocean = ocean[np.ix_(in_lat, in_lon)]
    out['sound_cells'] = int(sound_ocean.size)
    out['sound_ocean'] = int(sound_ocean.sum())

    # Cell size in km at this latitude -- more legible than degrees.
    mid_lat = float(np.mean(lat))
    dlat = float(np.median(np.diff(lat))) if len(lat) > 1 else src['resolution']
    dlon = float(np.median(np.diff(lon))) if len(lon) > 1 else src['resolution']
    out['cell_km'] = (dlon * 111.32 * np.cos(np.radians(mid_lat)), dlat * 110.57)

    # Distance from each site to the nearest ocean cell centre -- how far the "value
    # at Bamfield" actually is from Bamfield.
    out['site_km'] = {}
    for name, (site_lat, site_lon) in SITES.items():
        dy = (lat[:, None] - site_lat) * 110.57
        dx = (lon[None, :] - site_lon) * 111.32 * np.cos(np.radians(site_lat))
        dist = np.hypot(dx, dy)
        dist[~ocean] = np.inf
        out['site_km'][name] = float(dist.min())

    out['range'] = (float(np.nanmin(values)), float(np.nanmax(values)))

    path = Path(__file__).resolve().parent / f'compare_{preset}.nc'
    ds.to_netcdf(path)
    out['saved'] = path.name
    out['kb'] = path.stat().st_size / 1024
    return out


def report(out):
    print(f"\n{'=' * 72}\n{out['preset']}  ({out['resolution']} deg)\n{'=' * 72}")
    if out.get('newest') is not None:
        print(f"  newest step   {out['newest']}  ({out['lag_days']} days behind today, '{out['label']}')")
        print(f"  time axis     {out['n_steps']} steps")
    if out.get('empty_steps'):
        print(f"  EMPTY steps   {', '.join(out['empty_steps'])}  <- present on the axis, no data in them")
    if out['error']:
        print(f"  FAILED        {out['error']}")
        return
    print(f"  used step     {out['used']}")
    print(f"  grid          {out['shape'][0]} lat x {out['shape'][1]} lon = {out['n_cells']:,} cells")
    print(f"  cell size     {out['cell_km'][0]:.1f} x {out['cell_km'][1]:.1f} km")
    print(f"  ocean / land  {out['n_ocean']:,} / {out['n_land']:,}")
    print(f"  IN THE SOUND  {out['sound_ocean']:,} ocean cells (of {out['sound_cells']:,} in the box)")
    print(f"  SST range     {out['range'][0]:.2f} to {out['range'][1]:.2f} C")
    print( "  nearest ocean cell to each site:")
    for name, km in out['site_km'].items():
        print(f"      {name:<18} {km:5.1f} km")
    print(f"  saved         {out['saved']}  ({out['kb']:.0f} kB)")


if __name__ == '__main__':
    presets = sys.argv[1:] or list(f.SOURCES)
    results = []
    for preset in presets:
        print(f'\nprobing {preset} ...', flush=True)
        try:
            out = probe(preset)
        except Exception as err:
            out = {'preset': preset, 'resolution': f.SOURCES[preset]['resolution'],
                   'error': f'{type(err).__name__}: {err}'}
        results.append(out)
        report(out)

    print(f"\n{'=' * 72}\nSUMMARY\n{'=' * 72}")
    print(f"{'preset':<12} {'lag':>5}  {'cell km':>14}  {'ocean':>8}  {'in sound':>9}")
    for out in results:
        if out['error'] and 'sound_ocean' not in out:
            print(f"{out['preset']:<12} {'--':>5}  {'--':>14}  {'--':>8}  {'FAILED':>9}")
            continue
        cell = f"{out['cell_km'][0]:.1f} x {out['cell_km'][1]:.1f}"
        print(f"{out['preset']:<12} {out['lag_days']:>4}d  {cell:>14}  "
              f"{out['n_ocean']:>8,}  {out['sound_ocean']:>9,}")
