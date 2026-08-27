"""Render the SST archive as a week of small multiples, offline.

The map app is the destination, but a map app is a slow way to answer "did the fetch
work and does the field look sane". This does that in one picture and needs nothing but
the archive and matplotlib -- no map stack, no network, no browser.

It is also the check that the cell geometry is right. The coastline drawn here comes
from Natural Earth, not from the SST product's own land mask, so the two are independent:
if cell_edges() were off by half a cell the water would visibly sit inside the land.
That error is close to invisible without a coastline to compare against.
"""

import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
from shapely.geometry import box as shapely_box

import barkley_sst as sst

warnings.filterwarnings('ignore')

HERE = Path(__file__).resolve().parent
NE_DIR = Path.home() / '.local/share/cartopy/shapefiles/natural_earth/physical'

SITES = {
    'Bamfield':        (48.835, -125.135),
    'Cape Beale':      (48.786, -125.213),
    'Folger Pinnacle': (48.814, -125.281),
}

LAND_FILL = '#d8d4cf'
LAND_EDGE = '#6b6560'

# Rebuilt from the library's stops rather than imported from cmocean, so the figure and
# the map cannot drift apart: both render the same temperature as the same colour.
CMAP = LinearSegmentedColormap.from_list(
    'barkley_thermal', [(p, c) for p, c in sst.THERMAL_STOPS])


def load_land(bounds):
    clip = shapely_box(*bounds)
    return gpd.read_file(NE_DIR / 'ne_10m_land.shp', bbox=clip.bounds).clip(clip)


def main(zoom=None, out_name=None):
    ds = sst.read_grid()
    day_list = sst.dates(ds)
    variable = sst.variable_name(ds)
    flagged = sst.flag_disconnected(ds)

    extent = zoom or sst.BOX
    land = load_land((extent['lon'][0], extent['lat'][0],
                      extent['lon'][1], extent['lat'][1]))

    lat_edges = sst.cell_edges(ds['latitude'].values)
    lon_edges = sst.cell_edges(ds['longitude'].values)

    columns = 4
    rows = int(np.ceil(len(day_list) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(4.1 * columns, 3.7 * rows))
    axes = np.atleast_1d(axes).ravel()
    mesh = None

    for index, date in enumerate(day_list):
        ax = axes[index]
        field = np.asarray(ds[variable].values[index], dtype=float)

        mesh = ax.pcolormesh(lon_edges, lat_edges, field, cmap=CMAP,
                             vmin=sst.COLOR_RANGE[0], vmax=sst.COLOR_RANGE[1],
                             shading='flat')

        # Hatch the unreachable water rather than hiding it. Deleting it would be a
        # silent edit to the data; leaving it plain would let the Strait of Georgia
        # read as the warmest part of Barkley Sound. One patch per flagged cell --
        # pcolormesh applies a hatch to the whole mesh, not to selected cells.
        for fi, fj in zip(*np.nonzero(flagged)):
            ax.add_patch(Rectangle(
                (lon_edges[fj], lat_edges[fi]),
                lon_edges[fj + 1] - lon_edges[fj],
                lat_edges[fi + 1] - lat_edges[fi],
                facecolor='none', edgecolor='#1a1a1a', hatch='////',
                linewidth=0.0, zorder=4))

        land.plot(ax=ax, facecolor=LAND_FILL, edgecolor=LAND_EDGE,
                  linewidth=0.6, zorder=3)

        for name, (site_lat, site_lon) in SITES.items():
            ax.plot(site_lon, site_lat, marker='o', markersize=4.5,
                    markerfacecolor='#ffffff', markeredgecolor='#111111',
                    markeredgewidth=1.1, zorder=6)

        ax.set_xlim(extent['lon'])
        ax.set_ylim(extent['lat'])
        ax.set_aspect(1 / np.cos(np.radians(np.mean(extent['lat']))))
        ax.set_title(date, fontsize=10)
        ax.tick_params(labelsize=7)

    for spare in axes[len(day_list):]:
        spare.set_axis_off()

    label = 'Barkley Sound' if zoom else 'study box'
    fig.suptitle(f'Satellite SST, {day_list[0]} to {day_list[-1]}  —  {label}',
                 fontsize=13, y=0.99)

    cbar = fig.colorbar(mesh, ax=axes.tolist(), orientation='horizontal',
                        fraction=0.04, pad=0.05, aspect=55)
    cbar.set_label(f'Sea surface temperature (°C)   —   fixed scale '
                   f'{sst.COLOR_RANGE[0]:.0f}-{sst.COLOR_RANGE[1]:.0f}', fontsize=9.5)
    cbar.ax.tick_params(labelsize=8)

    out = HERE / (out_name or 'preview_week.png')
    fig.savefig(out, dpi=130, bbox_inches='tight', facecolor='white')
    print(f'wrote {out.name}')
    return out


if __name__ == '__main__':
    main()
    main(zoom={'lon': (-125.55, -124.95), 'lat': (48.72, 49.05)},
         out_name='preview_week_sound.png')
