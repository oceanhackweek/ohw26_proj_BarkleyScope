# C-PROOF glider data for BarkleyScope

Glider observations inside the BarkleyScope study box —
longitude **-126.80 to -124.50**, latitude **47.85 to 49.36** — harvested from the
[IOOS Glider DAC ERDDAP](https://gliders.ioos.us/erddap) and kept as two netCDF archives.

**If you are building a visualization, everything you need is `read_archive()`. Skip to
"Reading the data".**

## The two archives

| File | What it is | Size | In git? |
|---|---|---|---|
| `cproof_glider_realtime.nc` | Rolling record from the real-time feeds, updated daily. What a "last 7 days" view reads. | ~3 MB | **Yes** |
| `cproof_glider_delayed.nc` | Historical reference record from the reprocessed `-delayed` datasets. Calibrated, quality controlled, and far denser. | ~37 MB | No — rebuild it |

They are deliberately kept separate rather than blended, because the difference between
them is scientific, not cosmetic:

- **Delayed-mode is calibrated; real-time is not.** Real-time values have had only a
  gross-range screen applied here. Do not present them as calibrated measurements.
- **Delayed-mode is roughly 650× denser.** Deployment `dfo-walle652-20210902` carries
  1,316 real-time observations against **861,530** delayed ones. The real-time feed is
  heavily decimated for bandwidth.
- **They cover different periods.** Delayed-mode data lag real time by months to years,
  because reprocessing happens after the glider is recovered.

A reasonable dashboard shows the real-time archive for "what is happening now" and the
delayed archive for "what is normal for this time of year" — and labels which is which.

The delayed archive is not in git because of its size. Build it once, locally:

```bash
python data/update_cproof_glider.py --mode delayed      # a couple of minutes
```

## Variables

Every archive carries all seven science variables C-PROOF gliders fly, on a single
`obs` dimension, alongside `time`, `latitude`, `longitude`, and `depth`.

| Variable | Units | Notes |
|---|---|---|
| `temperature` | °C | Present on every deployment |
| `salinity` | 1e-3 (PSU) | Present on every deployment |
| `density` | kg m⁻³ | Present on every deployment |
| `oxygen_concentration` | µmol L⁻¹ | **Missing on ~30% of deployments** — not every glider flies an optode |
| `chlorophyll` | mg m⁻³ | Fluorometer; see the note on negatives below |
| `backscatter_700` | m⁻¹ sr⁻¹ | Optical backscatter at 700 nm |
| `cdom` | ppb | Coloured dissolved organic matter |

Variables a glider did not carry come back as `NaN`. **Always check coverage before
plotting** — an oxygen panel will be empty for a third of the deployments:

```python
frame["oxygen_concentration"].notna().mean()      # fraction of rows with oxygen
```

### Negative chlorophyll and backscatter are not errors

The optical channels are raw counts converted with factory coefficients and are **not
dark-corrected**, so small negative values are ordinary instrument behaviour in clear
deep water. The 1st percentile of chlorophyll is about **-0.46 mg m⁻³**. Clipping at
zero would blank roughly a quarter of the bio-optical record. If you need a
presentation-friendly axis, clamp the *colour scale*, not the data.

## Reading the data

```python
import sys; sys.path.insert(0, "data")
import cproof_glider as cproof

# The last week of real-time data — the dashboard call
recent = cproof.read_archive(cproof.REALTIME_ARCHIVE, last_days=7)

# The whole historical record, temperature only (much lighter in memory)
history = cproof.read_archive(cproof.DELAYED_ARCHIVE, variables=["temperature"])

# A fixed window, a couple of variables
window = cproof.read_archive(
    cproof.REALTIME_ARCHIVE,
    start="2026-06-01", end="2026-08-01",
    variables=["temperature", "oxygen_concentration"],
)
```

You get a tidy pandas DataFrame, one row per observation, sorted by time:

```
deployment  glider  time (UTC, tz-aware)  latitude  longitude  depth  <variables…>
```

`deployment` is the ERDDAP dataset ID; `glider` is the vehicle name pulled out of it
(`eva035`, `marvin1003`, …). A single glider appears across several deployments.

**Use `variables=` on the delayed archive.** Reading all seven columns across three
million observations is several hundred megabytes in memory, and most plots need one
or two.

Prefer xarray? The files are CF-1.10 and open directly:

```python
import xarray as xr
ds = xr.open_dataset("data/cproof_glider_delayed.nc")
```

## Keeping it up to date

The daily job runs on a personal fork (`tborgfeldt/ohw26_proj_BarkleyScope`) rather than
here, because it commits the refreshed archive back into the repository it runs in and
that would add a ~3 MB binary to this repo's history every night. The copy of
`cproof_glider_realtime.nc` committed here is therefore a **snapshot**, current as of the
commit that added it; pull a fresh one from the fork, or run the command below yourself,
if you need observations newer than that.

```bash
python data/update_cproof_glider.py --mode realtime     # what the daily job runs
python data/update_cproof_glider.py --mode delayed      # refresh the reference record
python data/verify_archives.py                          # confirm nothing is broken
python data/verify_archives.py --mode realtime          # only the tracked archive
```

Updates are **additive and idempotent**. Each deployment resumes from the last
observation already stored — state is derived from the archive itself, not from a
sidecar file — so running twice appends nothing, and a run after a missed week
backfills the whole gap rather than only the last day.

That design is a response to a real property of the source: **the DAC catalogue is not
stable.** Repeated identical searches have returned 10, 25, and 38 datasets within
minutes as the server reloads datasets. Because updates only ever add, a deployment
missed by one run is picked up by the next and successive runs converge on full
coverage. For the same reason, **avoid `--rebuild`** unless you have a specific reason:
if the catalogue happens to be thin at that moment, the rebuilt archive will be thin too.

## What is out there *right now* — `cproof_https.py`

The archives above come from the IOOS DAC. For a live "what is in the water today"
panel they are the wrong source, because **C-PROOF's own server runs several days
ahead of the DAC.** Checked 2026-08-27: the DAC had no record of
`dfo-hal1002-20260817` at all, and its `dfo-eva035` copy stopped three days short,
while both were current on C-PROOF. `cproof_https.py` reads
[the C-PROOF server](https://cproof.uvic.ca/gliderdata/deployments) directly, where
real-time netCDF is published as static files and refreshed hourly.

```bash
python data/cproof_https.py                        # what is reporting in the box now
python data/cproof_https.py --grid                 # also cache the gridded files
python data/cproof_https.py --geojson tracks.json  # write map-ready tracks
```

```python
import sys; sys.path.insert(0, "data")
import cproof_https as live

now = live.snapshot()                    # same columns as read_archive(), current to the hour
deployments = live.available_now()       # what is flying, with tracks and metadata
layer = live.track_geojson(deployments)  # FeatureCollection for MapLibre
grid = live.load_grid(deployments[0])    # depth x profile Dataset for a curtain plot
```

`snapshot()` returns exactly the columns `read_archive()` does, so anything already
reading the archives can read a live snapshot without changes. Downloads are cached
under `data/cproof/` (gitignored) and revalidated with `If-Modified-Since`, so
repeated calls cost one 304 per file rather than a re-download.

**Two products per deployment.** The timeseries (~1–2 MB) is one row per observation
and is what `snapshot()` reads. The gridded file (17–60 MB) is `depth × profile` and
carries the `*_adjusted` and `*_qc` variables the timeseries lacks — use it for
curtain and pcolor plots, where it is dramatically lighter:
`dfo-hal1002-20260817` is 677 profiles gridded against 12,089 scattered observations.

Three quirks of this source the module handles, each of which silently corrupts a
plot if you do not:

- **A "deployment" directory is not a mission.** When a glider is recovered and
  redeployed mid-mission, C-PROOF opens a new dated directory but keeps the original
  start time, and the newer file contains *both* legs. `dfo-eva035-20260806` and
  `-20260826` are one mission; reading both double-counts the overlap.
  `collapse_missions()` keeps only the superset.
- **Filenames are not regular.** The real-time grid is `_grid.nc` for one deployment
  and `_grid_adjusted.nc` for another. Files are found by listing the directory and
  ranking candidates, never by building a URL from the deployment name.
- **A missing sensor can come back as a copy of another one.**
  `dfo-colin1142-20260708`, whose catalogue comment reads "no O2 on this deployment",
  publishes an `oxygen_concentration` identical to `backscatter_700` — labelled
  µmol/L, valued 8.1e-5 to 5.9e-3, and comfortably inside any range check.
  `blank_mismapped_channels()` catches it on exact equality.

Real-time data is **not calibrated**; the same gross-range screen the archives use is
applied here, and nothing more. Label it accordingly.

### The nightly transect watch

`.github/workflows/watch-glider-transects.yml` runs `watch_glider_transects.py` at
**00:00 UTC daily** — the same slot the archive updater uses on its fork — and commits
two small tracked files when, and only when, something has actually changed:

| File | What it is | Size |
|---|---|---|
| `cproof_transects.json` | The manifest: every deployment with a track in the box whose last fix is within 30 days, plus resolved real-time file URLs and a `seen` ledger | ~5 KB |
| `cproof_transects.geojson` | The same tracks as LineStrings, coloured by deployment | ~46 KB |

Read the manifest instead of querying C-PROOF, if all you need is *what is out there*:

```python
import json
manifest = json.load(open("data/cproof_transects.json"))
for transect in manifest["transects"]:
    print(transect["deployment"], transect["first_seen"], transect["files"]["grid"])
```

The job downloads no netCDF files — one catalogue request plus a directory listing per
deployment — so it finishes in seconds. Two details worth knowing if you change it:

- **The `seen` ledger is what makes "new" mean anything.** It records when each
  transect *first* appeared and is never pruned, so a deployment that drops out of the
  30-day window and comes back is reported as **returned**, not as new. Without it, a
  rebuilt manifest would announce every transect as new.
- **The manifest stores no `age`.** Age is a function of when you look, so storing it
  would make the file differ from itself on every run — turning the "did anything
  change" test that gates the nightly commit into "did the job run", and producing an
  empty commit every night. Derive age from `last_fix` at read time.

Run it by hand any time; it is idempotent, and `--dry-run` writes nothing:

```bash
python data/watch_glider_transects.py --dry-run
python data/watch_glider_transects.py --lookback-days 90
```

## The gridded mission set — `glider_adjusted/`

The archives above are one row per observation. For a curtain or `pcolormesh` plot you
want the *gridded* product instead: depth × profile, with the calibrated `*_adjusted`
fields and their QC flags. `fetch_grid_adjusted.py` pulls the `_grid_adjusted.nc` file
for every mission on the two lines that cross the study box.

```bash
python data/fetch_grid_adjusted.py              # 26 files, 10.68 GB
python data/fetch_grid_adjusted.py --dry-run    # just show the plan
python data/fetch_grid_adjusted.py --compress   # zlib on the way in, ~5-8x smaller
```

Missions are selected from C-PROOF's catalogue rather than a hand-typed list, so one
added next month is picked up without editing code:

| Group | Selected by | Count |
|---|---|---|
| `southern_line/` | `project == "Southern Line"` | 11 |
| `svi_shelf/` | `comment == "SVI Shelf from Bamfield"` | 15 |

Note that the SVI Shelf missions are identified by their **comment**, not their project
— C-PROOF files them under `LB Line`, so keying on `project` would miss all 15.

### These files are not in git

Each is 42 MB to 940 MB (uncompressed float64 on a 1100-bin depth axis that is mostly
NaN below the dive depth), and **21 of the 26 are over GitHub's 100 MB per-file limit**.
Splitting the push per file does not help — that limit is enforced per file, not per
push. So they are gitignored and mirrored as release assets, which allow 2 GB each:

```bash
gh release download glider-adjusted-v1        # pull the mirrored copies
bash data/upload_glider_adjusted.sh           # re-upload; skips what is already there
```

`glider_adjusted/manifest.json` *is* committed. It records every file's source URL, byte
size, server `Last-Modified`, and verification result, so the set is auditable without
downloading a gigabyte.

### What gets excluded, and why

Only `<deployment>_grid_adjusted.nc` is taken — never `_grid.nc`, `_grid_delayed.nc`,
`_grid_delayed_adjusted.nc`, or `_grid_CTDadjusted.nc`. The match is on the exact
filename, which also rules out the stray copies of *other* deployments' grids that sit
in some `L0-gridfiles` directories (`dfo-eva035-20250619/` holds a
`dfo-eva035-20250527_grid.nc`); taking those would file one mission's data under
another's name.

Four missions in the two groups are dropped:

| Deployment | Reason |
|---|---|
| `dfo-eva035-20260806` | Continuation directory — same `deployment_start` as `dfo-eva035-20260826`, whose file is the superset. Keeping both double-counts every overlapping profile. |
| `dfo-eva035-20250825` | No adjusted product on the server |
| `dfo-eva035-20260423` | No adjusted product on the server |
| `dfo-hal1002-20260817` | No adjusted product on the server |

A filename ending in `_grid_adjusted.nc` is not proof the calibration was ever run, so
every downloaded file is opened and checked for `temperature_adjusted` carrying finite
values. Anything failing is moved to `glider_adjusted/rejected/` rather than deleted, so
the call stays inspectable. All 26 currently pass.

## Map-ready tracks — `glider_adjusted_tracks.geojson`

The map app cannot read the gridded set directly: that is 10.68 GB, and a browser needs
about a megabyte of line geometry. But geometry is all a track layer wants, and the
gridded files carry it cheaply — `longitude`/`latitude` are 1-D coordinates on `time`,
one point per profile. `build_historical_tracks.py` reads only those, clips to `BOX`,
splits into drawable segments, and writes a file small enough to commit.

```bash
python data/build_historical_tracks.py            # after any fetch_grid_adjusted.py run
python data/build_historical_tracks.py --dry-run  # report, write nothing
```

**104 segments, 28,446 points, 0.72 MB** from the 26 deployments. Segments are cut
wherever a straight line would invent a path — a spatial jump over `MAX_GAP_DEG` (0.05°,
matching the app's own config) or a time gap over `MAX_GAP_HOURS` (24 h).

### Colouring by time

Each feature carries two numeric ramp keys on a shared origin (`epoch_start`, the
earliest deployment), so a consumer can switch without rebuilding the file:

| Property | Meaning |
|---|---|
| `epoch_days` | Days since `epoch_start` of the **deployment**. One colour per deployment. Range `0`–`epoch_days_max`. |
| `segment_epoch_days` | Days since `epoch_start` of **this segment's own first profile**. Honest where a file holds a mission it is not named for. Range `segment_epoch_days_min`–`_max`. |
| `deployment_month`, `segment_month` | The same two, as `YYYY-MM`, for a discrete month/year legend. |

**Do not use the files' own `deployment_start` attribute** — 13 of the 26 carry a
placeholder (`2018-07-12`, `2000-01-01`, `2022-12-07`). The date in the directory name is
reliable and agrees with the first observation in 24 of 26; that is what these fields use.

Two `bumblebee998` deployments carry an entire earlier mission from December 2022 ahead
of the one they are named for, so their `segment_epoch_days` goes negative (down to
`-444`). The origin is anchored on deployments rather than segments on purpose —
anchoring on segments would stretch the ramp over 1,358 days to serve four outlier
segments and flatten the difference across every other track.

## Instrument sites — `folger_sites.geojson`

The two Ocean Networks Canada sites in Folger Passage, as Points, written by the same
script. Coordinates come from the ONC metadata shipped with the data already in
`data/folger/`, not from a gazetteer.

| Site | Code | Lon | Lat | Depth |
|---|---|---|---|---|
| Folger Deep | `FGPD` | −125.280955 | 48.813797 | 98 m |
| Folger Pinnacle | `FGPPN` | −125.281500 | 48.808292 | 25 m |

They are ~650 m apart and differ by ~70 m of depth, so they must not be collapsed to one
marker — at low zoom they overplot. Note that `data/sst/compare_panels.py` labels
(48.814, −125.281) as "Folger Pinnacle", but per ONC that coordinate is Folger *Deep*;
do not copy it from there.

## Files

| File | Purpose |
|---|---|
| `cproof_glider.py` | The shared library — discovery, fetching, QC, netCDF I/O, update logic |
| `cproof_https.py` | Live view straight from the C-PROOF server — what is in the box now |
| `fetch_grid_adjusted.py` | Bulk download of the gridded `_grid_adjusted.nc` mission set |
| `build_historical_tracks.py` | Turns that set into committable map tracks + the Folger sites |
| `upload_glider_adjusted.sh` | Mirrors that set to the GitHub release, one deployment at a time |
| `watch_glider_transects.py` | Nightly check for new transects in the box; writes the manifest |
| `update_cproof_glider.py` | CLI entry point for the scheduled job |
| `verify_archives.py` | Post-rebuild checks; exits non-zero if anything is wrong |
| `Glider_ERDDAP_DataPull.ipynb` | Annotated walkthrough of the same pipeline |

The notebook and the scheduled job both import `cproof_glider.py`, so they cannot drift
apart — a GitHub Action cannot import functions defined in notebook cells.
