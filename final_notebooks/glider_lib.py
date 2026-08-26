"""Shared data-loading and plotting functions for the BarkleyScope glider/CTD notebooks.

This is a copy of the column-standardization, loader, and plot functions defined in
Sections 4-6 of `Glider_Curtain_Plot.ipynb`, factored out so more than one notebook/app
(the 3D curtain notebook, `Glider_Map_App.ipynb`, and future mooring-time-series /
ocean-current-field views) can share one implementation instead of drifting apart.

`Glider_Curtain_Plot.ipynb` currently still defines these inline rather than importing
from here -- the two are kept in sync by hand for now. If that becomes a maintenance
problem, point the notebook's Section 4-6 cells at `from glider_lib import ...` instead.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Column & coordinate standardization (Glider_Curtain_Plot.ipynb Section 4)
# ---------------------------------------------------------------------------

STANDARD_ALIASES = {
    "lon": ["lon", "longitude", "long", "lng", "x", "lon_dec", "decimallongitude"],
    "lat": ["lat", "latitude", "y", "lat_dec", "decimallatitude"],
    "depth": ["depth", "z", "depth_m", "z_pos"],
}


def resolve_column(available, standard_key, aliases, override=None):
    """Find the actual column/variable name for a standard field, matching case-insensitively.

    `override` (e.g. from a COLUMN_MAP) is tried first if given; otherwise falls back to the
    alias list for `standard_key`.
    """
    lookup = {str(c).lower(): c for c in available}
    candidates = [override] if override else aliases.get(standard_key, [standard_key])
    for candidate in candidates:
        if candidate and str(candidate).lower() in lookup:
            return lookup[str(candidate).lower()]
    raise KeyError(
        f"Could not find a column for '{standard_key}' (tried {candidates}). "
        f"Available columns: {list(available)}. "
        f"Set COLUMN_MAP['{standard_key}'] explicitly if your file uses a different name."
    )


def standardize_longitude(lon):
    """Convert longitude to the standard -180-180 range, regardless of whether the source used
    that convention or 0-360. Idempotent -- safe to call on already-standard data."""
    lon = np.asarray(lon, dtype=float)
    return ((lon + 180) % 360) - 180


# ---------------------------------------------------------------------------
# 2. Real data loader (Glider_Curtain_Plot.ipynb Section 5)
# ---------------------------------------------------------------------------

def load_platform_data(path, file_type, column_map):
    """Load a real glider track or CTD cast and standardize it to Longitude/Latitude/Depth/<variable>.

    Works for both platform types: a CTD cast is just a file where lon/lat barely vary.
    `column_map` maps standard keys ("lon", "lat", "depth", "variable") to actual column names.
    lon/lat/depth are auto-detected (case-insensitive, common aliases) if left as None in
    column_map -- only "variable" must be given, since it's arbitrary per dataset.
    """
    if file_type == "csv":
        raw = pd.read_csv(path)
    elif file_type in ("netcdf", "nc"):
        import xarray as xr
        raw = xr.open_dataset(path).to_dataframe().reset_index()
    else:
        raise ValueError(f"Unsupported FILE_TYPE: {file_type!r} (expected 'csv' or 'netcdf')")

    lon_col = resolve_column(raw.columns, "lon", STANDARD_ALIASES, column_map.get("lon"))
    lat_col = resolve_column(raw.columns, "lat", STANDARD_ALIASES, column_map.get("lat"))
    depth_col = resolve_column(raw.columns, "depth", STANDARD_ALIASES, column_map.get("depth"))
    if not column_map.get("variable"):
        raise KeyError("COLUMN_MAP['variable'] must be set -- it can't be auto-detected.")
    var_col = resolve_column(raw.columns, "variable", {}, column_map["variable"])

    df = raw[[lon_col, lat_col, depth_col, var_col]].copy()
    df.columns = ["Longitude", "Latitude", "Depth", column_map["variable"]]
    df["Longitude"] = standardize_longitude(df["Longitude"])
    df = df.dropna().reset_index(drop=True)
    return df


def generate_sample_glider_data(num_points=500, variable_col="Temperature",
                                 lon_range=(-126.8, -124.5), lat_range=(47.85, 49.36),
                                 max_depth=150):
    """Simulate a sawtooth glider track with a synthetic variable field.

    Used as a placeholder layer on the map so it isn't empty before a real
    GLIDER.DATA_PATH file is configured -- same synthetic-data approach as
    Glider_Curtain_Plot.ipynb Section 3.
    """
    time = np.linspace(0, 10, num_points)
    lon = lon_range[0] + (lon_range[1] - lon_range[0]) * (time / time.max())
    lat = lat_range[0] + (lat_range[1] - lat_range[0]) * (time / time.max())
    depth = (max_depth / 2) * (1 + np.sin(2 * np.pi * time))
    variable = 12 - (depth * 0.02) + np.random.normal(0, 0.3, num_points)
    return pd.DataFrame({"Longitude": lon, "Latitude": lat, "Depth": depth, variable_col: variable})


# ---------------------------------------------------------------------------
# 3. Bathymetry clip/drape helpers (Glider_Curtain_Plot.ipynb Section 6) --
#    only needed if a popup plot is built with bathymetry=<loaded grid>.
# ---------------------------------------------------------------------------

def clip_and_decimate_bathymetry(bathy, lon_bounds, lat_bounds, buffer_deg=0.02, max_grid_size=200):
    """Crop a bathymetry grid to the area around some data (+ buffer) and thin it for fast 3D rendering."""
    lon, lat, depth = bathy["lon"], bathy["lat"], bathy["depth"]

    lon_mask = (lon >= lon_bounds[0] - buffer_deg) & (lon <= lon_bounds[1] + buffer_deg)
    lat_mask = (lat >= lat_bounds[0] - buffer_deg) & (lat <= lat_bounds[1] + buffer_deg)

    lon_clip = lon[lon_mask]
    lat_clip = lat[lat_mask]

    if len(lon_clip) == 0 or len(lat_clip) == 0:
        raise ValueError(
            "Bathymetry grid does not cover this data's footprint.\n"
            f"  Bathymetry covers lon [{lon.min():.3f}, {lon.max():.3f}], lat [{lat.min():.3f}, {lat.max():.3f}]\n"
            f"  Data (+ buffer) needs lon [{lon_bounds[0]-buffer_deg:.3f}, {lon_bounds[1]+buffer_deg:.3f}], "
            f"lat [{lat_bounds[0]-buffer_deg:.3f}, {lat_bounds[1]+buffer_deg:.3f}]\n"
            "  Get a bathymetry file that covers the data's actual location, or plot without bathymetry (bathymetry=None)."
        )

    depth_clip = depth[np.ix_(lat_mask, lon_mask)]

    lon_step = max(1, len(lon_clip) // max_grid_size)
    lat_step = max(1, len(lat_clip) // max_grid_size)

    return {
        "lon": lon_clip[::lon_step],
        "lat": lat_clip[::lat_step],
        "depth": depth_clip[::lat_step, ::lon_step],
    }


def add_bathymetry_surface(fig, bathy, lon_bounds, lat_bounds, buffer_deg=0.02,
                            max_grid_size=200, colorscale="gray", opacity=0.85):
    """Add a shaded seafloor Surface trace to an existing 3D figure, clipped to the data's footprint."""
    import plotly.graph_objects as go

    patch = clip_and_decimate_bathymetry(bathy, lon_bounds, lat_bounds, buffer_deg, max_grid_size)
    fig.add_trace(go.Surface(
        x=patch["lon"], y=patch["lat"], z=patch["depth"],
        colorscale=colorscale, showscale=False, opacity=opacity,
        lighting=dict(ambient=0.6, diffuse=0.8, specular=0.1),
    ))
    return fig


# ---------------------------------------------------------------------------
# 4. Plot functions (Glider_Curtain_Plot.ipynb Section 7) -- unchanged so a
#    map popup shows exactly the same figure the curtain notebook produces.
# ---------------------------------------------------------------------------

def plot_glider_curtain(df, variable_col, variable_label=None, color_scale="Thermal",
                         title=None, marker_size=4, bathymetry=None,
                         bathy_buffer_deg=0.02, bathy_max_grid_size=200,
                         bathy_colorscale="gray", bathy_opacity=0.85):
    """Build an interactive 3D 'curtain' plot of a track/cast colored by one variable,
    optionally draped over a clipped patch of bathymetry."""
    import plotly.graph_objects as go

    variable_label = variable_label or variable_col
    title = title or f"3D {variable_label} Curtain Plot"

    fig = go.Figure()

    if bathymetry is not None:
        lon_bounds = (df["Longitude"].min(), df["Longitude"].max())
        lat_bounds = (df["Latitude"].min(), df["Latitude"].max())
        add_bathymetry_surface(fig, bathymetry, lon_bounds, lat_bounds,
                                buffer_deg=bathy_buffer_deg, max_grid_size=bathy_max_grid_size,
                                colorscale=bathy_colorscale, opacity=bathy_opacity)

    fig.add_trace(go.Scatter3d(
        x=df["Longitude"], y=df["Latitude"], z=df["Depth"],
        mode="markers",
        marker=dict(size=marker_size, color=df[variable_col], colorscale=color_scale,
                    colorbar=dict(title=variable_label)),
        name=variable_label,
    ))

    fig.update_layout(
        title=title,
        scene=dict(xaxis_title="Longitude", yaxis_title="Latitude", zaxis_title="Depth (m)"),
    )
    return fig


def plot_ctd_profile(df, variable_col, variable_label=None, title=None,
                      line_color="#1b6ca8", line_width=2, marker_size=4):
    """Standard 2D CTD profile: <variable> vs. depth, surface at top.

    Unlike a glider, a CTD cast doesn't move through lon/lat -- rendering it in 3D space
    (like a curtain) would misleadingly imply horizontal extent it doesn't actually have.
    """
    import plotly.graph_objects as go

    variable_label = variable_label or variable_col
    title = title or f"CTD Profile: {variable_label}"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df[variable_col], y=df["Depth"],
        mode="lines+markers",
        line=dict(color=line_color, width=line_width),
        marker=dict(size=marker_size, color=line_color),
        name=variable_label,
    ))
    fig.update_layout(
        title=title,
        xaxis_title=variable_label,
        yaxis_title="Depth (m)",
        yaxis=dict(autorange="reversed"),  # surface at top
    )
    return fig
