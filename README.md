# ohw26_proj_BarkleyScope

## Project Name

**BarkleyScope** — an interactive map of what is being measured in and around Barkley
Sound, BC.

## One-line Description

A marimo + MapLibre web app that puts C-PROOF glider tracks (live and historical),
satellite sea surface temperature, and the Ocean Networks Canada instrument sites in
Folger Passage on one map, with click-through plots of the underlying profiles.

## The app

`final_notebooks/Real-Time_Glider_WebApp.py` — a marimo notebook running a MapLibre map,
with a switch at the top of the map between two views.

**Real-time.** Every C-PROOF glider with a fix in the trailing `ACTIVE_DAYS` window (one
day by default), read from C-PROOF's own server and current to the hour. One point per
observation; a red dot marks the last recorded position, and clicking it gives the time.
Click a track for a 3D temperature curtain plot in the side panel. These values are **not
calibrated** — a gross-range screen is the only filter applied.

**Historical.** Every Southern Line and SVI Shelf deployment with a gridded, calibrated
file: 26 deployments, 28,452 profile positions from 2024-02 to 2026-08, coloured by
deployment date. Plus the eight moorings and buoys that have a day-of-year temperature
climatology — click one for its plot.

Both views carry the two Folger Passage sites as fixed reference points and a satellite SST
layer with a date picker. Nothing is drawn *between* observations in either view, because
neither product says what happened there.

### How it works

The app reads small precomputed files, not the archives behind them. Committed geometry is
3.4 MB against the ~10.7 GB it is derived from, so a page load is cheap and needs no
network except for the live glider fetch and the basemap tiles.

1. `glider_lib.load_active_gliders()` fetches the live glider timeseries at page load,
   through `data/cproof_https.py`, and caches the netCDF under `data/cproof/` with
   `If-Modified-Since` — reruns cost one 304 per file.
2. Everything else is read from a committed GeoJSON: the historical tracks, the Folger
   sites, the climatology sites, the SST layer.
3. The map is built once and never rebuilt. View switches, selection highlights and SST
   dates are pushed as MapLibre property updates, so clicking never re-renders the map.
4. Clicks are hit-tested in Python against the loaded data, and the side panel is built
   from whatever was hit — a curtain plot for a glider, a climatology image for a site.

### Data, and how often it refreshes

| Source | What the app uses | Refresh |
|---|---|---|
| [C-PROOF](https://cproof.uvic.ca/gliderdata/deployments/) live server | Real-time glider timeseries — the real-time view | C-PROOF publishes hourly; the app fetches on every page load |
| C-PROOF gridded `_grid_adjusted.nc` | 26 calibrated deployments → `glider_adjusted_tracks.geojson` — the historical view | Manual: `fetch_grid_adjusted.py`, then `build_historical_tracks.py` |
| [Ocean Networks Canada](https://data.oceannetworks.ca) | 7 mooring records → day-of-year climatologies and the site markers | Manual: ONC download, then `onc_climatology.py --all`, then `build_climatology_sites.py` |
| [DFO / MEDS](https://www.meds-sdmm.dfo-mpo.gc.ca) buoy C46206 | La Perouse Bank surface record, 1988–2022 → its climatology | Manual, and the record itself ends 2022 |
| NOAA CoastWatch ERDDAP | Geo-polar blended SST, newest 7 days → `sst_barkley_layer.geojson` | GitHub Action, **manual dispatch only**; the product publishes ~2 days behind |
| Esri Ocean | Basemap tiles | Live, per tile request |

One scheduled job runs unattended: `watch-glider-transects.yml`, daily at 00:00 UTC, which
records any new glider transect in the study box and commits the manifest. The SST job has
its schedule commented out deliberately — it is dispatched by hand.

Study box: longitude **−126.80 to −124.50**, latitude **47.85 to 49.36**.

The IOOS Glider DAC archive (`data/cproof_glider.py`, `cproof_glider_realtime.nc`) is
**not** what the app reads. It stays as an alternative `MODE` for working offline or
wanting the quality-controlled record; the live server runs days ahead of it.

### Running it

Open it through the JupyterLab "marimo" launcher tile, not the file browser. Once per
account, install the app's UI packages into the *user* site so they survive a server
restart:

```bash
python -m pip install --user maplibre==0.3.6 anywidget plotly
```

Skipping that step is what used to make the app open blank — the kernel runs in the shared
conda base env, which marimo treats as read-only and which is rebuilt from the image on
every restart. `final_notebooks/MARIMO_APP_STATUS.md` has the full diagnosis.

For a presentation, `final_notebooks/serve_app.sh` serves the app with no code cells or
editor chrome and prints a link (`/user/<you>/proxy/absolute/2718/`). It is proxied through
your own hub server, so it is live only while both are running, and it is not public.

## Data not in the repo

Raw records are gitignored; the committed artefacts are the small map-ready files the app
reads. To rebuild any of those from scratch you need the source data locally:

* `data/glider_adjusted/` — 10.68 GB of gridded C-PROOF missions. Mirrored to a GitHub
  release by `data/upload_glider_adjusted.sh`, or re-fetch with `fetch_grid_adjusted.py`.
* `data/folger/`, `data/barkley/`, `data/buoys/` — the ONC and DFO records behind the
  climatologies, downloaded by hand from each provider.
* `final_notebooks/Glider_Curtain_Plot.ipynb` additionally expects two local files:
  `Barkley_Sound_Bathymetry.nc` (GEBCO_2026; its coverage stops ~65 km short of Barkley
  Sound, an open issue) and `NE_San_Diego_Trough_Aug_2022.csv` (an example CalCOFI cast).
  With `CONFIG["USE_SAMPLE_DATA"] = True`, the default, it runs on synthetic data instead.

## Folder structure

* `final_notebooks` — the app, the shared plotting library (`glider_lib.py`), the curtain
  plot and map notebooks, and the design/status docs for each.
* `data` — one subfolder and one reader per data source, each with its own README. Large
  files are gitignored; the committed artefacts are the small map-ready ones the app
  actually reads: `glider_adjusted_tracks.geojson` (1.2 MB), `sst_barkley_layer.geojson`
  (2.1 MB), `climatology_sites.geojson` and `folger_sites.geojson` (a few kB each).
* `contributor_folders` — per-person scratch space, to keep merge conflicts down. One
  exception the app depends on: `Dwight/climatology/` holds the eight climatology plots the
  historical view opens, and `Dwight/onc_climatology.py` builds them.
* `viz_notebooks` — visualization experiments (empty so far).

Do not commit large datasets. Keep a local copy in the same relative path instead, and add
it to `.gitignore`.

### Where the details are written down

Each pipeline documents itself; these are the ground-truth files, kept current with
measured numbers rather than estimates.

| Doc | Covers |
|---|---|
| `data/README.md` | Both glider archives, the live server reader, the gridded mission set, and the precomputed map tracks |
| `data/sst/README.md`, `data/sst/INTEGRATING_THE_LAYER.md` | The SST pipeline, from download to the layer the app draws |
| `data/folger_taylor/README.md`, `METHODS.md` | The Folger Passage anomaly pipeline |
| `final_notebooks/MARIMO_APP_STATUS.md` | How the app is put together, how to run it, and the constraints not to break |
| `final_notebooks/REALTIME_WEBAPP_SUMMARY.md` | The real-time loading path |
| `final_notebooks/GLIDER_TRACK_CHANGES.md` | What the map draws, what it refuses to draw, and why |
| `final_notebooks/VOILA_TROUBLESHOOTING.md` | Why the ipyleaflet + Voila path was abandoned |

## Collaborators

| Name                | Role                |
|---------------------|---------------------|
| Taylor Borgfeldt      | data mining |
| Ben Limer             | data visualization |
| Dwight Owens          | data mining |
| Anais Gentilhomme     | data mining |
| Shannon McClish       | data visualization |
| Carter Burtlake       | floater |

## Planning

* Initial idea: "short description"
* Ideation Slide: [Add link](https://docs.google.com/presentation/d/1_KLEDpLLvtKpH3awDlZRAiOKuHzbEti4CWmhEykuCG8/edit?slide=id.g3f85357d4e2_2_0#slide=id.g3f85357d4e2_2_0)
* Slack channel: local-knowledge-app
* Final presentation: Add link

## Background

## Goals

## Workflow/Roadmap

## Results/Findings

## Lessons Learned

## References
