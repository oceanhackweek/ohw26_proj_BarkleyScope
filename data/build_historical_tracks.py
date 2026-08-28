"""Precompute map-ready glider tracks from the gridded adjusted files.

The map app cannot read ``data/glider_adjusted/`` directly -- that is 10.68 GB across
26 files, and a browser needs about a megabyte of geometry. But geometry is all a
track layer wants, and the gridded files carry it cheaply: ``longitude`` and
``latitude`` are 1-D coordinates on ``time``, one point per profile, so a whole
deployment's path is a few thousand pairs sitting next to gigabytes of depth grid.

**Tracks are points, not lines.** One point per profile, exactly where and when the
glider surfaced. A LineString would have to decide what to draw *between* consecutive
profiles, and there is no honest answer: these files sample anywhere from every ~9
minutes to every ~1 hour, so any join either invents a path across a real gap or
shreds a sparsely-sampled transit into dashes depending on where the threshold lands.
Points state what is known and assert nothing about what happened in between, which
also means this script has no gap-threshold to tune and no way to mislead by getting
one wrong.

Run it after any ``fetch_grid_adjusted.py`` run::

    python data/build_historical_tracks.py
    python data/build_historical_tracks.py --dry-run     # report, write nothing

Outputs, both committed:

``glider_adjusted_tracks.geojson``
    One MultiPoint feature per deployment -- so a colour ramp keyed on deployment
    date paints a whole deployment in one expression, and the per-deployment
    properties are stored once rather than 28,000 times.

``folger_sites.geojson``
    The two Ocean Networks Canada instrument sites in Folger Passage, as Points.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cproof_glider import BOX                                   # noqa: E402

DATA_DIR = Path(__file__).resolve().parent
GRID_DIR = DATA_DIR / "glider_adjusted"
TRACKS_OUT = DATA_DIR / "glider_adjusted_tracks.geojson"
SITES_OUT = DATA_DIR / "folger_sites.geojson"

#: Coordinate precision in the output. 5 decimal places is ~1 m at this latitude,
#: far finer than a glider's surface fix, and it roughly halves the file.
PRECISION = 5

#: Ocean Networks Canada instrument sites in Folger Passage, both inside the study
#: box. Coordinates are taken from the ONC metadata shipped with the data already in
#: ``data/folger/``, not from a gazetteer:
#:
#: - Folger Deep: ``folgerDeepDataSet.nc`` global attributes, corroborated by the
#:   ``_OM.json`` location section (48.813797, -125.280955).
#: - Folger Pinnacle: ``station_lat``/``station_lon`` on the Pinnacle hourly netCDF.
#:
#: Note these are ~650 m apart and differ by ~70 m of depth, so they must not be
#: collapsed to one marker. Beware: ``data/sst/compare_panels.py`` labels
#: (48.814, -125.281) as "Folger Pinnacle", but per ONC that is Folger *Deep* --
#: do not copy the coordinate from there.
FOLGER_SITES = [
    {
        "name": "Folger Deep",
        "code": "FGPD",
        "lon": -125.280955,
        "lat": 48.813797,
        "depth_m": 98,
        "source": "data/folger/folgerDeepDataSet.nc",
    },
    {
        "name": "Folger Pinnacle",
        "code": "FGPPN",
        "lon": -125.281500,
        "lat": 48.808292,
        "depth_m": 25,
        "source": "data/folger/FolgerPassage_FolgerPinnacle_..._avg1hour.nc",
    },
]

_STAMP = re.compile(r"-(\d{4})(\d{2})(\d{2})$")


def deployment_date(name: str) -> pd.Timestamp:
    """The deployment date, taken from the directory name rather than the file.

    The files' own ``deployment_start`` attribute is not trustworthy: 13 of the 26
    carry a placeholder (``2018-07-12``, ``2000-01-01``, ``2022-12-07``) instead of
    the real date. C-PROOF's directory stamp is internally consistent and agrees with
    the first observation in 24 of 26 files, so it is the better key.
    """
    match = _STAMP.search(name)
    if not match:
        raise ValueError(f"no date stamp in deployment name: {name}")
    return pd.Timestamp("-".join(match.groups()))


def read_track(path: Path) -> pd.DataFrame:
    """Longitude, latitude and time per profile, box-clipped and time-ordered.

    Only the three coordinates are touched, so this reads kilobytes out of a file
    that may be most of a gigabyte.
    """
    with xr.open_dataset(path, decode_timedelta=False) as dataset:
        frame = pd.DataFrame({
            "lon": np.asarray(dataset["longitude"].values, dtype=float),
            "lat": np.asarray(dataset["latitude"].values, dtype=float),
            "time": pd.to_datetime(dataset["time"].values),
        })

    frame = frame[np.isfinite(frame["lon"]) & np.isfinite(frame["lat"])]
    frame = frame[
        frame["lon"].between(*BOX["lon"]) & frame["lat"].between(*BOX["lat"])
    ]
    return frame.sort_values("time").reset_index(drop=True)


def modal_month(frame: pd.DataFrame) -> str:
    """The ``YYYY-MM`` that most of this deployment's profiles fall in.

    A deployment straddling a month boundary gets the month it mostly occupied,
    rather than whichever month happened to contain its first profile.
    """
    return Counter(frame["time"].dt.strftime("%Y-%m")).most_common(1)[0][0]


def build_tracks(grid_dir: Path = GRID_DIR, log=print) -> tuple[dict, list[dict]]:
    """Every deployment's box-clipped profile positions, as MultiPoint features."""
    paths = sorted(grid_dir.glob("*/*_grid_adjusted.nc"))
    if not paths:
        raise SystemExit(f"no gridded files under {grid_dir} -- run fetch_grid_adjusted.py first")

    features: list[dict] = []
    report: list[dict] = []

    for path in paths:
        name = path.name.replace("_grid_adjusted.nc", "")
        group = path.parent.name
        start = deployment_date(name)
        frame = read_track(path)

        if frame.empty:
            report.append({"deployment": name, "group": group,
                           "stamp": start.strftime("%Y-%m-%d"), "points": 0, "months": []})
            log(f"  {name:26s}     0 pts in box -- skipped")
            continue

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "MultiPoint",
                "coordinates": [
                    [round(lon, PRECISION), round(lat, PRECISION)]
                    for lon, lat in zip(frame["lon"], frame["lat"])
                ],
            },
            "properties": {
                "deployment": name,
                "glider": name.split("-")[1],
                "group": group,
                "n_points": len(frame),
                # From the directory stamp -- one value for the whole deployment,
                # which is what "colour by time of deployment" means.
                "deployment_start": start.strftime("%Y-%m-%d"),
                "deployment_month": start.strftime("%Y-%m"),
                # Observed span, from the data rather than the name. These disagree
                # with the two fields above exactly where a file holds a mission it
                # is not named for -- see the note build_tracks prints.
                "first_profile": frame["time"].iloc[0].strftime("%Y-%m-%dT%H:%M"),
                "last_profile": frame["time"].iloc[-1].strftime("%Y-%m-%dT%H:%M"),
                "observed_month": modal_month(frame),
                # One timestamp per coordinate, same order. Kept so the click-through
                # plots another team member is adding can tie a point back to a
                # profile without reopening the netCDF. Minute resolution: a glider
                # surfaces for minutes, and seconds would cost ~90 KB for nothing.
                "times": [t.strftime("%Y-%m-%dT%H:%M") for t in frame["time"]],
            },
        })

        report.append({
            "deployment": name,
            "group": group,
            "stamp": start.strftime("%Y-%m-%d"),
            "points": len(frame),
            "months": sorted(frame["time"].dt.strftime("%Y-%m").unique()),
        })
        log(f"  {name:26s} {len(frame):5d} pts in box")

    return _finalize(features), report


def _finalize(features: list[dict]) -> dict:
    """Attach the numeric ramp key and the collection-level colour domain.

    ``epoch_days`` exists because MapLibre's ``interpolate`` needs a number to ramp
    over, and a date string is not one. Zero is the earliest deployment in the set,
    so the domain is stable and the app does not have to scan the features to find
    its own colour bounds.
    """
    if not features:
        return {"type": "FeatureCollection", "features": []}

    starts = [pd.Timestamp(f["properties"]["deployment_start"]) for f in features]
    earliest = min(starts).normalize()

    for feature, start in zip(features, starts):
        feature["properties"]["epoch_days"] = int((start - earliest).days)

    return {
        "type": "FeatureCollection",
        "epoch_start": earliest.strftime("%Y-%m-%d"),
        "epoch_days_max": max(f["properties"]["epoch_days"] for f in features),
        "months": sorted({f["properties"]["deployment_month"] for f in features}),
        "features": features,
    }


def build_sites() -> dict:
    """The two Folger Passage instrument sites as a Point FeatureCollection."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [site["lon"], site["lat"]]},
                "properties": {k: v for k, v in site.items() if k not in ("lon", "lat")},
            }
            for site in FOLGER_SITES
        ],
    }


def summarize(collection: dict, report: list[dict], log=print) -> None:
    """Print the things worth eyeballing before committing the output."""
    features = collection["features"]
    points = sum(f["properties"]["n_points"] for f in features)
    log(f"\n{len(features)} deployment(s), {points} points")
    log(f"colour domain: {collection['epoch_start']} + 0..{collection['epoch_days_max']} days")
    log(f"deployment months: {len(collection['months'])} "
        f"({collection['months'][0]} .. {collection['months'][-1]})")

    # A deployment whose data predates its own name is carrying someone else's
    # mission. Worth naming explicitly rather than leaving it to be discovered as a
    # strange colour on the map.
    for entry in report:
        early = [m for m in entry["months"] if m < entry["stamp"][:7]]
        if early:
            log(f"  NOTE {entry['deployment']}: holds data from {', '.join(early)}, "
                f"before its own stamp {entry['stamp']}")

    empty = [e["deployment"] for e in report if e["points"] == 0]
    if empty:
        log(f"  NOTE no profiles in box: {', '.join(empty)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--grid-dir", type=Path, default=GRID_DIR)
    parser.add_argument("--tracks-out", type=Path, default=TRACKS_OUT)
    parser.add_argument("--sites-out", type=Path, default=SITES_OUT)
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    arguments = parser.parse_args(argv)

    collection, report = build_tracks(arguments.grid_dir)
    summarize(collection, report)

    sites = build_sites()
    if arguments.dry_run:
        print("\n(dry run -- nothing written)")
        return 0

    arguments.tracks_out.write_text(json.dumps(collection))
    arguments.sites_out.write_text(json.dumps(sites, indent=1))
    print(f"\nwrote {arguments.tracks_out} "
          f"({arguments.tracks_out.stat().st_size / 1e6:.2f} MB)")
    print(f"wrote {arguments.sites_out} ({len(sites['features'])} sites)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
