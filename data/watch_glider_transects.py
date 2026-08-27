#!/usr/bin/env python3
"""Record which glider transects are in the BarkleyScope box, and notice new ones.

Run daily (00:00 UTC) by .github/workflows/watch-glider-transects.yml:

    python data/watch_glider_transects.py

It maintains two small tracked files, both derived from the C-PROOF catalogue:

``cproof_transects.json``
    The manifest. Every deployment with a track inside the study box whose last fix
    is recent, plus a ``seen`` ledger recording when each transect *first* appeared.
    The ledger is what makes "new" mean anything: without it, a restarted job would
    call every deployment new.

``cproof_transects.geojson``
    The same deployments as map-ready LineStrings, coloured by C-PROOF's own
    per-deployment colour. This is what a map app should read -- it saves querying
    the C-PROOF server on every page load, and it is a few KB rather than the
    1-60 MB of the netCDF files it points at.

Only the catalogue is downloaded (one request, ~3.5 MB) plus a directory listing per
deployment to resolve its real-time file URLs. No netCDF files are fetched, so the
job finishes in seconds and costs nothing to run nightly.

Like ``update_cproof_glider.py``, the state lives in the output rather than in a
sidecar, so the job is idempotent and self-healing: a run after a missed week
re-derives everything from the catalogue and simply picks up whatever is new.

Also useful by hand::

    python data/watch_glider_transects.py --dry-run     # show the diff, write nothing
    python data/watch_glider_transects.py --lookback-days 90
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cproof_https as live                                         # noqa: E402
from cproof_glider import BOX, DATA_DIR, DISCOVERY_LOOKBACK_DAYS    # noqa: E402

MANIFEST = DATA_DIR / "cproof_transects.json"
GEOJSON = DATA_DIR / "cproof_transects.geojson"

#: Manifest schema version. Bump if the shape changes in a way a reader must notice;
#: a reader can then refuse politely instead of misinterpreting fields.
SCHEMA = 1


# --------------------------------------------------------------------------------------
# Building the manifest
# --------------------------------------------------------------------------------------

def describe(deployment: live.Deployment, session=None, resolve_files: bool = True) -> dict:
    """One deployment as a JSON-friendly record."""
    inside = deployment.in_box()
    track = deployment.track[inside]

    record = {
        "deployment": deployment.name,
        "glider": deployment.glider,
        "project": deployment.project,
        "comment": deployment.comment,
        "start": deployment.start.isoformat(),
        "last_fix": deployment.end.isoformat(),
        # Deliberately no age: it is a function of when you look, so storing it would
        # make the manifest differ from itself on every run and turn "changed" -- which
        # gates the nightly commit -- into "ran". Derive it from last_fix at read time.
        "active": deployment.active,
        "color": deployment.color,
        "url": deployment.url,
        "profiles_total": int(len(inside)),
        "profiles_in_box": int(inside.sum()),
    }
    if len(track):
        record["bbox_in_box"] = {
            "lon": [round(float(track[:, 0].min()), 4), round(float(track[:, 0].max()), 4)],
            "lat": [round(float(track[:, 1].min()), 4), round(float(track[:, 1].max()), 4)],
        }

    if resolve_files:
        # Resolved every run rather than cached: C-PROOF renames these as processing
        # advances (a deployment can gain an `_adjusted` variant mid-mission), so a URL
        # frozen at first sight goes stale. Two cheap directory listings per deployment.
        record["files"] = {
            product: live.realtime_url(deployment, product, session)
            for product in live.PRODUCTS
        }
    return record


def load_manifest(path: Path) -> dict:
    """The previous manifest, or an empty one on first run."""
    if not path.exists():
        return {"schema": SCHEMA, "transects": [], "seen": {}}
    manifest = json.loads(path.read_text())
    if manifest.get("schema") != SCHEMA:
        raise SystemExit(
            f"{path} is schema {manifest.get('schema')}, this script writes {SCHEMA}. "
            "Delete it to rebuild, or check out a matching version of this script."
        )
    return manifest


def build(lookback_days: float, resolve_files: bool = True, log=print) -> tuple[dict, list]:
    """Assemble the current manifest body and the deployments behind it."""
    catalogue = live.fetch_catalogue()
    deployments = live.available_now(recent_days=lookback_days, catalogue=catalogue)

    session = live._session() if resolve_files else None
    body = {
        "schema": SCHEMA,
        "source": live.SERVER,
        "box": {"lon": list(BOX["lon"]), "lat": list(BOX["lat"])},
        "lookback_days": lookback_days,
        "catalogue_deployments": len(catalogue),
        "transects": [describe(d, session, resolve_files) for d in deployments],
    }
    log(f"{len(catalogue)} deployments in the catalogue; "
        f"{len(deployments)} with a track in the box in the last {lookback_days:g} days")
    return body, deployments


def merge_ledger(previous: dict, body: dict, now: str) -> dict:
    """Carry ``first_seen`` forward, and stamp it on transects appearing for the first time.

    Entries are never removed. A deployment that has left the lookback window is still a
    transect that happened here, and its ledger entry is what stops it being announced
    as new all over again if it briefly reappears.
    """
    ledger = dict(previous.get("seen") or {})
    for record in body["transects"]:
        name = record["deployment"]
        entry = ledger.get(name)
        if entry is None:
            entry = {"first_seen": now}
        entry["last_fix"] = record["last_fix"]
        entry["profiles_in_box"] = record["profiles_in_box"]
        ledger[name] = entry
        record["first_seen"] = entry["first_seen"]
    return dict(sorted(ledger.items()))


# --------------------------------------------------------------------------------------
# What changed
# --------------------------------------------------------------------------------------

def diff(previous: dict, body: dict) -> dict:
    """New, still-running, and departed transects, comparing manifests."""
    was = {record["deployment"]: record for record in previous.get("transects") or []}
    now = {record["deployment"]: record for record in body["transects"]}
    ledger = previous.get("seen") or {}

    return {
        # Never seen in the ledger either -- so a deployment that dropped out of the
        # window and came back is "returned", not "new".
        "new": [name for name in now if name not in was and name not in ledger],
        "returned": [name for name in now if name not in was and name in ledger],
        "advanced": [name for name in now if name in was
                     and now[name]["last_fix"] != was[name]["last_fix"]],
        "departed": [name for name in was if name not in now],
    }


def subject(changes: dict, body: dict) -> str:
    """A one-line commit subject describing the change."""
    count = len(body["transects"])
    if changes["new"]:
        return f"New glider transect in Barkley box: {', '.join(changes['new'])}"
    if changes["returned"]:
        return f"Glider transect back in Barkley box: {', '.join(changes['returned'])}"
    if changes["departed"] and not changes["advanced"]:
        return f"Glider transect ended: {', '.join(changes['departed'])}"
    return f"Update glider transects ({count} reporting in the Barkley box)"


def report(changes: dict, body: dict) -> str:
    """Markdown summary, for the Actions run page and the console."""
    lines = [
        f"**{len(body['transects'])}** transect(s) in the box, "
        f"last fix within {body['lookback_days']:g} days.",
        "",
        "| deployment | project | last fix (UTC) | age (d) | in box | first seen |",
        "|---|---|---|---|---|---|",
    ]
    moment = pd.Timestamp.now(tz="UTC")
    for record in body["transects"]:
        marker = " 🆕" if record["deployment"] in changes["new"] else ""
        age = (moment - pd.Timestamp(record["last_fix"])).total_seconds() / 86400
        lines.append(
            f"| `{record['deployment']}`{marker} | {record['project']} | "
            f"{record['last_fix'][:16].replace('T', ' ')} | {age:.1f} | "
            f"{record['profiles_in_box']}/{record['profiles_total']} | "
            f"{record.get('first_seen', '')[:10]} |"
        )

    for label, key in [("New", "new"), ("Returned", "returned"), ("Ended", "departed")]:
        if changes[key]:
            lines += ["", f"**{label}:** " + ", ".join(f"`{n}`" for n in changes[key])]
    return "\n".join(lines)


def _emit(name: str, value: str, single_line: bool = False) -> None:
    """Write a step summary or output, when running under GitHub Actions.

    ``single_line`` collapses newlines, because ``GITHUB_OUTPUT`` is a ``key=value``
    file: a value containing a line break silently becomes a second, malformed entry.
    Deployment names come from a third-party catalogue, so this is not hypothetical
    enough to leave to chance.
    """
    target = os.environ.get(name)
    if not target:
        return
    if single_line:
        value = " ".join(value.split())
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(value + "\n")


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lookback-days", type=float, default=DISCOVERY_LOOKBACK_DAYS,
                        help="how recent a last fix must be to appear in the manifest "
                             f"(default: {DISCOVERY_LOOKBACK_DAYS}; deliberately wider than "
                             "cproof_https.RECENT_DAYS so a missed week loses nothing)")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--geojson", type=Path, default=GEOJSON)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    parser.add_argument("--no-resolve-files", action="store_true",
                        help="skip resolving real-time file URLs (one fewer request per "
                             "deployment; the manifest then only locates deployments, "
                             "not their files)")
    arguments = parser.parse_args(argv)

    previous = load_manifest(arguments.manifest)
    body, deployments = build(arguments.lookback_days,
                              resolve_files=not arguments.no_resolve_files)
    changes = diff(previous, body)

    now = pd.Timestamp.now(tz="UTC").isoformat()
    body["seen"] = merge_ledger(previous, body, now)

    # `updated` records when the content last *changed*, not when it was last checked.
    # Stamping every run would rewrite the file nightly even when nothing happened, and
    # a manifest that changes daily regardless is a manifest whose diff means nothing.
    comparable = {key: value for key, value in body.items() if key != "updated"}
    was_comparable = {key: value for key, value in previous.items() if key != "updated"}
    changed = comparable != was_comparable
    body["updated"] = now if changed else previous.get("updated", now)

    summary = report(changes, body)
    print(summary)
    _emit("GITHUB_STEP_SUMMARY", summary)

    if not changed:
        print("\nNothing changed.")
        _emit("GITHUB_OUTPUT", "changed=false")
        return 0

    line = subject(changes, body)
    print(f"\n{line}")
    _emit("GITHUB_OUTPUT", "changed=true")
    _emit("GITHUB_OUTPUT", f"subject={line}", single_line=True)

    if arguments.dry_run:
        print("(--dry-run: nothing written)")
        return 0

    # The manifest is meant to be read and diffed by people, so it is indented. The
    # GeoJSON is a coordinate blob that only a map consumes -- indenting it would
    # triple the size of a file that is rewritten whenever an active glider moves.
    arguments.manifest.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    arguments.geojson.write_text(
        json.dumps(live.track_geojson(deployments), sort_keys=True,
                   separators=(",", ":")) + "\n"
    )
    print(f"wrote {arguments.manifest} and {arguments.geojson}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
