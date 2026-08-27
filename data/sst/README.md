# Satellite SST for BarkleyScope

Gridded sea surface temperature over Barkley Sound, from download through to the map
layer the app draws.

This document is meant as ground truth: every script, what it reads, what it writes, and
how one feeds the next. Numbers quoted were measured on the files in this folder on
**2026-08-27**, not estimated.

---

## The pipeline at a glance

```
                    NOAA ERDDAP  (coastwatch.pfeg.noaa.gov)
                             |
                             |  fetch_sst_barkley.py          [NETWORK]
                             v
                 ../sst_barkley_realtime.nc                   THE DELIVERABLE
                  7 days, 32x48 grid, 45 kB
                             |
          +------------------+-------------------+
          |                  |                   |
          |  verify_sst.py   |                   |
          |  48 checks       |                   |
          |  [gate]          |                   |
          v                  v                   v
    (pass/fail)        barkley_sst.py       preview_panels.py
                       THE LIBRARY          -> preview_week*.png
                             |                  (offline sanity check)
                             |
          land_mask_1km.nc --+  <- make_land_mask.py <- Natural Earth 10m
          (clips cells to      |     (cartopy's cached coastline; no network)
           the coastline)      |
                               v
                    cell_polygons(clip=True)
                       GeoJSON per day
                               |
              +----------------+----------------+
              |                                 |
      map_layers.py                      preview_map.py
      THE REGISTRY                       -> barkley_sst_map.html
      collect() -> sources/layers        (standalone, no widget kernel)
              |
       +------+---------------------+
       |                            |
       v                            v
  sst_map_test.py            export_layer.py
  (our marimo app,           |
   imports this folder)      v
                       ../sst_barkley_layer.geojson    <-- HAND THIS OVER
                       2.14 MB, 8,428 features, self-contained
                             |
                             v
                       THE SHARED APP
                       (needs nothing from data/sst/)
```

**The file to hand over is `data/sst_barkley_layer.geojson`.** Everything above it is how
that file gets made.

Everything below the fetch runs **offline**, including the mask. Only
`fetch_sst_barkley.py`, `compare_resolutions.py` and `same_day_check.py` touch the
network.

---

## Stage 1 — Download

### `fetch_sst_barkley.py` **[needs network]**

Pulls a rolling window of gridded SST from NOAA's ERDDAP and writes the archive.

| | |
|---|---|
| **Reads** | NOAA ERDDAP griddap, `coastwatch.pfeg.noaa.gov` |
| **Writes** | `../sst_barkley_realtime.nc` (one level up, in shared `data/`) |
| **Run** | `python fetch_sst_barkley.py` · `--force` · `--verbose` |
| **Exit** | `0` success or already-current · `1` any failure |

Configuration lives in one block at the top. `ACTIVE_SOURCE = 'blended5km'` selects from
three presets (`oisst`, `blended5km`, `mur1km`); each preset carries the quirks that
reach into the query itself — variable name, whether there is a vestigial depth axis,
whether longitudes run 0–360. Switching products means changing that one constant.
`N_DAYS = 7` is *seven newest available steps*, not seven calendar days — satellite
products publish days behind, so "today minus 7" would return a mostly empty file.

Two operational properties it was written for:

- **Idempotent.** It first asks the server what exists and compares against what is on
  disk. If they match it exits `0` without touching the network, so running it hourly is
  harmless. It compares the `{date: source}` mapping, not just dates, so a day upgraded
  from preliminary to final still counts as a change.
- **Fails safe.** On any network error it exits `1` and leaves the previous archive
  untouched — no partial write, no deletion. A consumer keeps serving stale-but-valid
  data rather than being handed a half-written file. The old file is replaced only after
  a complete fetch, via an atomic write.

> Its `USAGE` docstring referred to `fetch_oisst_barkley.py` — a name left over from
> before the OISST → blend switch. Corrected 2026-08-27.

### The archive — `../sst_barkley_realtime.nc`

The one deliverable. Everything downstream reads this file and nothing else.

| | |
|---|---|
| Days | 7 — currently **2026-08-18 → 2026-08-24** |
| Grid | 32 lat × 48 lon at 0.05° (≈ 5.6 × 3.7 km per cell) |
| Ocean cells | 1,220 per day |
| Size | 45 kB |
| Variable | `analysed_sst`, plus a `source` coordinate per day |

It lives in `data/` rather than `data/sst/` so a map app's config resolves every dataset
from one directory, matching its sibling `cproof_glider_realtime.nc`.

**It is a snapshot.** Nothing refreshes it automatically. As of 2026-08-27 it is three
days behind — roughly one day of that is the product's own publishing lag, the rest is
that no scheduled job exists yet.

---

## Stage 2 — Verify

### `verify_sst.py`

The gate between a fetch and trusting the result. Run it after any fetch.

| | |
|---|---|
| **Reads** | the archive, and `land_mask_1km.nc` |
| **Writes** | nothing — prints PASS/FAIL |
| **Run** | `python verify_sst.py` |
| **Exit** | `0` all pass · `1` any failure |

**48 checks, all passing.** Deliberately the same shape as `data/verify_archives.py`,
which does this job for the glider archives. It targets the failures that would quietly
poison a map rather than crash it:

- **Cell geometry** — centres reconstructed from edges. A half-cell offset produces a map
  that looks fine until you notice water on land.
- **Coverage of `REGION`** — SST that stops short leaves a blank margin nobody sees until
  a presentation.
- **GeoJSON validity** — rings closed, properties present. MapLibre silently *drops*
  malformed features instead of raising.
- **Clipping, both directions** — nothing containing water was dropped, nothing that is
  entirely land was kept. These two use deliberately opposite tolerances so each only
  fires on an unambiguous error.
- **Flagged water** — the Strait of Georgia cells must stay flagged.
- **Colour determinism** — the same temperature must be the same colour in the previews
  and in the live map.

---

## Stage 3 — The library

### `barkley_sst.py`

Every consumer goes through here, so the awkward parts are solved once. The SST
counterpart to `cproof_glider.py` and deliberately the same shape. Returns an xarray
`Dataset` rather than a DataFrame, because SST is a grid and flattening it to rows loses
the thing that makes it a grid.

| | |
|---|---|
| **Reads** | the archive, `land_mask_1km.nc` |
| **Writes** | nothing — it is a library |

**Constants:** `SST_ARCHIVE`, `LAND_MASK`, `BOX`, `COLOR_RANGE` (10–20 °C, fixed
year-round), `THERMAL_STOPS`, `SOURCE_CAVEAT`.

**Functions:**

| Function | Purpose |
|---|---|
| `read_grid(path=None, last_days=None)` | Open the archive |
| `dates(ds)` | `['2026-08-18', …]` |
| `cell_edges(centres)` | N centres → N+1 edges. **Nothing should reimplement this.** |
| `flag_disconnected(ds)` | Water unreachable from the open Pacific |
| `water_mask(path=None)` | The ~1 km mask, cached per process |
| `cell_polygons(ds, date, decimals=3, clip=False)` | **The output that feeds every map** |
| `color_stops()` / `color_for(v)` | The shared colour ramp |
| `summary(ds)` | One line per day, for logs |

### The four awkward parts it solves

1. **Cells are stored as centres and drawn as rectangles.** Span centre-to-centre and the
   whole field lands half a cell off — far enough here to put water on land, subtle
   enough to survive review. `cell_edges()` does it correctly.

2. **Some water is not the water you think it is.** Five warm cells (~19 °C) at the
   north-east corner are Strait of Georgia water, on the *far* side of Vancouver Island.
   `flag_disconnected()` finds them by connectivity, not a hand-drawn polygon, so it keeps
   working if the box, product or resolution changes. They are flagged and muted on the
   map, never deleted.

3. **`source: 'final'` does not mean what it usually means.** The blend publishes once, so
   every step is labelled `final` purely because the preset has a single entry. It is a
   near-real-time analysis about two days behind, *not* a reprocessed quality-controlled
   record. Caption with `SOURCE_CAVEAT`.

4. **The product's land mask is coarser than the coastline.** Measured against a 1 km
   coastline, **5.6% of the drawn area was land**, and **16 cells were land entirely**
   yet still reported a temperature. `clip=True` fixes the *footprint*; the value is
   untouched and still a 5 km measurement. See Stage 4.

   Port Alberni is the instructive case: it sits at the head of a fjord about a kilometre
   wide, so its 20.5 km² cell is mostly hillside. Clipping keeps it but reduces it to
   **6.5 km² in two parts** — the inlet channel — rather than discarding a real
   measurement or painting the valley walls.

   The same coarse mask errs in **both** directions: as well as reporting temperature over
   land, it withholds it from genuine nearshore water, which renders as white notches
   along the shore in `preview_week_sound.png`. Clipping cannot recover those -- the
   product never published a value there. Whether to fill them from a neighbour or leave
   them honestly blank is still undecided.

> **Verified not to be a projection or alignment problem.** Sliding the SST water-mask
> against the 1 km mask across ±3 cells, agreement peaks at **exactly zero offset
> (95.4%)**; every non-zero shift is worse. Landmark spot-checks agree — Folger Pinnacle,
> Bamfield, Cape Beale and open Pacific all resolve to water, Mt Arrowsmith to land.

---

## Stage 4 — The coastline mask

### `make_land_mask.py`

Run **once**; the output is what matters.

| | |
|---|---|
| **Reads** | Natural Earth 10 m land polygons, from cartopy's cache — **no network** |
| **Writes** | `land_mask_1km.nc` — 49 kB, 162 × 241 at 0.01°, 74.9% water |
| **Run** | `python make_land_mask.py` |

A finer mask cannot come from the 5 km product itself. It is rasterised from Natural
Earth's 10 m land polygons, which cartopy keeps in `~/.local/share/cartopy` (already
present, on the persistent volume). Six polygons overlap this box; the rasterisation
takes under a second. A cell is water unless its centre falls inside land — centre-based
to match how `cell_polygons()` selects sub-cells, so the two cannot disagree at a
boundary.

0.01° is chosen to give five sub-cells across each 0.05° SST cell. Finer would follow the
shore more closely but multiplies the polygon count the map carries, for detail below
what a 5 km measurement can justify.

**Result of clipping:** land inside the drawn area **5.6% → 0.1%**, 16 all-land cells
dropped, payload **2.03 → 2.20 MB** (+8%). The small increase is because adjacent water
pixels are merged into runs rather than emitted individually — a mean of **1.15
sub-polygons per cell**, max 5. Geometry becomes `MultiPolygon`. 1,010 of 1,204 cells are
open water and keep their full rectangle; 194 are clipped.

**Caveat:** Natural Earth 10 m is a generalised coastline, not a survey — expect a few
hundred metres of error along a complex shore. A large improvement on the product's own
mask, not ground truth.

> An earlier version derived this mask from MUR L4's land mask. The two agree to within
> 2.4% of cells, but MUR meant keeping a 310 kB fetched file alive purely to rebuild from,
> and its 1 km raster could not resolve Alberni Inlet — it called the whole cell land.

---

## Stage 5 — The map layer

### `map_layers.py` — the registry

The seam between several people's datasets and one app. Each dataset contributes **one
entry in `LAYERS` and one builder function**; nobody edits the app's `map` cell.

| | |
|---|---|
| **Reads** | archive (via `barkley_sst`), `../cproof_glider_realtime.nc` (via `cproof_glider`) |
| **Writes** | nothing — returns objects |

```python
sources, layers, groups, skipped = map_layers.collect(CONFIG_MAP)
plan = map_layers.visibility_plan(groups, enabled={...}, steps={...})
```

Currently produces **10 layers from 10 sources**: 7 SST day-layers + 3 glider deployment
lines, drawn in that order so tracks sit on top of the fill.

Two rules the app's architecture forces (see `final_notebooks/MARIMO_APP_STATUS.md`):

1. **Everything is baked into the style at construction.** The widget's post-construction
   `add_source`/`add_layer` calls are transient comm messages that do not survive a page
   reload. `collect()` therefore returns every source and layer up front, for one
   `construct_basemap_style(...)` call. One SST day is baked visible — the newest — so a
   reconnect still shows a working map.
2. **Showing/hiding is separate from building.** The `map` cell must never re-run;
   rebuilding the widget live can black-screen the map. `visibility_plan()` is a pure
   function of the control state, applied from a cell *downstream* of the map via
   `MapWidget.set_visibility()`.

A builder returns `None` when its data file is absent and `collect()` drops it with a
reason rather than raising — one missing file disables one layer, not the whole app.

Config lives in `DEFAULT_CONFIG`; `CLIP_TO_COAST: True` is what turns on Stage 4.

### `sst_map_test.py` — the app

marimo + MapLibre. A copy of `final_notebooks/Web_App_test.py`, structurally faithful,
with the hand-listed layers replaced by the registry. **The original is not modified.**

Open it through the JupyterLab **marimo launcher tile**, not the file browser (which
opens a text editor). Note the launcher runs `marimo edit --sandbox`, which builds an
isolated environment from the PEP-723 header at the top of the file — so that header must
list everything reached *transitively*, including `xarray`, `netCDF4` and `requests`.

### `export_layer.py` — the handoff

| | |
|---|---|
| **Reads** | the archive, the mask (via `barkley_sst`) |
| **Writes** | `../sst_barkley_layer.geojson` — 2.14 MB, 8,428 features |
| **Run** | `python export_layer.py` · `--days 3` · `--pretty` |

`map_layers.py` hands our app live Python objects, which requires that app to import this
folder. That is right when both live in one repo; it is not something you can hand
someone. This writes the same layer as **one file** instead.

All seven days live in a single `FeatureCollection`, each feature tagged with its `date`,
so the consumer filters one property rather than juggling seven sources:

```javascript
filter: ["==", ["get", "date"], "2026-08-24"]
```

Geometry is already clipped to the coastline, so the consumer needs no land mask, no
xarray, no netCDF reader, and nothing from `data/sst/`.

Per-feature properties: `sst` (°C), `lat`, `lon`, `flagged`, `date`.

Styling metadata travels in the collection's top-level `properties` — renderers ignore
it, but it means the layer looks the same in the shared app as in every figure here:

| Key | Use |
|---|---|
| `maplibre_fill_color` | A ready-made `interpolate` expression — paste it in |
| `color_range` | `[10.0, 20.0]` °C, fixed year-round |
| `dates` / `default_date` | What to offer, and what to show first |
| `flag_note` | Render `flagged=true` muted, not hidden — 21 features |
| `source_caveat` | The caption this data must carry |

**Regenerate it after every fetch.** `verify_sst.py` checks the export against the archive
and fails if the two have drifted. The scheduled workflow below does both, so in practice
the copy on `main` is already current.

The file **is** committed. It compresses to about 0.14 MB, so a daily refresh costs roughly
50 MB of history a year, and having it in the repo means anyone -- including an app that
cannot run this code -- can read it straight from a raw GitHub URL.

---

## Side branches

These do not feed the app. They exist as evidence and as fast sanity checks.

| Script | Network | Reads | Writes |
|---|---|---|---|
| `preview_panels.py` | no | archive | `preview_week.png`, `preview_week_sound.png` |
| `preview_map.py` | no | archive, mask, glider | `barkley_sst_map.html` (2.6 MB) |
| `compare_resolutions.py` | **yes** | ERDDAP | `compare_*.nc` |
| `compare_panels.py` | no | `compare_*.nc` | `compare_resolutions.png` |
| `same_day_check.py` | **yes** | ERDDAP | `sameday_*.nc` |

`compare_panels.py` runs on the `.nc` files `compare_resolutions.py` fetches. **Those
files are not kept in the repo** — they are cached downloads, and the conclusions they
support are in the table below. Run `compare_resolutions.py` first to rebuild them.

`preview_panels.py` is the quickest honest answer to "did the fetch work and does the
field look sane" — a week of small multiples, no server, no widget kernel.
`preview_map.py` renders from the *same* `cell_polygons()` output and colour ramp as the
platform map, so it is a faithful stand-in when the widget stack is unavailable.

> `compare_resolutions.py` and `same_day_check.py` both imported `fetch_oisst_barkley`,
> a module renamed during the OISST → blend switch, so neither could run — awkward, since
> the product-choice evidence rests on them. Repaired 2026-08-27; both import cleanly.
> Running them still needs the network.

---

## Which product, and why it is not the sharpest one

Chosen by measurement, not specification.

| Product | Resolution | Cells in the sound | Spatial std in the sound | Lag |
|---|---|---|---|---|
| OISST v2.1 | 0.25° | **2** | — | ~5–16 days |
| **Geo-polar blend** | **0.05°** | **57** | **1.087 °C** | **~2 days** |
| MUR L4 | 0.01° | 1,220 | 0.159 °C | ~1 day |

OISST puts *two* ocean cells inside Barkley Sound — a cell there is larger than the sound,
so Bamfield, Cape Beale and Folger Pinnacle collapse into the same pair.

MUR looks like the obvious choice and is the trap. Measured on the same day (2026-08-24)
inside the sound it carries **about a seventh** of the blend's spatial variability across
21× as many pixels, and disagrees with it on the mean by ~1 °C. It is a gap-filled
analysis: near this coastline it *fills* rather than measures, so its detail is smooth
fiction. The blend sits where resolution still tracks signal.

**Re-run `same_day_check.py` before anyone proposes switching on resolution alone** — once
its import is fixed.

### A note on the user agent

An earlier trial recorded the blend "returning empty" over this box and treated the
product as doubtful. It was not empty — the request was *refused*.
`coastwatch.pfeg.noaa.gov` redirects to `coastwatch.noaa.gov`, which answers the default
`python-requests` user agent with **403 Forbidden**. `fetch_sst_barkley.HEADERS` sets a
descriptive one. **Keep it.** That single misdiagnosis cost the project the right product
for a week.

---

## What this data is not

**Not a measurement of the water.** This is an L4 analysis — a model blends satellite
passes into a gap-free field, so a value near the coast is partly inferred. It is a skin
temperature of the top ~1 mm to ~1 m, not what a CTD at depth reports.

`data/folger/` holds hourly Folger Pinnacle and Folger Deep temperature back to 2011, and
the satellite cell sits ~1.3 km from the sensor. **Comparing them is the check that tells
you how far to trust this product on this coast. It has not been done yet, and it needs
no network.**

---

## Is every file used?

Nothing here is inert. Each file is either on the path from download to handed-over layer,
or it is a tool you run deliberately — and the difference is stated rather than implied.

**On the critical path** — break one and the layer stops being produced or trustworthy:

| File | Its job | Consumed by |
|---|---|---|
| `fetch_sst_barkley.py` | Downloads the archive | run by hand / cron |
| `make_land_mask.py` | Builds the coastline mask | run once |
| `land_mask_1km.nc` | The mask | `barkley_sst.cell_polygons(clip=True)` |
| `barkley_sst.py` | Reads, flags, clips, colours | every consumer below |
| `map_layers.py` | Builds MapLibre sources/layers | `sst_map_test.py` |
| `export_layer.py` | **Writes the handed-over file** | run after every fetch |
| `verify_sst.py` | 59 checks; the gate on all of it | run by hand |
| `sst_map_test.py` | Our marimo app | opened in marimo |
| `README.md`, `.gitignore` | This document; ignore rules | — |

**Deliberate tools, not pipeline** — nothing imports them, and nothing breaks if they are
not run. They are here because each answers a question that recurs:

| File | The question it answers | Note |
|---|---|---|
| `preview_panels.py` | "Did the fetch work and does the field look sane?" | Offline, seconds, no widget kernel |
| `preview_map.py` | "What does the layer actually look like?" | Standalone HTML, same ramp and geometry as the app |
| `compare_resolutions.py` | "How many pixels does each product put in the sound?" | **Needs network**; writes `compare_*.nc` |
| `compare_panels.py` | "Does the finer product actually show more?" | Draws the `compare_*.nc` above — run that first |
| `same_day_check.py` | "Is MUR smoother, or was that a different day?" | **Needs network** |

The three comparison scripts are the reproducible evidence for the single most
consequential decision here — which product. Their conclusions are in the table above;
their inputs are cached downloads and are not kept in the repo.

---

## Keeping it current

`.github/workflows/refresh-sst.yml` runs the whole pipeline daily and commits the result.

| | |
|---|---|
| **Schedule** | 11:00 UTC daily |
| **Manual** | Actions tab -> "Refresh satellite SST" -> Run workflow (with an optional `force`) |
| **Writes** | `data/sst_barkley_realtime.nc`, `data/sst_barkley_layer.geojson` |
| **Permissions** | `contents: write` -- nothing else |

Steps, in order: fetch -> **verify** -> export -> **verify again** -> commit only if something
changed. The verify step is a gate, not a formality: a bad archive fails the job before the
layer is rebuilt, so the copy on `main` stays the last known-good one.

Three things about the timing that are easy to get wrong:

- **11:00 UTC is chosen to avoid 00:00**, which `watch-glider-transects.yml` uses. Both jobs
  commit to `main`; two pushes in the same minute means one loses the race. Spacing them is
  cheaper than retry logic (the workflow retries anyway, three times, rebasing between).
- **The hour is otherwise arbitrary, and DST does not matter.** GitHub cron is UTC-only, but
  the product publishes about two days behind on NOAA's cadence, so the time of day changes
  nothing about which days come back.
- **A scheduled workflow is disabled automatically after 60 days of repository inactivity.**
  A real failure mode for a project that goes quiet after the hackweek.

### Being a good citizen of NOAA's server

ERDDAP's own documentation is blunt about the one thing that gets clients banned:
*"Don't make multiple simultaneous requests or you will be blacklisted!"* A blacklisted
IP gets `HTTP 403 -- Your IP address is on this ERDDAP's request blacklist.`

`fetch_sst_barkley.py` complies by construction: `collect()` is a plain sequential loop,
never threaded. It also follows the softer guidance — ERDDAP advises admins to ask a
script making a series of requests to *"be considerate of other users by putting a small
pause (2 seconds?) in the script between requests"* — via `PAUSE = 2.0`, applied between
day-requests but not before the first or after the last.

Cost per run:

| Situation | Requests | Added delay |
|---|---|---|
| Archive already current | **1** (the time axis, then it exits) | none |
| Archive stale | **8** (1 axis + 7 days) | 12 s |

The 503 that ERDDAP returns under load is request *shedding*, not a ban — it sheds when
memory runs high. Retries with backoff are the right response; hammering is not.

Worth knowing for CI specifically: GitHub Actions runs from **shared runner IPs**, so
this job is pooled with every other Actions user hitting the same server. Being
conspicuous there is not a cost we bear alone, which is why the pause is in the script
rather than argued away as unnecessary for seven requests.

### When a run fails

The fetcher fails safe: on any network error it exits non-zero and leaves the previous
archive untouched, so the job stops before committing and `main` keeps serving valid data.
The next run catches up on its own -- it asks what is published and takes the newest seven
steps, so a skipped day costs nothing.

This is not hypothetical. On 2026-08-27 NOAA's ERDDAP returned 503 for hours while it was
being migrated; the fetch retried three times, exited 1, and left the archive intact. See the
migration note in `fetch_sst_barkley.py` -- the dataset is being renamed as part of that move.

---

## File inventory

**Pipeline — required**

| File | Role |
|---|---|
| `fetch_sst_barkley.py` | Downloads the archive |
| `export_layer.py` | **Writes the file the shared app consumes** |
| `barkley_sst.py` | The library everything reads through |
| `make_land_mask.py` | Builds the coastline mask (run once) |
| `land_mask_1km.nc` | The mask itself, 43 kB — **needed at render time** |
| `verify_sst.py` | 48 checks |
| `map_layers.py` | Layer registry |
| `sst_map_test.py` | The marimo app |
| `../../.github/workflows/refresh-sst.yml` | Runs all of the above, daily |

**Evidence and previews**

| File | Role |
|---|---|
| `compare_resolutions.py`, `compare_panels.py`, `same_day_check.py` | Why the blend was chosen |
| `preview_panels.py`, `preview_map.py` | Offline sanity checks |

**Not kept**

No `.nc` files other than the archive and the mask. `compare_*.nc` and `sameday_*.nc` were
cached ERDDAP downloads; their conclusions live in "Which product, and why" above, and the
scripts that fetched them are still here. `barkley_map.py`, an earlier standalone marimo
bridge, was removed when `sst_map_test.py` superseded it.

**Generated, gitignored** — see `.gitignore`

`barkley_sst_map.html`, `preview_week*.png`, `compare_resolutions.png`. All rebuild
offline in seconds except `compare_resolutions.png`, which needs its inputs re-fetched
first.

---

## Known gaps

1. **Not validated against the ONC sensors.** Highest-value next step, needs no network.
   `data/folger/` has hourly Folger Pinnacle temperature back to 2011 and the satellite cell
   sits ~1.3 km away.
3. **Nearshore water the product withholds.** Clipping fixed colour appearing over land;
   it cannot recover SST the product never published for genuine nearshore water. Whether
   to fill those from a neighbour or leave them blank is undecided.

---

## Unrelated but unresolved

### The glider fetcher makes 6 simultaneous ERDDAP requests

**Not our code, and worth raising with whoever owns it.** Found while checking our own
compliance, not by auditing theirs.

`data/cproof_glider.py` fetches from **`https://gliders.ioos.us/erddap`** — the IOOS Glider
DAC, an ERDDAP — using a thread pool six wide:

```
data/cproof_glider.py:295    max_workers: int = 6      # fetch_many()
data/cproof_glider.py:310    with ThreadPoolExecutor(max_workers=max_workers) as pool:
data/cproof_glider.py:624    max_workers: int = 6      # update_archive(), the scheduled path
```

ERDDAP's admin documentation names this as the behaviour that gets a client banned:

> *"Don't make multiple simultaneous requests or you will be blacklisted!"*
> A blacklisted IP then gets `HTTP ERROR 403 - Access Forbidden -- Your IP address is on
> this ERDDAP's request blacklist. Did you often submit more than one request at a time?"*

Six is under the point where ERDDAP starts rejecting outright, but it is squarely the
"more than one simultaneous request, repeatedly and continuously" pattern the blacklist
exists for.

**Why it is worth a quick fix rather than a shrug.** `data/cproof_https.py` (line 371) has
the same shape against `cproof.uvic.ca`, and the glider path runs unattended from
`.github/workflows/watch-glider-transects.yml`. Scheduled jobs run on **shared GitHub
Actions IP ranges**, so a ban would not land only on this project — it would land on
whoever else is using that runner pool.

**The fix is a one-line default.** Nothing else has to change; `max_workers` is already a
parameter, and `pool.map` over a single worker is just a sequential loop:

```python
max_workers: int = 1,       # was 6 -- ERDDAP blacklists concurrent clients
```

Better still, mirror what `fetch_sst_barkley.py` does after that change: a `PAUSE = 2.0`
between requests, following ERDDAP's own suggestion that a script *"be considerate of
other users by putting a small pause (2 seconds?) in the script between requests"*.

Two things this is **not**:

- **Not a problem for the SST pipeline.** Different server. A ban on `gliders.ioos.us`
  would not touch our NOAA CoastWatch fetches.
- **Not urgent in the sense of "it is broken now."** No 403 has been observed. This is a
  standing risk, not a current outage.

Sources: [ERDDAP admin documentation](https://erddap.github.io/docs/server-admin/additional-information)



`data/PartII_API_Access.ipynb` carries a **live ONC API token in cell 3**. It has never
entered git history, and the repo `.gitignore` now excludes the file so a stray
`git add -A` cannot commit it — but **that `.gitignore` rule must be pushed for teammates
to have the same protection**, and the token itself still wants rotating and reading from
an environment variable:

```python
token = os.environ["ONC_TOKEN"]
```

Recorded here because this folder's notes are the only place it was being tracked, and
the docs that carried it have been folded into this README.
