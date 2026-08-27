"""A layer registry for the BarkleyScope map.

Several people are producing map layers -- glider tracks, satellite SST, moorings, more
coming -- and they all have to land on one app without their authors editing the same
lines. This module is the seam: each dataset contributes one entry in `LAYERS` and one
builder function, and nobody touches the app's `map` cell.

    LAYERS = [
        {"id": "sst",    "label": "Satellite SST", "order": 10, "build": build_sst, ...},
        {"id": "glider", "label": "Glider tracks", "order": 20, "build": build_glider, ...},
    ]

Two rules the app's own architecture forces on us (MARIMO_APP_STATUS.md):

1. **Everything is baked into the style at construction.** The widget's post-construction
   `add_source`/`add_layer` calls are transient comm messages that do not survive a page
   reload, so a layer added that way vanishes on reconnect. `collect()` therefore returns
   every source and layer up front, for one `construct_basemap_style(...)` call.

2. **Showing and hiding is a separate concern from building.** The app's `map` cell must
   never re-run -- rebuilding the widget in a live session can black-screen the map. So
   visibility is applied afterwards, from a cell downstream of the map, via
   `MapWidget.set_visibility()`. `visibility_plan()` computes what that cell should do.

A builder returns `None` when its data file is absent, and `collect()` drops it with a
reason instead of raising. That is deliberate: this repo already has a layer whose file
was never committed (the CTD cast in `Web_App_test.py`), and one missing file should
disable one layer, not the whole app.

Layers that step through time (SST has one frame per day) declare `steps`; their layer
ids follow the convention `f"{group_id}-{step}"` so the visibility planner can find them.
"""

from __future__ import annotations

import sys
from pathlib import Path

SST_DIR = Path(__file__).resolve().parent
DATA_DIR = SST_DIR.parent
REPO = DATA_DIR.parent

for _p in (SST_DIR, DATA_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from maplibre.layer import Layer, LayerType          # noqa: E402
from maplibre.sources import GeoJSONSource           # noqa: E402

import barkley_sst as sst                            # noqa: E402


# ---------------------------------------------------------------------------
# Configuration -- same key style as the app's existing CONFIG_MAP entries, so
# this block can be pasted into `Web_App_test.py`'s `config` cell unchanged.
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "SST": {
        "DATA_PATH": str(sst.SST_ARCHIVE),
        "FILE_TYPE": "netcdf",
        "VARIABLE_LABEL": "Sea surface temperature (°C)",
        "COLOR_SCALE": "Thermal",
        "COLOR_RANGE": sst.COLOR_RANGE,   # fixed year-round; see the note in barkley_sst
        "FILL_OPACITY": 0.72,
        "FLAGGED_OPACITY": 0.16,          # unreachable water: muted, not deleted
        "COORD_DECIMALS": 3,
        # Clip each 5 km cell to its water area using the ~1 km mask. The product's own
        # land mask is coarser than the coastline, so unclipped cells paint colour
        # inland -- 4.5% of the drawn area was land, and 20 cells were land entirely.
        "CLIP_TO_COAST": True,
    },
    "GLIDER": {
        "DATA_PATH": str(DATA_DIR / "cproof_glider_realtime.nc"),
        "FILE_TYPE": "netcdf",
        "VARIABLE_LABEL": "Temperature (°C)",
        "LINE_COLOR": "#f4a261",
        "LINE_WIDTH": 2.5,
        "TRACK_DAYS": 30,
    },
}


# ---------------------------------------------------------------------------
# Builders. Each returns {"sources": {...}, "layers": [...], "steps": [...] | None}
# or None when its data is not available.
# ---------------------------------------------------------------------------

def build_sst(cfg):
    """One fill layer per day, all hidden except the newest.

    Seven layers rather than one layer whose data is swapped, because swapping source
    data is another post-construction call that does not survive a reload -- baking all
    seven in means a reconnect still shows a working map.
    """
    if not sst.SST_ARCHIVE.exists():
        return None

    grid = sst.read_grid()
    days = sst.dates(grid)
    if not days:
        return None

    stops = sst.color_stops(cfg["COLOR_RANGE"])
    sources, layers = {}, []

    for day in days:
        source_id = f"sst-src-{day}"
        sources[source_id] = GeoJSONSource(
            data=sst.cell_polygons(grid, day, decimals=cfg["COORD_DECIMALS"],
                                   clip=cfg.get("CLIP_TO_COAST", False))
        ).to_dict()
        layers.append(Layer(
            id=f"sst-{day}",
            type=LayerType.FILL,
            source=source_id,
            # Baked-in visibility is the state a reconnect falls back to, so the newest
            # day is the one that survives a reload.
            layout={"visibility": "visible" if day == days[-1] else "none"},
            paint={
                "fill-color": ["interpolate", ["linear"], ["get", "sst"], *stops],
                # Flagged cells are water unreachable from the open Pacific on this grid
                # -- Strait of Georgia, behind Vancouver Island. Faded rather than
                # removed: visibly present, visibly not part of the story.
                "fill-opacity": ["case", ["get", "flagged"],
                                 cfg["FLAGGED_OPACITY"], cfg["FILL_OPACITY"]],
            },
        ))

    return {"sources": sources, "layers": layers, "steps": days}


def build_glider(cfg):
    """One LineString per deployment from the committed real-time archive.

    Per deployment, not one joined line: concatenating deployments draws a straight leg
    between wherever one glider stopped and another started, which is not a track.
    """
    path = Path(cfg["DATA_PATH"])
    if not path.exists():
        return None

    import pandas as pd
    import cproof_glider as cproof

    frame = cproof.read_archive(path, variables=["temperature"])
    if frame.empty:
        return None

    cutoff = frame["time"].max() - pd.Timedelta(days=cfg["TRACK_DAYS"])
    recent = frame[frame["time"] >= cutoff].sort_values("time")

    sources, layers = {}, []
    for name, part in recent.groupby("deployment"):
        coords = [[round(float(x), 4), round(float(y), 4)]
                  for x, y in zip(part["longitude"], part["latitude"])]
        if len(coords) < 2:
            continue
        source_id = f"glider-src-{name}"
        sources[source_id] = GeoJSONSource(data={
            "type": "Feature",
            "properties": {"deployment": name},
            "geometry": {"type": "LineString", "coordinates": coords},
        }).to_dict()
        layers.append(Layer(
            id=f"glider-{name}",
            type=LayerType.LINE,
            source=source_id,
            layout={"visibility": "visible"},
            paint={"line-color": cfg["LINE_COLOR"], "line-width": cfg["LINE_WIDTH"]},
        ))

    if not layers:
        return None
    return {"sources": sources, "layers": layers, "steps": None}


# ---------------------------------------------------------------------------
# The registry itself. Adding a dataset means adding one entry here and one
# builder above -- no other file changes.
# ---------------------------------------------------------------------------

LAYERS = [
    {
        "id": "sst",
        "label": "Satellite SST",
        "order": 10,          # drawn first, so everything else sits on top of the fill
        "build": build_sst,
        "default": True,
        "missing": "no SST archive -- run data/sst/fetch_sst_barkley.py",
    },
    {
        "id": "glider",
        "label": "Glider tracks",
        "order": 20,
        "build": build_glider,
        "default": True,
        "missing": "no glider archive -- see data/README.md",
    },
]


def collect(config=None):
    """Build every registered layer.

    Returns `(sources, layers, groups, skipped)`, where `layers` is in draw order and
    `groups` carries what the toggle UI needs (label, layer ids, time steps).
    """
    config = config or DEFAULT_CONFIG
    sources, layers, groups, skipped = {}, [], [], []

    for spec in sorted(LAYERS, key=lambda s: s["order"]):
        cfg = config.get(spec["id"].upper(), {})
        built = spec["build"](cfg) if cfg else None
        if not built:
            skipped.append((spec["id"], spec["missing"]))
            continue
        sources.update(built["sources"])
        layers.extend(built["layers"])
        groups.append({
            "id": spec["id"],
            "label": spec["label"],
            "default": spec["default"],
            "ids": [layer.id for layer in built["layers"]],
            "steps": built["steps"],
        })

    return sources, layers, groups, skipped


def visibility_plan(groups, enabled=None, steps=None):
    """Map every layer id to whether it should be visible.

    Pure function of the control state, so the app's apply-cell stays a two-line loop and
    this logic can be tested without a browser.
    """
    enabled = enabled or {}
    steps = steps or {}
    plan = {}

    for group in groups:
        on = enabled.get(group["id"], group["default"])
        if group["steps"]:
            # A stepped group shows exactly one frame at a time. Layer ids follow the
            # f"{group_id}-{step}" convention the builder used.
            chosen = steps.get(group["id"], group["steps"][-1])
            for step in group["steps"]:
                plan[f"{group['id']}-{step}"] = on and step == chosen
        else:
            for layer_id in group["ids"]:
                plan[layer_id] = on

    return plan
