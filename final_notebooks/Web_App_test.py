# /// script
# dependencies = [
#     "anywidget==0.11.0",
#     "maplibre==0.3.6",
#     "marimo>=0.24.0",
#     "numpy==2.4.6",
#     "pandas==3.0.5",
# ]
# [tool.marimo.venv]
# path = "/home/.pixi/envs/default"
# ///

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def title(mo):
    mo.md(r"""
    # Glider / CTD Map App — Barkley Sound

    marimo + MapLibre rebuild of `Glider_Map_App.ipynb` (which used ipyleaflet + Voila) — see
    `VOILA_TROUBLESHOOTING.md` for why that path was painful. This runs directly from the cryocloud
    JupyterHub's built-in marimo route, no separate process/proxy setup needed.

    **Scaffold note:** real glider data isn't wired up yet. This pass proves out the map and
    click-to-plot mechanics using data that's already on disk:

    - **CTD** — the real `NE_San_Diego_Trough_Aug_2022.csv` cast, *relocated* to a random point
      inside Barkley Sound (its true position is San Diego, well outside this map) so it appears as
      a clickable marker. Only the position is fake here — the salinity/depth values plotted are the
      real measured cast.
    - **Glider** — a fully synthetic sawtooth track generated within the region, the same fallback
      `glider_lib.generate_sample_glider_data()` already uses when no real glider file is configured.

    Click near the CTD marker or the glider track below to render its plot.
    """)
    return


@app.cell
def nb_imports():
    import marimo as mo
    import numpy as np
    import pandas as pd

    from maplibre.ipywidget import MapWidget
    from maplibre.map import MapOptions
    from maplibre.layer import Layer, LayerType
    from maplibre.sources import RasterTileSource, GeoJSONSource
    from maplibre.controls import Marker, NavigationControl, ScaleControl, FullscreenControl
    from maplibre.basemaps import construct_basemap_style

    from glider_lib import (
        load_platform_data,
        generate_sample_glider_data,
        plot_ctd_profile,
        plot_glider_curtain,
    )

    return (
        FullscreenControl,
        GeoJSONSource,
        Layer,
        LayerType,
        MapOptions,
        MapWidget,
        Marker,
        NavigationControl,
        RasterTileSource,
        ScaleControl,
        construct_basemap_style,
        generate_sample_glider_data,
        load_platform_data,
        mo,
        np,
        plot_ctd_profile,
        plot_glider_curtain,
    )


@app.cell
def config_header(mo):
    mo.md(r"""
    ## Configuration

    Same shape as `CONFIG_MAP` in `Glider_Map_App.ipynb` -- region bounding box plus per-platform
    settings. Kept in one place so swapping in real glider data later is a one-line change (see the
    data-shape note at the bottom of this notebook).
    """)
    return


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
            "VARIABLE_LABEL": "Temperature (°C)",
            "COLOR_SCALE": "Thermal",
            "LINE_COLOR": "#f4a261",
            "DEPTH_POSITIVE_DOWN": True,
        },
        "RANDOM_SEED": 42,  # fixed so the relocated CTD marker doesn't jump on every rerun
    }
    return (CONFIG_MAP,)


@app.cell
def data_header(mo):
    mo.md(r"""
    ## Load CTD + glider data (scaffold)

    Real CTD cast (unchanged loader), relocated for map testing; fully synthetic glider track.
    See the data-shape note at the bottom for what changes once a real glider file exists.
    """)
    return


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
def map_header(mo):
    mo.md(r"""
    ## Build the MapLibre basemap

    Esri's public Ocean/World_Ocean_Base XYZ tiles wired in as a raw raster source/layer -- visually
    matches the Esri Ocean Basemap `Glider_Map_App.ipynb` used with ipyleaflet, no API key needed.
    """)
    return


@app.cell
def map(
    CONFIG_MAP,
    FullscreenControl,
    GeoJSONSource,
    Layer,
    LayerType,
    MapOptions,
    MapWidget,
    Marker,
    NavigationControl,
    RasterTileSource,
    ScaleControl,
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
    _basemap_style = construct_basemap_style(
        layers=[_esri_layer],
        sources={"esri-ocean": _esri_source.to_dict()},
        name="esri-ocean-basemap",
    )

    map_widget = MapWidget(
        MapOptions(
            style=_basemap_style,
            bounds=(_lon_lo, _lat_lo, _lon_hi, _lat_hi),
            fit_bounds_options={"padding": 20},
        ),
        height=520,
        controls=[NavigationControl(), ScaleControl(), FullscreenControl()],
    )

    # --- CTD marker ---
    map_widget.add_marker(Marker(lng_lat=(ctd_lon, ctd_lat)))

    # --- Glider track ---
    _glider_line = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat] for lon, lat in zip(glider_df["Longitude"], glider_df["Latitude"])],
        },
        "properties": {},
    }
    map_widget.add_source("glider-track", GeoJSONSource(data=_glider_line))
    map_widget.add_layer(Layer(
        id="glider-track-line",
        type=LayerType.LINE,
        source="glider-track",
        paint={"line-color": CONFIG_MAP["GLIDER"]["LINE_COLOR"], "line-width": 3},
    ))

    map_ui = mo.ui.anywidget(map_widget)
    map_ui
    return (map_ui,)


@app.cell
def click_header(mo):
    mo.md(r"""
    ## Click-to-plot

    MapLibre's click event reports a single map-wide `(lng, lat)`, not "which marker/layer was
    clicked" the way ipyleaflet's per-marker `on_click` did. So instead of an in-map popup, a click
    anywhere near the CTD marker or the glider track re-renders the matching plot in the panel below
    -- proximity is checked in Python against the marker's fixed point and the track's vertices.
    Zoom in a bit for a more precise hit if the map is fully zoomed out.
    """)
    return


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

    selection_plot if selection_plot is not None else mo.md(
        "*Click near the CTD marker or the glider track above to see its plot here.*"
    )
    return


@app.cell
def data_shape(mo):
    mo.md(r"""
    ## Data shape, once real CTD/glider files are available

    Both platforms load through the same `glider_lib.load_platform_data()` and standardize to one
    4-column schema: **`Longitude`, `Latitude`, `Depth`, `<variable>`** (e.g. `Temperature`,
    `Salt2`). Source files can be CSV or NetCDF (`FILE_TYPE`).

    - **Column names are auto-detected**, case-insensitively, via `STANDARD_ALIASES` --
      `Lon`/`Longitude`/`lng`/`x`/`Lon_Dec`, `Lat`/`Latitude`/`y`/`Lat_Dec`, `Depth`/`z`/`depth_m`.
      Only `COLUMN_MAP["variable"]` must be set explicitly, since it's dataset-specific (e.g.
      `"Salt2"` for the real CTD file's preferred salinity sensor).
    - **Longitude** is standardized to -180..180 automatically, whatever convention the source file
      used.
    - **`DEPTH_POSITIVE_DOWN`** controls sign convention on load; this app negates to plot-native
      negative-down depth afterward, same as `Glider_Curtain_Plot.ipynb`.

    The two platforms differ in what varies row to row:

    | | Longitude / Latitude | Depth | Rendered as |
    |---|---|---|---|
    | **CTD cast** | ~constant (instrument stationary) | one row per depth bin | 2D profile: variable vs. depth |
    | **Glider track** | varies every row (moving platform) | varies every row, sawtooth as it dives/climbs | 3D "curtain": scatter colored by variable |

    Once a real glider file exists: set `CONFIG_MAP["GLIDER"]["DATA_PATH"]` +
    `COLUMN_MAP["variable"]`, replace the `generate_sample_glider_data(...)` call above with
    `load_platform_data(...)`, and drop the CTD relocation step -- everything downstream (the map
    layer, `plot_glider_curtain`, `plot_ctd_profile`) already works unmodified.
    """)
    return


if __name__ == "__main__":
    app.run()
