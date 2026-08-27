"""What C-PROOF has in the water over Barkley Sound *right now*, from C-PROOF directly.

This is the live-view companion to :mod:`cproof_glider`. The two answer different
questions and deliberately use different sources:

``cproof_glider``  (IOOS Glider DAC ERDDAP)
    The *archive*. Server-side subsetting, QARTOD flags, every provider's gliders --
    the right tool for "what is normal here" and for anything historical.

``cproof_https``  (this module, https://cproof.uvic.ca/gliderdata)
    The *nowcast*. C-PROOF publishes real-time netCDF as static files, refreshed
    hourly, and they run several days ahead of what reaches the DAC. Checked on
    2026-08-27: the DAC had no record of ``dfo-hal1002-20260817`` at all and its
    ``dfo-eva035`` copy stopped 3 days short, while both were current here. That
    gap is the entire reason this module exists -- a "what is out there now" panel
    cannot be built on the DAC.

The trade is that there is no query interface. Files are all-or-nothing downloads
and the naming is not quite regular, so most of the work below is discovery:
finding which deployments touch the study box, collapsing the ones that are really
one mission, and picking the real-time file out of a directory listing.

Frames come back in the same shape :func:`cproof_glider.read_archive` returns --
``COLUMNS``, one row per observation -- so anything already reading the archive can
read a live snapshot without changes.

Quick start::

    python data/cproof_https.py                 # what is out there now
    python data/cproof_https.py --grid          # ...and cache the gridded files too

    import cproof_https as live
    now = live.snapshot()                       # tidy DataFrame, clipped to the box
    live.track_geojson(live.available_now())    # map-ready FeatureCollection
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cproof_glider import (  # noqa: E402
    BOX,
    COLUMNS,
    DATA_DIR,
    SCIENCE_VARS,
    apply_gross_range_qc,
)

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

SERVER = "https://cproof.uvic.ca/gliderdata/deployments"

#: Every deployment C-PROOF has ever flown, with its full track as a LineString.
#: One ~3.5 MB request replaces per-deployment discovery queries entirely.
CATALOGUE_URL = f"{SERVER}/cproof-deployments.geojson"

#: Downloaded files live here. Gitignored -- they are large, and reproducible in
#: seconds from the server.
CACHE_DIR = DATA_DIR / "cproof"

#: A deployment counts as "now" if its most recent fix is within this many days.
#: Two weeks rather than two days on purpose: a glider that surfaced five days ago
#: is still in the water and still the answer to "what is out there", and C-PROOF
#: leaves ``active`` set on missions for a while after recovery, so recency of data
#: is the more honest test.
RECENT_DAYS = 14

#: Real-time products, in preference order per deployment. C-PROOF is not consistent
#: about these names -- ``dfo-hal1002-20260817`` publishes ``<name>_grid.nc`` while
#: ``dfo-eva035-20260826`` publishes only ``<name>_grid_adjusted.nc`` -- so the file
#: is *found* by listing the directory and ranking candidates, never by building a
#: URL from the deployment name. Anything with ``delayed`` in it is excluded here by
#: construction: that is the post-recovery reprocessing, which by definition does not
#: exist yet for a glider still flying.
PRODUCTS = {
    # One row per observation. ~1-2 MB. What snapshot() reads.
    "timeseries": {
        "directory": "L0-timeseries",
        "ranked_suffixes": ["", "_adjusted", "_CTDadjusted"],
    },
    # depth x profile grid, plus QC flags and *_adjusted variables the timeseries
    # lacks. 17-60 MB, uncompressed float64. What a curtain or pcolor plot wants.
    "grid": {
        "directory": "L0-gridfiles",
        "ranked_suffixes": ["_grid", "_grid_adjusted", "_grid_CTDadjusted"],
    },
}

#: C-PROOF's native netCDF spells the science variables exactly as the archive does,
#: so no renaming is needed.
NATIVE_TO_ARCHIVE = {name: name for name in SCIENCE_VARS}

#: Which channel to believe when two of them come back byte-identical. See
#: :func:`blank_mismapped_channels` -- ``oxygen_concentration`` sits last because it is
#: the slot that actually fails: roughly a third of the fleet flies no optode, and at
#: least one deployment publishes a copy of another sensor there rather than nothing.
CHANNEL_PRECEDENCE = [
    "temperature", "salinity", "density",
    "chlorophyll", "backscatter_700", "cdom",
    "oxygen_concentration",
]

TIMEOUT = 120
RETRY_ATTEMPTS = 3


# --------------------------------------------------------------------------------------
# Deployments
# --------------------------------------------------------------------------------------

@dataclass
class Deployment:
    """One entry from the C-PROOF catalogue, with its track."""

    name: str                       # e.g. "dfo-eva035-20260826"
    glider: str                     # e.g. "dfo-eva035"
    start: pd.Timestamp
    end: pd.Timestamp
    active: bool
    project: str
    comment: str
    url: str
    color: str
    track: np.ndarray = field(repr=False)   # (N, 2), lon/lat, one vertex per profile

    @property
    def mission(self) -> tuple[str, pd.Timestamp]:
        """Key identifying the *mission*, which is not the same as the directory.

        When a glider is recovered and redeployed inside one science mission, C-PROOF
        opens a new dated directory but keeps the original start time -- and the newer
        directory's file carries both legs. ``dfo-eva035-20260806`` and
        ``dfo-eva035-20260826`` are one mission by this key, and the 0826 file is a
        strict superset of the 0806 one (same 7,183 timestamps plus 489 newer). Reading
        both would double-count every observation in the overlap.
        """
        return (self.glider, self.start)

    def in_box(self, box: dict | None = None) -> np.ndarray:
        """Boolean mask over ``track`` of the vertices inside the study box."""
        box = BOX if box is None else box
        lon, lat = self.track[:, 0], self.track[:, 1]
        return (
            (lon >= box["lon"][0]) & (lon <= box["lon"][1])
            & (lat >= box["lat"][0]) & (lat <= box["lat"][1])
        )

    @property
    def age_days(self) -> float:
        return (pd.Timestamp.now(tz="UTC") - self.end).total_seconds() / 86400


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "BarkleyScope/cproof_https"
    return session


def _get(url: str, session: requests.Session | None = None, **kwargs) -> requests.Response:
    """GET with a few retries -- the server is a plain Apache and occasionally stalls."""
    session = session or _session()
    last: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = session.get(url, timeout=TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as error:      # pragma: no cover - network
            last = error
            if attempt == RETRY_ATTEMPTS - 1:
                break
    raise RuntimeError(f"could not fetch {url}: {last}")


def _timestamp(value) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC") if value else pd.NaT


def fetch_catalogue(session: requests.Session | None = None) -> list[Deployment]:
    """Every C-PROOF deployment, newest last fix first.

    One request. The catalogue carries each track as a LineString with a vertex per
    profile, which is enough to answer "does this deployment touch Barkley Sound"
    without downloading a single netCDF file.
    """
    payload = _get(CATALOGUE_URL, session).json()

    deployments = []
    for feature in payload["features"]:
        properties = feature["properties"]
        geometry = feature["geometry"] or {}

        coordinates = geometry.get("coordinates") or []
        if geometry.get("type") == "MultiLineString":
            coordinates = [point for part in coordinates for point in part]
        if not coordinates:
            continue

        name = properties["deployment_name"]
        deployments.append(Deployment(
            name=name,
            glider=f"{properties['glider_name']}{properties['glider_serial']}",
            start=_timestamp(properties.get("deployment_start")),
            end=_timestamp(properties.get("deployment_end")),
            active=bool(properties.get("active")),
            project=properties.get("project") or "",
            comment=properties.get("comment") or "",
            url=properties.get("url") or f"{SERVER}/{name.rsplit('-', 1)[0]}/{name}",
            color=properties.get("color") or "#f4a261",
            track=np.asarray(coordinates, dtype=float)[:, :2],
        ))

    return sorted(deployments, key=lambda d: d.end, reverse=True)


def collapse_missions(deployments: list[Deployment]) -> list[Deployment]:
    """Keep one directory per mission -- the one holding the most data.

    See :attr:`Deployment.mission` for why continuation directories exist. The winner
    is the one whose track runs latest, which is also the one whose file is the
    superset.
    """
    best: dict[tuple[str, pd.Timestamp], Deployment] = {}
    for deployment in deployments:
        seen = best.get(deployment.mission)
        if seen is None or deployment.end > seen.end:
            best[deployment.mission] = deployment
    return sorted(best.values(), key=lambda d: d.end, reverse=True)


def available_now(recent_days: float = RECENT_DAYS, box: dict | None = None,
                  catalogue: list[Deployment] | None = None,
                  session: requests.Session | None = None) -> list[Deployment]:
    """Deployments with data in the study box that are still reporting.

    "Still reporting" is measured from the last fix rather than the catalogue's
    ``active`` flag, which stays set for a while after recovery.
    """
    deployments = catalogue if catalogue is not None else fetch_catalogue(session)
    live = [
        deployment for deployment in collapse_missions(deployments)
        if deployment.age_days <= recent_days and deployment.in_box(box).any()
    ]
    return sorted(live, key=lambda d: d.end, reverse=True)


# --------------------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------------------

_HREF = re.compile(r'href="([^"]+\.nc)"', re.IGNORECASE)


def list_remote_files(deployment: Deployment, product: str = "timeseries",
                      session: requests.Session | None = None) -> list[str]:
    """Filenames in a deployment's product directory, from the Apache index."""
    directory = PRODUCTS[product]["directory"]
    listing = _get(f"{deployment.url}/{directory}/", session).text
    return sorted({Path(href).name for href in _HREF.findall(listing)})


def realtime_url(deployment: Deployment, product: str = "timeseries",
                 session: requests.Session | None = None) -> str | None:
    """URL of the real-time file for a deployment, or ``None`` if it has none.

    Candidates are ranked by :data:`PRODUCTS`, so a deployment publishing only
    ``_grid_adjusted.nc`` resolves just as cleanly as one publishing ``_grid.nc``.
    Path segments are percent-encoded: one glider directory (``dfo—walle652``) has a
    Unicode em-dash in its name.
    """
    spec = PRODUCTS[product]
    available = list_remote_files(deployment, product, session)

    for suffix in spec["ranked_suffixes"]:
        candidate = f"{deployment.name}{suffix}.nc"
        if candidate in available:
            return f"{deployment.url}/{spec['directory']}/{quote(candidate)}"

    # Fall back to any real-time file that at least belongs to this deployment, so a
    # naming convention we have not seen yet degrades to "works" rather than "silent
    # no data". Delayed files are never real-time, whatever else they are called.
    for candidate in available:
        if candidate.startswith(deployment.name) and "delayed" not in candidate:
            return f"{deployment.url}/{spec['directory']}/{quote(candidate)}"
    return None


def download(url: str, destination: Path, refresh: bool = True,
             session: requests.Session | None = None, log=print) -> Path:
    """Fetch ``url`` to ``destination``, re-using the cached copy when unchanged.

    Files are rewritten hourly on the server, so the cache is validated with
    ``If-Modified-Since`` against the ``Last-Modified`` we stored alongside it. That
    turns a repeated call into one cheap 304 rather than a re-download of every file.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sidecar = destination.with_suffix(destination.suffix + ".meta.json")

    headers = {}
    if destination.exists() and sidecar.exists() and refresh:
        stamp = json.loads(sidecar.read_text()).get("last_modified")
        if stamp:
            headers["If-Modified-Since"] = stamp
    elif destination.exists() and not refresh:
        log(f"  cached   {destination.name} (not revalidated)")
        return destination

    session = session or _session()
    response = session.get(url, timeout=TIMEOUT, headers=headers, stream=True)
    if response.status_code == 304:
        log(f"  cached   {destination.name}")
        return destination
    response.raise_for_status()

    # Write to a temporary neighbour first: an interrupted download must not leave a
    # truncated file that later looks like a valid cache hit.
    partial = destination.with_suffix(destination.suffix + ".part")
    with partial.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1 << 20):
            handle.write(chunk)
    partial.replace(destination)

    if response.headers.get("Last-Modified"):
        sidecar.write_text(json.dumps({
            "url": url,
            "last_modified": response.headers["Last-Modified"],
        }))
    log(f"  fetched  {destination.name} ({destination.stat().st_size / 1e6:.1f} MB)")
    return destination


def cached_path(deployment: Deployment, url: str) -> Path:
    return CACHE_DIR / deployment.name / Path(url).name


def fetch(deployment: Deployment, product: str = "timeseries", refresh: bool = True,
          session: requests.Session | None = None, log=print) -> Path | None:
    """Resolve and download one deployment's real-time file. ``None`` if it has none."""
    url = realtime_url(deployment, product, session)
    if url is None:
        log(f"  no real-time {product} for {deployment.name}")
        return None
    return download(url, cached_path(deployment, url), refresh=refresh,
                    session=session, log=log)


def fetch_many(deployments: list[Deployment], product: str = "timeseries",
               refresh: bool = True, workers: int = 4, log=print) -> dict[str, Path]:
    """Download several deployments' files concurrently."""
    session = _session()

    def one(deployment: Deployment) -> tuple[str, Path | None]:
        return deployment.name, fetch(deployment, product, refresh, session, log)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, deployments))
    return {name: path for name, path in results if path is not None}


# --------------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------------

def depth_from_pressure(pressure, latitude) -> np.ndarray:
    """Metres below the surface from in-situ pressure.

    Only a fallback: every real-time file checked carries its own ``depth``, as a
    *coordinate* rather than a data variable (which is why it does not show up in
    ``ds.data_vars``). This reproduces it to within 0.000 m on all four deployments
    tested, so it exists for files that might omit it, not because it is normally
    needed. TEOS-10 where available, else the standard 1.0197 dbar/m approximation.
    """
    pressure = np.asarray(pressure, dtype=float)
    latitude = np.asarray(latitude, dtype=float)
    try:
        import gsw
    except ImportError:                                  # pragma: no cover
        return pressure * 1.0197
    # z_from_p needs a finite latitude; the box is small enough that its centre is a
    # harmless stand-in for the handful of samples with no fix.
    fallback = float(np.mean(BOX["lat"]))
    latitude = np.where(np.isfinite(latitude), latitude, fallback)
    return -gsw.z_from_p(pressure, latitude)


def blank_mismapped_channels(frame: pd.DataFrame, log=print) -> pd.DataFrame:
    """Blank a science channel that is a byte-identical copy of another one.

    Real, and not caught by any range check. ``dfo-colin1142-20260708`` -- whose own
    catalogue comment reads "no O2 on this deployment" -- publishes an
    ``oxygen_concentration`` variable that is element-for-element identical to
    ``backscatter_700``, units and all (8.1e-5 to 5.9e-3 "umol l-1", where real
    dissolved oxygen here runs 20-350). It sits comfortably inside the gross-range
    screen, so without this an oxygen panel would plot backscatter and look plausible.

    Only exact equality counts, so two genuinely correlated sensors are never touched.
    The lower-precedence member of the pair is the one blanked.
    """
    clean = frame.copy()
    present = [name for name in CHANNEL_PRECEDENCE if name in clean]

    for position, trusted in enumerate(present):
        for suspect in present[position + 1:]:
            both = clean[trusted].notna() & clean[suspect].notna()
            if both.sum() < 10:
                continue
            if np.array_equal(clean.loc[both, trusted].to_numpy(),
                              clean.loc[both, suspect].to_numpy()):
                log(f"  {suspect}: identical to {trusted} on {both.sum():,} values "
                    f"-- blanked as a mis-mapped channel")
                clean[suspect] = np.nan
    return clean


def load_timeseries(deployment: Deployment, path: Path | None = None,
                    box: dict | None = None, clip_to_box: bool = True,
                    refresh: bool = True, session: requests.Session | None = None,
                    log=print) -> pd.DataFrame:
    """One deployment's real-time observations, in :data:`cproof_glider.COLUMNS` shape.

    Sensors the glider did not fly come back as ``NaN`` columns rather than missing
    ones -- ``dfo-hal1002`` flies no optode, so its ``oxygen_concentration`` is empty
    -- which keeps frames from different gliders concatenable.
    """
    import xarray as xr

    if path is None:
        path = fetch(deployment, "timeseries", refresh=refresh, session=session, log=log)
    if path is None:
        return pd.DataFrame(columns=COLUMNS)

    with xr.open_dataset(path) as dataset:
        frame = pd.DataFrame({
            "time": pd.to_datetime(dataset["time"].values, utc=True),
            "latitude": dataset["latitude"].values.astype("f8"),
            "longitude": dataset["longitude"].values.astype("f8"),
        })
        # `depth` is a coordinate here, not a data variable, so it is easy to miss and
        # conclude it has to be derived. Prefer the file's own; derive only if absent.
        if "depth" in dataset.variables:
            frame["depth"] = dataset["depth"].values.astype("f8")
        else:
            frame["depth"] = depth_from_pressure(
                dataset["pressure"].values, frame["latitude"].to_numpy(),
            )
        for native, archive in NATIVE_TO_ARCHIVE.items():
            frame[archive] = (
                dataset[native].values.astype("f8") if native in dataset.variables
                else np.nan
            )

    frame.insert(0, "deployment", deployment.name)
    frame.insert(1, "glider", deployment.glider)
    frame = frame.dropna(subset=["time", "latitude", "longitude"])

    # Per deployment, not on the concatenated frame: a channel is mis-mapped for one
    # glider's processing run, and comparing across deployments would never match.
    frame = blank_mismapped_channels(frame, log=log)

    if clip_to_box:
        box = BOX if box is None else box
        inside = (
            frame["longitude"].between(*box["lon"])
            & frame["latitude"].between(*box["lat"])
        )
        if not inside.all():
            log(f"  {deployment.name}: kept {inside.sum():,} of {len(frame):,} "
                f"observations inside the box")
        frame = frame[inside]

    return frame[COLUMNS].reset_index(drop=True)


def load_grid(deployment: Deployment, path: Path | None = None, refresh: bool = True,
              session: requests.Session | None = None, log=print):
    """One deployment's real-time gridded file as an ``xarray.Dataset``.

    ``depth`` x ``time`` (one column per profile), with ``longitude``/``latitude`` per
    profile and the ``*_adjusted`` and ``*_qc`` variables the timeseries does not carry.
    This is what a curtain or pcolor plot should use: ``dfo-hal1002-20260817`` is 677
    profiles here against 12,089 scattered observations in the timeseries.

    The caller owns the returned dataset and should close it.
    """
    import xarray as xr

    if path is None:
        path = fetch(deployment, "grid", refresh=refresh, session=session, log=log)
    if path is None:
        return None
    return xr.open_dataset(path)


def snapshot(recent_days: float = RECENT_DAYS, box: dict | None = None,
             clip_to_box: bool = True, refresh: bool = True, qc: bool = True,
             deployments: list[Deployment] | None = None, log=print) -> pd.DataFrame:
    """Every real-time observation currently available in the study box.

    The headline call, and a drop-in replacement for
    ``cproof_glider.read_archive(REALTIME_ARCHIVE, last_days=...)`` -- same columns,
    same units, but current to the last hour instead of the DAC's several-day lag.
    """
    if deployments is None:
        deployments = available_now(recent_days, box)
    if not deployments:
        return pd.DataFrame(columns=COLUMNS)

    session = _session()
    frames = [
        load_timeseries(deployment, box=box, clip_to_box=clip_to_box,
                        refresh=refresh, session=session, log=log)
        for deployment in deployments
    ]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    if frame.empty:
        return frame

    if qc:
        # Real-time data is uncalibrated; the same gross-range screen the archive
        # applies is applied here so the two are comparable rather than subtly not.
        frame = apply_gross_range_qc(frame, log=log)
    return frame.sort_values(["deployment", "time"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Map layers
# --------------------------------------------------------------------------------------

def track_geojson(deployments: list[Deployment], box: dict | None = None,
                  clip_to_box: bool = False, precision: int = 5) -> dict:
    """Tracks as a FeatureCollection, ready to hand to MapLibre as a GeoJSON source.

    Each feature carries the deployment's own catalogue colour, so a multi-deployment
    map styles itself from ``["get", "color"]`` with no palette to maintain. No file
    downloads are involved -- the geometry comes from the catalogue.

    ``precision`` rounds coordinates to that many decimals -- five is about a metre,
    far finer than a surfacing position is meaningful. It keeps the output small, and
    keeps a version-controlled copy from churning on upstream reprocessing jitter in
    digits nobody plots.
    """
    features = []
    for deployment in deployments:
        track = deployment.track
        if clip_to_box:
            track = track[deployment.in_box(box)]
        if len(track) < 2:
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": np.round(track, precision).tolist(),
            },
            "properties": {
                "deployment": deployment.name,
                "glider": deployment.glider,
                "project": deployment.project,
                "color": deployment.color,
                "active": deployment.active,
                "start": deployment.start.isoformat(),
                "end": deployment.end.isoformat(),
                "age_days": round(deployment.age_days, 2),
            },
        })
    return {"type": "FeatureCollection", "features": features}


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------

def summarize(deployments: list[Deployment], box: dict | None = None) -> pd.DataFrame:
    """A table of what is out there, for printing."""
    rows = []
    for deployment in deployments:
        inside = deployment.in_box(box)
        rows.append({
            "deployment": deployment.name,
            "project": deployment.project,
            "last fix (UTC)": deployment.end.strftime("%Y-%m-%d %H:%M"),
            "age (d)": round(deployment.age_days, 1),
            "active": deployment.active,
            "profiles": len(inside),
            "in box": f"{inside.sum()}/{len(inside)} ({100 * inside.mean():.0f}%)",
        })
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recent-days", type=float, default=RECENT_DAYS,
                        help=f"how recent a last fix must be to count (default {RECENT_DAYS})")
    parser.add_argument("--grid", action="store_true",
                        help="also cache the gridded files (17-60 MB each)")
    parser.add_argument("--no-refresh", action="store_true",
                        help="use cached files as-is, without revalidating against the server")
    parser.add_argument("--geojson", type=Path,
                        help="write the tracks to this file as GeoJSON")
    arguments = parser.parse_args(argv)

    print(f"C-PROOF real-time, box lon {BOX['lon']} lat {BOX['lat']}")
    deployments = available_now(arguments.recent_days)
    if not deployments:
        print(f"\nNothing has reported in the box in the last {arguments.recent_days:g} days.")
        return 0

    print(f"\n{len(deployments)} deployment(s) reporting in the last "
          f"{arguments.recent_days:g} days:\n")
    print(summarize(deployments).to_string(index=False))

    print("\nReal-time files:")
    frame = snapshot(deployments=deployments, refresh=not arguments.no_refresh)
    if arguments.grid:
        fetch_many(deployments, "grid", refresh=not arguments.no_refresh)

    print(f"\n{len(frame):,} observations in the box, "
          f"{frame['time'].min():%Y-%m-%d %H:%M} to {frame['time'].max():%Y-%m-%d %H:%M} UTC")
    coverage = frame[SCIENCE_VARS].notna().mean().sort_values(ascending=False)
    print("\nVariable coverage:")
    for name, fraction in coverage.items():
        print(f"  {name:<24} {100 * fraction:5.1f}%")

    if arguments.geojson:
        arguments.geojson.write_text(json.dumps(track_geojson(deployments)))
        print(f"\nwrote {arguments.geojson}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
