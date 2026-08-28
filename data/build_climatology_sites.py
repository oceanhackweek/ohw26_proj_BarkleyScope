"""Precompute the map layer for the sites that have a day-of-year climatology.

``contributor_folders/Dwight/onc_climatology.py`` builds a day-of-year temperature
climatology for eight moorings and buoys around Barkley Sound, and writes one
``<key>_climatology.png`` per site. The map app draws those sites and opens the
matching plot when one is clicked. This script writes the small file that connects
the two: where each site is, what it is called, and which image belongs to it.

**Coordinates come from each record's own metadata, never from a gazetteer.** The ONC
netCDF files carry ``station_lat``/``station_lon``/``station_depth`` global attributes;
the ONC CSVs carry the same three as ``#LATITUDE``/``#LONGITUDE``/``#DEPTH`` header
lines; the DFO/MEDS buoy CSV carries per-record ``LATITUDE``/``LONGITUDE`` columns, of
which the median is taken. That is the same rule ``build_historical_tracks.py`` follows
for the two Folger sites, and it is why the two files agree on Folger to 6 decimals.

One wrinkle, handled: the MEDS buoy file writes longitude as a positive number (126.0)
in a column labelled ``LONGITUDE``, meaning degrees *west*. Read literally it puts La
Perouse Bank in Kazakhstan. ``onc_climatology.py`` applies ``-abs()`` for the same
reason; so does this.

Run it after any ``onc_climatology.py --all`` run, or whenever a site is added::

    python data/build_climatology_sites.py
    python data/build_climatology_sites.py --dry-run     # report, write nothing

Output, committed:

``climatology_sites.geojson``
    One Point feature per site, carrying the station name, depth, record span, the
    repo-relative path to its climatology PNG, and a ``group`` of ``folger``,
    ``barkley`` or ``buoy``. The app draws the non-Folger ones as their own layer --
    the Folger pair already has one, from ``build_historical_tracks.py`` -- but
    hit-tests clicks against every feature here, so all eight are clickable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cproof_glider import BOX  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent
REPO = DATA_DIR.parent
CLIM_DIR = REPO / "contributor_folders" / "Dwight" / "climatology"
OUT = DATA_DIR / "climatology_sites.geojson"

#: Same precision as the track precompute: ~1 m at this latitude.
PRECISION = 6

#: Display name and grouping per site key, ordered shallow inshore first, then down
#: the canyon, then the offshore buoy. The key is `onc_climatology.py`'s own site key,
#: which is also the climatology PNG's filename stem.
#:
#: The key -> FILE mapping is not repeated here. It comes from that script's
#: `discover_sites()`, so this precompute reads exactly the record each climatology was
#: built from. Duplicating its file-picking rules would be a slow-motion bug: it prefers
#: a .nc over a .csv for the same station, and for Folger Deep the two are different
#: records entirely -- `folgerDeepDataSet.nc` covers 2009-2015, while the CSV the
#: climatology actually uses covers 2016-2026.
SITES = {
    "pinnacle":     ("Folger Pinnacle",          "folger"),
    "deep":         ("Folger Deep",              "folger"),
    "upperslope":   ("Barkley Upper Slope",      "barkley"),
    "node":         ("Barkley Node",             "barkley"),
    "hydrates":     ("Barkley Canyon Hydrates",  "barkley"),
    "mideast":      ("Barkley Canyon Mid-East",  "barkley"),
    "axis":         ("Barkley Canyon Axis",      "barkley"),
    "laperusebank": ("La Perouse Bank (C46206)", "buoy"),
}


def _from_netcdf(path: Path) -> dict:
    """Read station position and depth from an ONC netCDF's global attributes."""
    import netCDF4

    with netCDF4.Dataset(path) as ds:
        attrs = {name: ds.getncattr(name) for name in ds.ncattrs()}

    def _first(*names):
        for name in names:
            if name in attrs:
                return attrs[name]
        return None

    lat = _first("station_lat", "latitude", "geospatial_lat_min")
    lon = _first("station_lon", "longitude", "geospatial_lon_min")
    depth = _first("station_depth", "depth", "geospatial_vertical_min")
    if lat is None or lon is None:
        raise RuntimeError(f"{path.name}: no station position in its global attributes")
    return {"lat": _number(lat), "lon": _number(lon), "depth_m": _number(depth)}


def _from_onc_csv(path: Path) -> dict:
    """Read station position and depth from an ONC CSV's ``#KEY: value`` header."""
    header = {}
    with path.open() as handle:
        for line in handle:
            if not line.startswith("#"):
                break
            match = re.match(r"#(\w+):\s*([^/]+)", line)
            if match:
                header[match.group(1).upper()] = match.group(2).strip()
    try:
        return {"lat": _number(header["LATITUDE"]),
                "lon": _number(header["LONGITUDE"]),
                "depth_m": _number(header.get("DEPTH"))}
    except KeyError as error:
        raise RuntimeError(f"{path.name}: header has no {error}") from None


def _from_meds_csv(path: Path) -> dict:
    """Read buoy position from a DFO/MEDS CSV's own columns.

    The median, not the first row: a moored buoy's reported position wanders by a few
    hundredths of a degree over 34 years of watch circle and re-deployments.

    ``LONGITUDE`` here is degrees WEST written positive. Taking it at face value moves
    the buoy to the other side of the planet, so the sign is forced negative -- the same
    thing `onc_climatology.py` does when it loads this file.
    """
    frame = pd.read_csv(path, usecols=["LATITUDE", "LONGITUDE", "DEPTH"], low_memory=False)
    return {
        "lat": float(frame["LATITUDE"].median()),
        "lon": -abs(float(frame["LONGITUDE"].median())),
        # A surface buoy measures at the surface. Its DEPTH column is the water depth
        # under the mooring, which is a different quantity from the instrument depth
        # every other site here reports -- so it goes in its own field rather than
        # being passed off as one.
        "depth_m": None,
        "water_depth_m": float(frame["DEPTH"].median()),
    }


def _number(value) -> float | None:
    """Pull a float out of an attribute that may carry its unit ('983.3817m')."""
    if value is None:
        return None
    if isinstance(value, (int, float, np.floating, np.integer)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _record_span(path: Path, group: str) -> tuple[str, str] | None:
    """The record's first and last day, cheapest way first.

    ONC download names carry the span they were subset to
    (``..._20110203T170000Z_20260811T180000Z-NaN_...``), which costs nothing to read.
    Failing that, a netCDF's own ``time_coverage_*`` attributes. Failing that -- the
    buoy export, whose name carries only years -- the DATE column, which does mean
    reading the file, but only that one column.
    """
    match = re.search(r"(\d{8})T\d{6}Z_(\d{8})T\d{6}Z", path.name)
    if match:
        return (str(pd.Timestamp(match.group(1)).date()),
                str(pd.Timestamp(match.group(2)).date()))

    if path.suffix == ".nc":
        import netCDF4

        with netCDF4.Dataset(path) as ds:
            attrs = {name: ds.getncattr(name) for name in ds.ncattrs()}
        start, end = attrs.get("time_coverage_start"), attrs.get("time_coverage_end")
        if start and end:
            return str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date())
        return None

    if group == "buoy":
        dates = pd.to_datetime(pd.read_csv(path, usecols=["DATE"], low_memory=False)["DATE"],
                               errors="coerce")
        return str(dates.min().date()), str(dates.max().date())
    return None


def _discover() -> dict[str, Path]:
    """`onc_climatology.discover_sites()`, imported rather than reimplemented."""
    sys.path.insert(0, str(REPO / "contributor_folders" / "Dwight"))
    try:
        from onc_climatology import discover_sites  # noqa: PLC0415
    except ImportError as error:
        raise SystemExit(
            "could not import contributor_folders/Dwight/onc_climatology.py, which owns "
            f"the site -> file mapping this script reads: {error}"
        ) from None
    return discover_sites()


def build() -> dict:
    discovered = _discover()
    features = []
    for key, (name, group) in SITES.items():
        path = discovered.get(key)
        if path is None:
            print(f"  SKIP    {key}: onc_climatology.discover_sites() found no file for it")
            continue

        if path.suffix == ".nc":
            position = _from_netcdf(path)
        elif group == "buoy":
            position = _from_meds_csv(path)
        else:
            position = _from_onc_csv(path)

        lon = round(position["lon"], PRECISION)
        lat = round(position["lat"], PRECISION)
        inside = (BOX["lon"][0] <= lon <= BOX["lon"][1]
                  and BOX["lat"][0] <= lat <= BOX["lat"][1])
        if not inside:
            print(f"  SKIP    {key}: ({lon}, {lat}) is outside the study box")
            continue

        png = CLIM_DIR / f"{key}_climatology.png"
        if not png.exists():
            # Not fatal: a site without a plot still belongs on the map, it just has
            # nothing to open. The app treats a null the same way it treats a click on
            # empty water, rather than rendering a broken image.
            print(f"  WARN    {key}: {png.relative_to(REPO)} is missing")

        span = _record_span(path, group)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "key": key,
                "name": name,
                "group": group,
                "depth_m": position["depth_m"],
                "water_depth_m": position.get("water_depth_m"),
                "record_start": span[0] if span else None,
                "record_end": span[1] if span else None,
                "climatology_png": (str(png.relative_to(REPO)) if png.exists() else None),
                "source": str(path.relative_to(REPO)),
            },
        })
        depth = position["depth_m"]
        label = f"{depth:6.0f} m" if depth is not None else "surface"
        span_text = f"{span[0]}..{span[1]}" if span else "span unknown"
        print(f"  {key:13s} ({lon:11.6f}, {lat:9.6f})  {label:>8s}  {span_text}")

    return {"type": "FeatureCollection", "features": features}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be written, write nothing")
    args = parser.parse_args(argv)

    print(f"Reading station metadata from {DATA_DIR}")
    collection = build()
    if not collection["features"]:
        print("nothing to write -- no site files found")
        return 1

    payload = json.dumps(collection, indent=1)
    print(f"\n{len(collection['features'])} site(s), {len(payload) / 1024:.1f} kB")
    if args.dry_run:
        print(f"--dry-run: not writing {OUT.name}")
        return 0

    OUT.write_text(payload + "\n")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
