# Marimo Glider/CTD Map App — Status & Migration Guide

`Web_App_test.py` is a working marimo app: a full-viewport MapLibre map of Barkley Sound
with a CTD marker and a glider track, where clicking either pops open a plot (2D salinity
profile for the CTD, 3D temperature curtain for the glider) in a sidebar. It's a rebuild of
`Glider_Map_App.ipynb` (ipyleaflet + Voila — see `VOILA_TROUBLESHOOTING.md` for why that path
was abandoned), using MapLibre + marimo's own reactivity instead.

**All plotting math comes from `glider_lib.py`** (`plot_ctd_profile`, `plot_glider_curtain`,
`load_platform_data`, `generate_sample_glider_data`) — the same functions `Glider_Curtain_Plot.ipynb`
uses. The app itself contributes no new science, just the map + click-to-plot interface around
those functions. **This doc exists so the trajectory/curtain-plot work already done on real glider
data can be wired into this interface without re-deriving how the app is put together.**

Everything below reflects the live notebook as of 2026-08-27/28 (eighteenth pairing pass).

## Running it

Open `Web_App_test.py` through the JupyterLab "marimo" launcher tile
(`https://hub.cryointhecloud.com/user/<you>/marimo/`), not the plain file browser (that opens a
text editor, not the running app). It's a PEP-723 script (inline `# /// script` dependency
header at the top of the file) — if you ever run it with a bare `marimo edit Web_App_test.py`
from a terminal, use `--sandbox` or the header is ignored.

**Install the app's packages into the *user* site, once — not into the base env.** This is
what fixes the long-standing "opens blank in the hub" failure; see "Why it went blank"
below for the mechanism.

```bash
python -m pip install --user maplibre==0.3.6 anywidget plotly
```

`--user` puts them in `/home/jovyan/.local/lib/python3.14/site-packages`, which is on the
NFS home volume and therefore survives a server restart. Installing them into
`/home/.pixi/envs/default` (what a bare `pip install` does) works until the next restart
and no further: that env lives on the container overlay and is rebuilt from the image
every time. That is why they kept disappearing.

### Why it went blank (diagnosed 2026-08-28)

The hub's launcher tile runs `marimo edit --sandbox`, which normally builds a throwaway uv
venv per notebook — but both apps' PEP-723 headers carry

```toml
[tool.marimo.venv]
path = "/home/.pixi/envs/default"
```

and marimo 0.24 gives a *configured* venv precedence over the ephemeral sandbox
(`marimo/_session/managers/ipc.py`). So the kernel runs in the shared conda base env, and
marimo treats a configured venv as **read-only — it will not install anything into it**.
That env ships without `maplibre`, `anywidget` or `plotly`, so `nb_imports` raised
`ModuleNotFoundError`, every cell downstream of it — including `map` — never ran, and the
page rendered nothing at all. No error is visible without opening the cell, which is why
this read as "the map is broken" rather than "a package is missing".

Reproduced and fixed on 2026-08-28: with the three packages on the user site,
`marimo export html` (which executes every cell through marimo's own runtime) completes
with no failed cells.

There was a **second, independent** version of the same failure hiding behind it, for
anyone who runs without that venv pin — a real sandbox builds from the `dependencies` list,
which was missing `requests`, `netCDF4`, `xarray` and `gsw`. Those are not imported by the
app file; they come in one module deeper, through `glider_lib` → `data/cproof_https.py` →
`data/cproof_glider.py`. `marimo export html --sandbox` failed with
`No module named 'requests'` in `glider_data` and "An ancestor raised an exception" in
every cell after it — the same blank page, a different cause. The header now lists them,
and that path exports clean too.

**`Web_App_test.py` still does not run**, for an unrelated and already-known reason: it
reads `NE_San_Diego_Trough_Aug_2022.csv`, which is gitignored and absent from a clean
checkout, so `ctd_data` raises `FileNotFoundError` and `map` never runs. A fix sits in a
local `git stash`. `Real-Time_Glider_WebApp.py` is the one that works.

## Showing it in a presentation

`final_notebooks/serve_app.sh` serves the real-time app in marimo's *app* mode — no code
cells, no editor chrome — and prints a link:

```
https://hub.cryointhecloud.com/user/<you>/proxy/absolute/2718/
```

The link is live only while that command is running and while your own hub server is up;
it is proxied through your singleuser server, so anyone opening it needs access to that
server. It is not a public URL. The script's comments explain the two proxy details that
have to be right (bind IPv4, and use the `/proxy/absolute/<port>/` route with a matching
`--base-url`) — both are traps the image's own config file documents.

For a link that survives without a running server, `marimo export html` produces a
self-contained ~7.5 MB snapshot. The map renders and pans, since MapLibre is client-side,
but anything that needs Python — the view switch, click-to-plot — will not respond.

## Architecture

Ten cells, in dependency order:

| Cell | Public names | Role |
|---|---|---|
| `nb_imports` | `mo`, `np`, `pd`, maplibre classes, `load_platform_data`, `generate_sample_glider_data` | Imports needed by data-loading + the map. **Deliberately excludes** the plot functions — see below. |
| `plot_fn_imports` | `plot_ctd_profile`, `plot_glider_curtain` | Imports needed only by the click→plot path. Split out on purpose (see "Two import cells" below). |
| `config` | `CONFIG_MAP` | The one place to point at real data. |
| `about_note` | `about_md` | Static markdown shown in the map's "i" popover. Not data logic. |
| `ctd_data` | `ctd_df`, `ctd_var`, `ctd_lon`, `ctd_lat` | Loads/prepares the CTD cast. |
| `glider_data` | `glider_df`, `glider_var` | Loads/prepares the glider track. **This is the cell to change for real glider data.** |
| `map` | `map_widget`, `map_ui` | Builds the MapLibre map (basemap + CTD marker + glider line) and displays it, full-viewport. Runs **once**, at load, forever. |
| `click_plot` | `selection_plot` | Reads the map's last click, proximity-matches it against the CTD point / glider vertices, builds the matching plot via `glider_lib`. |
| *(unnamed, `mo.state`)* | `get_plot_closed`, `set_plot_closed` | Shared open/closed flag for the plot panel. |
| `plot_overlay` | — | Renders `selection_plot` (or a placeholder) into a `mo.sidebar(...)`. |

Dataflow: `config` → `ctd_data`/`glider_data` → `map` (draws markers/track) and, independently,
→ `click_plot` (hit-tests + builds the figure) → `plot_overlay` (displays it).

## Config surface — `CONFIG_MAP`

Everything migration-relevant is meant to go through the `config` cell:

```python
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
        "DATA_PATH": "path/to/glider_data.csv",  # placeholder -- unused until glider_data (below) is swapped over
        "FILE_TYPE": "csv",
        "COLUMN_MAP": {"lon": None, "lat": None, "depth": None, "variable": "Temperature"},
        "VARIABLE_LABEL": "Temperature (°C)",
        "COLOR_SCALE": "Thermal",
        "LINE_COLOR": "#f4a261",
        "DEPTH_POSITIVE_DOWN": True,
    },
    "RANDOM_SEED": 42,
}
```

`lon`/`lat`/`depth` in `COLUMN_MAP` are auto-detected case-insensitively via `STANDARD_ALIASES`
in `glider_lib.py` (handles `longitude`/`lng`/`x`, `latitude`/`y`, `z`/`depth_m`, etc.) — leave
them `None` unless your file uses something not in that alias list. Only `"variable"` must be
set explicitly, since it's arbitrary per dataset.

**`GLIDER["DATA_PATH"]`/`FILE_TYPE`/`COLUMN_MAP` are a placeholder as of 2026-08-28** — the same
`"path/to/glider_data.csv"` placeholder `Glider_Curtain_Plot.ipynb`'s own `CONFIG["GLIDER"]` uses,
added here ahead of time so the app's config shape already matches the notebook's. They're inert
right now: `glider_data` (below) doesn't read them yet, still calling
`generate_sample_glider_data(...)` instead. **This `CONFIG_MAP` is not synced with the notebook's
`CONFIG` in any automatic way** — they're two independently hand-maintained Python dicts in two
separate files (compare `CONFIG_MAP["CTD"]` above to the notebook's `CONFIG["CTD"]`: identical
values, because someone read the notebook and retyped them here by hand when the CTD marker was
wired up — nothing propagates on its own). Once real glider data has a real path/columns in the
notebook, the same manual copy needs to happen here.

## Migrating real glider data into the app

Right now `glider_data` calls `generate_sample_glider_data(...)` (a synthetic sawtooth track) as
a placeholder, and `CONFIG_MAP["GLIDER"]`'s `DATA_PATH`/`FILE_TYPE`/`COLUMN_MAP` (above) are
placeholder values not yet read by any code. To swap in your team's real trajectory data, the
intended path (already spelled out in `about_md`, i.e. the app's own "i" popover) is:

1. Replace the placeholder `DATA_PATH` (and `COLUMN_MAP["variable"]`, and `FILE_TYPE` if it's
   NetCDF) in `CONFIG_MAP["GLIDER"]` with the real values — copied by hand from whatever
   `Glider_Curtain_Plot.ipynb`'s own `CONFIG["GLIDER"]` ends up using once it points at a real
   file (see "Known gap" above — that notebook still has its own placeholder there too, as of
   this writing).
2. In `glider_data`, replace the `generate_sample_glider_data(...)` call with
   `load_platform_data(_glider_cfg["DATA_PATH"], _glider_cfg["FILE_TYPE"], _glider_cfg["COLUMN_MAP"])`
   — the exact same call `ctd_data` already makes. It returns a `Longitude`/`Latitude`/`Depth`/
   `<variable>` dataframe, which is exactly what `map` and `click_plot` already consume — **no
   other cell should need to change** for this swap alone.
3. Once real glider data is in and positioned correctly, the CTD's synthetic relocation step in
   `ctd_data` (the `_rng.uniform(...)` block that fakes a Barkley Sound position for a
   San-Diego-based cast) can be dropped too, once/if a real, correctly-located CTD cast is
   available — same `load_platform_data` call, just without the relocation lines after it.
4. If a real glider track has many more points than the synthetic 500-point sawtooth, sanity-check
   `click_plot`'s `_TOLERANCE_DEG = 0.05` proximity radius — it's a flat degrees-based hit-test
   against every point in `glider_df`, not a real nearest-line-segment test, and was tuned against
   the synthetic track's spacing.
5. `plot_glider_curtain`/`plot_ctd_profile` themselves need no changes to work in the app — they're
   called with the same signature the notebook already uses (`df`, `variable_col`,
   `variable_label=...`, `color_scale=...`/`line_color=...`). If your team's real-data work added
   new parameters to those functions (e.g. `bathymetry=...`, which both already support), just add
   the matching keyword args to the `plot_ctd_profile(...)`/`plot_glider_curtain(...)` calls in
   `click_plot`.

## Known gap: bathymetry (checked 2026-08-28)

`Glider_Curtain_Plot.ipynb`'s real-data glider config has had `"USE_BATHYMETRY": True` since its
first commit — its curtain plot drapes the glider track over real Barkley Sound seafloor
(`Barkley_Sound_Bathymetry.nc`) via a `load_bathymetry()` function. **That loader only exists
inline in the notebook — it was never factored into `glider_lib.py`.** `glider_lib.py` does have
the two functions that *consume* an already-loaded bathymetry dict
(`clip_and_decimate_bathymetry`, `add_bathymetry_surface`, both already wired into
`plot_glider_curtain`'s `bathymetry=` parameter), just not the loader that produces that dict from
a file. So today, `click_plot` in the app could pass `bathymetry=...` to `plot_glider_curtain(...)`,
but there's nothing importable to produce it — this is a preexisting gap in `glider_lib.py`, not a
regression, and it means the app **cannot yet show the bathymetry-draped curtain the notebook can**
until `load_bathymetry` (and its `BATHY_ALIASES` dict) is ported over the same way the other loader
functions were.

**Also worth confirming with whoever has the working real-data setup:** this repo's copy of
`Glider_Curtain_Plot.ipynb` still has `CONFIG["GLIDER"]["DATA_PATH"] = "path/to/glider_data.csv"` —
a placeholder, not a real file path. If a real path is being used successfully elsewhere, it
hasn't been committed to this file/branch yet, so the exact `COLUMN_MAP` needed for the real
glider file isn't yet visible in the repo.

## Design constraints — do not break these when migrating

These came from real, previously-shipped bugs (full history in the pairing-session notes, not
duplicated here) — worth respecting rather than rediscovering:

- **`map` must never re-run after initial load.** It depends only on `config`/`ctd_data`/
  `glider_data`/`about_md` — nothing click-volatile (`selection_plot`, `get_plot_closed`, etc.).
  If a future edit makes `map` reference anything that changes per-click, the map will rebuild
  and flash/reset on every click.
- **Two separate import cells on purpose** (`nb_imports` vs. `plot_fn_imports`). If you add a new
  `glider_lib` import that only `click_plot` needs, put it in `plot_fn_imports`, not `nb_imports`
  — importing something new into `nb_imports` and reloading it also reruns `map` (since `map` is
  downstream of `nb_imports`), which can break an already-mounted map widget in a live browser tab.
- **Don't build `MapOptions(bounds=..., fit_bounds_options=...)`** for the initial camera — it's
  unreliable in this MapLibre widget (computed against a zero-size detached container before the
  map is attached to the DOM). Use `center=(lon, lat), zoom=N` instead, as `map` already does.
- **Never interpolate a raw `plotly.graph_objects.Figure` into an f-string / `mo.Html(...)`** —
  wrap it in `mo.as_html(...)` first (`click_plot` already does this). A raw Figure's `str()` is
  its internal repr, not HTML, and renders as inert text.
- **Don't rely on inline `onclick`/`onerror` HTML attributes, or `<script>` tags, inside
  `mo.Html(...)` content** — marimo's renderer strips/ignores both. Any interactivity in this app
  needs to go through real marimo primitives (`mo.ui.*`, `mo.state`), which is why the plot panel
  uses `mo.sidebar` + `mo.ui.button` rather than hand-rolled CSS/JS (that was tried across many
  earlier iterations and never worked reliably).
- **The `mo.sidebar`-based popup architecture is considered closed/stable — don't rearchitect
  it.** It replaced five earlier CSS-positioning approaches that all had rendering bugs; it's been
  user-confirmed working end-to-end.

## Known open issue

The plot panel's "✕ Close" button does not reliably close the panel (confirmed in a real browser,
not just automated tests) — the button's Python-side logic matches marimo's documented pattern for
this (`mo.ui.button(on_click=..., on_change=...)` + `mo.state(..., allow_self_loops=True)`), so
this looks like an environment/event-delivery issue rather than a code bug, but it's unresolved.
**Workaround already in place and accepted as fine for now:** clicking anywhere else on the map
that isn't near a marker/track point clears the panel anyway (a side effect of the hit-test
missing, not the close button itself).

## Data status (as of this doc)

- **CTD:** real measured cast (`NE_San_Diego_Trough_Aug_2022.csv`, `Salt2`/`Depth`), but at a
  **fake position** (randomly placed inside Barkley Sound — its true location is San Diego).
- **Glider:** fully synthetic (`generate_sample_glider_data`) — this is the piece your team's real
  trajectory/curtain-plot work is meant to replace, per "Migrating real glider data" above.
