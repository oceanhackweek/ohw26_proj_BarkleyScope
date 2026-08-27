# Real-Time Glider Web App — Summary of Changes

Adds a live map/curtain view of active C-PROOF gliders, built as a marimo app.
(Submitted separately as [PR #10](https://github.com/oceanhackweek/ohw26_proj_BarkleyScope/pull/10); this file documents the change on `main`.)

## `final_notebooks/glider_lib.py`

Added `load_active_gliders(mode="live", variable_col="temperature", active_days=1, min_points=2)`.

- Loads every C-PROOF glider deployment with data in the trailing `active_days` window.
- `mode` picks the data source:
  - `"live"` (default) — reads straight from C-PROOF's own server via `data/cproof_https.py`'s
    `snapshot()`. Runs ahead of the IOOS DAC archive, which has been caught missing a deployment
    entirely or stopping days early, so this is the right source for a "what's in the water right
    now" view. Refreshed hourly.
  - `"realtime"` / `"delayed"` — reads the netCDF archive via `data/cproof_glider.py`'s
    `read_archive()`. `"realtime"` is a daily-refreshed snapshot committed to git (can be stale
    between pulls); `"delayed"` is the calibrated historical record, months to years behind. Use
    these only when the archived/QC'd view is wanted specifically, or to work offline.
- Reshapes the source's long multi-deployment DataFrame into a list of per-deployment DataFrames
  standardized to `Longitude`/`Latitude`/`Depth`/`Time`/`<variable_col>`. The first three columns
  match `load_platform_data()`'s own schema, so existing plotting code (`plot_glider_curtain()`,
  the map/click-plot cells) doesn't need to know which loader or mode produced a given DataFrame.
- "Active" means "has an observation inside the last `active_days` days" — a convention this
  function imposes, since neither data source has its own deployment-status flag.
- That window bounds the **observations returned**, not just which deployments qualify. `snapshot()`
  uses `recent_days` only to pick deployments and then hands back each one's full history, so
  without this cut an "active in the last day" map drew three-week tracks, and a glider whose newest
  in-box fix was days old still drew a line whose endpoint read as its current position. A
  deployment with nothing inside the window now drops out rather than showing a stale track.
- Drops deployments with fewer than `min_points` valid observations (need at least 2 to form a
  map line).
- Returns: `[{"deployment": "dfo-eva035-20260615", "glider": "eva035", "df": <DataFrame>}, ...]`

## `final_notebooks/Real-Time_Glider_WebApp.py`

New marimo app that renders the map + glider curtain from `load_active_gliders()`'s output.

Clicking a track selects it: the whole transect (every gap-split segment of that deployment, plus
its markers) turns `SELECTED_COLOR` orange while the rest stay `LINE_COLOR` slate. The highlight is
a data-driven MapLibre paint expression keyed on each feature's `deployment` property, pushed by the
`glider_highlight` cell via `set_paint_property` — the `map` cell is never rebuilt, since it must
never re-run once the widget is live.

## `pyproject.toml`

New project-level marimo config. Sets `[tool.marimo.runtime] auto_instantiate = true` so every
cell in the app runs on open (map and glider tracks render immediately, no manual stepping
required). This applies to every marimo notebook in the repo, since marimo finds this file by
walking up from whichever notebook is opened.
