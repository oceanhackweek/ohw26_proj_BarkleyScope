# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "anywidget==0.11.0",
#     "gsw==3.6.23",
#     "maplibre==0.3.6",
#     "marimo>=0.24.0",
#     "netCDF4==1.7.4",
#     "numpy==2.5.2",
#     "pandas==3.0.5",
#     "plotly==7.0.0",
#     "requests==2.34.2",
#     "xarray==2026.7.0",
# ]
# [tool.marimo.venv]
# path = "/home/.pixi/envs/default"
# ///
#
# gsw, netCDF4, requests and xarray are not imported by this file -- they are
# what the DATA path pulls in, one module deeper: glider_lib ->
# data/cproof_https.py (requests, xarray, gsw) -> data/cproof_glider.py
# (netCDF4). Leaving them out is invisible in the hub, whose kernel runs in the
# configured venv below (a full conda env that already has them), and fatal
# anywhere marimo builds an ephemeral venv from this list instead: `glider_data`
# dies on `No module named 'requests'`, and every cell downstream -- including
# `map` -- reports "An ancestor raised an exception" and renders nothing. A blank
# page, with the cause one cell up from anything that looks map-related.
#
# [tool.marimo.venv].path pins the kernel to the hub's shared conda env rather
# than an ephemeral sandbox. marimo treats a configured venv as read-only and
# will NOT install into it, so anything this app needs that the env lacks
# (maplibre, anywidget, plotly) has to be installed there by hand -- and that env
# lives on the container overlay, so it is wiped on every server restart. Install
# into the persistent user site instead, which survives restarts:
#
#     python -m pip install --user maplibre==0.3.6 anywidget plotly
#
# See MARIMO_APP_STATUS.md, "Running it".

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def nb_imports():
    import marimo as mo
    import pandas as pd

    # maplibre optionally binds to the Shiny web framework and warns on import
    # if 'shiny' isn't installed ("Please install 'maplibre[shiny]'..."). This
    # app is marimo-only and never touches those bindings, so the warning is
    # pure noise -- silenced exactly as the warning's own message suggests
    # (set the 'maplibre' logger to ERROR), rather than installing an unused
    # 'shiny' dependency just to make an unrelated warning go away.
    import logging as _logging

    _logging.getLogger("maplibre").setLevel(_logging.ERROR)

    from maplibre.ipywidget import MapWidget
    from maplibre.map import MapOptions
    from maplibre.layer import Layer, LayerType
    from maplibre.sources import RasterTileSource, GeoJSONSource
    from maplibre.controls import NavigationControl, ScaleControl, FullscreenControl
    from maplibre.basemaps import construct_basemap_style

    # Only the data-loading function lives here -- `glider_data` (and
    # therefore `map`, which reads its output) is legitimately downstream of
    # it. Split `plot_glider_curtain` into its own cell (`plot_fn_imports`) on
    # purpose: it's only used by `click_plot`, never by `map`. Editing
    # `glider_lib.py`'s plotting functions and reloading only needs to rerun
    # `plot_fn_imports` -- rerunning THIS cell (e.g. via a blanket
    # `importlib.reload` + `ctx.run_cell('nb_imports')`) cascades to `map`
    # too, which forces a brand-new `MapWidget`/`map_ui` object into an
    # already-live browser session and can break the mount (confirmed: this
    # is what caused a black-screen map after a naive glider_lib reload once
    # `plot_glider_curtain` needed a margin/colorbar tweak -- the map cell
    # isn't supposed to ever re-run after initial load, see its own comments
    # below).
    from glider_lib import load_active_gliders

    return (
        GeoJSONSource,
        Layer,
        LayerType,
        MapOptions,
        MapWidget,
        NavigationControl,
        RasterTileSource,
        ScaleControl,
        construct_basemap_style,
        load_active_gliders,
        mo,
        pd,
    )


@app.cell(hide_code=True)
def config():
    CONFIG_MAP = {
        "REGION": {"lon_range": (-126.8, -124.5), "lat_range": (47.85, 49.36)},  # Barkley Sound, BC
        "GLIDER": {
            "MODE": "live",               # "live", "realtime", or "delayed". "live" reads
                                           # data/cproof_https.py's snapshot() straight from
                                           # C-PROOF's own server (hourly refresh, current to
                                           # within the hour) -- per data/README.md this runs
                                           # days ahead of the IOOS DAC archive the other two
                                           # modes read, which the DAC has been caught missing
                                           # deployments on entirely. "realtime"/"delayed" fall
                                           # back to that archive (data/cproof_glider_*.nc) --
                                           # "realtime" is a daily-refreshed snapshot committed
                                           # to git and can be stale between pulls; "delayed" is
                                           # the calibrated historical record, months/years behind.
            "ACTIVE_DAYS": 1,             # Matches "live"'s hourly refresh cadence: a deployment
                                           # with a fix in the last day is genuinely active right
                                           # now. (This value used to need inflating to 15 to find
                                           # anything, back when MODE="realtime" read a committed
                                           # archive snapshot that had gone stale -- not needed
                                           # once reading live.)
            "MIN_TRACK_POINTS": 2,        # a MapLibre LineString needs >=2 coordinate pairs.
            "MAX_HOLD_HOURS": 8,          # drop observations whose position is frozen this long.
                                           # Position only updates when a glider surfaces, so a
                                           # fix repeating for a couple of minutes is normal; one
                                           # repeating for hours means the position stopped being
                                           # reported at all (land/bench simulation, recovered
                                           # glider still emitting, stuck GPS) and should not be
                                           # drawn anywhere. Real drift is NOT masked -- a parked
                                           # glider still moves with the current. None disables.
            "VARIABLE": "temperature",    # science variable to plot/color by -- present on every
                                           # deployment (unlike 5 of the other 6 science variables).
            "VARIABLE_LABEL": "Temperature (°C)",
            "COLOR_SCALE": "Thermal",
            "LINE_COLOR": "#37474f",      # every track that is NOT the current selection.
            "SELECTED_COLOR": "#e5308f",  # the track you clicked. Applied by the
                                           # `glider_highlight` cell through a data-driven
                                           # paint expression keyed on each feature's own
                                           # "deployment" property, so selecting never
                                           # rebuilds the map (see that cell, and `map`'s
                                           # note about never re-running).
                                           #
                                           # Magenta, not the orange it used to be. That
                                           # orange cleared only 1.20:1 against the Esri
                                           # basemap's own water (#a8c9e8), so a selected
                                           # track barely separated from the sea it was
                                           # drawn on; this clears 2.37:1, the same bar
                                           # the historical ramp was built to. It is also
                                           # a different hue from that ramp, which
                                           # matters in the legend, where the live and
                                           # historical swatches sit two lines apart.
            "HEAD_RADIUS": 7,             # the newest fix of each deployment, drawn bigger
                                           # and white-ringed so the leading end of a track
                                           # is obvious -- with the trail behind it, that
                                           # is what shows which way the glider is going.
            "DEPTH_POSITIVE_DOWN": True,
        },
        "HISTORICAL": {
            # Every deployment on the Southern Line and the SVI Shelf line that has a
            # gridded adjusted file, precomputed by data/build_historical_tracks.py.
            # That script reads the 10.68 GB of netCDF; this app reads only its ~1.3 MB
            # output, so switching views costs one file read and no network.
            "TRACKS": "../data/glider_adjusted_tracks.geojson",
            "SITES": "../data/folger_sites.geojson",
            # Every site with a day-of-year temperature climatology, precomputed by
            # data/build_climatology_sites.py from the records
            # contributor_folders/Dwight/onc_climatology.py builds those climatologies
            # from. Clicking one in the historical view opens its climatology plot.
            "CLIMATOLOGY_SITES": "../data/climatology_sites.geojson",
            # Points, not lines. The gridded files sample anywhere from every ~9 min to
            # every ~1 h, so any line joining consecutive profiles either invents a path
            # across a real gap or shreds a sparse transit into dashes depending on where
            # the threshold lands -- see data/README.md. Points assert nothing in between.
            "POINT_RADIUS": 2.2,
            # Sequential ramp over deployment date, keyed on each feature's `epoch_days`.
            # Orange rather than the usual blue because the basemap *is* blue: the Esri
            # ocean tiles sample #a8c9e8, and a blue ramp's light end disappears into the
            # water. Every step here clears 2:1 contrast against that water (min 2.07),
            # single hue, monotonic lightness.
            "RAMP": ["#e35e27", "#d55114", "#c3480c", "#b04009", "#9e3807", "#8c3105", "#7a2a04"],
            # Ocean Networks Canada instrument sites in Folger Passage. Shown in BOTH
            # views -- they are fixed reference locations, useful next to a live glider
            # as much as next to the historical record. They sit ~650 m apart, so they
            # overplot until you zoom in.
            # The two ONC sites are drawn as anchors (DOM markers -- see `map`).
            # Greyed out in the real-time view, where they are context next to a
            # glider that is actually reporting; black in the historical view, where
            # the moorings are the only continuously-present instruments on the map.
            "SITE_RADIUS": 6,
            "SITE_COLOR_LIVE": "#9aa3ab",
            "SITE_COLOR_HISTORICAL": "#0b0b0b",
            # The non-Folger climatology sites -- La Perouse Bank and the five Barkley
            # Canyon moorings -- are drawn only in the historical view, so they take
            # the historical colour and never need to switch. Folger keeps its own
            # layer, which is in both views; drawing it twice here would double-plot
            # it in the historical view.
            "CLIM_SITE_RADIUS": 6,
        },
    }
    return (CONFIG_MAP,)


@app.cell(hide_code=True)
def about_note(mo, sst_meta):
    about_md = mo.md(f"""
    **About this app:** marimo + MapLibre rebuild of `Glider_Map_App.ipynb` (which used ipyleaflet +
    Voila; see `VOILA_TROUBLESHOOTING.md` for why that path was painful).

    - **Glider** -- real C-PROOF glider deployments, loaded through `glider_lib.load_active_gliders()`
      straight from C-PROOF's own server (`data/cproof_https.py`, refreshed hourly) -- current to the
      hour rather than the IOOS DAC archive's multi-day lag (see `data/README.md`). Only deployments
      with an observation inside the trailing `CONFIG_MAP["GLIDER"]["ACTIVE_DAYS"]` window are shown,
      and only the part of each track that falls *inside* that window is drawn -- so what you see is
      where the gliders have been over that period, not their whole deployment history. Widen
      `ACTIVE_DAYS` to see further back. A glider that has left the study box contributes nothing to
      the window and drops off the map rather than leaving a stale line behind.

      Drawn as one point per observation -- 30-second samples, positions dead-reckoned between GPS
      fixes -- rather than a line, on the same reasoning as the historical layer below: nothing in
      this product says what happened between two fixes, so nothing is drawn there. These are not
      surfacings only; the live timeseries has no profile key on it once `snapshot()` has reduced it
      to the shared archive columns, and picking surfacings by a shallow-depth cut swings between 4
      and 10 points a day depending on where the cut lands.

      The newest fix of each deployment is drawn bigger, with a white ring: that is where the glider
      is now, and the trail behind it is the direction it came from.

      Click anywhere on a deployment to select it: all of its points turn magenta and a 3D curtain
      plot of that deployment opens in the sidebar. Data is real-time and **not calibrated** -- only
      a gross-range screen has been applied.

    - **Historical** -- the switch at the top swaps the live view for every deployment on the
      **Southern Line** and the **SVI Shelf from Bamfield** line that has a gridded adjusted file:
      26 deployments, 28,452 profile positions, coloured by deployment date.

      This view also shows the eight moorings and buoys that have a day-of-year temperature
      climatology -- the two Folger Passage sites, five Barkley Canyon moorings from 398 m down to
      983 m, and the La Perouse Bank buoy. **Click any of them** for its climatology: the day-of-year
      mean with 1 and 2 sd bands, the current year overlaid. Records run from 9 to 34 years depending
      on the site. Built by `contributor_folders/Dwight/onc_climatology.py`; the screening rules and
      caveats are in that folder's `CLIMATOLOGY.md`.

      Zoom in before clicking in Barkley Canyon: Hydrates, Mid-East and Axis sit within 0.016 deg of
      each other and Folger Deep and Pinnacle within 0.006, so at the opening zoom they overplot. The
      click resolves to the nearest site, not the first one drawn, so zooming is enough to separate
      them.

      Each profile is drawn as its own point and nothing is drawn between them. The gridded files
      sample anywhere from every ~9 minutes to every ~1 hour, so a line joining consecutive profiles
      would either invent a path across a real gap or break a sparse transit into dashes, depending
      on where a threshold landed. Points assert only what was measured, so sparse deployments
      genuinely look sparse.

      Positions come from `data/glider_adjusted_tracks.geojson`, precomputed by
      `data/build_historical_tracks.py` -- the app reads ~1.3 MB of geometry, never the 10.68 GB of
      netCDF behind it. Colour is keyed on the date in each deployment's directory name; the files'
      own `deployment_start` attribute is wrong in 13 of the 26.

    - **Folger Deep** and **Folger Pinnacle** -- the two Ocean Networks Canada instrument sites in
      Folger Passage, the only sites shown in *both* views, as fixed reference points. They are greyed out over the
      real-time view, where a reporting glider is the subject, and black over the historical one,
      where the moorings are the only continuously-present instruments on the map. They sit ~650 m
      apart and overplot until you zoom in.

    - **Sea surface temperature** -- satellite SST, one fill layer for every date available at once,
      switched by the "SST date" control (top left). {sst_meta["source_caveat"]} The colour scale is
      fixed at {sst_meta["color_range"][0]:.0f}-{sst_meta["color_range"][1]:.0f}°C year-round,
      deliberately not autoscaled per day, so unchanged water doesn't appear to change temperature as
      you switch dates. Faint cells in the far corner are real water the satellite can see but this
      study box isn't about -- muted, not hidden. See `data/sst/INTEGRATING_THE_LAYER.md` for the full
      pipeline.

    **Data shape:** `load_active_gliders()` standardizes every deployment to `Longitude`, `Latitude`,
    `Depth`, `<variable>` -- the same schema `glider_lib.load_platform_data()` produces for a plain
    CSV/NetCDF file, so any future platform wired in through that loader works with the map/click-plot
    cells unmodified.

    ---

    **Data sources and citations.** Everything on this map is somebody else's observation. Cite the
    source, not this app.

    - **Ocean Networks Canada** -- the Folger Passage and Barkley Canyon moorings, and the
      climatologies built from them. Each deployment has its own DOI; the full list, as ONC issues it,
      is in `data/folger/Folger_Citations.md` and `data/barkley/Barkley_Citations.md`. Data portal:
      [data.oceannetworks.ca](https://data.oceannetworks.ca). Form:
      *Ocean Networks Canada Society. YEAR. Station Instrument Deployed DATE. https://doi.org/...*

    - **C-PROOF** (Canadian-Pacific Robotic Ocean Observing Facility, University of Victoria) -- every
      glider deployment, live and historical.
      [cproof.uvic.ca/gliderdata/deployments](https://cproof.uvic.ca/gliderdata/deployments/) is the
      live server this app reads; the quality-controlled archive is on the
      [IOOS Glider DAC](https://gliders.ioos.us/erddap). Real-time values are **not calibrated**.

    - **DFO / MEDS** -- buoy C46206, La Perouse Bank, 1988-2022, via
      [Fisheries and Oceans Canada](https://www.meds-sdmm.dfo-mpo.gc.ca).

    - **NOAA CoastWatch** -- the Geo-polar blended SST analysis, via
      [coastwatch.pfeg.noaa.gov/erddap](https://coastwatch.pfeg.noaa.gov/erddap). Basemap tiles are
      Esri Ocean.

    Per-source detail, including what was screened and why, lives in `data/README.md`,
    `data/sst/README.md` and `data/folger_taylor/METHODS.md`.
    """)
    return (about_md,)


@app.cell(hide_code=True)
def glider_data(CONFIG_MAP, load_active_gliders):
    _glider_cfg = CONFIG_MAP["GLIDER"]
    glider_var = _glider_cfg["VARIABLE"]

    glider_records = load_active_gliders(
        mode=_glider_cfg["MODE"],
        variable_col=glider_var,
        active_days=_glider_cfg["ACTIVE_DAYS"],
        min_points=_glider_cfg["MIN_TRACK_POINTS"],
        max_hold_hours=_glider_cfg["MAX_HOLD_HOURS"],
    )

    if _glider_cfg["DEPTH_POSITIVE_DOWN"]:
        for _rec in glider_records:
            _rec["df"]["Depth"] = -_rec["df"]["Depth"].abs()

    print(f"Glider: {len(glider_records)} active deployment(s) in the last "
          f"{_glider_cfg['ACTIVE_DAYS']} day(s) (mode={_glider_cfg['MODE']!r})")
    return (glider_records,)


@app.cell
def historical_data(CONFIG_MAP):
    # The historical view's entire data cost: two small JSON reads, no network.
    #
    # This cell's only input is CONFIG_MAP, which never changes after load, so it runs
    # exactly once -- which matters because `map` depends on it and `map` must never
    # re-run (see that cell). Load failure degrades to an empty FeatureCollection
    # rather than an exception: a missing precompute should cost you the historical
    # layer, not the whole app including the live map.
    import json as _json
    from pathlib import Path as _Path

    _cfg = CONFIG_MAP["HISTORICAL"]
    _here = _Path(__file__).resolve().parent

    def _load(relative, what):
        _path = (_here / relative).resolve()
        try:
            _data = _json.loads(_path.read_text())
        except (OSError, ValueError) as _error:
            print(f"Historical: could not read {what} ({_path}): {_error}\n"
                  f"            run `python data/build_historical_tracks.py` to build it")
            return {"type": "FeatureCollection", "features": []}
        return _data

    historical_tracks = _load(_cfg["TRACKS"], "tracks")
    folger_sites = _load(_cfg["SITES"], "Folger sites")

    # Every site with a climatology, Folger included: the map draws the Folger pair
    # from `folger_sites` above (they belong in both views), so the LAYER below gets
    # only the others -- but the click hit-test reads this whole list, which is what
    # makes all eight clickable in the historical view.
    climatology_sites = _load(_cfg["CLIMATOLOGY_SITES"], "climatology sites")
    climatology_layer_sites = {
        "type": "FeatureCollection",
        "features": [_f for _f in climatology_sites["features"]
                     if _f["properties"].get("group") != "folger"],
    }

    _n_points = sum(_f["properties"].get("n_points", 0)
                    for _f in historical_tracks["features"])
    _with_plot = sum(1 for _f in climatology_sites["features"]
                     if _f["properties"].get("climatology_png"))
    print(f"Historical: {len(historical_tracks['features'])} deployment(s), "
          f"{_n_points} profile positions, "
          f"{len(folger_sites['features'])} instrument site(s), "
          f"{len(climatology_sites['features'])} climatology site(s) "
          f"({_with_plot} with a plot)")
    return climatology_layer_sites, climatology_sites, folger_sites, historical_tracks


@app.cell(hide_code=True)
def sst_data():
    # Loaded once from the SST pipeline's own export -- see
    # data/sst/INTEGRATING_THE_LAYER.md. cwd at kernel start is NOT this
    # notebook's own directory (confirmed: the hub launches marimo from
    # /home/jovyan), so a plain relative "data/..." path would resolve wrong --
    # anchor to this file's own location instead, same pattern glider_lib.py
    # already uses for the same reason.
    import json
    from pathlib import Path

    _sst_path = Path(__file__).resolve().parent.parent / "data" / "sst_barkley_layer.geojson"
    sst_layer = json.loads(_sst_path.read_text())
    sst_meta = sst_layer["properties"]
    return sst_layer, sst_meta


@app.cell(hide_code=True)
def sst_date_control(mo, sst_meta):
    # Real mo.sidebar, not a hand-rolled floating div -- the same proven layout
    # primitive `plot_overlay` already uses for the curtain-plot panel (adopted
    # there specifically because hand-rolled position:fixed divs kept causing
    # hard-to-pin-down rendering/overlap bugs). mo.sidebar has no per-call
    # side/position option (its own source disables .left()/.right()/.center()/
    # .style()), so this stacks in the SAME left dock as the plot sidebar, "in
    # the order [mo.sidebar calls are] called" per its docstring -- not a fully
    # independent screen region, but a real, reliable one rather than guessed
    # pixel offsets.
    #
    # Defined AND displayed in this same cell -- this is sst_date_picker's only
    # defining cell, so it is exempt from re-running on its own value changes
    # (same rule that lets map_ui live inside `map`). It must NEVER be
    # referenced inside `map`'s cell body, even just for display: marimo
    # reruns any cell that references a changed UI element by name, at
    # whole-cell granularity -- that would force `map` to rebuild the widget
    # on every date change, exactly what `map`'s own comments warn against.
    #
    # The legend lives in `map`'s own floating overlay instead of here -- it's
    # static (sst_meta never changes), so baking it into map's one-time HTML
    # keeps it in the same DOM insertion as the map, and it looked better
    # bottom-right on the map itself than duplicated in this panel too.
    sst_date_picker = mo.ui.dropdown(
        options=sst_meta["dates"],
        value=sst_meta["default_date"],
        label="SST date",
    )

    mo.sidebar(mo.vstack([mo.md("**Sea Surface Temperature**"), sst_date_picker]))
    return (sst_date_picker,)


@app.cell(hide_code=True)
def map(
    CONFIG_MAP,
    GeoJSONSource,
    Layer,
    LayerType,
    MapOptions,
    MapWidget,
    NavigationControl,
    RasterTileSource,
    ScaleControl,
    about_md,
    climatology_layer_sites,
    construct_basemap_style,
    folger_sites,
    glider_records,
    historical_tracks,
    mo,
    sst_layer,
    sst_meta,
):
    _lon_lo, _lon_hi = CONFIG_MAP["REGION"]["lon_range"]
    _lat_lo, _lat_hi = CONFIG_MAP["REGION"]["lat_range"]

    ESRI_OCEAN_TILES = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}"
    )
    _esri_source = RasterTileSource(tiles=[ESRI_OCEAN_TILES], tile_size=256, min_zoom=0, max_zoom=16)
    _esri_layer = Layer(id="esri-ocean-basemap", type=LayerType.RASTER, source="esri-ocean")

    # --- Satellite SST fill layer -- see data/sst/INTEGRATING_THE_LAYER.md. One source
    # carries every available day at once (filtered by `date` in the sst_date_filter cell,
    # not by swapping sources); baked in here, before the glider layers, since it is an
    # opaque-ish fill and would bury anything drawn under it. Static at construction time --
    # only sst_meta["default_date"] is read here, never sst_date_picker.value, for the same
    # reason glider_highlight exists as a separate cell: referencing a live-changing UI
    # element inside `map`'s body would make `map` re-run on every date change.
    _sst_fill = Layer(
        id="sst",
        type=LayerType.FILL,
        source="sst-src",
        filter=["==", ["get", "date"], sst_meta["default_date"]],
        paint={
            "fill-color": sst_meta["maplibre_fill_color"],
            # Flagged cells are real water (Strait of Georgia, behind Vancouver Island) just
            # not water this study box's story is about -- faded, not hidden.
            "fill-opacity": ["case", ["get", "flagged"], 0.16, 0.72],
        },
    )

    # --- Live glider positions: ONE GeoJSONSource of Points, one per observation.
    # Points, not a LineString, for the same reason the historical layer is points
    # (see data/README.md): a line has to decide what happened between two fixes, and
    # nothing in this product says. These are 30-second samples whose positions are
    # dead-reckoned between GPS fixes -- roughly 20 m apart, so at map zoom they read
    # as a continuous trail anyway, and zooming in shows what was actually sampled
    # rather than a drawn-in path.
    #
    # This also retires the gap-splitting the LineString version needed. That existed
    # to avoid drawing a straight "fake" connector across a real gap -- a line that
    # looked clickable but had no data near it. Points cannot draw a connector, so
    # there is no gap threshold left to tune, and every drawn point is by construction
    # a real observation that click_plot's proximity test will match.
    #
    # NOT surfacing-only. The live timeseries carries `profile_index`, but `snapshot()`
    # returns exactly cproof_glider.COLUMNS (an invariant the archive path shares) and
    # that does not include it, so there is no profile key on this frame. Picking
    # surfacings by a shallow-depth cut instead was measured and rejected: on
    # dfo-eva035-20260826's last day it gives 4, 8, 9 or 10 points depending on whether
    # the cut is 1, 2, 3 or 5 m, and the count is not even monotonic in the threshold.
    # That is a knob that silently changes what the map claims, which is exactly what
    # the historical layer's points were chosen to avoid.
    _glider_point_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(_lon), float(_lat)]},
            # Cosmetic only -- click_plot hit-tests against glider_records' own
            # DataFrames, not these properties. Every point carries its deployment so
            # one click lights the whole transect (see _highlight_expr below).
            "properties": {"deployment": _rec["deployment"], "glider": _rec["glider"]},
        }
        for _rec in glider_records
        for _lon, _lat in zip(_rec["df"]["Longitude"], _rec["df"]["Latitude"])
    ]
    _glider_points_collection = {"type": "FeatureCollection", "features": _glider_point_features}

    # --- The newest fix of each deployment ---
    # Drawn bigger and white-ringed, on top of the trail. A track of identical dots says
    # where a glider has been but not which end is now; this marks the leading end, and
    # the trail behind it gives the direction.
    #
    # A circle layer rather than a DOM Marker, though a marker's pin shape would read as
    # "here" more literally. Markers cannot be hidden per view -- they are not layers, so
    # `set_visibility` does not reach them -- and a live glider's current position would
    # then sit on the historical map too, where it means nothing. This layer switches off
    # with the rest of the live view.
    #
    # An "X" was the other idea and is not available: MapLibre can only draw a text
    # symbol from a `glyphs` endpoint, and the one font server reachable from here
    # (tiles.openfreemap.org) returns no Access-Control-Allow-Origin header, so a browser
    # would refuse the fetch even though the glyph itself is there.
    _head_features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(_rec["df"]["Longitude"].iloc[_i]),
                                float(_rec["df"]["Latitude"].iloc[_i])],
            },
            "properties": {"deployment": _rec["deployment"], "glider": _rec["glider"]},
        }
        for _rec in glider_records
        # By TIME, not by row order: the loader sorts, but this should not silently
        # depend on that -- picking the wrong row would put "the glider is here now" in
        # the wrong place, which is the one error this marker exists to prevent.
        for _i in [int(_rec["df"]["Time"].to_numpy().argmax())]
    ]
    _glider_head_collection = {"type": "FeatureCollection", "features": _head_features}

    # Selection highlight, as a data-driven paint expression rather than a rebuild.
    # MapLibre evaluates this per feature against the "deployment" property every feature
    # already carries, so switching the highlight is a one-property update pushed from
    # `glider_highlight` -- the map itself is never rebuilt, which this cell must never do
    # (see its note below). "" is a sentinel matching no deployment, so nothing starts
    # highlighted; `glider_highlight` re-sends this same shape with the selected name.
    # Every point of one deployment carries that deployment's name, so clicking anywhere
    # on it lights up the whole transect, not just the point clicked.
    def _highlight_expr(selected=""):
        return [
            "case",
            ["==", ["get", "deployment"], selected],
            CONFIG_MAP["GLIDER"]["SELECTED_COLOR"],
            CONFIG_MAP["GLIDER"]["LINE_COLOR"],
        ]

    glider_highlight_expr = _highlight_expr

    # Larger than the historical layer's 2.2 px and with a stroke, so the two point
    # layers stay tellable apart when a presenter switches between them: the live
    # deployment reads as a chain of distinct beads, the historical record as a fine
    # spray. No stroke on historical, because 28,452 stroked points is a smear.
    _glider_point_layer = Layer(
        id="glider-positions",
        type=LayerType.CIRCLE,
        source="glider-positions",
        paint={
            "circle-radius": 3.4,
            "circle-color": _highlight_expr(),
            "circle-stroke-width": 0.8,
            "circle-stroke-color": "#ffffff",
            "circle-opacity": 0.95,
        },
    )

    # --- Historical layer: every profile position from the gridded adjusted files ---
    # One MultiPoint feature per deployment, so this single interpolate expression
    # paints a whole deployment at once, keyed on the `epoch_days` the precompute
    # already wrote. Days rather than a date string because `interpolate` needs a
    # number; the domain comes from the file so the ramp never has to be re-derived.
    #
    # Starts hidden. `historical_toggle_visibility` flips it, never this cell.
    _hist_cfg = CONFIG_MAP["HISTORICAL"]
    _ramp = _hist_cfg["RAMP"]
    _span = max(historical_tracks.get("epoch_days_max", 1), 1)
    _ramp_stops = []
    for _i, _colour in enumerate(_ramp):
        _ramp_stops += [_span * _i / (len(_ramp) - 1), _colour]

    _historical_layer = Layer(
        id="historical-points",
        type=LayerType.CIRCLE,
        source="historical-points",
        paint={
            "circle-radius": _hist_cfg["POINT_RADIUS"],
            "circle-color": ["interpolate", ["linear"], ["get", "epoch_days"], *_ramp_stops],
            "circle-opacity": 0.85,
        },
        layout={"visibility": "none"},
    )

    # --- Folger Passage instrument sites ---
    # Visible in both views: fixed reference points, not part of either data mode.
    # Greyed out over the real-time view and black over the historical one, pushed by
    # `historical_toggle_visibility` the same way the glider highlight is.
    #
    # A circle layer, after an attempt at anchor-shaped DOM markers was reverted. That
    # attempt failed for a reason worth recording, because it rules out a whole class
    # of ideas here: **the app's CSS cannot reach anything inside the map widget.**
    # marimo renders its UI plugins into a shadow root, so a `.folger-anchor` rule in
    # this cell's <style> never matched the marker elements MapLibre creates inside
    # that root. The markers rendered as MapLibre's own default blue teardrop pins in
    # both views -- no mask, no colour, no view switch.
    #
    # What that leaves: anything drawn inside the map has to be styled by MapLibre
    # itself, through layer paint properties (this) or through a Marker's own `color`
    # option. Icons are separately out of reach -- a symbol layer needs `glyphs` or
    # `sprite` in the style, both URLs to files this app has nowhere to serve from,
    # and the anchor character U+2693 is absent from the only glyph server reachable
    # here (tiles.openfreemap.org: 54 glyphs in the 9728-9983 range, no 9875).
    _folger_layer = Layer(
        id="folger-sites",
        type=LayerType.CIRCLE,
        source="folger-sites",
        paint={
            "circle-radius": _hist_cfg["SITE_RADIUS"],
            # Baked as the live colour, matching the view this map opens in. A page
            # reload comes back here regardless of where the switch is sitting, since
            # the recolour is a post-render send -- same trade-off, and same direction
            # of failure, as the selection highlight.
            "circle-color": _hist_cfg["SITE_COLOR_LIVE"],
            "circle-stroke-width": 1.6,
            "circle-stroke-color": "#ffffff",
        },
    )

    _glider_head_layer = Layer(
        id="glider-head",
        type=LayerType.CIRCLE,
        source="glider-head",
        paint={
            "circle-radius": CONFIG_MAP["GLIDER"]["HEAD_RADIUS"],
            # Same expression as the trail, so the newest fix is highlighted along with
            # its own deployment rather than becoming a third colour to decode.
            "circle-color": _highlight_expr(),
            "circle-stroke-width": 2.5,
            "circle-stroke-color": "#ffffff",
        },
    )

    # --- Climatology sites: La Perouse Bank and the five Barkley Canyon moorings ---
    # Historical view only, so the baked visibility is "none" and the colour is the
    # historical one -- unlike the Folger pair, these never appear over the live view
    # and so never need recolouring. Folger is deliberately not in this source: it has
    # its own layer above, drawn in both views, and putting it here as well would
    # double-plot it every time the historical view is on.
    _clim_layer = Layer(
        id="climatology-sites",
        type=LayerType.CIRCLE,
        source="climatology-sites",
        paint={
            "circle-radius": _hist_cfg["CLIM_SITE_RADIUS"],
            "circle-color": _hist_cfg["SITE_COLOR_HISTORICAL"],
            "circle-stroke-width": 1.6,
            "circle-stroke-color": "#ffffff",
        },
        layout={"visibility": "none"},
    )

    # All five source/layer pairs are baked directly into the initial style
    # (see earlier pass's long comment for why -- add_source/add_layer after
    # construction only fire once, ever, and don't survive reconnects). That
    # constraint is exactly why the historical layer is created here, hidden,
    # rather than added when the view is first switched to.
    #
    # Layer order is draw order: historical points sit under the live positions so
    # that switching to historical never buries a live glider, and Folger sits on top
    # of both.
    _basemap_style = construct_basemap_style(
        layers=[_esri_layer, _sst_fill, _historical_layer, _glider_point_layer,
                _glider_head_layer, _clim_layer, _folger_layer],
        sources={
            "esri-ocean": _esri_source.to_dict(),
            "sst-src": GeoJSONSource(data=sst_layer).to_dict(),
            "glider-positions": GeoJSONSource(data=_glider_points_collection).to_dict(),
            "glider-head": GeoJSONSource(data=_glider_head_collection).to_dict(),
            "historical-points": GeoJSONSource(data=historical_tracks).to_dict(),
            "folger-sites": GeoJSONSource(data=folger_sites).to_dict(),
            "climatology-sites": GeoJSONSource(data=climatology_layer_sites).to_dict(),
        },
        name="esri-ocean-basemap",
    )

    # `bounds`/`fit_bounds_options` are only applied inside maplibre-gl's own
    # `Map` constructor (`_.bounds && (this.resize(), this.fitBounds(...))`),
    # which this widget's anywidget `render()` runs BEFORE the map's container
    # div is appended to the DOM (`e.appendChild(r)` is the last line of the
    # bundled `render()`) -- so fitBounds computes against a detached, 0x0
    # container and lands on a bogus, way-too-zoomed-out camera (confirmed
    # live: view_state came back centered ~46.3N zoom ~6.3, a ~170km region
    # stretched to cover ~1500km of coastline). `center`/`zoom` don't have
    # this problem -- `jumpTo` just sets the requested lng/lat/zoom directly,
    # no viewport-size-dependent fitting math -- so use those instead, matching
    # the same center/zoom the original ipyleaflet Glider_Map_App.ipynb used
    # (MapLibre order is [lon, lat]).
    _center_lon = (_lon_lo + _lon_hi) / 2
    _center_lat = (_lat_lo + _lat_hi) / 2

    map_widget = MapWidget(
        MapOptions(
            style=_basemap_style,
            center=(_center_lon, _center_lat),
            zoom=8,
        ),
        height="100vh",
        # No FullscreenControl -- our own CSS already keeps this always
        # full-viewport, and it's a plausible source of confusion (native
        # browser fullscreen makes the map's own container the fullscreen
        # root, hiding anything positioned outside it).
        controls=[NavigationControl(), ScaleControl()],
    )

    # IMPORTANT: map_ui is created AND displayed in this same cell, and this
    # cell's own inputs never change after notebook load -- nothing here
    # depends on `clicked` or `selection_plot`, so this cell runs exactly
    # once, ever. That's what keeps the map (and now the plot panel's
    # *positioning*, see below) stable across clicks.
    # Legend swatches: one flex-segment per color_stops entry -- baked in here (not a
    # separate cell) because sst_meta never changes after load, so referencing it again
    # here carries zero extra re-run risk, and keeps the legend in the SAME one-time DOM
    # insertion as the map itself rather than a second mo.Html competing for render order.
    _sst_swatches = "".join(
        f'<span style="flex:1;height:12px;background:{_hex}"></span>'
        for _, _hex in sst_meta["color_stops"]
    )

    map_ui = mo.ui.anywidget(map_widget)

    # The view switch. Defined HERE, in the cell it is displayed in, on purpose: a UI
    # element's own defining cell is exempt from re-running on its own value changes
    # (the same rule `click_plot` documents for the time slider). So the toggle can
    # live inside the map's stable DOM without the map ever being rebuilt underneath
    # it. `historical_toggle_visibility` reads the value and pushes layer visibility;
    # nothing downstream of it touches `map_widget`'s construction.
    view_toggle = mo.ui.radio(
        options=["Real-time", "Historical"],
        value="Real-time",
        inline=True,
    )

    # Static legend, covering both views at once rather than swapping with the mode.
    # Swapping it would mean a cell that re-renders on toggle and paints over a fixed,
    # full-viewport map -- the exact pattern the plot panel had to be rebuilt to avoid
    # (see `#plot-panel-slot` below). A legend small enough to always show costs less
    # than that risk.
    _epoch_start = historical_tracks.get("epoch_start", "")
    _months = historical_tracks.get("months") or [""]
    _ramp_css = ", ".join(_hist_cfg["RAMP"])
    _ramp_mid = _hist_cfg["RAMP"][len(_hist_cfg["RAMP"]) // 2]
    # The legend used to name the two Folger sites outright. With eight sites it names
    # the groups instead -- the panel has to stay small enough to leave visible in both
    # views, and the "i" popover carries the full list.
    _site_count = len(folger_sites["features"]) + len(climatology_layer_sites["features"])
    _live_colour = CONFIG_MAP["GLIDER"]["LINE_COLOR"]
    _active_days = CONFIG_MAP["GLIDER"]["ACTIVE_DAYS"]
    _active_days_label = f"{_active_days:g} day" + ("" if _active_days == 1 else "s")

    # `#plot-panel-slot` lives here, inside the ONE part of this app proven to
    # render stably (nothing about this cell ever re-runs after load, unlike
    # `plot_overlay`). `plot_overlay` (a separate cell, so a click never
    # touches the map's own DOM/WebGL) fills or clears this slot's *contents*
    # on each click instead of creating its own independent fixed-position
    # container -- an earlier attempt at that (a second `position: fixed` div
    # built fresh in `plot_overlay` on every click, even portaled to <body> to
    # dodge a suspected CSS containing-block trap) was never reliably visible
    # and needed an unrelated click elsewhere to "wake up" -- symptomatic of
    # marimo doing something click-triggered-render-specific (an update
    # animation wrapper, virtualization, etc.) that this cell, which never
    # re-renders, simply never hits. Routing all future updates through a
    # slot that's part of THIS stable render sidesteps whatever that was,
    # without needing to know exactly what it was.
    # `:empty` on the slot means it needs no explicit show/hide JS at all --
    # no children -> invisible and non-blocking; populated -> the panel
    # styling (fixed, sized, positioned) applies automatically.
    mo.Html(f"""
    <style>
      .glider-map-root {{
        position: fixed;
        inset: 0;
        z-index: 1;
        overflow: hidden;
        background: #0b1a2b;
      }}
      .glider-map-root .map-layer {{
        position: absolute;
        inset: 0;
      }}
      .glider-map-root .map-layer,
      .glider-map-root .map-layer * {{
        margin: 0;
        padding: 0;
      }}
      .glider-map-root .app-title {{
        position: absolute;
        top: 16px;
        left: 16px;
        z-index: 2;
        color: #fff;
        font: 600 15px/1.3 system-ui, sans-serif;
        background: rgba(10, 20, 30, 0.72);
        padding: 8px 14px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.35);
        pointer-events: none;
      }}
      /* Vertically centered, on the RIGHT edge now -- the fifteenth pass gave
         the plot its own permanent `mo.sidebar` on the LEFT, which used to
         overlap this button when it lived at middle-left. Right edge is clear
         of the sidebar, and (per earlier passes) also clear of marimo's own
         top-right kernel-status control and bottom memory-usage bar, since
         this is neither top nor bottom. */
      .glider-map-root .about-toggle {{
        position: absolute;
        top: 50%;
        right: 16px;
        transform: translateY(-50%);
        z-index: 2;
        max-width: 360px;
      }}
      .glider-map-root .about-toggle summary {{
        cursor: pointer;
        list-style: none;
        width: 34px;
        height: 34px;
        border-radius: 50%;
        background: rgba(10, 20, 30, 0.72);
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
        font: 600 16px system-ui, sans-serif;
        box-shadow: 0 2px 10px rgba(0,0,0,0.35);
      }}
      .glider-map-root .about-toggle summary::-webkit-details-marker {{ display: none; }}
      .glider-map-root .about-toggle[open] summary {{
        border-radius: 10px 0 0 10px;
        width: auto;
        justify-content: flex-start;
        padding: 8px 12px;
      }}
      /* Opens to the LEFT now that the toggle itself is right-anchored --
         opening rightward from a right-edge toggle would run off-screen. */
      .glider-map-root .about-body {{
        background: rgba(15, 22, 30, 0.94);
        color: #eaeaea;
        padding: 14px 16px;
        border-radius: 10px 0 10px 10px;
        max-height: 60vh;
        overflow-y: auto;
        box-shadow: 0 6px 20px rgba(0,0,0,0.4);
        font-size: 13px;
        line-height: 1.5;
        position: absolute;
        top: 0;
        right: 100%;
        margin-right: 8px;
      }}
      .glider-map-root .about-body code {{
        background: rgba(255,255,255,0.1);
        padding: 1px 4px;
        border-radius: 4px;
      }}
      /* Top centre, clear of the title (top-left) and the about button (mid-right). */
      .glider-map-root .view-switch {{
        position: absolute;
        top: 14px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 3;
        background: rgba(10, 20, 30, 0.72);
        color: #fff;
        padding: 6px 12px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.35);
        font: 500 13px/1.2 system-ui, sans-serif;
      }}
      /* marimo renders the radio as its own labelled inputs; keep them on one line
         and inherit the dark panel's text colour instead of the notebook's. */
      .glider-map-root .view-switch label,
      .glider-map-root .view-switch span {{ color: #fff; }}
      .glider-map-root .view-switch > * {{ margin: 0; }}
      .glider-map-root .map-legend {{
        position: absolute;
        left: 16px;
        bottom: 16px;
        z-index: 2;
        background: rgba(10, 20, 30, 0.78);
        color: #f2f4f6;
        padding: 14px 16px;
        border-radius: 12px;
        box-shadow: 0 2px 14px rgba(0,0,0,0.4);
        font: 400 14px/1.5 system-ui, sans-serif;
        max-width: 320px;
        pointer-events: none;
      }}
      .glider-map-root .map-legend b {{ font-weight: 600; }}
      /* One row per entry: swatch column, then label. The swatch column is a fixed
         width so the three labels line up whatever size the dots are. */
      .glider-map-root .legend-row {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 7px 0;
      }}
      .glider-map-root .legend-key {{
        flex: 0 0 20px;
        display: flex;
        justify-content: center;
        align-items: center;
      }}
      .glider-map-root .legend-sub {{
        color: #b9c2cb;
        font-size: 12px;
      }}
      .glider-map-root .legend-ramp {{
        height: 10px;
        border-radius: 3px;
        margin: 4px 0 3px 30px;
        background: linear-gradient(to right, {_ramp_css});
      }}
      .glider-map-root .legend-credit {{
        margin-top: 8px;
        padding-top: 6px;
        border-top: 1px solid rgba(255,255,255,0.18);
        color: #aab3bb;
        font-size: 10px;
        line-height: 1.35;
      }}
      .glider-map-root .legend-ends {{
        display: flex;
        justify-content: space-between;
        margin-left: 30px;
        color: #b9c2cb;
        font-size: 11.5px;
      }}
      /* The three swatches are sized in the same order the map draws them -- historical
         profile positions smallest, live glider positions bigger, moorings biggest --
         so the legend reads as a size key as well as a colour key. */
      .glider-map-root .legend-dot {{
        display: inline-block;
        border-radius: 50%;
        border: 1px solid #fff;
      }}
      .glider-map-root .legend-historical {{
        width: 8px;
        height: 8px;
        background: {_ramp_mid};
      }}
      .glider-map-root .legend-live {{
        width: 11px;
        height: 11px;
        background: {_live_colour};
      }}
      /* Deliberately neither of the map's two site colours: those swap with the view,
         and this legend does not. */
      .glider-map-root .legend-site {{
        width: 17px;
        height: 17px;
        background: #c8ced4;
        border-width: 2px;
      }}
      /* Bottom-right -- the one corner nothing else claims: .app-title is
         top-left, .about-toggle is right-CENTER (deliberately, to clear
         marimo's own top-right/bottom chrome), the plot sidebar docks left.
         pointer-events: none, matching .app-title -- purely informational,
         never meant to intercept clicks meant for the map underneath. */
      .glider-map-root .sst-legend {{
        position: absolute;
        bottom: 28px;
        right: 16px;
        z-index: 2;
        width: 240px;
        background: rgba(10, 20, 30, 0.78);
        color: #eaeaea;
        padding: 10px 12px;
        border-radius: 10px;
        font: 12px/1.4 system-ui, sans-serif;
        box-shadow: 0 2px 10px rgba(0,0,0,0.35);
        pointer-events: none;
      }}
      .glider-map-root .sst-legend .ramp {{
        display: flex;
        margin: 6px 0 3px;
      }}
    </style>
    <div class="glider-map-root">
      <div class="map-layer">{map_ui}</div>
      <div class="app-title">Glider Map -- Barkley Sound</div>
      <div class="view-switch">{view_toggle}</div>
      <div class="map-legend">
        <div class="legend-row">
          <span class="legend-key"><span class="legend-dot legend-live"></span></span>
          <span><b>Real-time</b> glider<br>
            <span class="legend-sub">positions, last {_active_days_label}<br>
              ringed dot = newest fix</span></span>
        </div>
        <div class="legend-row">
          <span class="legend-key"><span class="legend-dot legend-historical"></span></span>
          <span><b>Historical</b> glider<br>
            <span class="legend-sub">profile positions by date</span></span>
        </div>
        <div class="legend-ramp"></div>
        <div class="legend-ends"><span>{_months[0]}</span><span>{_months[-1]}</span></div>
        <div class="legend-row">
          <span class="legend-key"><span class="legend-dot legend-site"></span></span>
          <span><b>Stationary instruments</b><br>
            <span class="legend-sub">{_site_count} sites — click one in Historical</span></span>
        </div>
        <div class="legend-credit">
          Data: Ocean Networks Canada · C-PROOF · DFO/MEDS · NOAA CoastWatch —
          citations and access points under <b>i</b>
        </div>
      </div>
      <div class="sst-legend">
        <b>Sea surface temperature</b>
        <div class="ramp">{_sst_swatches}</div>
        <div style="display:flex;justify-content:space-between">
          <span>{sst_meta['color_range'][0]:.0f} &deg;C</span><span>{sst_meta['color_range'][1]:.0f} &deg;C</span>
        </div>
        <div style="margin-top:6px;opacity:0.75">
          Fixed scale -- a colour means the same temperature on every date.
          Faded cells are water unreachable from the open Pacific.
        </div>
      </div>
      <details class="about-toggle">
        <summary>i</summary>
        <div class="about-body">{about_md}</div>
      </details>
    </div>
    """)
    return glider_highlight_expr, map_ui, map_widget, view_toggle


@app.cell(hide_code=True)
def historical_toggle_visibility(CONFIG_MAP, map_widget, view_toggle):
    # Switch the view by flipping layer visibility, never by rebuilding the map.
    #
    # Same discipline as `glider_highlight`, and for the same reason: `map` builds
    # `map_widget`/`map_ui` and must never re-run, or a brand-new widget gets forced
    # into a live browser session and the mount breaks. Reading `map_widget` here and
    # calling a method on it does not re-run `map` -- marimo's dataflow only runs
    # downstream. Both layers already exist in the baked style, so this is a one-word
    # layout-property update per layer, not a source swap.
    #
    # `set_visibility` goes out through `add_call`, the same post-render comm path
    # `set_paint_property` uses, so these do not accumulate in widget state -- and,
    # equally, are not replayed on reconnect. After a page reload the map comes back
    # in the baked-in default (real-time visible, historical hidden) regardless of
    # where the toggle is sitting. That degrades to "shows the live view", never to a
    # blank or wrong map, which is the right way round.
    #
    # The Folger sites are deliberately absent from the visibility switch: they are
    # fixed reference points that belong in both views. They do change colour with the
    # view, though -- greyed out over the live view, where a reporting glider is the
    # subject, and black over the historical one, where the moorings are the only
    # continuously-present instruments on the map. That is a paint property, pushed
    # exactly like the glider highlight, and for the same reason: the app's own CSS
    # cannot reach inside the map (marimo renders its plugins into a shadow root), so
    # anything drawn on the map has to be coloured by MapLibre itself.
    _historical = view_toggle.value == "Historical"

    map_widget.set_visibility("historical-points", _historical)
    map_widget.set_visibility("climatology-sites", _historical)
    map_widget.set_visibility("glider-positions", not _historical)
    map_widget.set_visibility("glider-head", not _historical)
    map_widget.set_paint_property(
        "folger-sites", "circle-color",
        CONFIG_MAP["HISTORICAL"]["SITE_COLOR_HISTORICAL"] if _historical
        else CONFIG_MAP["HISTORICAL"]["SITE_COLOR_LIVE"],
    )

    historical_view = _historical
    return (historical_view,)


@app.cell(hide_code=True)
def click_plot(climatology_sites, glider_records, historical_view, map_ui,
               set_plot_closed):
    _clicked = (map_ui.value or {}).get("clicked") or {}
    _click_lon, _click_lat = _clicked.get("lng"), _clicked.get("lat")
    _TOLERANCE_DEG = 0.05  # generous proximity radius for hit-testing a click against a track
    _SITE_TOLERANCE_DEG = 0.03  # tighter, for point sites -- see the nearest-wins note below

    def _near(lon, lat, lon2, lat2, tol=_TOLERANCE_DEG):
        return lon is not None and abs(lon - lon2) < tol and abs(lat - lat2) < tol

    # Each view answers a click with its own kind of thing, and never both: a glider
    # deployment over the live view, a fixed site's climatology over the historical
    # one. Whichever view is off contributes None, which also means switching views
    # clears the panel rather than stranding a selection under a hidden layer.
    selected_glider_record = None
    selected_site = None

    if not historical_view:
        for _rec in glider_records:
            if any(_near(_click_lon, _click_lat, lon2, lat2)
                   for lon2, lat2 in zip(_rec["df"]["Longitude"], _rec["df"]["Latitude"])):
                selected_glider_record = _rec
                break  # first deployment within tolerance wins -- same precision as today's
                       # single-glider hit-test, generalized from 1 candidate to N
    elif _click_lon is not None:
        # NEAREST within tolerance, not first within tolerance -- unlike the glider
        # hit-test above, which can afford first-wins because two deployments rarely
        # overlap. These sites genuinely do overlap: Hydrates, Mid-East and Axis sit
        # within 0.016 deg of each other on the canyon floor, and Folger Deep and
        # Pinnacle within 0.006 deg. First-wins would make three of the five canyon
        # sites unreachable by clicking. The tolerance is tighter than the glider one
        # for the same reason.
        _hits = [
            (max(abs(_click_lon - _f["geometry"]["coordinates"][0]),
                 abs(_click_lat - _f["geometry"]["coordinates"][1])), _f)
            for _f in climatology_sites["features"]
        ]
        _hits = [(_d, _f) for _d, _f in _hits if _d < _SITE_TOLERANCE_DEG]
        if _hits:
            selected_site = min(_hits, key=lambda pair: pair[0])[1]["properties"]

    # Reset the close flag on every new valid selection so clicking a
    # (possibly different) marker/track point always reopens the panel, even
    # if it was previously closed -- this cell re-runs on every map click, so
    # this naturally fires each time, only when a real hit is found.
    #
    # Plot-building moved downstream (glider_time_control/filtered_glider_plot):
    # the time slider's value needs to drive a replot, and a UI element's own
    # defining cell is exempt from re-running on its own value changes -- if
    # this cell both defined the slider and read its value, dragging it would
    # silently do nothing after the first click. This cell now only hit-tests.
    if selected_glider_record is not None or selected_site is not None:
        set_plot_closed(False)
    return selected_glider_record, selected_site


@app.cell(hide_code=True)
def site_panel(mo, selected_site):
    # The climatology plot for a clicked site, as a data URI.
    #
    # Base64 rather than a file path or an <img src> pointing at the repo: the app is
    # served by marimo, which does not serve arbitrary repo files over HTTP, so a path
    # that works on disk would 404 in the browser. Embedding the bytes sidesteps the
    # question entirely. It is only done for the ONE site that was clicked -- all eight
    # at once would be ~1.6 MB of PNG on every page.
    #
    # A missing file degrades to a note, not a broken image: the plots live in
    # contributor_folders/Dwight/climatology/ and are rebuilt by that folder's own
    # script, so a checkout can legitimately be missing one.
    import base64
    from pathlib import Path as _Path

    if selected_site is None:
        site_plot = None
    else:
        _repo = _Path(__file__).resolve().parent.parent
        _png = selected_site.get("climatology_png")
        _path = (_repo / _png) if _png else None

        _depth = selected_site.get("depth_m")
        _where = f"{_depth:.0f} m" if _depth else "sea surface"
        _span = ""
        if selected_site.get("record_start") and selected_site.get("record_end"):
            _span = f" · {selected_site['record_start'][:4]}–{selected_site['record_end'][:4]}"

        _header = mo.md(f"### {selected_site['name']}\n{_where}{_span}")

        # The explanation sits behind a "?" in the plot's top-right corner rather than
        # under it. It is the same few sentences every time, so after the first read it
        # is just something between the reader and the next plot -- but a climatology
        # with sd bands is not self-explanatory either, so it has to be reachable.
        #
        # Pure CSS: :hover for a mouse, :focus-within (with tabindex) so it also opens
        # from the keyboard and on a touch screen, where there is no hover at all. No
        # <script>, which marimo strips from cell HTML anyway.
        _help = (
            "Day-of-year mean with 1 and 2 sd bands, pooled over &plusmn;7 days across "
            "all years of the record, with the current year overlaid. Only QAQC-passed "
            "values are used, so gaps are shown as gaps. Built by "
            "<code>onc_climatology.py</code>; screening rules and caveats are in "
            "<code>contributor_folders/Dwight/CLIMATOLOGY.md</code>."
        )
        _style = """
        <style>
          .clim-figure { position: relative; line-height: 0; }
          .clim-figure img { width: 100%; height: auto; border-radius: 6px;
                              background: #fff; display: block; }
          .clim-help {
            position: absolute; top: 10px; right: 10px;
            width: 22px; height: 22px; border-radius: 50%;
            background: rgba(10, 20, 30, 0.78); color: #fff;
            font: 600 13px/22px system-ui, sans-serif; text-align: center;
            cursor: help; user-select: none; outline: none;
          }
          .clim-help:hover, .clim-help:focus { background: rgba(10, 20, 30, 0.95); }
          .clim-help .clim-help-body {
            display: none;
            position: absolute; top: 28px; right: 0; width: 260px;
            padding: 10px 12px; border-radius: 8px;
            background: rgba(10, 20, 30, 0.96); color: #eaeaea;
            font: 400 12px/1.45 system-ui, sans-serif; text-align: left;
            box-shadow: 0 4px 16px rgba(0,0,0,0.45); cursor: default; z-index: 5;
          }
          .clim-help .clim-help-body code {
            background: rgba(255,255,255,0.12); padding: 1px 3px; border-radius: 3px;
          }
          .clim-help:hover .clim-help-body,
          .clim-help:focus-within .clim-help-body { display: block; }
        </style>
        """

        if _path is not None and _path.exists():
            _uri = "data:image/png;base64," + base64.b64encode(_path.read_bytes()).decode()
            _body = mo.Html(
                _style
                + '<div class="clim-figure">'
                + f'<img src="{_uri}" alt="Day-of-year temperature climatology for '
                + f'{selected_site["name"]}" />'
                + '<span class="clim-help" tabindex="0" role="note" '
                + 'aria-label="About this plot">?'
                + f'<span class="clim-help-body">{_help}</span></span>'
                + "</div>"
            )
        else:
            _body = mo.md(
                "_No climatology plot for this site yet._ Build one with "
                "`python contributor_folders/Dwight/onc_climatology.py --all "
                "--outdir climatology/`."
            )

        site_plot = mo.vstack([_header, _body])
    return (site_plot,)


@app.cell(hide_code=True)
def glider_highlight(
    glider_highlight_expr,
    map_widget,
    selected_glider_record,
):
    # Paint the selected deployment in SELECTED_COLOR, everything else in LINE_COLOR.
    #
    # This is a separate cell from `map` on purpose, for the same reason `click_plot` is:
    # `map` builds `map_widget`/`map_ui` and must never re-run, or a brand-new widget gets
    # forced into a live browser session and the mount breaks. Reading `map_widget` here and
    # calling a method on it does not re-run `map` -- marimo's dataflow only runs downstream.
    #
    # `set_paint_property` goes out through the widget's post-render path, which is a plain
    # comm `send()` rather than a synced traitlet, so these calls do not accumulate in widget
    # state -- each click just sends one small property update. The flip side is that they are
    # not replayed on reconnect: after a page reload the map comes back with the baked-in
    # sentinel expression (nothing highlighted) until the next click. That degrades to "no
    # highlight", never to a broken or misleading map, which is the right way round.
    _selected = selected_glider_record["deployment"] if selected_glider_record else ""
    _expression = glider_highlight_expr(_selected)
    map_widget.set_paint_property("glider-positions", "circle-color", _expression)
    map_widget.set_paint_property("glider-head", "circle-color", _expression)
    return


@app.cell(hide_code=True)
def sst_date_filter(map_widget, sst_date_picker):
    # Separate cell from `map`, same reasoning as `glider_highlight`: reading
    # map_widget here and calling a method on it does not re-run `map` --
    # marimo's dataflow only runs downstream. set_filter is a transient comm
    # message like set_paint_property, so it does not survive a page reload --
    # the map comes back showing sst_meta["default_date"] (the baked-in filter)
    # until the next date change, same "degrades to a sane default, never to a
    # broken map" behavior as glider_highlight's selection state.
    map_widget.set_filter("sst", ["==", ["get", "date"], sst_date_picker.value])
    return


@app.cell(hide_code=True)
def plot_overlay(
    get_plot_closed,
    glider_decimation_slider,
    glider_time_slider,
    mo,
    selection_plot,
    set_plot_closed,
    site_plot,
    time_range_label,
):
    # ALTERNATIVE ARCHITECTURE (fifteenth pass): use marimo's own native
    # `mo.sidebar` instead of a hand-rolled `position: fixed` div built via
    # `mo.Html(f"...")`. Every earlier design (passes six through fourteen)
    # built the popup out of custom CSS + raw HTML strings, and kept hitting
    # rendering bugs that were hard to pin down even with a real browser test
    # harness. `mo.sidebar(...)` is a first-class marimo layout primitive,
    # rendered by marimo's own React code as part of the actual app shell --
    # confirmed by the user in their own browser: plots are stable and appear
    # immediately on click, no cursor-position sensitivity. Docs: "You may use
    # more than one `mo.sidebar` - they will be displayed in the order they
    # are called," and it "still needs to be the last expression in the cell."
    _closed = get_plot_closed()
    _visible = (selection_plot is not None or site_plot is not None) and not _closed

    if _visible:
        # Close button: `on_change` (not `on_click`) calls `set_plot_closed`.
        # `mo.ui.button`'s own docstring describes `on_click` as "a callable
        # called on click that takes the current value ... and returns a new
        # value" -- i.e. `on_click` is for computing the button's OWN next
        # value (the counter-button example), not a general side-effect hook.
        # `on_change` is documented as "callback to run when this element's
        # value changes," and it's the mechanism marimo's own docs use for
        # every `mo.state`-syncing example (e.g. `mo.ui.slider(...,
        # on_change=set_state)`). Switched to that exact pattern: `on_click`
        # just increments the button's internal counter (any change), and
        # `on_change` (fired as a result of that change) calls
        # `set_plot_closed(True)`.
        _close_button = mo.ui.button(
            value=0,
            on_click=lambda v: v + 1,
            on_change=lambda _v: set_plot_closed(True),
            label="\u2715 Close",
            kind="neutral",
        )
        # glider_decimation_slider sits directly ABOVE glider_time_slider (point
        # density above time window), both below the plot, with time_range_label
        # last since it reports on where glider_time_slider is currently set.
        #
        # The site panel carries no sliders: they scope a glider deployment's own time
        # axis, and a day-of-year climatology has neither a live window nor a point
        # density to thin. `click_plot` guarantees only one of the two is ever set.
        # Hide the map legend while a panel is open. The panel docks left, over the
        # corner the legend sits in, and two stacked boxes of small text there is
        # exactly the crowding this corner was just cleaned up to avoid.
        #
        # The rule ships INSIDE the panel rather than from a cell of its own, which
        # makes it self-cleaning: a <style> element applies for as long as it is in the
        # document, and this one is unmounted with the panel it came in. No state to
        # keep in sync, and no way for the legend to stay hidden after the panel closes.
        #
        # It can reach the legend because both are ordinary light DOM -- the map cell's
        # HTML output, not the map widget. Anything inside the widget itself is in a
        # shadow root that page CSS cannot enter, which is what defeated the earlier
        # attempt at styling the Folger markers; the legend is not in there.
        _hide_legend = mo.Html(
            "<style>.glider-map-root .map-legend { display: none; }</style>"
        )
        if site_plot is not None:
            _content = mo.vstack([_hide_legend, _close_button, site_plot])
        else:
            _content = mo.vstack([
                _hide_legend, _close_button, selection_plot,
                glider_decimation_slider, glider_time_slider, time_range_label,
            ])
    else:
        # No placeholder panel. An empty sidebar is 480 px of dark chrome over the map,
        # crowding the legend to say nothing, so nothing is rendered at all until
        # something is selected and the map gets that width back.
        _content = None

    # A trailing conditional EXPRESSION, not an early return. marimo compiles a cell's
    # body as a module, so a `return` anywhere but the end of the file's own function
    # wrapper is a SyntaxError ("'return' outside function") -- and it fails at compile
    # time, taking every cell down with it. This form keeps the sidebar as the last
    # expression, which is what marimo renders, and evaluates to None when there is
    # nothing to show, which renders nothing.
    mo.sidebar(_content, width="480px") if _visible else None
    return


@app.cell(hide_code=True)
def _(mo):
    # Native marimo reactive state for the popup's open/closed flag -- NOT a
    # DOM/JS trick. Every popup design since pass six relied on inline
    # `onclick`/`onerror` HTML attributes to react to a close-button click
    # without coupling `plot_overlay` to anything else click-volatile --
    # confirmed via a real headless-browser test that marimo's HTML renderer
    # strips inline event-handler attributes entirely (it parses `mo.Html(...)`
    # strings into a React element tree, not a raw innerHTML dump, and drops
    # `on*` attributes along the way), so that mechanism never fired, ever, in
    # any real browser. `mo.state` is marimo's actual supported primitive for
    # this "small piece of state read/written by different cells" need.
    #
    # `allow_self_loops=True` is required here specifically: the close button
    # lives INSIDE `plot_overlay`, which also reads `get_plot_closed()` -- so
    # clicking it calls `set_plot_closed(True)` from within the very cell that
    # reads the getter, a self-loop. `mo.state`'s default (`allow_self_loops
    # =False`) means "the cell that called the setter won't be re-run, even
    # if it references the getter" -- confirmed via marimo's own docstring.
    # Without this flag, the close click WAS registering (kernel-side state
    # did flip), but `plot_overlay` was specifically exempted from re-running
    # in response to its own click, so nothing visibly changed until some
    # OTHER trigger (a new marker click, changing `selection_plot`) forced a
    # rerun anyway -- exactly the reported symptom ("close button does not
    # work, you have to click on another marker to replace the plot").
    get_plot_closed, set_plot_closed = mo.state(False, allow_self_loops=True)
    return get_plot_closed, set_plot_closed


@app.cell(hide_code=True)
def _():
    # Split out from `nb_imports` on purpose -- see the comment there. Only
    # `click_plot` (and therefore `plot_overlay`) should ever need to rerun
    # when this specific function changes; `map`/`glider_data` must never
    # depend on this cell.
    from glider_lib import plot_glider_curtain

    return (plot_glider_curtain,)


@app.cell(hide_code=True)
def glider_decimation_control(mo, selected_glider_record):
    # Thins the plotted points for readability -- weeks of frequent-sampling data
    # renders very clustered/hard-to-read otherwise. Purely a display-density
    # knob (which points get PLOTTED), separate from glider_time_slider (which
    # TIME WINDOW gets considered) -- the two compose but don't affect each
    # other's meaning.
    #
    # Fixed 1-25 range, not deployment-scoped, but still keyed off
    # selected_glider_record so a new click resets it to 1 (show everything)
    # rather than carrying over the previous deployment's setting -- same
    # reset-on-new-click convention as glider_time_control.
    #
    # Must be a SEPARATE cell from filtered_glider_plot, which reads .value: a
    # UI element's own defining cell is exempt from re-running on its own value
    # changes -- if this cell also consumed .value, dragging it wouldn't do
    # anything after the first click.
    if selected_glider_record is None:
        glider_decimation_slider = None
    else:
        glider_decimation_slider = mo.ui.slider(
            start=1,
            stop=25,
            step=1,
            value=1,        # default: show every record, no thinning
            debounce=True,
            include_input=True,
            label="Point spacing (every Nth record)",
        )
    return (glider_decimation_slider,)


@app.cell(hide_code=True)
def glider_time_control(mo, selected_glider_record):
    # Scoped to the CLICKED deployment's own already-cached full time range -- no
    # new fetch, just narrows what of the already-loaded DataFrame gets plotted.
    # Default = the full cached span (show everything, same as before this
    # slider existed); dragging narrows it.
    #
    # Must be a SEPARATE cell from filtered_glider_plot, which reads .value: a UI
    # element's own defining cell is exempt from re-running on its own value
    # changes (same rule that keeps `map` from re-running when map_ui changes) --
    # if this cell also consumed .value, dragging the slider wouldn't do
    # anything after the first click.
    if selected_glider_record is None:
        glider_time_slider = None
    else:
        _times = selected_glider_record["df"]["Time"]
        _span_hours = max(1, int((_times.max() - _times.min()).total_seconds() // 3600) + 1)
        glider_time_slider = mo.ui.slider(
            start=1,
            stop=_span_hours,
            step=1,
            value=_span_hours,       # default: show the full cached range
            debounce=True,
            include_input=True,
            label="Hours of history to show",
        )
    return (glider_time_slider,)


@app.cell(hide_code=True)
def filtered_glider_plot(
    CONFIG_MAP,
    glider_decimation_slider,
    glider_time_slider,
    mo,
    pd,
    plot_glider_curtain,
    selected_glider_record,
):
    if selected_glider_record is None or glider_time_slider is None or glider_decimation_slider is None:
        selection_plot = None
        time_range_label = None
    else:
        _df = selected_glider_record["df"]
        _t_end = _df["Time"].max()
        _t_start = _t_end - pd.Timedelta(hours=glider_time_slider.value)
        _filtered = _df[_df["Time"] >= _t_start]

        # Thin the time-filtered data for readability -- applied AFTER the time-range
        # filter, and never changes what the label reports below: the label describes
        # the true underlying time window, not the (possibly slightly shorter,
        # depending on stride alignment) span of the decimated points actually plotted.
        _display_df = _filtered.iloc[::glider_decimation_slider.value]

        _glider_cfg = CONFIG_MAP["GLIDER"]
        # Short glider codename only (e.g. "dfo-eva035" -> "eva", "dfo-hal1002" -> "hal") --
        # strip the "dfo-" prefix (present on live-mode data; a no-op if absent, e.g.
        # archive mode) and strip the trailing serial digits, leaving just the name.
        # On its own title line under the variable, since the full deployment
        # id/codename was more detail than useful in a compact sidebar plot.
        _short_glider = selected_glider_record["glider"].removeprefix("dfo-").rstrip("0123456789")
        _fig = plot_glider_curtain(
            _display_df, _glider_cfg["VARIABLE"],
            variable_label=_glider_cfg["VARIABLE_LABEL"],
            color_scale=_glider_cfg["COLOR_SCALE"],
            title=f"3D {_glider_cfg['VARIABLE_LABEL']}<br>{_short_glider}",
        )
        selection_plot = mo.as_html(_fig)

        # "Etc/GMT+7" is POSIX-sign-inverted (it means UTC-7, i.e. PDT) -- a
        # fixed offset with no DST rules, which is what was asked for, not the
        # DST-aware `America/Los_Angeles` zone (which would read PST/-8 part of
        # the year).
        _start_local = _t_start.tz_convert("Etc/GMT+7")
        _end_local = _t_end.tz_convert("Etc/GMT+7")
        time_range_label = mo.md(
            f"**Showing:** {_start_local:%Y-%m-%d %H:%M} – {_end_local:%Y-%m-%d %H:%M} PDT"
        )
    return selection_plot, time_range_label


if __name__ == "__main__":
    app.run()
