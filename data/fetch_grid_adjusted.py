"""Download the ``_grid_adjusted.nc`` files for the Southern Line and SVI Shelf missions.

Companion to :mod:`cproof_https`, which answers "what is in the water right now".
This script answers the other question -- "give me the whole gridded record for the
two lines that cross the Barkley Sound box" -- and it is a bulk download rather than
a nowcast, so it lives on its own.

Mission selection comes straight from C-PROOF's catalogue, never from a hand-typed
list of deployment names, so a mission added next month is picked up automatically:

``Southern Line``
    ``project == "Southern Line"``. 12 deployments across bumblebee998, colin1142,
    hal1002 and marvin1003.

``SVI Shelf from Bamfield``
    ``comment == "SVI Shelf from Bamfield"``. 18 deployments, all eva035. Note this
    is a *comment*, not a project -- C-PROOF files these under ``LB Line`` (and one
    under ``Calvert Island Line``), so keying on ``project`` would miss all of them.

The gridded files are uncompressed float64 on a 1100-bin depth axis that is mostly
NaN below whatever depth the glider actually reached, so they are enormous on the
wire (42 MB to 940 MB each, ~10.7 GB for the set) and compress by roughly 8x. Pass
``--compress`` to rewrite each one with zlib on the way in.

Usage::

    python data/fetch_grid_adjusted.py                # raw, as published
    python data/fetch_grid_adjusted.py --compress     # zlib, ~1/8th the size
    python data/fetch_grid_adjusted.py --dry-run      # just show the plan
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cproof_https import CATALOGUE_URL, _get, _session      # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "glider_adjusted"

#: The two mission groups, each as (subfolder, catalogue field, exact value).
#: Matching is exact rather than substring: ``project == "South Line"`` is a
#: different set of deployments than ``"Southern Line"`` and must not be swept in.
GROUPS = [
    ("southern_line", "project", "Southern Line"),
    ("svi_shelf", "comment", "SVI Shelf from Bamfield"),
]

GRIDFILES = "L0-gridfiles"
_HREF = re.compile(r'href="([^"]+\.nc)"', re.IGNORECASE)


def select(session: requests.Session) -> list[dict]:
    """One entry per *mission* in either group, with its grid_adjusted URL.

    A deployment can match both groups; it is kept once, under whichever group is
    listed first in :data:`GROUPS`.

    Directories are then collapsed to missions, the same way
    :func:`cproof_https.collapse_missions` does it. When a glider is recovered and
    redeployed without a full turnaround, C-PROOF opens a *continuation* directory
    that re-publishes the whole mission to date under a later date stamp, so the
    same profiles appear under two names. ``dfo-eva035-20260806`` and
    ``dfo-eva035-20260826`` are one such pair -- both carry ``deployment_start``
    2026-08-06, and the later directory's file is a superset. Keying on
    (glider, start) and keeping the latest ``deployment_end`` takes the superset and
    drops the prefix; taking both would double-count every overlapping profile.
    """
    payload = _get(CATALOGUE_URL, session).json()

    chosen: dict[str, dict] = {}
    for feature in payload["features"]:
        properties = feature["properties"]
        for folder, field, value in GROUPS:
            if (properties.get(field) or "").strip() != value:
                continue
            name = properties["deployment_name"]
            chosen.setdefault(name, {
                "name": name,
                "group": folder,
                "glider": f"{properties.get('glider_name')}{properties.get('glider_serial')}",
                "project": properties.get("project") or "",
                "comment": properties.get("comment") or "",
                "start": properties.get("deployment_start"),
                "end": properties.get("deployment_end"),
                "base": properties.get("url")
                        or f"{CATALOGUE_URL.rsplit('/', 1)[0]}/{name.rsplit('-', 1)[0]}/{name}",
            })
            break

    best: dict[tuple[str, str], dict] = {}
    superseded: list[dict] = []
    for deployment in sorted(chosen.values(), key=lambda d: d["name"]):
        key = (deployment["glider"], str(deployment["start"]))
        incumbent = best.get(key)
        if incumbent is None:
            best[key] = deployment
        elif str(deployment["end"]) > str(incumbent["end"]):
            best[key] = deployment
            superseded.append(dict(incumbent, skip=f"superseded by {deployment['name']}"))
        else:
            superseded.append(dict(deployment, skip=f"superseded by {incumbent['name']}"))

    return sorted(best.values(), key=lambda d: d["name"]), superseded


def resolve(deployment: dict, session: requests.Session) -> dict:
    """Attach the grid_adjusted URL and size, or record why there is none.

    The file is found by listing the directory, not by assuming the name exists --
    and the listing is filtered to *this* deployment's prefix, because several
    ``L0-gridfiles`` directories also carry a stray copy of the previous mission's
    grid (``dfo-eva035-20250619/`` holds a ``dfo-eva035-20250527_grid.nc``). Taking
    those would file one mission's data under another's name.
    """
    wanted = f"{deployment['name']}_grid_adjusted.nc"
    try:
        listing = _get(f"{deployment['base']}/{GRIDFILES}/", session).text
    except RuntimeError as error:
        deployment["skip"] = f"directory unreadable: {error}"
        return deployment

    available = sorted({Path(href).name for href in _HREF.findall(listing)})
    if wanted not in available:
        mine = [f for f in available if f.startswith(deployment["name"])]
        deployment["skip"] = f"no _grid_adjusted.nc (publishes: {', '.join(mine) or 'nothing'})"
        return deployment

    deployment["file"] = wanted
    deployment["url"] = f"{deployment['base']}/{GRIDFILES}/{wanted}"
    response = session.head(deployment["url"], timeout=120, allow_redirects=True)
    deployment["remote_bytes"] = int(response.headers.get("Content-Length", 0))
    deployment["last_modified"] = response.headers.get("Last-Modified", "")
    return deployment


def verify_adjusted(path: Path) -> tuple[bool, str]:
    """Is this actually an adjusted product, or just a file named like one?

    The filename is not evidence. C-PROOF's naming is inconsistent enough that a
    ``_grid_adjusted.nc`` can be published without the calibrated fields ever having
    been computed -- and a file carrying only the raw channels is the *same* data as
    ``_grid.nc``, so accepting it on the strength of its name would quietly mix
    unadjusted profiles into a set that is supposed to be uniformly adjusted.

    ``temperature_adjusted`` is the test: it is the field every genuine adjusted
    product has, and it must contain finite values, not just exist as an all-NaN
    placeholder.
    """
    import numpy as np
    import xarray as xr

    try:
        with xr.open_dataset(path) as dataset:
            if "temperature_adjusted" not in dataset.variables:
                present = sorted(v for v in dataset.variables if v.endswith("_adjusted"))
                return False, ("no temperature_adjusted "
                               f"(has: {', '.join(present) or 'no adjusted fields at all'})")
            finite = int(np.isfinite(dataset["temperature_adjusted"].values).sum())
            if finite == 0:
                return False, "temperature_adjusted present but entirely NaN"
            return True, f"{finite} finite temperature_adjusted points"
    except Exception as error:                          # pragma: no cover - corrupt file
        return False, f"unreadable: {error}"


def download(deployment: dict, out_dir: Path, compress: bool,
             session: requests.Session, log=print) -> dict:
    """Fetch one file, optionally rewriting it with zlib compression.

    Skips a file already on disk at the expected size, so the script is safe to
    re-run after an interrupted download of a 10 GB set. A compressed target cannot
    be size-checked against the server, so it is skipped on existence alone.

    Every file is put through :func:`verify_adjusted` before it counts as fetched. A
    file that fails is moved aside to ``rejected/`` rather than deleted, so the
    decision stays auditable instead of vanishing into a log line.
    """
    target = out_dir / deployment["group"] / deployment["file"]
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and (compress or target.stat().st_size == deployment["remote_bytes"]):
        deployment["local_bytes"] = target.stat().st_size
        ok, detail = verify_adjusted(target)
        deployment["adjusted_check"] = detail
        if not ok:
            return _reject(deployment, target, out_dir, detail, log)
        log(f"  have  {deployment['file']}")
        return deployment

    partial = target.with_suffix(".nc.part")
    with session.get(deployment["url"], timeout=600, stream=True) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)

    if compress:
        import xarray as xr

        with xr.open_dataset(partial) as dataset:
            encoding = {name: {"zlib": True, "complevel": 5} for name in dataset.data_vars}
            dataset.to_netcdf(target, encoding=encoding)
        partial.unlink()
    else:
        partial.replace(target)

    deployment["local_bytes"] = target.stat().st_size

    ok, detail = verify_adjusted(target)
    deployment["adjusted_check"] = detail
    if not ok:
        return _reject(deployment, target, out_dir, detail, log)

    ratio = f" ({deployment['local_bytes'] / deployment['remote_bytes']:.0%})" if compress else ""
    log(f"  got   {deployment['file']}  {deployment['local_bytes'] / 1e6:.1f} MB{ratio}")
    return deployment


def _reject(deployment: dict, target: Path, out_dir: Path, detail: str, log) -> dict:
    """Move a file that is not genuinely adjusted out of the set, keeping the evidence."""
    quarantine = out_dir / "rejected" / deployment["group"]
    quarantine.mkdir(parents=True, exist_ok=True)
    target.replace(quarantine / target.name)
    deployment["skip"] = f"not a true adjusted file: {detail}"
    deployment.pop("local_bytes", None)
    log(f"  REJECT {deployment['file']}: {detail}")
    return deployment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output folder")
    parser.add_argument("--compress", action="store_true",
                        help="rewrite each file with zlib (~1/8th the size)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true", help="resolve, but download nothing")
    arguments = parser.parse_args(argv)

    session = _session()
    deployments, superseded = select(session)
    print(f"{len(deployments)} mission(s) in the two mission groups "
          f"({len(superseded)} continuation directory/ies collapsed away)")
    for deployment in superseded:
        print(f"  skip  {deployment['name']}: {deployment['skip']}")

    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        deployments = list(pool.map(lambda d: resolve(d, session), deployments))

    ready = [d for d in deployments if "url" in d]
    skipped = superseded + [d for d in deployments if "skip" in d]
    total = sum(d["remote_bytes"] for d in ready)
    print(f"{len(ready)} publish a _grid_adjusted.nc ({total / 1e9:.2f} GB); "
          f"{len(deployments) - len(ready)} do not")
    for deployment in deployments:
        if "skip" in deployment:
            print(f"  skip  {deployment['name']}: {deployment['skip']}")

    if not arguments.dry_run:
        print()
        with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
            fetched = list(pool.map(
                lambda d: download(d, arguments.out, arguments.compress, session), ready))

        rejected = [d for d in fetched if "skip" in d]
        ready = [d for d in fetched if "skip" not in d]
        skipped += rejected
        print(f"\n{len(ready)} verified adjusted; {len(rejected)} rejected")

        manifest = arguments.out / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(
            {"source": CATALOGUE_URL, "groups": [g[0] for g in GROUPS],
             "compressed": arguments.compress,
             "files": ready, "skipped": skipped}, indent=1, default=str))
        print(f"\nwrote {manifest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
