# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "anywidget==0.11.0",
#     "maplibre==0.3.6",
#     "marimo>=0.24.0",
#     "numpy==2.5.2",
#     "pandas==3.0.5",
#     "plotly==7.0.0",
# ]
# [tool.marimo.venv]
# path = "/home/.pixi/envs/default"
# ///

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
            "MAX_GAP_DEG": 0.05,          # split a track wherever consecutive points jump farther
                                           # than this (degrees) -- matches click_plot's own
                                           # _TOLERANCE_DEG by design, so we never draw a "fake"
                                           # connector line across a real gap that would look
                                           # clickable but isn't (no real data point is ever near it).
            "VARIABLE": "temperature",    # science variable to plot/color by -- present on every
                                           # deployment (unlike 5 of the other 6 science variables).
            "VARIABLE_LABEL": "Temperature (°C)",
            "COLOR_SCALE": "Thermal",
            "LINE_COLOR": "#37474f",      # every track that is NOT the current selection.
            "SELECTED_COLOR": "#f4a261",  # the track you clicked. Applied by the
                                           # `glider_highlight` cell through a data-driven
                                           # paint expression keyed on each feature's own
                                           # "deployment" property, so selecting never
                                           # rebuilds the map (see that cell, and `map`'s
                                           # note about never re-running).
            "DEPTH_POSITIVE_DOWN": True,
        },
        "HISTORICAL": {
            # Every deployment on the Southern Line and the SVI Shelf line that has a
            # gridded adjusted file, precomputed by data/build_historical_tracks.py.
            # That script reads the 10.68 GB of netCDF; this app reads only its ~1.3 MB
            # output, so switching views costs one file read and no network.
            "TRACKS": "../data/glider_adjusted_tracks.geojson",
            "SITES": "../data/folger_sites.geojson",
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
            "SITE_RADIUS": 6,
            "SITE_COLOR": "#ffffff",
            "SITE_STROKE": "#0b0b0b",
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

      Click a track to select it: the whole transect turns orange and a 3D curtain plot of that
      deployment opens in the sidebar. Data is real-time and **not calibrated** -- only a gross-range
      screen has been applied.

    - **Historical** -- the switch at the top swaps the live view for every deployment on the
      **Southern Line** and the **SVI Shelf from Bamfield** line that has a gridded adjusted file:
      26 deployments, 28,452 profile positions, coloured by deployment date. Clicking does nothing
      in this view yet -- the click-through plots are still to come.

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
      Folger Passage, shown in *both* views as fixed reference points. They sit ~650 m apart and
      overplot until you zoom in.

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

    _n_points = sum(_f["properties"].get("n_points", 0)
                    for _f in historical_tracks["features"])
    print(f"Historical: {len(historical_tracks['features'])} deployment(s), "
          f"{_n_points} profile positions, "
          f"{len(folger_sites['features'])} instrument site(s)")
    return folger_sites, historical_tracks


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

    # --- Glider track source/layer: ONE GeoJSONSource, a FeatureCollection with
    # one LineString feature per CONTIGUOUS segment of each active deployment.
    # Real gliders sometimes go dark for a stretch and resurface elsewhere --
    # a single LineString spanning that gap would draw a straight "fake" line
    # across empty space that LOOKS clickable but has no real data anywhere
    # near it (click_plot only matches clicks near actual observed points).
    # Splitting on any gap bigger than MAX_GAP_DEG (matching click_plot's own
    # proximity radius by design) means every segment we DO draw is guaranteed
    # clickable along its whole length, and we never draw a segment that can't be.
    _MAX_GAP_DEG = CONFIG_MAP["GLIDER"]["MAX_GAP_DEG"]

    def _split_on_gaps(df, max_gap_deg=_MAX_GAP_DEG):
        """Split a track into contiguous segments, breaking wherever consecutive points
        jump farther apart than max_gap_deg -- each returned segment is safe to render
        as one continuous line with no real-data dead zones along it."""
        if len(df) < 2:
            return [df]
        _lon = df["Longitude"].to_numpy()
        _lat = df["Latitude"].to_numpy()
        _jump = ((_lon[1:] - _lon[:-1]) ** 2 + (_lat[1:] - _lat[:-1]) ** 2) ** 0.5
        _breaks = [i + 1 for i, d in enumerate(_jump) if d > max_gap_deg]
        _bounds = [0] + _breaks + [len(df)]
        return [df.iloc[_bounds[i]:_bounds[i + 1]] for i in range(len(_bounds) - 1)]

    # Compute every (record, segment) pair once -- shared by both the line
    # features below and the point-marker features that follow, so a track
    # is never split into gap-segments twice.
    _glider_segments = [
        (_rec, _segment)
        for _rec in glider_records
        for _segment in _split_on_gaps(_rec["df"])
    ]

    _glider_features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lon, lat in zip(_segment["Longitude"], _segment["Latitude"])],
            },
            # Cosmetic only -- click_plot hit-tests against glider_records' own DataFrames,
            # not these properties. Every segment split from one deployment still carries
            # that deployment's own tags, so the glider identity is preserved per segment.
            "properties": {"deployment": _rec["deployment"], "glider": _rec["glider"]},
        }
        for _rec, _segment in _glider_segments
        if len(_segment) >= 2  # a lone point can't be a LineString
    ]

    # --- Glider segment position markers ---
    # A small circle at the first point of EVERY segment (moving or not) -- a
    # LineString with near-zero spatial extent (a genuinely parked glider, not
    # just a short gap) renders as nothing at all, since a zero-length line has
    # no direction to draw a stroke along. This marker guarantees every segment
    # stays visible and clickable regardless of how much it actually moved.
    _glider_point_features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(_segment["Longitude"].iloc[0]), float(_segment["Latitude"].iloc[0])],
            },
            "properties": {"deployment": _rec["deployment"], "glider": _rec["glider"]},
        }
        for _rec, _segment in _glider_segments
    ]
    _glider_points_collection = {"type": "FeatureCollection", "features": _glider_point_features}

    # Selection highlight, as a data-driven paint expression rather than a rebuild.
    # MapLibre evaluates this per feature against the "deployment" property every feature
    # already carries, so switching the highlight is a one-property update pushed from
    # `glider_highlight` -- the map itself is never rebuilt, which this cell must never do
    # (see its note below). "" is a sentinel matching no deployment, so nothing starts
    # highlighted; `glider_highlight` re-sends this same shape with the selected name.
    # Every segment split from one deployment carries that deployment's name, so clicking
    # any segment lights up all of them -- the whole transect, not just the piece clicked.
    def _highlight_expr(selected=""):
        return [
            "case",
            ["==", ["get", "deployment"], selected],
            CONFIG_MAP["GLIDER"]["SELECTED_COLOR"],
            CONFIG_MAP["GLIDER"]["LINE_COLOR"],
        ]

    glider_highlight_expr = _highlight_expr

    _glider_point_layer = Layer(
        id="glider-segment-markers",
        type=LayerType.CIRCLE,
        source="glider-points",
        paint={
            "circle-radius": 5,
            "circle-color": _highlight_expr(),
            "circle-stroke-width": 1,
            "circle-stroke-color": "#ffffff",
        },
    )
    _glider_collection = {"type": "FeatureCollection", "features": _glider_features}
    _glider_layer = Layer(
        id="glider-track-line",
        type=LayerType.LINE,
        source="glider-track",
        paint={"line-color": _highlight_expr(), "line-width": 3},
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
    # Drawn last so they sit above every track. Circles rather than a symbol layer
    # with text on purpose -- a symbol layer needs a `glyphs` URL in the style, which
    # this basemap does not define, and a missing glyphs endpoint fails the whole
    # style rather than just the labels. The names live in the legend instead.
    _folger_layer = Layer(
        id="folger-sites",
        type=LayerType.CIRCLE,
        source="folger-sites",
        paint={
            "circle-radius": _hist_cfg["SITE_RADIUS"],
            "circle-color": _hist_cfg["SITE_COLOR"],
            "circle-stroke-width": 2,
            "circle-stroke-color": _hist_cfg["SITE_STROKE"],
        },
    )

    # All five source/layer pairs are baked directly into the initial style
    # (see earlier pass's long comment for why -- add_source/add_layer after
    # construction only fire once, ever, and don't survive reconnects). That
    # constraint is exactly why the historical layer is created here, hidden,
    # rather than added when the view is first switched to.
    #
    # Layer order is draw order: historical points sit under the live track so that
    # switching to historical never buries a live glider, and Folger sits on top of
    # both.
    _basemap_style = construct_basemap_style(
        layers=[_esri_layer, _sst_fill, _historical_layer, _glider_layer,
                _glider_point_layer, _folger_layer],
        sources={
            "esri-ocean": _esri_source.to_dict(),
            "sst-src": GeoJSONSource(data=sst_layer).to_dict(),
            "glider-track": GeoJSONSource(data=_glider_collection).to_dict(),
            "glider-points": GeoJSONSource(data=_glider_points_collection).to_dict(),
            "historical-points": GeoJSONSource(data=historical_tracks).to_dict(),
            "folger-sites": GeoJSONSource(data=folger_sites).to_dict(),
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
    _site_names = " · ".join(_f["properties"]["name"] for _f in folger_sites["features"])

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
        background: rgba(10, 20, 30, 0.72);
        color: #eaeaea;
        padding: 10px 12px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.35);
        font: 400 11.5px/1.45 system-ui, sans-serif;
        max-width: 260px;
        pointer-events: none;
      }}
      .glider-map-root .map-legend b {{ font-weight: 600; }}
      .glider-map-root .legend-ramp {{
        height: 9px;
        border-radius: 3px;
        margin: 5px 0 3px;
        background: linear-gradient(to right, {_ramp_css});
      }}
      .glider-map-root .legend-ends {{
        display: flex;
        justify-content: space-between;
        color: #b9c2cb;
        font-size: 10.5px;
      }}
      .glider-map-root .legend-site {{
        display: inline-block;
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #fff;
        border: 2px solid #0b0b0b;
        vertical-align: -1px;
        margin-right: 5px;
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
        <b>Historical</b> — profile positions by deployment date
        <div class="legend-ramp"></div>
        <div class="legend-ends"><span>{_months[0]}</span><span>{_months[-1]}</span></div>
        <div style="margin-top:7px"><span class="legend-site"></span>{_site_names}</div>
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
def historical_toggle_visibility(map_widget, view_toggle):
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
    # Folger sites are deliberately absent from this list: they are fixed reference
    # points that belong in both views.
    _historical = view_toggle.value == "Historical"

    map_widget.set_visibility("historical-points", _historical)
    for _layer in ("glider-track-line", "glider-segment-markers"):
        map_widget.set_visibility(_layer, not _historical)

    historical_view = _historical
    return (historical_view,)


@app.cell(hide_code=True)
def click_plot(glider_records, historical_view, map_ui, set_plot_closed):
    _clicked = (map_ui.value or {}).get("clicked") or {}
    _click_lon, _click_lat = _clicked.get("lng"), _clicked.get("lat")
    _TOLERANCE_DEG = 0.05  # generous proximity radius for hit-testing a click against a track

    def _near(lon, lat, lon2, lat2, tol=_TOLERANCE_DEG):
        return lon is not None and abs(lon - lon2) < tol and abs(lat - lat2) < tol

    # Historical is a look-only view for now: clicking a track opens nothing. The
    # click-through plots are another team member's work, so leave the selection empty
    # rather than half-wiring a panel they will replace. Guarding the hit-test rather
    # than returning early keeps this cell's single return statement intact, which is
    # what marimo reads to know the cell defines `selected_glider_record`.
    #
    # This also clears any live-view selection on the way in, so switching views never
    # strands an orange highlight under a layer that is no longer visible.
    selected_glider_record = None
    if not historical_view:
        for _rec in glider_records:
            if any(_near(_click_lon, _click_lat, lon2, lat2)
                   for lon2, lat2 in zip(_rec["df"]["Longitude"], _rec["df"]["Latitude"])):
                selected_glider_record = _rec
                break  # first deployment within tolerance wins -- same precision as today's
                       # single-glider hit-test, generalized from 1 candidate to N

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
    if selected_glider_record is not None:
        set_plot_closed(False)
    return (selected_glider_record,)


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
    map_widget.set_paint_property("glider-track-line", "line-color", _expression)
    map_widget.set_paint_property("glider-segment-markers", "circle-color", _expression)
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
    _visible = selection_plot is not None and not _closed

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
        _content = mo.vstack([
            _close_button, selection_plot,
            glider_decimation_slider, glider_time_slider, time_range_label,
        ])
    else:
        _content = mo.md("_Click a glider track to see a plot here._")

    mo.sidebar(_content, width="480px")
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
