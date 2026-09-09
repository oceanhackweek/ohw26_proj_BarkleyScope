# Day-of-year temperature climatologies, Barkley moorings and buoys

`onc_climatology.py` builds a day-of-year temperature climatology from the records in
`data/folger`, `data/barkley` and `data/buoys`, and scores a new
measurement against it as **normal (within 1 sd) / unusual (1-2 sd) / extreme
(beyond 2 sd)**. `check_latest.py` runs the current readings through it and draws
the cross-site summary.

## Sites

Discovered from the data directories; station name comes from the ONC filename and
depth from each file's own metadata, so dropping a new ONC download in either folder
is enough to add a site.

| key | station | depth | record | day-of-year sd |
|-----|---------|-------|--------|----------------|
| `pinnacle`   | Folger Pinnacle          |  25 m | 2011-2026 | 0.43-1.47 C |
| `deep`       | Folger Deep              |  98 m | 2016-2026 | 0.19-0.93 C |
| `chinacreekunderwaternetwork` | China Creek Underwater Network | 109 m | 2019-2026 | 0.15-0.49 C |
| `upperslope` | Barkley Upper Slope      | 398 m | 2009-2026 | 0.18-0.38 C |
| `node`       | Barkley Node             | 643 m | 2018-2026 | 0.12-0.18 C |
| `hydrates`   | Barkley Canyon Hydrates  | 871 m | 2013-2026 | 0.09-0.14 C |
| `mideast`    | Barkley Canyon Mid-East  | 900 m | 2009-2026 | 0.10-0.15 C |
| `axis`       | Barkley Canyon Axis      | 983 m | 2010-2026 | 0.12-0.16 C |
| `laperusebank` | La Peruse Bank (C46206) | surface | 1988-2022 | 0.94-1.54 C |

## Method

* ONC files: only QAQC flags 1/2/7 are kept; everything else is dropped, so records
  have gaps rather than filled values.
* DFO/MEDS buoy files: the file's own `Q_FLAG` is **not** used -- at La Peruse Bank,
  flag 1 ("appears correct") spans -33 to +79 C while flag 4 ("erroneous") spans an
  ordinary 7.3-18.6 C, so the column cannot be trusted. The series is screened on its
  values instead: a 2-25 C gross range, then a spike test against a centred 13-hour
  rolling median (this is what removes the second, bad telemetry stream interleaved at
  a different minute offset in 2008, 2009 and 2017), then hourly averaging, then a
  robust day-of-year test at 5 MAD-scaled sds for sustained excursions a local median
  cannot see. At La Peruse that is 4,082 of 237,882 raw records removed (1.7 %), and
  it takes the record's range from -51.3/+79.2 C to a physical 3.7-19.9 C. The report
  prints the screening tally for any file that goes through it.
* Each day of year pools every observation within +/- 7 days across all years, so each
  estimate rests on thousands of hourly values from 9-18 years rather than the handful
  a single calendar date would give. Mean and sd curves get a light 5-day circular
  smooth.
* Feb 29 is folded onto Feb 28 so the day-of-year axis is a fixed 365-day cycle;
  otherwise everything after February shifts by a day in leap years.
* The sd bands are checked against each record itself. Every site lands within a few
  points of the Gaussian 68.3 / 27.2 / 4.6 % split, except Folger Deep (63.9 / 33.5 /
  2.6 %) whose distribution has fatter shoulders and thinner tails. Each table also
  carries p05-p95 if you prefer distribution-free thresholds.
* Variability is strongly seasonal at every site, which is why anomalies are reported
  in sd units rather than degrees.
* China Creek is the one site whose seasonal cycle runs the other way: warmest around
  1 March, coldest around 10 July, opposite in phase to the shelf and canyon sites. It
  sits at 109 m inside Alberni Inlet, behind a sill, and its deep water is renewed by
  cold dense water spilling in during the upwelling season. In 2026 that arrives as a
  staircase of discrete steps through May and June rather than as a smooth seasonal
  decline -- individual renewal pulses, not a slow drift. Any cross-site reading of
  "warm for the time of year" has to account for the fact that its time of year is
  reversed.

## Use

```bash
python onc_climatology.py --list                             # discovered sites
python onc_climatology.py --site node                        # summary report
python onc_climatology.py --site node --check 2026-08-26T21:30 5.05
python onc_climatology.py --all --outdir climatology/        # every site: csv + png
python check_latest.py                                       # score the current readings
```

```python
from onc_climatology import load_series, build_climatology, classify, classify_series
obs  = load_series("upperslope")
clim = build_climatology(obs)     # 365 rows: mean, sd, n, n_years, p05-p95, lo1/hi1/lo2/hi2
classify(clim, "2026-08-26T18:30", 6.05, obs=obs)   # -> anomaly, z, band, label, percentile
classify_series(clim, new_obs)                       # a whole new series
```

`climatology/<site>_climatology.csv` is the pre-built table (one row per day of year),
`climatology/<site>_climatology.png` the envelope plot with the current year overlaid,
and `climatology/latest_vs_climatology.{csv,png}` the cross-site comparison.

## Caveats

* Coverage is uneven year to year at every site, so these are record climatologies,
  not clean fixed-baseline normals. The 2014-2016 marine heatwave is inside every
  baseline and warms it slightly.
* La Peruse Bank ends 2022-04-13, so a present-day reading is being compared against a
  baseline that stops four years short. The record warms +0.010 C/yr (+0.34 C over 33
  years), so the recent end of the distribution is slightly under-weighted.
* Barkley Node has the shortest record (2018-2026, 9 years, 2,250-2,967 values per
  day of year). Its bands are the least well constrained of the deep sites.
* China Creek's distribution is the least Gaussian of any site: 60.5 / 39.0 / 0.4 %
  against the expected 68.3 / 27.2 / 4.6 % split. It has fat shoulders and almost no
  tail, so a z-score there is a poorer guide to rarity than elsewhere and the p05-p95
  columns are the better threshold.
* The deep canyon sites have a very small seasonal cycle (0.14-0.28 C) relative to
  their sub-seasonal variability, so day-of-year climatology matters less there than
  at the shelf sites -- but the sd is also tiny, so small absolute anomalies still
  score as large z.
* `check_latest.py` prints a warning when the value being checked differs from the
  last archived value by more than 0.1 C, which usually means the reading came from
  the live dashboard and the archive has not caught up (or the wrong sensor/depth).

## Latest month from the API (`latest_month.py`, `Latest_Month_App.py`)

`check_latest.py` scores a handful of hand-typed spot readings. `latest_month.py`
pulls a whole recent window straight from the ONC API instead and scores **every hour**
in it, so the comparison is a curve against an envelope rather than one point against a
band. The statistics are unchanged -- it calls `onc_climatology.classify_series`.

```bash
python latest_month.py                        # last 30 days, every ONC site
python latest_month.py --site node --days 14
python latest_month.py --offline              # no API: score the tail of the archives
python latest_month.py --no-plots             # tables only
python latest_month.py --format png           # raster instead of the default svg
```

Figures are **SVG** by default, and the app renders them inline as vector via
`latest_month.as_svg` -- which namespaces each figure's element ids, without
which two matplotlib SVGs on one page resolve each other's clip paths and lose
content. See the Figures section of `ENSO.md`.

`Latest_Month_App.py` is the same thing as a marimo app -- site and window pickers, a
summary table, the cross-site figure, and a per-site detail plot:

```bash
marimo edit Latest_Month_App.py               # to work on it
./../../final_notebooks/serve_app.sh          # pattern for serving in app mode
```

### The token

Read from `$ONC_TOKEN`, falling back to `~/.onc_token`. It is never printed, logged, or
written into any output file. To set it without it entering your shell history:

```bash
read -s -p 'ONC token: ' T && printf '%s' "$T" > ~/.onc_token \
    && chmod 600 ~/.onc_token && unset T
```

`~/.onc_token` deliberately lives outside the repo, so no `git add -A` can pick it up.
This is the direction `data/sst/README.md` already asks for, after a live token was
found sitting in a notebook cell.

### How sites are resolved

Nothing is hardcoded, because a guessed location code silently returns the wrong
mooring's data rather than failing:

* The ONC **CSV** exports carry `#STNCODE` in their preamble, which *is* the ONC
  location code -- Mid-East resolves to `BACME` for free.
* The **NetCDF** exports do not, but they carry `station_lat`/`station_lon`. Those are
  matched against ONC's own location list, and a nearest match further than 2 km is a
  hard error rather than a guess.
* The device category is whichever one at that location actually reports the
  `seawatertemperature` **property**, asked for via the API rather than assumed to be
  CTD. ONC separates two codes that are easy to conflate: `seawatertemperature` is the
  *property* code, shared by every instrument measuring it, while the *sensor category*
  code is what that device calls the channel -- plain `temperature`. Matching the
  property name against the sensor-category field finds nothing anywhere, which fails
  every site at once rather than quietly returning the wrong series.
* Where more than one device category at a location carries the property -- an oxygen
  sensor and a turbidity meter each report their own temperature -- CTD is preferred,
  because that is what the archives and therefore the climatology were built from.
  Without an explicit preference the choice falls to dict ordering.

Resolved codes and the resolved sensor category are cached in `onc_locations.json`
beside the script. A cache written before the sensor category was recorded is treated
as absent rather than reused.

### When a site goes quiet

An instrument that stops reporting yields an empty window, which is a normal condition
here rather than an error: Folger Deep's CTD has been silent since 2026-07-18. Such a
site keeps its full column schema, reports `n = 0` and a `no data returned` verdict,
and still shows the archive's own last value and timestamp -- which is the pair that
distinguishes an outage from a fetch bug. One quiet site does not stop the run.

### Comparability with the climatology

* The pull is resampled to **hourly** (`resamplePeriod=3600`), because the climatology
  was built on hourly averages. Scoring raw sub-minute scalars against an hourly sd
  would inflate every z.
* The same QAQC filter is applied to the fetched data as to the archives -- flags 1/2/7
  kept, everything else dropped as a gap.
* Timestamps come back tz-naive UTC, matching `load_series`, so the day-of-year index
  lines up.
* The prebuilt `<site>_climatology.csv` is used when present (milliseconds); otherwise
  the climatology is rebuilt from the archive (tens of seconds per site).

### Reading the output

`verdict` is a **window-level** label and is deliberately coarser than the per-reading
one in `check_latest.py`: a single hour beyond 2 sd is noise, whereas a month that
averages beyond 1 sd is not. It keys off the window mean and the fraction of time spent
outside 1 sd, not off the worst single point -- so a site can read `normal` while still
showing hours beyond 2 sd in its detail plot. Both numbers are in the table.

In the per-site figure, excursions are drawn as **filled area** between the observation
and the 1 sd edge rather than as a marker per hour. At a site that sits outside the band
for most of the month, per-point markers cover the line they are annotating and the eye
reads dot density instead of distance.

### Caveats

* **La Perouse Bank is absent.** It is a DFO/MEDS buoy, not an ONC station, so it has no
  ONC location code and cannot come through this API at all. It stays archive-only until
  a live source is found.
* `--offline` scores the tail of the archived files, which end days to weeks before the
  present and at a *different* date per site. It is a structural check of the scoring and
  plotting path, not a current one; the cross-site figure says so in its subtitle when
  the per-site windows disagree by more than two days.
* Everything in the parent `## Caveats` section still applies -- these are record
  climatologies, not fixed-baseline normals, and the deep canyon sites have very small
  sd, so small absolute anomalies still score as large z.

## Is it ENSO? (`enso_context.py`, `ENSO_App.py`)

`latest_month.py` scores the present against the day-of-year climatology, which
answers "is this unusual" but not "is this El Nino". `enso_context.py` measures
each site's lagged relationship to the ONI over its whole record and scores the
present against that instead. See **ENSO.md** -- including why the shelf and the
deep canyon respond with opposite sign at different lags, and why that split is
the reason to believe the pattern is not just "warm years are warm".
