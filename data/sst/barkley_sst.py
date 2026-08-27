"""Read the Barkley Sound satellite SST archive and shape it for a map.

WHAT THIS IS
    The SST counterpart to cproof_glider.py, and deliberately the same shape: a module
    constant for the box, one for the archive path, and a reader that hands back the
    data ready to use. Anything that draws SST -- the preview figures, the map app --
    goes through here, so the awkward parts are solved once.

    The glider library returns a tidy DataFrame because glider data is a list of
    observations. This one returns an xarray Dataset because SST is a grid, and
    flattening a grid to rows loses the thing that makes it a grid.

THE THREE AWKWARD PARTS

    1. Cells are stored as centres and drawn as rectangles.
       A netCDF grid records the coordinate at the middle of each cell. A map draws a
       box. Build that box by spanning centre-to-centre and the whole field lands half
       a cell off -- far enough here to put water on land, and subtle enough to survive
       review. cell_edges() does the conversion; nothing should reimplement it.

    2. Some water is not the water you think it is.
       At the north-east corner the grid carries five warm cells (about 19 C) that are
       Strait of Georgia water, on the FAR side of Vancouver Island. Drawn on a map of
       Barkley Sound they read as a hot patch in the study area. They are not reachable
       from the open Pacific across this grid, so flag_disconnected() finds them by
       connectivity rather than by a hand-drawn polygon -- which means it keeps working
       if the box, the product or the resolution changes. They are flagged, never
       deleted: the map mutes them, and nothing is silently thrown away.

    3. The 'source' label says 'final' and does not mean what that usually means.
       For a two-stage product like OISST, 'prelim' and 'final' are real quality tiers.
       The blend this archive uses publishes once, so every step is labelled 'final'
       purely because the preset has a single entry. It is a near-real-time analysis
       about two days behind, not a reprocessed quality-controlled record. Do not
       caption it as one -- see SOURCE_CAVEAT.

WHAT IT IS NOT
    Not a measurement of the water. This is an L4 analysis: a model blends satellite
    passes into a gap-free field, so a value near the coast is partly inferred. It was
    chosen over the finer 1 km MUR product precisely because MUR infers far more --
    inside the sound MUR's spatial variability is about a seventh of this product's,
    across 21x as many pixels. Finer was smoother, not truer. Validate against the ONC
    in-water sensors in data/folger/ before treating fine detail as real.

USAGE
    import barkley_sst as sst

    ds = sst.read_grid()                       # the whole archive
    ds = sst.read_grid(last_days=3)            # the newest three days
    geo = sst.cell_polygons(ds, '2026-08-24')  # GeoJSON, ready for a map layer
"""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

# ---------------------------------------------------------------------------
# Where things are
# ---------------------------------------------------------------------------

SST_DIR = Path(__file__).resolve().parent          # data/sst -- the machinery
DATA_DIR = SST_DIR.parent                          # data     -- the shared datasets

# One archive, in the shared directory, so the map app's config points at a single
# place for every dataset it loads. Named to match its sibling cproof_glider_realtime.nc.
SST_ARCHIVE = DATA_DIR / 'sst_barkley_realtime.nc'

# A ~1 km land/water mask covering the same box, built once by make_land_mask.py from
# MUR L4's land mask. Only the mask is borrowed, never MUR's temperatures. Used to clip
# the 5 km cells to their water area -- see cell_polygons(clip=True).
LAND_MASK = SST_DIR / 'land_mask_1km.nc'

# The study box, identical to cproof_glider.BOX and to CONFIG_MAP["REGION"] in both map
# apps. The archive covers it with about 5 km of margin on every side, because ERDDAP
# snaps outward to whole cells.
BOX = {'lon': (-126.80, -124.50), 'lat': (47.85, 49.36)}

# ---------------------------------------------------------------------------
# Presentation constants
# ---------------------------------------------------------------------------

# Fixed year-round, and deliberately not computed from the data. Autoscaling per day
# would repaint the map every time the date changed, so unchanged water would appear to
# change temperature as a user scrubbed through the week. Wide enough for the full
# seasonal swing on this shelf; a summer week uses roughly the middle half of it.
COLOR_RANGE = (10.0, 20.0)

# cmocean's 'thermal', sampled. Perceptually uniform and colourblind-safe -- unlike the
# rainbow maps still common in SST figures, where a banding artefact reads as a front
# that is not there. Matches CONFIG_MAP["GLIDER"]["COLOR_SCALE"] = "Thermal", so the
# satellite field and the glider track speak the same colour language.
THERMAL_STOPS = [
    (0.000, '#042333'), (0.125, '#19337c'), (0.250, '#563b9c'),
    (0.375, '#83508f'), (0.500, '#b15f82'), (0.625, '#df7064'),
    (0.750, '#f99341'), (0.875, '#f9c641'), (1.000, '#e8fa5b'),
]


def color_stops(color_range=None):
    """Colour ramp as [value, hex, value, hex, ...] in data units.

    That flat alternating form is what MapLibre's 'interpolate' expression expects, so a
    layer can be styled straight from this without the app hand-writing colours. Keeping
    the ramp here rather than in each app is what stops the preview figure and the live
    map from drifting into showing the same temperature as two different colours.
    """
    low, high = color_range or COLOR_RANGE
    flat = []
    for position, hex_color in THERMAL_STOPS:
        flat.extend([low + position * (high - low), hex_color])
    return flat


def color_for(value, color_range=None):
    """Interpolate one value to a hex colour -- for ipyleaflet, which styles per feature
    in Python rather than with a declarative expression like MapLibre."""
    low, high = color_range or COLOR_RANGE
    if value is None or not np.isfinite(value):
        return '#00000000'
    position = min(max((value - low) / (high - low), 0.0), 1.0)
    for (p0, c0), (p1, c1) in zip(THERMAL_STOPS, THERMAL_STOPS[1:]):
        if position <= p1:
            span = (position - p0) / (p1 - p0) if p1 > p0 else 0.0
            rgb0 = [int(c0[k:k + 2], 16) for k in (1, 3, 5)]
            rgb1 = [int(c1[k:k + 2], 16) for k in (1, 3, 5)]
            return '#%02x%02x%02x' % tuple(
                round(a + span * (b - a)) for a, b in zip(rgb0, rgb1))
    return THERMAL_STOPS[-1][1]

SOURCE_CAVEAT = (
    "Near-real-time L4 analysis, about two days behind. Every step is labelled 'final' "
    "because the product publishes once -- that is not a quality tier."
)

_FLAG_NOTE = (
    'Water not reachable from the open Pacific across this grid -- Strait of Georgia, '
    'the far side of Vancouver Island. Real data, wrong basin for this map.'
)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def variable_name(ds):
    """Return the SST variable in this archive.

    Not standardised across products -- OISST calls it 'sst', the L4 analyses
    'analysed_sst' -- so it is discovered rather than assumed. The archive carries
    exactly one data variable, which makes this unambiguous.
    """
    names = [name for name in ds.data_vars]
    if len(names) != 1:
        raise ValueError(f'expected one data variable, found {names}')
    return names[0]


def read_grid(path=None, last_days=None):
    """Open the SST archive.

    `last_days` keeps only the newest N steps. It counts steps present in the file, not
    calendar days back from today: the product publishes days behind real time, so
    "today minus three" would routinely select nothing at all.
    """
    path = Path(path) if path else SST_ARCHIVE
    if not path.exists():
        raise FileNotFoundError(
            f'{path} not found. Build it with:\n'
            f'    python {SST_DIR.name}/fetch_sst_barkley.py'
        )
    ds = xr.open_dataset(path).load()
    if last_days is not None:
        ds = ds.isel(time=slice(-int(last_days), None))
    return ds


def dates(ds):
    """The archive's time axis as 'YYYY-MM-DD' strings, oldest first."""
    return [str(value)[:10] for value in pd.to_datetime(ds['time'].values)]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def cell_edges(centres):
    """Turn N cell-centre coordinates into the N+1 edges that bound them.

    See awkward part 1 in the module docstring. Spacing is measured per-interval rather
    than assumed uniform, so this stays correct on an irregular axis.
    """
    centres = np.asarray(centres, dtype=float)
    if centres.size == 1:
        return np.array([centres[0] - 0.5, centres[0] + 0.5])
    step = np.diff(centres)
    inner = centres[:-1] + step / 2
    return np.concatenate([[centres[0] - step[0] / 2], inner,
                           [centres[-1] + step[-1] / 2]])


def flag_disconnected(ds):
    """Boolean mask, True where water cannot be reached from the open Pacific.

    Labels connected components of the ocean mask and keeps the largest as the real
    ocean; anything else is a basin this grid cannot reach. See awkward part 2.

    The mask is built from cells that hold data on ANY day, so a cloudy day does not
    change the geometry -- otherwise the flagged set would flicker from day to day.

    This is resolution-dependent by design and that is the point: at 0.25 deg it flags
    two Strait of Georgia cells, at 5 km five, and at a fine enough resolution the real
    channels open and it flags nothing. Each of those is the correct answer for that
    grid, which a hand-drawn exclusion polygon could not be.
    """
    from scipy import ndimage

    values = ds[variable_name(ds)].values
    ocean = np.isfinite(values).any(axis=0)
    labelled, count = ndimage.label(ocean)
    if count <= 1:
        return np.zeros_like(ocean, dtype=bool)
    sizes = ndimage.sum(ocean, labelled, range(1, count + 1))
    main = int(np.argmax(sizes)) + 1
    return ocean & (labelled != main)


_WATER_MASK_CACHE = {}


def water_mask(path=None):
    """The ~1 km water mask as (lat, lon, boolean array). Cached; read once per process.

    Raises a pointed error rather than silently falling back, because a caller that asked
    for clipping and quietly got unclipped rectangles would be worse than a failure.
    """
    path = Path(path or LAND_MASK)
    key = str(path)
    if key not in _WATER_MASK_CACHE:
        if not path.exists():
            raise FileNotFoundError(
                f'{path.name} is missing -- run make_land_mask.py to build it. '
                'It is needed to clip 5 km cells to their water area.')
        ds = xr.open_dataset(path)
        _WATER_MASK_CACHE[key] = (ds['latitude'].values,
                                  ds['longitude'].values,
                                  ds['water'].values.astype(bool))
    return _WATER_MASK_CACHE[key]


def _merge_runs(mask):
    """Boolean 2-D mask -> few half-open rectangles (r0, r1, c0, c1) covering the True.

    One rectangle per True cell would multiply the feature count by ~25 and the payload
    with it. Merging horizontal runs, then stacking identical runs vertically, gets a
    typical coastal cell down to a handful of boxes with no loss of shape.
    """
    runs = []
    n_rows, n_cols = mask.shape
    for r in range(n_rows):
        c = 0
        while c < n_cols:
            if mask[r, c]:
                c0 = c
                while c < n_cols and mask[r, c]:
                    c += 1
                runs.append((r, c0, c))
            else:
                c += 1

    merged, pending = [], {}
    for r, c0, c1 in runs:
        key = (c0, c1)
        prior = pending.get(key)
        if prior is not None and prior[1] == r:          # directly below the last one
            pending[key] = (prior[0], r + 1)
        else:
            if prior is not None:
                merged.append((prior[0], prior[1], c0, c1))
            pending[key] = (r, r + 1)
    for (c0, c1), (r0, r1) in pending.items():
        merged.append((r0, r1, c0, c1))
    return merged


class _Clipper:
    """Turns one 5 km cell into the water part of its footprint, at ~1 km.

    The 5 km product's land mask is coarser than the coastline: some of its ocean cells
    are wholly land, and many are mostly land, so drawn whole they put colour on
    hillsides. Clipping keeps the value exactly as it is -- still a 5 km measurement --
    and only corrects the footprint it is painted over.
    """

    def __init__(self, mask_path=None):
        lat, lon, water = water_mask(mask_path)
        self.water = water
        self.lat_edges = cell_edges(lat)
        self.lon_edges = cell_edges(lon)
        self.lat, self.lon = lat, lon

    # The parent cell's bounds arrive rounded to `decimals`, while the mask's own
    # coordinates are unrounded float32. At a boundary those disagree by ~1e-6, which is
    # enough to move searchsorted by one and silently discard a whole edge column of
    # water. This tolerance is far larger than that noise and far smaller than the
    # mask's own 0.01 deg spacing, so it cannot pull in a neighbouring cell.
    _EPS = 1e-3

    def polygons(self, south, north, west, east, decimals):
        """MultiPolygon coordinates for the water inside this cell.

        Returns [] when the cell is entirely land -- the caller drops it. Returns the
        unclipped rectangle when the mask does not reach this cell at all, since absence
        of coverage is not evidence of land.
        """
        i0, i1 = np.searchsorted(self.lat, [south - self._EPS, north - self._EPS])
        j0, j1 = np.searchsorted(self.lon, [west - self._EPS, east - self._EPS])
        block = self.water[i0:i1, j0:j1]
        if block.size == 0:
            # Outside the mask's coverage -- keep the cell as it was rather than
            # inventing a verdict about it.
            return [[[[west, south], [east, south], [east, north],
                      [west, north], [west, south]]]]
        if not block.any():
            return []
        if block.all():
            # Wholly water -- keep the plain rectangle rather than rebuilding it.
            return [[[[west, south], [east, south], [east, north],
                      [west, north], [west, south]]]]

        polygons = []
        for r0, r1, c0, c1 in _merge_runs(block):
            # Clamp to the parent cell: a 1 km cell straddling the edge must not make
            # the clipped footprint larger than the cell it came from.
            s = round(max(float(self.lat_edges[i0 + r0]), south), decimals)
            n = round(min(float(self.lat_edges[i0 + r1]), north), decimals)
            w = round(max(float(self.lon_edges[j0 + c0]), west), decimals)
            e = round(min(float(self.lon_edges[j0 + c1]), east), decimals)
            if n <= s or e <= w:
                continue                      # collapsed by rounding; nothing to draw
            polygons.append([[[w, s], [e, s], [e, n], [w, n], [w, s]]])
        return polygons


def cell_polygons(ds, date=None, decimals=3, clip=False):
    """One day of SST as a GeoJSON FeatureCollection, one rectangle per ocean cell.

    Both map stacks in this repo take GeoJSON directly -- ipyleaflet as a GeoJSON layer,
    MapLibre as a GeoJSONSource -- so this is the common currency between them.

    Land cells are omitted rather than emitted as null: a map draws nothing for them
    either way, and dropping them here is roughly a fifth fewer features to ship.

    Each feature carries its value, its centre, and whether it is flagged, so the layer
    can style and label from properties alone without reaching back into the array.

    `decimals` rounds the polygon coordinates. The netCDF stores its axes as float32, so
    an edge that should read -126.85 arrives as -126.84999465942383; left alone, every
    corner ships seventeen digits of float noise and a week of cells runs to megabytes.
    Three decimals is ~100 m, well inside a 5 km cell, and rounds this product's edges
    exactly since they fall on multiples of 0.05 degrees.

    `clip=True` replaces each rectangle with the water part of its own footprint, taken
    from the ~1 km mask in land_mask_1km.nc, and drops cells with no water in them at
    all. This is a rendering correction, not a data one: the value is unchanged and is
    still a 5 km measurement. Without it, a 5.6 x 3.7 km rectangle laid over a coastline
    this convoluted paints colour well inland -- Alberni Inlet is about a kilometre wide,
    so the cell covering it is mostly hillside. Geometry becomes MultiPolygon.
    """
    variable = variable_name(ds)
    available = dates(ds)
    date = str(date)[:10] if date is not None else available[-1]
    if date not in available:
        raise KeyError(f'{date} not in archive (have {available[0]} to {available[-1]})')

    step = ds.isel(time=available.index(date))
    field = np.asarray(step[variable].values, dtype=float)
    lat = step['latitude'].values
    lon = step['longitude'].values
    lat_edges = np.round(cell_edges(lat), decimals)
    lon_edges = np.round(cell_edges(lon), decimals)
    flagged = flag_disconnected(ds)
    clipper = _Clipper() if clip else None

    features = []
    for i in range(field.shape[0]):
        for j in range(field.shape[1]):
            value = field[i, j]
            if not np.isfinite(value):
                continue                        # land, or a gap the analysis left
            # Plain floats, not numpy scalars: these get JSON-serialised into a map
            # style, and numpy scalars serialise at full precision regardless of rounding.
            south, north = float(lat_edges[i]), float(lat_edges[i + 1])
            west, east = float(lon_edges[j]), float(lon_edges[j + 1])
            if clipper is None:
                geometry = {
                    'type': 'Polygon',
                    # GeoJSON rings are [lon, lat] and must close on the first point.
                    'coordinates': [[[west, south], [east, south], [east, north],
                                     [west, north], [west, south]]],
                }
            else:
                parts = clipper.polygons(south, north, west, east, decimals)
                if not parts:
                    # No water anywhere in this cell at 1 km. The 5 km product called it
                    # ocean and gave it a temperature; it is land. Drop it.
                    continue
                geometry = {'type': 'MultiPolygon', 'coordinates': parts}
            features.append({
                'type': 'Feature',
                'geometry': geometry,
                'properties': {
                    # 0.01 C: finer than an L4 analysis can justify, and `decimals`
                    # now governs geometry rather than this.
                    'sst': round(float(value), 2),
                    'lat': round(float(lat[i]), 4),
                    'lon': round(float(lon[j]), 4),
                    'flagged': bool(flagged[i, j]),
                },
            })

    return {
        'type': 'FeatureCollection',
        'features': features,
        'properties': {
            'date': date,
            'units': step[variable].attrs.get('units', 'degree_C'),
            'color_range': list(COLOR_RANGE),
            'source_caveat': SOURCE_CAVEAT,
            'flag_note': _FLAG_NOTE,
        },
    }


def summary(ds):
    """A one-line-per-day description, for logs and for sanity-checking a fetch."""
    variable = variable_name(ds)
    flagged = flag_disconnected(ds)
    lines = []
    for index, date in enumerate(dates(ds)):
        field = ds[variable].values[index]
        good = field[np.isfinite(field)]
        lines.append(f'{date}  {good.size:>5,} ocean cells  '
                     f'{good.min():5.2f} to {good.max():5.2f} C  mean {good.mean():5.2f}')
    lines.append(f'{flagged.sum()} cell(s) flagged as unreachable water')
    return '\n'.join(lines)


if __name__ == '__main__':
    grid = read_grid()
    print(f'{SST_ARCHIVE.name}  ({SST_ARCHIVE.stat().st_size / 1024:.0f} kB)')
    print(f'variable: {variable_name(grid)}')
    print(summary(grid))
