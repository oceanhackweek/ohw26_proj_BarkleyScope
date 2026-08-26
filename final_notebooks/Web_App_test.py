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


@app.cell
def nb_imports():
    import marimo as mo
    import numpy as np
    import pandas as pd

    from maplibre.ipywidget import MapWidget
    from maplibre.map import MapOptions
    from maplibre.layer import Layer, LayerType
    from maplibre.sources import RasterTileSource, GeoJSONSource
    from maplibre.controls import NavigationControl, ScaleControl, FullscreenControl
    from maplibre.basemaps import construct_basemap_style

    # Only the data-loading functions live here -- `ctd_data`/`glider_data`
    # (and therefore `map`, which reads their output) are legitimately
    # downstream of these. Split `plot_ctd_profile`/`plot_glider_curtain` into
    # their own cell (`plot_fn_imports`) on purpose: those are only used by
    # `click_plot`, never by `map`. Editing `glider_lib.py`'s plotting
    # functions and reloading only needs to rerun `plot_fn_imports` --
    # rerunning THIS cell (e.g. via a blanket `importlib.reload` +
    # `ctx.run_cell('nb_imports')`) cascades to `map` too, which forces a
    # brand-new `MapWidget`/`map_ui` object into an already-live browser
    # session and can break the mount (confirmed: this is what caused a
    # black-screen map after a naive glider_lib reload once `plot_glider_curtain`
    # needed a margin/colorbar tweak -- the map cell isn't supposed to ever
    # re-run after initial load, see its own comments below).
    from glider_lib import load_platform_data, generate_sample_glider_data

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
        generate_sample_glider_data,
        load_platform_data,
        mo,
        np,
    )


@app.cell
def config():
    CONFIG_MAP = {
        "REGION": {"lon_range": (-126.8, -124.5), "lat_range": (47.85, 49.36)},  # Barkley Sound, BC
        "CTD": {
            "DATA_PATH": "NE_San_Diego_Trough_Aug_2022.csv",
            "FILE_TYPE": "csv",
            "COLUMN_MAP": {"lon": None, "lat": None, "depth": None, "variable": "Salt2"},
            "VARIABLE_LABEL": "Salinity (PSU)",
            "LINE_COLOR": "#1b6ca8",
            "DEPTH_POSITIVE_DOWN": True,
        },
        "GLIDER": {
            # Placeholder, unused until glider_data below is swapped from
            # generate_sample_glider_data(...) to load_platform_data(...) --
            # mirrors the same placeholder shape/value already sitting in
            # Glider_Curtain_Plot.ipynb's own CONFIG["GLIDER"]. Fill in a real
            # DATA_PATH and set COLUMN_MAP["variable"] to make that swap; see
            # MARIMO_APP_STATUS.md for the full migration steps.
            "DATA_PATH": "path/to/glider_data.csv",
            "FILE_TYPE": "csv",
            "COLUMN_MAP": {"lon": None, "lat": None, "depth": None, "variable": "Temperature"},
            "VARIABLE_LABEL": "Temperature (°C)",
            "COLOR_SCALE": "Thermal",
            "LINE_COLOR": "#f4a261",
            "DEPTH_POSITIVE_DOWN": True,
        },
        "RANDOM_SEED": 42,  # fixed so the relocated CTD marker doesn't jump on every rerun
    }
    return (CONFIG_MAP,)


@app.cell(hide_code=True)
def about_note(mo):
    about_md = mo.md(r"""
    **About this scaffold:** real glider data isn't wired up yet. This pass proves out the map and
    click-to-plot mechanics using data that's already on disk -- marimo + MapLibre rebuild of
    `Glider_Map_App.ipynb` (which used ipyleaflet + Voila; see `VOILA_TROUBLESHOOTING.md` for why that
    path was painful).

    - **CTD** -- the real `NE_San_Diego_Trough_Aug_2022.csv` cast, *relocated* to a random point inside
      Barkley Sound (its true position is San Diego) so it appears as a clickable marker. Only the
      position is fake -- the salinity/depth values plotted are the real measured cast.
    - **Glider** -- a fully synthetic sawtooth track generated within the region
      (`glider_lib.generate_sample_glider_data()`), the fallback used when no real glider file is
      configured.

    **Data shape, once real files are available:** both platforms load through
    `glider_lib.load_platform_data()` and standardize to `Longitude`, `Latitude`, `Depth`, `<variable>`
    (CSV or NetCDF). Column names are auto-detected via `STANDARD_ALIASES`; only
    `COLUMN_MAP["variable"]` must be set explicitly. To wire in a real glider file: set
    `CONFIG_MAP["GLIDER"]["DATA_PATH"]` + `COLUMN_MAP["variable"]`, swap the
    `generate_sample_glider_data(...)` call for `load_platform_data(...)`, and drop the CTD relocation
    step -- everything downstream already works unmodified.
    """)
    return (about_md,)


@app.cell
def ctd_data(CONFIG_MAP, load_platform_data, np):
    _ctd_cfg = CONFIG_MAP["CTD"]
    _region = CONFIG_MAP["REGION"]
    ctd_var = _ctd_cfg["COLUMN_MAP"]["variable"]

    ctd_df = load_platform_data(_ctd_cfg["DATA_PATH"], _ctd_cfg["FILE_TYPE"], _ctd_cfg["COLUMN_MAP"])
    if _ctd_cfg["DEPTH_POSITIVE_DOWN"]:
        ctd_df["Depth"] = -ctd_df["Depth"].abs()

    # Scaffold-only: the real cast sits in San Diego, far outside Barkley Sound. Relocate it to a
    # fixed random point inside REGION so it renders as a clickable marker on this map -- only the
    # position is synthetic; Salt2/Depth stay the real measured values.
    _rng = np.random.default_rng(CONFIG_MAP["RANDOM_SEED"])
    ctd_lon = float(_rng.uniform(*_region["lon_range"]))
    ctd_lat = float(_rng.uniform(*_region["lat_range"]))
    ctd_df["Longitude"] = ctd_lon
    ctd_df["Latitude"] = ctd_lat

    print(f"CTD cast: {len(ctd_df)} rows, relocated to ({ctd_lon:.3f}, {ctd_lat:.3f}) for map testing")
    return ctd_df, ctd_lat, ctd_lon, ctd_var


@app.cell
def glider_data(CONFIG_MAP, generate_sample_glider_data):
    _glider_cfg = CONFIG_MAP["GLIDER"]
    glider_var = "Temperature"

    glider_df = generate_sample_glider_data(
        variable_col=glider_var,
        lon_range=CONFIG_MAP["REGION"]["lon_range"],
        lat_range=CONFIG_MAP["REGION"]["lat_range"],
    )
    if _glider_cfg["DEPTH_POSITIVE_DOWN"]:
        glider_df["Depth"] = -glider_df["Depth"].abs()

    print(f"Glider: {len(glider_df)} synthetic sample points across the region")
    return glider_df, glider_var


@app.cell
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
    ctd_lat,
    ctd_lon,
    glider_df,
    mo,
):
    _lon_lo, _lon_hi = CONFIG_MAP["REGION"]["lon_range"]
    _lat_lo, _lat_hi = CONFIG_MAP["REGION"]["lat_range"]

    ESRI_OCEAN_TILES = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}"
    )
    _esri_source = RasterTileSource(tiles=[ESRI_OCEAN_TILES], tile_size=256, min_zoom=0, max_zoom=16)
    _esri_layer = Layer(id="esri-ocean-basemap", type=LayerType.RASTER, source="esri-ocean")

    # --- CTD marker source/layer ---
    _ctd_point = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [ctd_lon, ctd_lat]},
        "properties": {},
    }
    _ctd_layer = Layer(
        id="ctd-point-marker",
        type=LayerType.CIRCLE,
        source="ctd-point",
        paint={
            "circle-radius": 8,
            "circle-color": CONFIG_MAP["CTD"]["LINE_COLOR"],
            "circle-stroke-width": 2,
            "circle-stroke-color": "#ffffff",
        },
    )

    # --- Glider track source/layer ---
    _glider_line = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat] for lon, lat in zip(glider_df["Longitude"], glider_df["Latitude"])],
        },
        "properties": {},
    }
    _glider_layer = Layer(
        id="glider-track-line",
        type=LayerType.LINE,
        source="glider-track",
        paint={"line-color": CONFIG_MAP["GLIDER"]["LINE_COLOR"], "line-width": 3},
    )

    # All three source/layer pairs are baked directly into the initial style
    # (see earlier pass's long comment for why -- add_source/add_layer after
    # construction only fire once, ever, and don't survive reconnects).
    _basemap_style = construct_basemap_style(
        layers=[_esri_layer, _glider_layer, _ctd_layer],
        sources={
            "esri-ocean": _esri_source.to_dict(),
            "glider-track": GeoJSONSource(data=_glider_line).to_dict(),
            "ctd-point": GeoJSONSource(data=_ctd_point).to_dict(),
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
    # (MapLibre order is [lon, lat], same as this file's ctd_lon/ctd_lat).
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
    map_ui = mo.ui.anywidget(map_widget)

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
    </style>
    <div class="glider-map-root">
      <div class="map-layer">{map_ui}</div>
      <div class="app-title">Glider / CTD Map -- Barkley Sound</div>
      <details class="about-toggle">
        <summary>i</summary>
        <div class="about-body">{about_md}</div>
      </details>
    </div>
    """)
    return (map_ui,)


@app.cell
def click_plot(
    CONFIG_MAP,
    ctd_df,
    ctd_lat,
    ctd_lon,
    ctd_var,
    glider_df,
    glider_var,
    map_ui,
    mo,
    plot_ctd_profile,
    plot_glider_curtain,
    set_plot_closed,
):
    _clicked = (map_ui.value or {}).get("clicked") or {}
    _click_lon, _click_lat = _clicked.get("lng"), _clicked.get("lat")
    _TOLERANCE_DEG = 0.05  # generous proximity radius for hit-testing a click against a marker/line

    def _near(lon, lat, lon2, lat2, tol=_TOLERANCE_DEG):
        return lon is not None and abs(lon - lon2) < tol and abs(lat - lat2) < tol

    _hit_ctd = _near(_click_lon, _click_lat, ctd_lon, ctd_lat)
    _hit_glider = not _hit_ctd and any(
        _near(_click_lon, _click_lat, lon2, lat2)
        for lon2, lat2 in zip(glider_df["Longitude"], glider_df["Latitude"])
    )

    if _hit_ctd:
        selection_plot = plot_ctd_profile(
            ctd_df, ctd_var,
            variable_label=CONFIG_MAP["CTD"]["VARIABLE_LABEL"],
            line_color=CONFIG_MAP["CTD"]["LINE_COLOR"],
        )
    elif _hit_glider:
        selection_plot = plot_glider_curtain(
            glider_df, glider_var,
            variable_label=CONFIG_MAP["GLIDER"]["VARIABLE_LABEL"],
            color_scale=CONFIG_MAP["GLIDER"]["COLOR_SCALE"],
        )
    else:
        selection_plot = None

    # Reset the close flag on every new valid selection so clicking a
    # (possibly different) marker/track point always reopens the panel, even
    # if it was previously closed -- this cell re-runs on every map click, so
    # this naturally fires each time, only when a real hit is found.
    if selection_plot is not None:
        set_plot_closed(False)

    # IMPORTANT: a raw plotly `go.Figure` only renders correctly when marimo's
    # own cell-output machinery inspects it directly (its registered
    # `formatters.formatter(go.Figure)` hook produces a `<marimo-plotly>`
    # custom element, which the browser auto-upgrades into a live interactive
    # chart on insertion). f-string-embedding a *raw* Figure into `mo.Html(...)`
    # (as `plot_overlay` does) skips that hook entirely -- Python's plain
    # `str(fig)`/`format(fig, "")` just dumps the figure's internal repr (a
    # huge text blob, base64 trace data and all), not HTML, and that's what
    # silently rendered as inert text/nothing-recognizable in the popup.
    # `mo.as_html(...)` runs the figure through marimo's real formatter first,
    # producing an actual `Html`-wrapped `<marimo-plotly>` element that DOES
    # embed and auto-upgrade correctly via f-string interpolation (same
    # mechanism `map_ui`'s widget mount already relies on -- custom elements
    # upgrade on DOM insertion regardless of how they were inserted, unlike a
    # plain `<script>` tag, which a browser will never execute when injected
    # via innerHTML).
    if selection_plot is not None:
        selection_plot = mo.as_html(selection_plot)
    return (selection_plot,)


@app.cell(hide_code=True)
def plot_overlay(get_plot_closed, mo, selection_plot, set_plot_closed):
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
        _content = mo.vstack([_close_button, selection_plot])
    else:
        _content = mo.md("_Click the CTD marker or glider track to see a plot here._")

    mo.sidebar(_content, width="480px")
    return


@app.cell
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


@app.cell
def _():
    # Split out from `nb_imports` on purpose -- see the comment there. Only
    # `click_plot` (and therefore `plot_overlay`) should ever need to rerun
    # when these specific functions change; `map`/`ctd_data`/`glider_data`
    # must never depend on this cell.
    from glider_lib import plot_ctd_profile, plot_glider_curtain

    return plot_ctd_profile, plot_glider_curtain


if __name__ == "__main__":
    app.run()
