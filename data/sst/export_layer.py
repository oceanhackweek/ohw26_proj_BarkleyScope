"""Write the SST layer as one self-contained GeoJSON file for the shared app.

WHY THIS EXISTS
    map_layers.py hands the shared app live Python objects, which means that app has to
    import this folder. That is the right integration when both live in one repo and one
    environment, but it is not a thing you can hand someone.

    This writes the same layer as a single file instead. Whoever maintains the shared app
    drops it in and adds a layer; they need nothing from data/sst/, no xarray, no netCDF
    reader, and no knowledge of how the archive is built.

WHAT IT PRODUCES
    ../sst_barkley_layer.geojson -- one FeatureCollection holding every day, each feature
    carrying the date it belongs to. One file rather than one per day because a map
    filters on a property far more easily than it juggles seven sources, and because a
    single artifact is what actually gets handed over and kept in sync.

    Geometry is already clipped to the coastline, so the consumer does not need the land
    mask either. Styling metadata travels in the collection's `properties`, so the layer
    renders the same colours here as in every figure this project produces.

USAGE
    python export_layer.py
    python export_layer.py --days 3        # only the newest 3 days
    python export_layer.py --pretty        # indented, for reading rather than shipping
"""

import argparse
import json
from pathlib import Path

import barkley_sst as sst

OUTPUT = sst.DATA_DIR / 'sst_barkley_layer.geojson'


def build(days=None, clip=True):
    """Every day's cells in one FeatureCollection, each feature tagged with its date."""
    grid = sst.read_grid()
    available = sst.dates(grid)
    wanted = available[-days:] if days else available

    features, units = [], 'degree_C'
    for date in wanted:
        collection = sst.cell_polygons(grid, date, clip=clip)
        units = collection['properties'].get('units', units)
        for feature in collection['features']:
            # The date lives on the feature so the app can filter one property rather
            # than load seven sources: ["==", ["get", "date"], "2026-08-24"].
            feature['properties']['date'] = date
            features.append(feature)

    return {
        'type': 'FeatureCollection',
        'features': features,
        # Not part of the GeoJSON spec's required shape, and deliberately ignored by any
        # renderer -- it is here so the consumer can style correctly without importing
        # this project or guessing at a colour scale.
        'properties': {
            'title': 'Satellite sea surface temperature, Barkley Sound',
            'variable': 'sea surface temperature',
            'units': units,
            'dates': wanted,
            'default_date': wanted[-1],
            'color_range': list(sst.COLOR_RANGE),
            'color_stops': [[position, colour] for position, colour in sst.THERMAL_STOPS],
            'maplibre_fill_color': ['interpolate', ['linear'], ['get', 'sst'],
                                    *sst.color_stops()],
            'flag_note': ('Features with flagged=true are water not reachable from the '
                          'open Pacific across this grid (Strait of Georgia, behind '
                          'Vancouver Island). Render them muted, not hidden.'),
            'geometry_note': ('Cells are clipped to the coastline from a 0.01 degree land '
                              'mask. The VALUE is still a 5 km measurement.'),
            'source_caveat': sst.SOURCE_CAVEAT,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--days', type=int, default=None,
                        help='export only the newest N days (default: all)')
    parser.add_argument('--pretty', action='store_true',
                        help='indent the output (roughly triples the size)')
    parser.add_argument('-o', '--output', type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    layer = build(days=args.days)
    text = json.dumps(layer, indent=2 if args.pretty else None,
                      separators=None if args.pretty else (',', ':'))
    args.output.write_text(text)

    dates = layer['properties']['dates']
    print(f'wrote {args.output.name}  ({len(text) / 1e6:.2f} MB)')
    print(f'  {len(layer["features"])} features across {len(dates)} days '
          f'({dates[0]} to {dates[-1]})')
    print(f'  default date {layer["properties"]["default_date"]}, '
          f'colour range {layer["properties"]["color_range"]} degC')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
