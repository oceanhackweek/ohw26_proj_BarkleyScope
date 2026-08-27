"""Precompute map-ready glider tracks from the gridded adjusted files.

The map app cannot read ``data/glider_adjusted/`` directly -- that is 10.68 GB across
26 files, and a browser needs about a megabyte of line geometry. But the geometry is
all that a track layer wants, and the gridded files carry it cheaply: ``longitude``
and ``latitude`` are 1-D coordinates on ``time``, one point per profile, so a whole
deployment's path is a few thousand pairs sitting next to gigabytes of depth grid.

This script reads only those coordinates, clips to the study box, splits the result
into drawable segments, and writes a GeoJSON small enough to commit. The app then
loads one file and never touches the netCDF at all -- the same split
``data/watch_glider_transects.py`` already uses for the real-time layer.

Run it after any ``fetch_grid_adjusted.py`` run::

    python data/build_historical_tracks.py
    python data/build_historical_tracks.py --dry-run     # report, write nothing

Outputs, both committed:

``glider_adjusted_tracks.geojson``
    One LineString per drawable segment, carrying the properties a colour ramp and a
    legend need.

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

#: Split a segment wherever consecutive points jump farther than this, in degrees.
#: Matches the map app's ``CONFIG_MAP["GLIDER"]["MAX_GAP_DEG"]`` on purpose: a track
#: clipped to the box leaves and re-enters, and joining those ends would draw a
#: straight line through water the glider never crossed.
MAX_GAP_DEG = 0.05

#: Split a segment wherever consecutive profiles are farther apart than this, in
#: hours. Profiles land roughly hourly, so this only fires on real discontinuities --
#: but it fires hard when it needs to. Two ``bumblebee998`` files carry an entire
#: earlier mission ahead of the one they are named for, separated by a ~14-month gap
#: (see :func:`summarize` output). Without a time split those become one feature
#: spanning 2022 to 2024, which both draws a bogus connector and drags a
#: deployment-date colour ramp across two years to serve one track.
MAX_GAP_HOURS = 24.0

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
    the first observation in 24 of 26 files, so it is the better key -- and where it
    disagrees, per-segment times computed from the data itself carry the truth.
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


def split_segments(frame: pd.DataFrame) -> list[pd.DataFrame]:
    """Break a track wherever drawing a straight line would invent a path.

    Two independent cuts, both necessary. The spatial one catches a glider that left
    the box and came back; the temporal one catches a file that holds more than one
    mission. A segment of a single point is dropped -- a LineString needs two.
    """
    if len(frame) < 2:
        return []

    jump_deg = np.hypot(frame["lon"].diff(), frame["lat"].diff())
    jump_hours = frame["time"].diff().dt.total_seconds() / 3600.0
    cut = (jump_deg > MAX_GAP_DEG) | (jump_hours > MAX_GAP_HOURS)

    segments = [part for _, part in frame.groupby(cut.cumsum())]
    return [segment for segment in segments if len(segment) >= 2]


def modal_month(segment: pd.DataFrame) -> str:
    """The ``YYYY-MM`` that most of this segment's profiles fall in.

    A deployment straddling a month boundary gets the month it mostly occupied,
    rather than whichever month happened to contain its first profile.
    """
    months = segment["time"].dt.strftime("%Y-%m")
    return Counter(months).most_common(1)[0][0]


def build_tracks(grid_dir: Path = GRID_DIR, log=print) -> tuple[dict, list[dict]]:
    """Every deployment's box-clipped track, as a GeoJSON FeatureCollection."""
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
        segments = split_segments(frame)

        for index, segment in enumerate(segments):
            coordinates = [
                [round(lon, PRECISION), round(lat, PRECISION)]
                for lon, lat in zip(segment["lon"], segment["lat"])
            ]
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "properties": {
                    "deployment": name,
                    "glider": name.split("-")[1],
                    "group": group,
                    "segment": index,
                    "n_points": len(segment),
                    # From the directory stamp -- one value for the whole deployment,
                    # which is what "colour by time of deployment" means.
                    "deployment_start": start.strftime("%Y-%m-%d"),
                    "deployment_month": start.strftime("%Y-%m"),
                    # From this segment's own profiles. These differ from the two
                    # fields above exactly where a file holds a mission it is not
                    # named for, so a ramp keyed on these stays honest there.
                    "segment_start": segment["time"].iloc[0].strftime("%Y-%m-%dT%H:%M"),
                    "segment_end": segment["time"].iloc[-1].strftime("%Y-%m-%dT%H:%M"),
                    "segment_month": modal_month(segment),
                },
            })

        report.append({
            "deployment": name,
            "group": group,
            "stamp": start.strftime("%Y-%m-%d"),
            "profiles_in_box": len(frame),
            "segments": len(segments),
            "months": sorted({modal_month(s) for s in segments}),
        })
        log(f"  {name:26s} {len(frame):5d} pts in box -> {len(segments):3d} segment(s)")

    return _finalize(features), report


def _finalize(features: list[dict]) -> dict:
    """Attach the numeric ramp key and the collection-level colour domain.

    ``epoch_days`` exists because MapLibre's ``interpolate`` needs a number to ramp
    over, and a date string is not one. Zero is the earliest deployment in the set,
    so the domain is stable and the app does not have to scan the features to find
    its own colour bounds -- it reads ``epoch_days_max`` and the month list here.
    """
    if not features:
        return {"type": "FeatureCollection", "features": []}

    starts = [pd.Timestamp(f["properties"]["deployment_start"]) for f in features]
    segment_starts = [pd.Timestamp(f["properties"]["segment_start"]) for f in features]

    # The origin is the earliest *deployment*, deliberately not the earliest segment.
    # Anchoring on segments would hand the origin to the two bumblebee998 files that
    # carry a stray 2022 mission, stretching the ramp over 1358 days to serve four
    # outlier segments and flattening the colour difference across everything else.
    # Those segments instead go negative, which is honest and which a consumer can
    # clamp to the light end -- the domain below says exactly how far negative.
    earliest = min(starts).normalize()

    for feature, start, segment_start in zip(features, starts, segment_starts):
        # Two ramp keys on one origin, so the app can switch between "one colour per
        # deployment" and "colour by when this piece was actually flown" without
        # rebuilding this file. They agree everywhere except those bumblebee998
        # deployments -- which is the whole point of keeping both.
        feature["properties"]["epoch_days"] = int((start - earliest).days)
        feature["properties"]["segment_epoch_days"] = int((segment_start - earliest).days)

    segment_days = [f["properties"]["segment_epoch_days"] for f in features]
    months = sorted({f["properties"]["segment_month"] for f in features})
    return {
        "type": "FeatureCollection",
        "epoch_start": earliest.strftime("%Y-%m-%d"),
        "epoch_days_max": max(f["properties"]["epoch_days"] for f in features),
        "segment_epoch_days_min": min(segment_days),
        "segment_epoch_days_max": max(segment_days),
        "months": months,
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
    log(f"\n{len(report)} deployment(s), {len(features)} segment(s), {points} points")
    log(f"colour domain: {collection['epoch_start']} + 0..{collection['epoch_days_max']} days")
    log(f"months spanned: {len(collection['months'])} "
        f"({collection['months'][0]} .. {collection['months'][-1]})")

    # A deployment whose data predates its own name is carrying someone else's
    # mission. Worth naming explicitly rather than leaving it to be discovered as a
    # strange colour on the map.
    for entry in report:
        early = [m for m in entry["months"] if m < entry["stamp"][:7]]
        if early:
            log(f"  NOTE {entry['deployment']}: holds data from {', '.join(early)}, "
                f"before its own stamp {entry['stamp']}")

    empty = [e["deployment"] for e in report if e["segments"] == 0]
    if empty:
        log(f"  NOTE no drawable segment in box: {', '.join(empty)}")


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
