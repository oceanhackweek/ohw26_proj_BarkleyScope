# ohw26_proj_BarkleyScope

## Project Name

**BarkleyScope** — an interactive map of what is being measured in and around Barkley
Sound, BC.

## One-line Description

A marimo + MapLibre web app that puts C-PROOF glider tracks (live and historical),
satellite sea surface temperature, and the Ocean Networks Canada instrument sites in
Folger Passage on one map, with click-through plots of the underlying profiles.

## The app

`final_notebooks/Real-Time_Glider_WebApp.py`. Two views, switched from the control at the
top of the map:

* **Real-time** — every C-PROOF glider deployment with an observation inside the trailing
  `ACTIVE_DAYS` window, read straight from C-PROOF's own server (refreshed hourly, and
  days ahead of the IOOS DAC archive). Drawn as one point per observation, not a line:
  nothing in the product says what happened between two fixes, so nothing is drawn there.
  Click a deployment to select it — its points turn orange and a 3D temperature curtain
  plot opens in the sidebar. Real-time data is **not calibrated**; only a gross-range
  screen is applied.
* **Historical** — every deployment on the Southern Line and the SVI Shelf from Bamfield
  line that has a gridded adjusted file: 26 deployments, 28,452 profile positions,
  2024-02 through 2026-08, coloured by deployment date. Clicking does nothing in this view
  yet.

Both views show **Folger Deep** and **Folger Pinnacle** as fixed reference points, and a
satellite **SST** fill layer with a date picker.

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

## Datasets

| Source | What we take | Where it lives |
|---|---|---|
| [C-PROOF](https://cproof.uvic.ca/gliderdata/deployments/) | Real-time glider timeseries, and the gridded `_grid_adjusted.nc` mission set behind the historical view | `data/cproof_https.py`, `data/fetch_grid_adjusted.py` |
| [IOOS Glider DAC](https://gliders.ioos.us/erddap) | The archived, quality-controlled glider record | `data/cproof_glider.py` |
| [Ocean Networks Canada](https://data.oceannetworks.ca) | Folger Passage temperature, Pinnacle (25 m, 2011–2026) and Deep (98 m, 2016–2026) | `data/folger/`, `data/folger_taylor/` |
| NOAA CoastWatch ERDDAP | Satellite SST over the study box | `data/sst/` |

Study box: longitude **−126.80 to −124.50**, latitude **47.85 to 49.36**.

Two files `final_notebooks/Glider_Curtain_Plot.ipynb` expects are **not** committed — keep
your own local copy in the same folder:

* `Barkley_Sound_Bathymetry.nc` — GEBCO_2026 grid used as the curtain-plot basemap. Its
  coverage currently stops ~65 km short of Barkley Sound itself (open issue).
* `NE_San_Diego_Trough_Aug_2022.csv` — example CalCOFI CTD cast for the 2D profile plot.

With `CONFIG["USE_SAMPLE_DATA"] = True` (the default) that notebook runs standalone on
synthetic data and neither file is required.

## Folder structure

* `final_notebooks` — the app, the shared plotting library (`glider_lib.py`), the curtain
  plot and map notebooks, and the design/status docs for each.
* `data` — one subfolder and one reader per data source, each with its own README. Large
  files are gitignored; the committed artefacts are the small map-ready ones
  (`glider_adjusted_tracks.geojson`, `folger_sites.geojson`, `sst_barkley_layer.geojson`).
* `contributor_folders` — per-person scratch space, to keep merge conflicts down.
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
