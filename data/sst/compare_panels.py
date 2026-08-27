"""Render the three SST products side by side, whole box and zoomed into the sound.

The numbers from compare_resolutions.py say how many pixels each product puts in
Barkley Sound. They do not say whether those pixels show anything real, and that is
the actual decision. A finer grid that has smoothed the coastal gradient away is
worse than a coarse one that shows it honestly -- MUR in particular is a gap-filled
analysis, so near a coastline it interpolates, and interpolated detail looks exactly
like measured detail on a map.

So: two rows. The top row frames the whole fetch box, where the shelf upwelling
gradient should read. The bottom row zooms to the sound, which is where the coarse
product is expected to fall apart and where the fine ones have to earn their place.

Everything here is offline -- it reads the compare_*.nc files written by
compare_resolutions.py, and the coastline comes from cartopy's already-cached
Natural Earth shapefiles.
"""

import warnings
from pathlib import Path

import cmocean
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.patches import Rectangle
from shapely.geometry import box as shapely_box

warnings.filterwarnings('ignore')

HERE = Path(__file__).resolve().parent

# Same box the fetch script uses, and the same one cproof_glider.py calls BOX.
BOX = {'lon': (-126.80, -124.50), 'lat': (47.85, 49.36)}
SOUND = {'lon': (-125.55, -124.95), 'lat': (48.72, 49.05)}
SITES = {
    'Bamfield':        (48.835, -125.135),
    'Cape Beale':      (48.786, -125.213),
    'Folger Pinnacle': (48.814, -125.281),
}

# One fixed range across all six panels. Per-panel autoscaling would make each product
# use the full ramp and look equally informative -- which is precisely the comparison
# being made here, so the scale has to be held still for the panels to mean anything.
VMIN, VMAX = 10.0, 20.0

# cmocean's thermal: perceptually uniform and colourblind-safe, unlike jet, and it is
# already what the map app's CONFIG_MAP declares ("COLOR_SCALE": "Thermal").
CMAP = cmocean.cm.thermal

LAND_FILL = '#d8d4cf'
LAND_EDGE = '#6b6560'
NE_DIR = Path.home() / '.local/share/cartopy/shapefiles/natural_earth/physical'

PRODUCTS = [
    ('compare_oisst.nc',      'sst',          'OISST v2.1',      '0.25 deg  ~18 x 28 km'),
    ('compare_blended5km.nc', 'analysed_sst', 'Geo-polar blend', '0.05 deg  ~3.7 x 5.5 km'),
    ('compare_mur1km.nc',     'analysed_sst', 'MUR L4',          '0.01 deg  ~0.7 x 1.1 km'),
]


def cell_edges(centres):
    """Turn N cell-centre coordinates into N+1 edges.

    pcolormesh draws a quad per cell and needs the corners. Handing it centres makes
    matplotlib infer edges by averaging neighbours, which shifts the whole field half a
    cell -- a small enough error to survive review and big enough to put water on land.
    """
    centres = np.asarray(centres, dtype=float)
    if centres.size == 1:
        return np.array([centres[0] - 0.5, centres[0] + 0.5])
    step = np.diff(centres)
    inner = centres[:-1] + step / 2
    return np.concatenate([[centres[0] - step[0] / 2], inner, [centres[-1] + step[-1] / 2]])


def load_land(bounds):
    """Clip the cached Natural Earth 10 m land polygons to a bounding box."""
    clip = shapely_box(*bounds)
    land = gpd.read_file(NE_DIR / 'ne_10m_land.shp', bbox=clip.bounds)
    return land.clip(clip)


def draw(ax, ds, variable, extent, land, show_sites, show_sound_box):
    lat = ds['latitude'].values
    lon = ds['longitude'].values
    field = np.squeeze(ds[variable].values)

    mesh = ax.pcolormesh(cell_edges(lon), cell_edges(lat), field,
                         cmap=CMAP, vmin=VMIN, vmax=VMAX, shading='flat')

    # Land over the data, not under it: these products write values into some coastal
    # cells that are mostly rock, and drawing the real coastline on top is the only way
    # to see whether a warm pixel is water or a land cell that leaked.
    land.plot(ax=ax, facecolor=LAND_FILL, edgecolor=LAND_EDGE, linewidth=0.6, zorder=3)

    if show_sound_box:
        ax.add_patch(Rectangle(
            (SOUND['lon'][0], SOUND['lat'][0]),
            SOUND['lon'][1] - SOUND['lon'][0],
            SOUND['lat'][1] - SOUND['lat'][0],
            fill=False, edgecolor='#111111', linewidth=1.4, linestyle=(0, (4, 2)), zorder=5))

    if show_sites:
        for name, (site_lat, site_lon) in SITES.items():
            ax.plot(site_lon, site_lat, marker='o', markersize=5.5,
                    markerfacecolor='#ffffff', markeredgecolor='#111111',
                    markeredgewidth=1.3, zorder=6)
            ax.annotate(name, (site_lon, site_lat), xytext=(6, 4),
                        textcoords='offset points', fontsize=7.5, zorder=6,
                        color='#111111',
                        path_effects=None)

    ax.set_xlim(extent['lon'])
    ax.set_ylim(extent['lat'])
    # Degrees of longitude are shorter than degrees of latitude away from the equator;
    # without this the map is stretched east-west and distances read wrong.
    ax.set_aspect(1 / np.cos(np.radians(np.mean(extent['lat']))))
    ax.tick_params(labelsize=7)
    return mesh


def main():
    fig, axes = plt.subplots(2, 3, figsize=(15, 10.5))
    mesh = None

    for column, (filename, variable, title, subtitle) in enumerate(PRODUCTS):
        path = HERE / filename
        if not path.exists():
            for row in range(2):
                axes[row, column].text(0.5, 0.5, f'{filename}\nmissing', ha='center',
                                       va='center', fontsize=9)
                axes[row, column].set_axis_off()
            continue

        ds = xr.open_dataset(path)
        field = np.squeeze(ds[variable].values)
        date = str(ds['time'].values[0])[:10]

        ocean_total = int(np.isfinite(field).sum())
        in_lat = (ds['latitude'].values >= SOUND['lat'][0]) & (ds['latitude'].values <= SOUND['lat'][1])
        in_lon = (ds['longitude'].values >= SOUND['lon'][0]) & (ds['longitude'].values <= SOUND['lon'][1])
        sound_ocean = int(np.isfinite(field[np.ix_(in_lat, in_lon)]).sum())

        for row, extent in enumerate([BOX, SOUND]):
            ax = axes[row, column]
            land = load_land((extent['lon'][0], extent['lat'][0],
                              extent['lon'][1], extent['lat'][1]))
            mesh = draw(ax, ds, variable, extent, land,
                        show_sites=(row == 1), show_sound_box=(row == 0))

        axes[0, column].set_title(f'{title}\n{subtitle}\n{date}   {ocean_total:,} ocean cells in box',
                                  fontsize=10, pad=8)
        axes[1, column].set_title(f'Barkley Sound  —  {sound_ocean:,} ocean cells',
                                  fontsize=9.5, pad=6)

    axes[0, 0].set_ylabel('whole fetch box', fontsize=9)
    axes[1, 0].set_ylabel('zoomed to the sound', fontsize=9)

    fig.suptitle('Can this product see Barkley Sound?  —  same colour scale on every panel',
                 fontsize=13, y=0.975)

    cbar = fig.colorbar(mesh, ax=axes, orientation='horizontal',
                        fraction=0.035, pad=0.06, aspect=55)
    cbar.set_label('Sea surface temperature (°C)', fontsize=9.5)
    cbar.ax.tick_params(labelsize=8)

    out = HERE / 'compare_resolutions.png'
    fig.savefig(out, dpi=130, bbox_inches='tight', facecolor='white')
    print(f'wrote {out.name}')


if __name__ == '__main__':
    main()
