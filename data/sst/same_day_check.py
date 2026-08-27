"""Is MUR actually smoother than the 5 km blend, or was that just a different day?

compare_panels.py rendered each product on its own newest day -- Aug 20 / 24 / 25 --
because that is what each publishes. That is the right picture for "how fresh is this
product", and the wrong one for "does this product carry structure", since a flat panel
could just be a flat day.

This pulls both fine products for the SAME day and measures the spatial variability
inside Barkley Sound. If MUR's extra pixels carry real signal, its spatial standard
deviation should be at least comparable to the blend's. If they are interpolation, it
will be markedly lower -- more pixels, less information.
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

warnings.filterwarnings('ignore')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_sst_barkley as f  # noqa: E402

HERE = Path(__file__).resolve().parent
SOUND = {'lon': (-125.55, -124.95), 'lat': (48.72, 49.05)}
DAY = pd.Timestamp('2026-08-24T09:00:00')      # newest day the blend carries


def grab(preset, variable, day):
    """Fetch one day for one preset, nearest available step."""
    f.ACTIVE_SOURCE = preset
    steps = f.candidate_steps()
    # Nearest step to the requested day -- products stamp their daily field at
    # different hours (OISST at 12:00, MUR at 09:00), so an exact match would miss.
    target = day.tz_localize('UTC') if day.tz is None else day
    timestamp, label = min(steps, key=lambda s: abs(s[0] - target))
    ds = f.fetch_step(label, timestamp).drop_vars('queryUrl')
    if f.SOURCES[preset]['lon_360']:
        ds = ds.assign_coords(longitude=f.to_180(ds['longitude'])).sortby('longitude')
    return ds, timestamp


def sound_stats(ds, variable):
    lat, lon = ds['latitude'].values, ds['longitude'].values
    field = np.squeeze(ds[variable].values)
    in_lat = (lat >= SOUND['lat'][0]) & (lat <= SOUND['lat'][1])
    in_lon = (lon >= SOUND['lon'][0]) & (lon <= SOUND['lon'][1])
    patch = field[np.ix_(in_lat, in_lon)]
    good = patch[np.isfinite(patch)]
    return {
        'n': good.size,
        'mean': float(np.mean(good)),
        'std': float(np.std(good)),
        'min': float(np.min(good)),
        'max': float(np.max(good)),
        'range': float(np.max(good) - np.min(good)),
    }


if __name__ == '__main__':
    print(f'target day: {DAY.date()}\n')
    rows = []
    for preset, variable in [('blended5km', 'analysed_sst'), ('mur1km', 'analysed_sst')]:
        ds, timestamp = grab(preset, variable, DAY)
        ds.to_netcdf(HERE / f'sameday_{preset}.nc')
        stats = sound_stats(ds, variable)
        stats['preset'] = preset
        stats['day'] = str(timestamp.date())
        rows.append(stats)
        print(f"{preset:<12} {timestamp.date()}  n={stats['n']:>6,}  "
              f"mean={stats['mean']:6.2f}  std={stats['std']:5.3f}  "
              f"range={stats['range']:5.2f}  ({stats['min']:.2f} to {stats['max']:.2f})")

    print()
    blend, mur = rows[0], rows[1]
    ratio = mur['std'] / blend['std'] if blend['std'] else float('nan')
    print(f"MUR spatial std is {ratio:.2f}x the blend's inside the sound, "
          f"on {mur['n'] / blend['n']:.0f}x as many pixels.")
    if ratio < 0.6:
        print("=> MUR's extra resolution is largely interpolation here, not signal.")
    elif ratio > 0.9:
        print("=> MUR carries comparable structure; its resolution is doing real work.")
    else:
        print("=> Intermediate: MUR is somewhat smoother but not flat.")
