"""Build the land/water mask that clips SST cells to the coastline.

WHY THIS EXISTS
    The 5 km Geo-Polar Blend carries its own land mask, and that mask is coarser than the
    real coastline. Measured before clipping, 4.5% of the drawn area was land and 20 of
    its 1,220 ocean cells were land entirely yet still reported a temperature -- Port
    Alberni sits at the head of a fjord about a kilometre wide, so the 20 km2 cell
    covering it is mostly hillside.

    A finer mask cannot come from the product itself, so it is rasterised from Natural
    Earth's 10 m land polygons, which cartopy keeps cached in
    ~/.local/share/cartopy. That is a true vector coastline rather than another
    gridded product, it needs no network, and it leaves this folder with no dependency
    on any fetched scratch file.

    (An earlier version derived the mask from MUR L4's land mask instead. Natural Earth
    replaced it: the two agree to within 2.4% of cells, but MUR meant keeping a 310 kB
    fetched file alive purely to rebuild a mask from.)

RESOLUTION
    0.01 degrees, matching the blend's 0.05 degree cells at 5 sub-cells across. Finer
    would follow the shore more closely but multiplies the polygon count the map has to
    carry, and the gain is below what a 5 km measurement can justify.

CAVEAT
    Natural Earth 10 m is a generalised coastline, not a survey. Expect a few hundred
    metres of error along a complex shore. A large improvement on the product's own mask,
    not ground truth.

USAGE
    python make_land_mask.py            # writes land_mask_1km.nc
"""

from pathlib import Path

import numpy as np
import xarray as xr

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'land_mask_1km.nc'

# Matches the archive's own box with a margin, so every 5 km cell -- including the ones
# ERDDAP snapped outward -- is fully covered by the mask.
BOUNDS = {'lon': (-126.85, -124.45), 'lat': (47.80, 49.41)}
STEP = 0.01


def land_geometry(bounds):
    """The union of Natural Earth land polygons overlapping the box, prepared for tests."""
    import cartopy.io.shapereader as shpreader
    from shapely.geometry import box
    from shapely.ops import unary_union
    from shapely.prepared import prep

    path = shpreader.natural_earth(resolution='10m', category='physical', name='land')
    region = box(bounds['lon'][0], bounds['lat'][0], bounds['lon'][1], bounds['lat'][1])
    geoms = [g for g in shpreader.Reader(path).geometries() if g.intersects(region)]
    if not geoms:
        raise RuntimeError('no Natural Earth land polygons overlap the box')
    return prep(unary_union(geoms)), len(geoms)


def build(output=OUTPUT, bounds=None, step=STEP):
    from shapely.geometry import Point

    bounds = bounds or BOUNDS
    land, n_polygons = land_geometry(bounds)

    lat = np.arange(bounds['lat'][0], bounds['lat'][1] + step / 2, step)
    lon = np.arange(bounds['lon'][0], bounds['lon'][1] + step / 2, step)

    # A cell is water unless its centre falls inside a land polygon. Centre-based to match
    # how cell_polygons() selects sub-cells, so the two cannot disagree at a boundary.
    water = np.ones((len(lat), len(lon)), dtype=bool)
    for i, y in enumerate(lat):
        for j, x in enumerate(lon):
            if land.contains(Point(float(x), float(y))):
                water[i, j] = False

    out = xr.Dataset(
        {'water': (('latitude', 'longitude'), water.astype('uint8'))},
        coords={'latitude': lat, 'longitude': lon},
    )
    out['water'].attrs = {
        'long_name': 'water mask (1 = water, 0 = land)',
        'comment': ('Rasterised from Natural Earth 10 m land polygons via cartopy. A '
                    'generalised coastline -- expect a few hundred metres of error along '
                    'a complex shore.'),
        'source': f'Natural Earth 10m physical/land ({n_polygons} polygons over this box)',
    }
    out.attrs = {
        'title': 'Land/water mask for the BarkleyScope study box',
        'purpose': ('Clip 5 km SST cells to their water area, and drop cells that are '
                    'entirely land, in barkley_sst.cell_polygons(clip=True).'),
        'resolution_deg': step,
    }
    out.to_netcdf(output)
    return out, water


if __name__ == '__main__':
    out, water = build()
    lat, lon = out['latitude'].values, out['longitude'].values
    print(f'wrote {OUTPUT.name}  ({OUTPUT.stat().st_size / 1024:.0f} kB)')
    print(f'  grid   {len(lat)} x {len(lon)} at {STEP} deg')
    print(f'  extent lat {lat.min():.2f}..{lat.max():.2f}  lon {lon.min():.2f}..{lon.max():.2f}')
    print(f'  water  {water.sum()} of {water.size} cells ({water.mean() * 100:.1f}%)')
