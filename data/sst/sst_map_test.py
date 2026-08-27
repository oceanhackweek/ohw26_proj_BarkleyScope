# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "anywidget==0.11.0",
#     "maplibre==0.3.6",
#     "marimo>=0.24.0",
#     "numpy==2.5.2",
#     "pandas==3.0.5",
#     # Not imported by this file, but reached transitively and therefore required in a
#     # sandbox, which builds an isolated venv from exactly this list:
#     #   xarray + netCDF4 -- barkley_sst.read_grid() opens the SST archive
#     #   netCDF4 + requests -- cproof_glider, imported by map_layers.build_glider
#     # The JupyterLab marimo tile launches `marimo edit --sandbox`, so omitting these
#     # fails at `import barkley_sst` even when they are installed in the outer env.
#     "xarray==2025.9.0",
#     "netCDF4==1.7.4",
#     "requests==2.34.2",
# ]
# [tool.marimo.venv]
# path = "/home/.pixi/envs/default"
# ///

# A copy of final_notebooks/Web_App_test.py, kept structurally faithful to it, with the
# hand-listed layers replaced by data/sst/map_layers.py's registry. The original is not
# modified -- if this pattern proves out, its owner can adopt it deliberately.
#
# Differences from the original, and why:
#   - Layers come from the registry, so adding a dataset means editing map_layers.py, not
#     this file's `map` cell.
#   - The CTD marker is gone: NE_San_Diego_Trough_Aug_2022.csv is gitignored and was never
#     committed, so the original's `ctd_data` cell raises here before anything renders.
#   - The synthetic sawtooth glider is replaced by the real committed track. Judging
#     whether real SST looks right against invented glider data would prove nothing.
#   - No plotly: nothing here draws a curtain or profile.

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def nb_imports():
    import sys
    from pathlib import Path

    import marimo as mo
    import numpy as np

    _HERE = Path(__file__).resolve().parent
    for _p in (_HERE, _HERE.parent):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    from maplibre.ipywidget import MapWidget
    from maplibre.map import MapOptions
    from maplibre.layer import Layer, LayerType
    from maplibre.sources import RasterTileSource
    from maplibre.controls import NavigationControl, ScaleControl
    from maplibre.basemaps import construct_basemap_style

    import barkley_sst as sst
    import map_layers

    return (Layer, LayerType, MapOptions, MapWidget, NavigationControl,
            RasterTileSource, ScaleControl, construct_basemap_style,
            map_layers, mo, np, sst)


@app.cell
def config(map_layers, sst):
    # Same shape as the original's CONFIG_MAP, extended with the layer blocks that
    # map_layers.py understands. REGION is read from barkley_sst.BOX rather than retyped,
    # so it cannot drift from the values the data was cut to.
    CONFIG_MAP = {
        "REGION": {"lon_range": sst.BOX["lon"], "lat_range": sst.BOX["lat"]},
        **map_layers.DEFAULT_CONFIG,
    }
    return (CONFIG_MAP,)


@app.cell
def layer_data(CONFIG_MAP, map_layers):
    # Every source and layer, built once, up front. The widget's post-construction
    # add_source/add_layer calls are transient comm messages that do not survive a page
    # reload, so anything added that way would vanish on reconnect.
    sst_sources, sst_layers, layer_groups, layer_skipped = map_layers.collect(CONFIG_MAP)

    print(f"{len(sst_layers)} layers from {len(layer_groups)} group(s)")
    for _id, _why in layer_skipped:
        print(f"  skipped {_id}: {_why}")
    return layer_groups, layer_skipped, sst_layers, sst_sources


@app.cell
def grid_data(sst):
    # Read separately from the layer build so the click readout can report a cell's whole
    # week, not just the day being displayed.
    grid = sst.read_grid()
    grid_dates = sst.dates(grid)
    return grid, grid_dates


@app.cell
def map(
    CONFIG_MAP,
    Layer,
    LayerType,
    MapOptions,
    MapWidget,
    NavigationControl,
    RasterTileSource,
    ScaleControl,
    construct_basemap_style,
    mo,
    sst,
    sst_layers,
    sst_sources,
):
    _lon_lo, _lon_hi = CONFIG_MAP["REGION"]["lon_range"]
    _lat_lo, _lat_hi = CONFIG_MAP["REGION"]["lat_range"]

    ESRI_OCEAN_TILES = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}"
    )
    # max_zoom is what the SOURCE publishes, not how far the user may zoom. Esri's
    # ocean basemap is cached globally to about level 13; asking for 14-16 returns
    # nothing, so the basemap silently drops out while the SST layer keeps drawing --
    # which reads as the SST layer being misaligned or oversized. Declaring 13 makes
    # MapLibre stretch the deepest real tile instead, so the basemap stays under the
    # data at every zoom.
    _esri_source = RasterTileSource(tiles=[ESRI_OCEAN_TILES], tile_size=256,
                                    min_zoom=0, max_zoom=13)
    _esri_layer = Layer(id="esri-ocean-basemap", type=LayerType.RASTER, source="esri-ocean")

    # Basemap first, then the registry's layers in their declared draw order. SST is a
    # filled polygon layer, so anything not drawn above it would be buried by it.
    _style = construct_basemap_style(
        layers=[_esri_layer, *sst_layers],
        sources={"esri-ocean": _esri_source.to_dict(), **sst_sources},
        name="esri-ocean-basemap",
    )

    # center/zoom rather than bounds/fit_bounds_options: the widget's render() appends its
    # container to the DOM *after* constructing the map, so fitBounds computes against a
    # detached 0x0 element and lands on a bogus camera. Confirmed in the bundled JS --
    # `e.appendChild(r)` is the last statement of render().
    map_widget = MapWidget(
        MapOptions(
            style=_style,
            center=((_lon_lo + _lon_hi) / 2, (_lat_lo + _lat_hi) / 2),
            zoom=8,
        ),
        height="100vh",
        controls=[NavigationControl(), ScaleControl()],
    )

    # IMPORTANT: this cell depends only on load-time inputs -- nothing here references the
    # toggles, the date picker, or the click position. That is what keeps it running
    # exactly once. Forcing a fresh MapWidget into a live browser session can black-screen
    # the map, so visibility is applied from a downstream cell instead (see
    # apply_visibility below).
    map_ui = mo.ui.anywidget(map_widget)

    _low, _high = CONFIG_MAP["SST"]["COLOR_RANGE"]
    _swatches = "".join(
        f'<span style="flex:1;height:12px;background:{_hex}"></span>'
        for _, _hex in sst.THERMAL_STOPS
    )

    mo.Html(f"""
    <style>
      .layer-map-root {{ position: fixed; inset: 0; z-index: 1; overflow: hidden;
                         background: #0b1a2b; }}
      .layer-map-root .map-layer {{ position: absolute; inset: 0; }}
      .layer-map-root .map-layer, .layer-map-root .map-layer * {{ margin: 0; padding: 0; }}
      .layer-map-root .app-title {{
        position: absolute; top: 16px; left: 16px; z-index: 2; color: #fff;
        font: 600 15px/1.3 system-ui, sans-serif; background: rgba(10,20,30,0.72);
        padding: 8px 14px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.35);
        pointer-events: none;
      }}
      .layer-map-root .sst-legend {{
        position: absolute; bottom: 28px; right: 16px; z-index: 2; width: 240px;
        background: rgba(10,20,30,0.78); color: #eaeaea; padding: 10px 12px;
        border-radius: 10px; font: 12px/1.4 system-ui, sans-serif;
        box-shadow: 0 2px 10px rgba(0,0,0,0.35); pointer-events: none;
      }}
      .layer-map-root .sst-legend .ramp {{ display: flex; margin: 6px 0 3px; }}
    </style>
    <div class="layer-map-root">
      <div class="map-layer">{map_ui}</div>
      <div class="app-title">BarkleyScope -- satellite SST + glider tracks</div>
      <div class="sst-legend">
        <b>Sea surface temperature</b>
        <div class="ramp">{_swatches}</div>
        <div style="display:flex;justify-content:space-between">
          <span>{_low:.0f} &deg;C</span><span>{_high:.0f} &deg;C</span>
        </div>
        <div style="margin-top:6px;opacity:0.75">
          Fixed scale -- a colour means the same temperature on every date.
          Faded cells are water unreachable from the open Pacific.
        </div>
      </div>
    </div>
    """)
    return map_ui, map_widget


@app.cell
def controls(grid_dates, layer_groups, mo):
    # Created here, read in other cells: a marimo UI element only reports interactive
    # values to cells downstream of the one that built it.
    layer_toggles = mo.ui.dictionary({
        _g["id"]: mo.ui.checkbox(value=_g["default"], label=_g["label"])
        for _g in layer_groups
    })
    date_picker = mo.ui.dropdown(
        options=grid_dates, value=grid_dates[-1], label="SST date",
    )
    return date_picker, layer_toggles


@app.cell
def apply_visibility(date_picker, layer_groups, layer_toggles, map_layers, map_widget):
    # The whole point of the architecture: this cell re-runs on every toggle, the `map`
    # cell never does. set_visibility() posts one comm message per call, and the widget's
    # JS applies each message as it arrives -- so repeated toggles keep working.
    _plan = map_layers.visibility_plan(
        layer_groups,
        enabled={_k: bool(_v) for _k, _v in layer_toggles.value.items()},
        steps={"sst": date_picker.value},
    )
    for _layer_id, _visible in _plan.items():
        map_widget.set_visibility(_layer_id, _visible)

    _shown = sum(1 for _v in _plan.values() if _v)
    print(f"{_shown}/{len(_plan)} layers visible")
    return


@app.cell
def readout(date_picker, grid, grid_dates, layer_skipped, layer_toggles, map_ui, mo, np, sst):
    # MapLibre reports one map-wide (lng, lat) per click rather than "which feature", so
    # the nearest cell is resolved here in Python -- the same idiom the original app uses
    # to hit-test its markers.
    _clicked = (map_ui.value or {}).get("clicked") or {}
    _lon, _lat = _clicked.get("lng"), _clicked.get("lat")

    if _lon is None:
        _panel = mo.md("*Click anywhere on the map to read that cell's week.*")
    else:
        _variable = sst.variable_name(grid)
        _lats, _lons = grid["latitude"].values, grid["longitude"].values
        _i = int(np.argmin(np.abs(_lats - _lat)))
        _j = int(np.argmin(np.abs(_lons - _lon)))
        _series = np.asarray(grid[_variable].values[:, _i, _j], dtype=float)

        if not np.isfinite(_series).any():
            _panel = mo.md(
                f"**({_lats[_i]:.3f}, {_lons[_j]:.3f})** -- land, or masked by the "
                "product. Its land mask is coarser than the real coastline, so some "
                "genuine nearshore water reads blank."
            )
        else:
            _rows = "\n".join(
                f"| {_d} | {_v:.2f} |" if np.isfinite(_v) else f"| {_d} | -- |"
                for _d, _v in zip(grid_dates, _series)
            )
            _finite = _series[np.isfinite(_series)]
            _panel = mo.md(f"""
**Cell ({_lats[_i]:.3f}, {_lons[_j]:.3f})**

mean {_finite.mean():.2f} &deg;C, range {_finite.min():.2f}--{_finite.max():.2f} &deg;C

| date | &deg;C |
|---|---|
{_rows}
            """)

    _notes = "".join(f"\n- **{_id}** unavailable: {_why}" for _id, _why in layer_skipped)

    mo.sidebar(
        mo.vstack([
            mo.md("### Layers"),
            layer_toggles,
            date_picker,
            mo.md(f"{sst.SOURCE_CAVEAT}{_notes}"),
            mo.md("---"),
            _panel,
        ]),
        width="330px",
    )
    return


if __name__ == "__main__":
    app.run()
