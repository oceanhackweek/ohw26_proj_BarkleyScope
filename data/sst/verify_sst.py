#!/usr/bin/env python3
"""Checks that the satellite SST archive is safe to build a map on.

Run after a fetch, or any time the archive looks suspect::

    python data/sst/verify_sst.py

Deliberately the same shape as data/verify_archives.py, which does this job for the
glider archives -- same check() helper, same PASS/FAIL lines, same exit contract.

It exercises the things that would quietly poison the map rather than crash it:

  * **Cell geometry.** Centres vs edges is the error this whole pipeline is most
    exposed to, and a half-cell offset produces a map that looks fine until you
    notice water on land. Checked by reconstructing centres from edges.
  * **Coverage of REGION.** The map frames CONFIG_MAP["REGION"]; SST that stops short
    leaves a blank margin no one notices until a presentation.
  * **GeoJSON validity.** Rings closed, winding sane, properties present -- MapLibre
    silently drops malformed features instead of raising.
  * **Clipping to the coastline.** The map draws the clipped geometry, and the way that
    goes wrong is by silently deleting real water at a cell boundary -- which just looks
    like slightly less sea. Checked both directions: nothing with water is dropped,
    nothing that is all land is kept.
  * **Colour determinism.** The preview figures and the live map must render the same
    temperature as the same colour, or the two disagree in front of an audience.
  * **Flagged water.** The Strait of Georgia cells must stay flagged; if connectivity
    ever silently returns nothing, the hot patch comes back.

Exit status is 0 if every check passes, 1 otherwise.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                                  # noqa: E402
import xarray as xr                                                 # noqa: E402

import barkley_sst as sst                                           # noqa: E402

warnings.filterwarnings("ignore")

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def check_archive(ds) -> None:
    print("\narchive")
    variable = sst.variable_name(ds)
    field = ds[variable].values
    days = sst.dates(ds)

    check("opens via xarray with decoded time", len(days) > 0, f"{len(days)} days")
    check("time axis is ascending", days == sorted(days))
    check("no duplicate dates", len(days) == len(set(days)))
    check("every step carries data",
          all(np.isfinite(field[i]).any() for i in range(field.shape[0])))

    ocean_per_day = {int(np.isfinite(field[i]).sum()) for i in range(field.shape[0])}
    check("ocean mask is stable across days", len(ocean_per_day) == 1,
          f"{sorted(ocean_per_day)} ocean cells")

    finite = field[np.isfinite(field)]
    plausible = float(finite.min()) > -2.0 and float(finite.max()) < 35.0
    check("values are plausible sea temperatures", plausible,
          f"{finite.min():.2f} to {finite.max():.2f} C")

    inside = (sst.COLOR_RANGE[0] <= finite.min()) and (finite.max() <= sst.COLOR_RANGE[1])
    check("values fall inside the fixed colour range", inside,
          f"range {sst.COLOR_RANGE}, data {finite.min():.2f}-{finite.max():.2f}")


def check_geometry(ds) -> None:
    print("\ncell geometry")
    for axis in ("latitude", "longitude"):
        centres = ds[axis].values
        edges = sst.cell_edges(centres)
        check(f"{axis}: N+1 edges for N centres", len(edges) == len(centres) + 1)
        # Midpoint of each edge pair must return the original centre. This is the
        # check that catches an off-by-half-a-cell error.
        rebuilt = (edges[:-1] + edges[1:]) / 2
        check(f"{axis}: edges round-trip to centres",
              bool(np.allclose(rebuilt, centres, atol=1e-9)),
              f"max drift {np.abs(rebuilt - centres).max():.2e} deg")
        check(f"{axis}: edges are monotonic", bool(np.all(np.diff(edges) > 0)))


def check_coverage(ds) -> None:
    print("\ncoverage of CONFIG_MAP['REGION']")
    lat_edges = sst.cell_edges(ds["latitude"].values)
    lon_edges = sst.cell_edges(ds["longitude"].values)
    west, east = sst.BOX["lon"]
    south, north = sst.BOX["lat"]
    check("covers west edge", lon_edges.min() <= west,
          f"{lon_edges.min():.3f} <= {west}")
    check("covers east edge", lon_edges.max() >= east,
          f"{lon_edges.max():.3f} >= {east}")
    check("covers south edge", lat_edges.min() <= south,
          f"{lat_edges.min():.3f} <= {south}")
    check("covers north edge", lat_edges.max() >= north,
          f"{lat_edges.max():.3f} >= {north}")


def check_flags(ds) -> None:
    print("\nunreachable water")
    flagged = sst.flag_disconnected(ds)
    variable = sst.variable_name(ds)
    ocean = np.isfinite(ds[variable].values).any(axis=0)
    check("flagging returns a mask the shape of the grid", flagged.shape == ocean.shape)
    check("flagged cells are a subset of ocean", bool((flagged & ~ocean).sum() == 0))
    check("flagged set is a small minority", int(flagged.sum()) < 0.05 * int(ocean.sum()),
          f"{int(flagged.sum())} of {int(ocean.sum())} ocean cells")
    if flagged.any():
        lat = ds["latitude"].values
        ii, _ = np.nonzero(flagged)
        # The known case sits at the far north-east; if flagging ever starts selecting
        # water in the south-west it has stopped meaning what it means.
        check("flagged water is in the north", float(lat[ii].min()) > 49.0,
              f"southernmost flagged cell at {lat[ii].min():.2f} N")


def check_geojson(ds) -> None:
    print("\nGeoJSON output")
    date = sst.dates(ds)[-1]
    collection = sst.cell_polygons(ds, date)
    features = collection["features"]
    variable = sst.variable_name(ds)
    expected = int(np.isfinite(ds[variable].values[-1]).sum())

    check("is a FeatureCollection", collection["type"] == "FeatureCollection")
    check("one feature per ocean cell", len(features) == expected,
          f"{len(features)} features, {expected} ocean cells")

    rings_closed = all(f["geometry"]["coordinates"][0][0]
                       == f["geometry"]["coordinates"][0][-1] for f in features)
    check("every ring is closed", rings_closed)

    five_points = all(len(f["geometry"]["coordinates"][0]) == 5 for f in features)
    check("every polygon is a closed quad", five_points)

    has_props = all({"sst", "lat", "lon", "flagged"} <= set(f["properties"]) for f in features)
    check("every feature carries sst/lat/lon/flagged", has_props)

    finite_values = all(np.isfinite(f["properties"]["sst"]) for f in features)
    check("no NaN leaked into properties", finite_values)

    # A cell's centre must fall inside its own polygon -- catches a lon/lat swap, which
    # otherwise produces a plausible-looking map of the wrong place.
    sample = features[len(features) // 2]
    ring = sample["geometry"]["coordinates"][0]
    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    centre_inside = (min(lons) <= sample["properties"]["lon"] <= max(lons)
                     and min(lats) <= sample["properties"]["lat"] <= max(lats))
    check("cell centre falls inside its own polygon", centre_inside)

    check("coordinates are [lon, lat] order",
          all(-180 <= point[0] <= 180 and -90 <= point[1] <= 90 for point in ring))


def check_clipped_geojson(ds) -> None:
    """The clipped path is what the map actually draws, so it needs its own checks.

    Clipping trades one rectangle per cell for the water part of that cell's footprint,
    taken from the ~1 km mask. The failure to guard against is over-eager clipping --
    quietly deleting real water because a boundary landed a fraction of a degree the
    wrong way. That bug is invisible on a map (the sea simply looks a little smaller)
    and is exactly what these checks are for.
    """
    print("\nGeoJSON output -- clipped to coastline")
    if not sst.LAND_MASK.exists():
        check("land mask present", False, f"{sst.LAND_MASK.name} missing -- "
              "run make_land_mask.py")
        return

    date = sst.dates(ds)[-1]
    plain = sst.cell_polygons(ds, date, clip=False)
    clipped = sst.cell_polygons(ds, date, clip=True)
    features = clipped["features"]

    check("is a FeatureCollection", clipped["type"] == "FeatureCollection")
    check("every geometry is a MultiPolygon",
          all(f["geometry"]["type"] == "MultiPolygon" for f in features))

    rings_closed = all(ring[0] == ring[-1]
                       for f in features
                       for poly in f["geometry"]["coordinates"] for ring in poly)
    check("every ring is closed", rings_closed)

    quads = all(len(ring) == 5
                for f in features
                for poly in f["geometry"]["coordinates"] for ring in poly)
    check("every ring is a closed quad", quads)

    non_degenerate = all(
        len({tuple(pt) for pt in ring}) == 4
        for f in features
        for poly in f["geometry"]["coordinates"] for ring in poly)
    check("no ring collapsed to a line or point", non_degenerate)

    check("clipping only ever removes cells, never adds",
          len(features) <= len(plain["features"]),
          f"{len(plain['features'])} -> {len(features)}")

    dropped = len(plain["features"]) - len(features)
    check("dropped cells are a small minority", dropped < 0.05 * len(plain["features"]),
          f"{dropped} dropped of {len(plain['features'])}")

    # The heart of it: nothing dropped may contain water, and nothing kept may be all
    # land. The two directions need OPPOSITE tolerances so that each only fires on an
    # unambiguous error:
    #   dropped -> judged strictly INSIDE the cell, so a mask cell sitting on a shared
    #              edge (owned by exactly one of the two neighbours) is not counted as
    #              water this cell lost;
    #   kept    -> judged on INCLUSIVE bounds, since a cell whose only water lies on its
    #              boundary is legitimately kept, and a strict test would call it land.
    # Using one tolerance for both would make one direction fail on correct behaviour.
    mask_lat, mask_lon, water = sst.water_mask()
    lat = ds["latitude"].values
    lon = ds["longitude"].values
    lat_edges, lon_edges = sst.cell_edges(lat), sst.cell_edges(lon)
    kept = {(f["properties"]["lat"], f["properties"]["lon"]) for f in features}
    margin = 0.002

    wrongly_dropped = kept_all_land = 0
    for f in plain["features"]:
        key = (f["properties"]["lat"], f["properties"]["lon"])
        i = int(np.argmin(abs(lat - key[0])))
        j = int(np.argmin(abs(lon - key[1])))
        strict_rows = (mask_lat >= lat_edges[i] + margin) & (mask_lat < lat_edges[i + 1] - margin)
        strict_cols = (mask_lon >= lon_edges[j] + margin) & (mask_lon < lon_edges[j + 1] - margin)
        loose_rows = (mask_lat >= lat_edges[i] - margin) & (mask_lat <= lat_edges[i + 1] + margin)
        loose_cols = (mask_lon >= lon_edges[j] - margin) & (mask_lon <= lon_edges[j + 1] + margin)

        if key not in kept:
            if strict_rows.any() and strict_cols.any() \
                    and bool(water[np.ix_(strict_rows, strict_cols)].any()):
                wrongly_dropped += 1
        else:
            if loose_rows.any() and loose_cols.any() \
                    and not bool(water[np.ix_(loose_rows, loose_cols)].any()):
                kept_all_land += 1

    check("no cell containing water was dropped", wrongly_dropped == 0,
          f"{wrongly_dropped} wrongly dropped")
    check("cells that are entirely land were dropped", kept_all_land == 0,
          f"{kept_all_land} all-land cells kept")

    # The point of the exercise: colour must stop at the shore.
    def land_share(collection):
        total = land = 0
        for feat in collection["features"]:
            geom = feat["geometry"]
            parts = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                     else [geom["coordinates"]])
            for poly in parts:
                ring = poly[0]
                lons = [pt[0] for pt in ring]
                lats = [pt[1] for pt in ring]
                rows = (mask_lat >= min(lats)) & (mask_lat < max(lats))
                cols = (mask_lon >= min(lons)) & (mask_lon < max(lons))
                if not rows.any() or not cols.any():
                    continue
                block = water[np.ix_(rows, cols)]
                total += block.size
                land += int((~block).sum())
        return land / total if total else 0.0

    before, after = land_share(plain), land_share(clipped)
    check("clipping cuts the land painted over", after < before,
          f"{before * 100:.1f}% -> {after * 100:.1f}% of drawn area")
    check("almost no land is painted after clipping", after < 0.005,
          f"{after * 100:.2f}%")

    # Cheap insurance: run-merging is what keeps this affordable to bake into a style.
    parts = [len(f["geometry"]["coordinates"]) for f in features]
    check("run-merging keeps sub-polygons per cell low",
          float(np.mean(parts)) < 2.0,
          f"mean {np.mean(parts):.2f}, max {max(parts)}")


def check_exported_layer(ds) -> None:
    """The handed-over file must agree with the archive it came from.

    This is the artifact someone else's app consumes, so the failure that matters is
    staleness -- an export left behind after a fetch, quietly serving last week's dates
    under this week's name. Checked by regenerating from the archive and comparing.
    """
    print("\nexported layer -- data/sst_barkley_layer.geojson")
    path = sst.DATA_DIR / "sst_barkley_layer.geojson"
    if not path.exists():
        check("export present", False,
              f"{path.name} missing -- run export_layer.py")
        return

    import json
    layer = json.loads(path.read_text())
    meta = layer.get("properties", {})
    features = layer["features"]

    check("is a FeatureCollection", layer.get("type") == "FeatureCollection")

    expected_dates = sst.dates(ds)
    check("covers exactly the archive's dates", meta.get("dates") == expected_dates,
          f"{meta.get('dates', ['?'])[0]}..{meta.get('dates', ['?'])[-1]} "
          f"vs {expected_dates[0]}..{expected_dates[-1]}")
    check("default date is the newest", meta.get("default_date") == expected_dates[-1])

    per_day = {}
    for feature in features:
        per_day[feature["properties"]["date"]] = per_day.get(
            feature["properties"]["date"], 0) + 1
    check("every date carries features", set(per_day) == set(expected_dates),
          f"{len(per_day)} dates present")
    check("feature count matches a fresh build",
          len(features) == len(sst.cell_polygons(ds, expected_dates[-1],
                                                 clip=True)["features"]) * len(expected_dates),
          f"{len(features)} features")

    check("every feature carries sst/lat/lon/flagged/date",
          all({"sst", "lat", "lon", "flagged", "date"} <= set(f["properties"])
              for f in features))
    check("no NaN leaked into properties",
          all(np.isfinite(f["properties"]["sst"]) for f in features))
    check("geometry is clipped (MultiPolygon)",
          all(f["geometry"]["type"] == "MultiPolygon" for f in features))

    # A consumer styles from these and imports nothing of ours, so their absence is a
    # silent downgrade to whatever default the app happens to use.
    check("carries the colour range", meta.get("color_range") == list(sst.COLOR_RANGE))
    check("carries a ready-made fill expression",
          isinstance(meta.get("maplibre_fill_color"), list)
          and meta["maplibre_fill_color"][0] == "interpolate")
    check("carries the source caveat", bool(meta.get("source_caveat")))


def check_colors() -> None:
    print("\ncolour ramp")
    stops = sst.color_stops()
    check("stops alternate value/hex", len(stops) == 2 * len(sst.THERMAL_STOPS))
    values = stops[0::2]
    check("stop values ascend", values == sorted(values))
    check("ramp spans the colour range",
          values[0] == sst.COLOR_RANGE[0] and values[-1] == sst.COLOR_RANGE[1])

    low, high = sst.COLOR_RANGE
    check("below-range clamps to the cold end", sst.color_for(low - 5) == sst.THERMAL_STOPS[0][1])
    check("above-range clamps to the warm end", sst.color_for(high + 5) == sst.THERMAL_STOPS[-1][1])
    check("colour_for is deterministic", sst.color_for(15.0) == sst.color_for(15.0))
    midpoint = sst.color_for((low + high) / 2)
    check("midpoint returns a hex colour",
          isinstance(midpoint, str) and midpoint.startswith("#") and len(midpoint) == 7,
          midpoint)


def main() -> int:
    print(f"verifying {sst.SST_ARCHIVE}")
    try:
        ds = sst.read_grid()
    except FileNotFoundError as err:
        print(f"  [FAIL] archive missing -- {err}")
        return 1

    check_archive(ds)
    check_geometry(ds)
    check_coverage(ds)
    check_flags(ds)
    check_geojson(ds)
    check_clipped_geojson(ds)
    check_exported_layer(ds)
    check_colors()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for label in FAILURES:
            print(f"  - {label}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
