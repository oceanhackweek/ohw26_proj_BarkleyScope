<!--
Authors: Taylor Borgfeldt and Claude (Anthropic)
Last modified: 2026-08-27
-->

# Folger Passage temperature anomalies — decisions and limitations

Methods record for the monthly temperature-anomaly products in this directory,
covering both Folger Pinnacle (25 m) and Folger Deep (98 m). It states what was
decided, why, and what the results cannot be used for. Every number below is
produced by `onc_folger.py` in this folder, run through `make_figures.py`; none was
transcribed by hand.

The decisions and limitations were established while building the Pinnacle product
and apply unchanged to Deep, which runs through the identical pipeline. Numbers
quoted without a station name are Pinnacle's.

## Source

Both records come from Ocean Networks Canada (Oceans 3.0) as hourly-averaged
"Clean" QC exports with NaN gap fill, in `../folger/`.

| | Folger Pinnacle | Folger Deep |
|---|---|---|
| Station code | FGPPN | FGPD |
| Position | 48.808292 °N, 125.281500 °W | 48.813797 °N, 125.280955 °W |
| Instrument depth | 25 m | 98 m |
| Device category | Acoustic Doppler Current Profiler 2 MHz | Conductivity Temperature Depth |
| Deployments | 12 | 10 |
| Record | 2011-02-03 → 2026-08-11 | 2016-01-01 → 2026-07-18 |
| Hourly rows | 136,033 | 92,430 |
| Missing | 25.5% | 10.8% |

"Clean" means ONC had already replaced QC flag 3 and 4 data with NaN before export.
We did not apply our own QC, and we did not second-guess theirs.

Three further files in `../folger/` — two netCDF and one JSON — have no reader in
this pipeline. The consequential one is `folgerDeepDataSet.nc`, which holds Folger
Deep for 2009–2015 and would roughly double that station's record; joining it across
the 2015/2016 seam is an unresolved question, deliberately deferred.

## Outputs

All ten are regenerated from the source CSVs by `python make_figures.py`.

| File | Contents |
|---|---|
| `pinnacle_coverage.png` | valid days per month, before any climatology |
| `pinnacle_anomaly.png` | anomaly time series, 200 dpi |
| `pinnacle_monthly_anomaly.csv` | 186 months: monthly mean, climatology, anomaly, valid-day count, threshold flags |
| `pinnacle_climatology.csv` | 12 calendar-month means, standard deviations, year counts |
| `deep_coverage.png` | as above, Folger Deep |
| `deep_anomaly.png` | as above, Folger Deep |
| `deep_monthly_anomaly.csv` | 126 months, same columns |
| `deep_climatology.csv` | same columns |
| `folger_timeseries_and_anomalies.png` | three panels on one time axis: daily means (both stations), then one common-baseline anomaly panel per station |
| `common_baseline_anomalies.csv` | the 89 months usable at both sites, one anomaly column per station |

### Code

| File | Role |
|---|---|
| `onc_folger.py` | the library — reading, aggregation, climatology, anomalies, plotting |
| `make_figures.py` | the driver — which files, in what order, written where |

## Decisions

### 1. Station scope: each site on its own baseline

The `folger/` directory holds two stations. Folger **Pinnacle** (FGPPN, 25 m, ADCP)
covers 2011–2026; Folger **Deep** (FGPD, 98 m, CTD) covers 2016–2026. Both are
analysed, each with **its own climatology and its own thresholds** — different depths
on different instruments over different eras, so their anomaly distributions are not
interchangeable. Pinnacle was built first and Deep followed through the identical
pipeline with one path changed.

For the two-site comparison only, both are rebaselined on the months usable at
*both* sites, so a difference between them cannot be an artefact of one having
sampled different weather than the other. That common baseline is narrower than
either full record — 89 months, n=6–9 years per calendar month — which is the price
of the comparison being meaningful.

### 2. Aggregation thresholds: ≥18 hours per day, ≥15 days per month

Hourly → daily requires 18 of 24 valid hours; daily → monthly requires 15 valid days.
Both are completeness rules, chosen so that a mean is only reported when it actually
represents the period it is labelled with.

These thresholds cost very little here. Of 5,669 calendar days, only **73** were lost
to the 18-hour rule; of 187 months, only **8** were lost to the 15-day rule. Nearly
all data loss is outright absence, not partial coverage being screened out. Because
the rules are barely binding, the results are not sensitive to their exact values.

Under-threshold periods are retained with a `False` flag and a NaN mean rather than
dropped, so coverage stays auditable and the time axis stays continuous.

### 3. The trailing partial month is excluded

The record ends 2026-08-11, mid-month. August 2026 is dropped by comparing the last
observation to the end of its own calendar month — never by hardcoding a date — so a
refreshed download or a different station self-corrects. This removed one month
(187 → 186) and changed no usable month, since 2026-08 held only 10 days and had
already failed the 15-day rule.

### 4. Baseline: the full usable record, 2011-02 to 2026-07

No 30-year normal is available; the record is 15.5 years with a 2.4-year hole. The
climatology is therefore the mean of all usable months per calendar month, 11–13
years per bin. This is stated in the plot subtitle rather than left implicit.

| Month | Clim (°C) | SD (°C) | n years |
|---|---|---|---|
| Jan | 8.84 | 0.65 | 12 |
| Feb | 8.51 | 0.77 | 13 |
| Mar | 8.47 | 0.77 | 13 |
| Apr | 8.80 | 0.58 | 12 |
| May | 9.10 | 0.45 | 12 |
| Jun | 9.44 | 0.27 | 11 |
| Jul | 9.63 | 0.23 | 11 |
| Aug | 10.16 | 0.33 | 11 |
| Sep | 10.71 | 0.58 | 11 |
| Oct | 11.49 | 0.95 | 11 |
| Nov | 11.03 | 1.29 | 12 |
| Dec | 9.69 | 0.96 | 12 |

The per-bin `n` is carried into `pinnacle_climatology.csv` so downstream users can
see which months are better supported.

### 5. Thresholds: fixed percentiles of the whole anomaly distribution

Following the NOAA PSL marine-heatwave time-series style, the 90th/95th/99th
percentiles are computed once over all 141 monthly anomalies:

| Percentile | Value | Months exceeding |
|---|---|---|
| 90th | +0.94 °C | 14 |
| 95th | +1.25 °C | 7 |
| 99th | +1.60 °C | 2 |

This is **not** the Hobday marine-heatwave definition, in which the threshold varies
by day-of-year. See limitation 3, which is the most consequential item in this
document.

### 6. Plot colours were validated, not chosen by eye

Bars are neutral gray; exceedances are purple (90th), pink (95th), yellow (99th).
The trio was checked against the CVD and contrast gates: worst adjacent
colour-vision-deficiency separation ΔE 16.3, worst normal-vision separation ΔE 19.6
(OKLab ×100; floors 8 and 15). Pink and yellow fall below 3:1 contrast on the light
surface, so the thresholds carry direct numeric labels and the CSV table ships
alongside — colour never carries meaning alone.

### 7. Daily means and anomalies share one figure and one time axis

`folger_timeseries_and_anomalies.png` stacks three panels on a single x-axis: daily
means for both stations on top, then one monthly-anomaly panel per station (Pinnacle,
then Deep). The two anomaly panels share a symmetric y-scale, so their amplitudes are
comparable rather than each being auto-scaled, and an event in the daily record can be
read straight down into both anomaly series.

The panels do **not** span the same period, and that is deliberate rather than an
oversight. The daily panel shows each station's full record (Pinnacle from 2011); the
anomaly panels use the common baseline and therefore begin in 2016. Cropping the daily
data to match would discard five years of observations to make the figure tidier. The
mismatch is stated in the subtitle. Pinnacle's 2011–2016 anomalies are not lost — they
are in `pinnacle_anomaly.png` and `pinnacle_monthly_anomaly.csv`, computed against
Pinnacle's own full baseline.

Daily lines break at gaps rather than interpolating across them. With records of
unequal coverage a continuous line would draw data that does not exist.

### 8. No trend was fitted

Neither a linear trend nor any other rate of change is reported here. Both records are
short for that purpose — 15.5 and 10.5 years — and both contain the 2014–16 Blob, so
where that event sits within a record would substantially drive any slope. A defensible
attempt would need the seasonal cycle and trend estimated together (the gaps remove
specific seasons, so a naive line partly measures which seasons were sampled) and
confidence intervals widened for the strong day-to-day autocorrelation. None of that
is implemented.

## Limitations

### 1. Both records have substantial gaps; Pinnacle's dominate

**Folger Pinnacle** — 101,282 of 136,033 hourly slots carry data; **25.5% is NaN**.
Nine gaps exceed seven days and account for **95.1%** of all missing hours:

| Last good | Next good | Days | Hours lost |
|---|---|---|---|
| 2017-06-02 | 2019-10-11 | 860.7 | 20,656 |
| 2012-04-02 | 2012-10-19 | 200.2 | 4,804 |
| 2023-12-11 | 2024-04-11 | 122.0 | 2,926 |
| 2015-03-20 | 2015-05-26 | 67.0 | 1,608 |
| 2011-09-20 | 2011-11-21 | 61.7 | 1,480 |
| 2015-06-13 | 2015-07-21 | 37.4 | 897 |
| 2011-12-23 | 2012-01-04 | 11.8 | 282 |
| 2012-01-11 | 2012-01-19 | 8.8 | 209 |
| 2017-05-24 | 2017-06-01 | 8.1 | 193 |

The 2017–2019 outage removes most of three calendar years. Because it spans whole
years rather than particular seasons, it does not bias the seasonal cycle — every
calendar month still has 11–13 years — but it rules out any statement about
interannual trend or event frequency over 2017–2019.

**Folger Deep** is a substantially cleaner record — 82,418 of 92,430 slots, **10.8%
NaN**, with only three gaps over seven days holding 81.5% of the missing hours:

| Last good | Next good | Days | Hours lost |
|---|---|---|---|
| 2019-09-22 | 2020-03-08 | 167.9 | 4,029 |
| 2018-01-18 | 2018-07-01 | 163.8 | 3,931 |
| 2022-07-29 | 2022-08-07 | 8.3 | 198 |

Both large gaps end on a deployment date, so they are unrecovered-mooring intervals
rather than sensor failures. Unlike Pinnacle's, they are ~5 months each and fall in
winter–spring, so they remove *parts of years*: Deep's per-calendar-month counts run
9–10 of a possible 11, with the deficit on Feb and Oct–Dec. The imbalance is one year
and does not materially skew the seasonal cycle, but it is a different failure mode
from Pinnacle's and worth knowing when the two are compared.

At the monthly step Deep loses almost nothing to the completeness rules: **no month
falls short of the 15-day rule**, and only 37 days fail the 18-hour rule. Every Deep
month with any data at all is usable.

### 2. The baseline is short, gappy, and contains the events it is used to measure

The 2014–2016 warm anomalies are the NE Pacific "Blob" and the 2015–16 El Niño.
Those months are *inside* the baseline, which raises the climatology slightly and
therefore makes the Blob anomalies read smaller, and every other month cooler, than
they would against an event-free baseline. Combined with the 15.5-year length and
the 2.4-year hole, these anomalies are **not comparable to products built on a WMO
30-year normal**.

### 3. A fixed threshold cannot detect summer events at either site

Anomaly variability is strongly seasonal at both stations. At Pinnacle the standard
deviation runs from **0.23 °C in July to 1.29 °C in November**, a factor of five; at
Deep, from **0.19 °C in July to 0.86 °C in November**, a factor of four. A single
whole-record threshold is therefore set almost entirely by autumn and winter
variability, and the consequence is the same at both depths:

> **Zero of Pinnacle's 14 exceedances and zero of Deep's 12 fall in June, July or
> August**, although those months are roughly a quarter of each record.

This must not be read as "Folger Passage has no summer marine heatwaves." It means
summer anomalies here are physically too small to clear a threshold calibrated on
winter. Detecting summer events requires a seasonally varying threshold (the Hobday
approach); that is a per-calendar-month change to the percentile calculation in
`plot_anomalies`, deliberately not applied so these figures match the requested
PSL-style specification.

### 4. Monthly resolution cannot resolve marine heatwave events

A marine heatwave is conventionally defined on daily data with a minimum duration of
five days. This product is monthly. It identifies anomalously warm *months*, which is
a coarser and different object — short intense events are averaged away, and no
event duration, onset date, or intensity metric can be derived from it.

### 5. Two depths at one location — and they are not measuring the same thing

25 m and 98 m at a single site in Folger Passage. Nothing here should be extrapolated
to the surface or across Barkley Sound.

The two depths are decoupled seasonally. Measured on the common baseline, their
**climatologies are uncorrelated (r = +0.03)**: Pinnacle is warmest in October and
coldest in February, while Deep is warmest in December and coldest in July — the
opposite phase, consistent with summer upwelling bringing cold water onto the shelf
while the shallower site follows surface heating. Pinnacle runs up to 2.4 °C warmer
in October; Deep runs 0.8 °C warmer in January.

Their **anomalies, by contrast, correlate strongly (r = +0.85, Spearman +0.87, 89
common months)**, with near-identical amplitude (sd 0.57 vs 0.54 °C). So departures
from each site's own seasonal cycle move together through the water column even
though the mean seasonal states do not.

The practical consequence: **a climatology from one depth must never be used for the
other**, which is why each station carries its own. Anomalies are the only quantity
here that is meaningfully comparable between them, and only on the common baseline.

### 6. Instrument heterogeneity is not accounted for

Temperature comes from 12 ADCP deployments at Pinnacle over 15 years and 10 CTD
deployments at Deep over 10 years — different instrument classes at the two sites.
Deployment-to-deployment offsets, calibration drift, and any change in effective
sensor depth are not corrected or tested for. ONC's own QC is the only control
applied. Deployment boundaries are listed in each source file's preamble and are
worth checking against any step changes in the anomaly series.

One artefact is known and reported by `inspect()`: the Deep export contains a
**duplicated timestamp at `2023-09-15 16:30`**, two partial hourly bins straddling
the Device 8 deployment. Both are NaN, so no value is double-counted and the
aggregation is unaffected — `resample` bins them into the same day. It is left in
place rather than silently dropped, but it does break index uniqueness and would
corrupt a positional join against another record.

## Reproducing

Every figure and table in this folder is regenerated by one command, from nothing but
the source CSVs:

```bash
python make_figures.py                  # all stations, comparison, into this folder
python make_figures.py --station deep   # one station only
python make_figures.py --outdir /tmp/x  # write elsewhere
python make_figures.py --no-report      # skip the printed inspection report
```

Each run prints an inspection report per file first — station metadata, columns, QC
flags, time range, integrity checks, sampling regularity, and gaps longer than seven
days — so the state of the input is on the record beside the output.

### Applying it to other data

Edit the `STATIONS` block near the top of `make_figures.py` and nothing else. Each
entry needs a display label and a path to an ONC "clean, averaged" scalar CSV; depth,
station code, and instrument are read from that file's own preamble. Thresholds live
in one line beneath it (`MIN_HOURS, MIN_DAYS, DPI = 18, 15, 200`). Set
`COMPARE = None` to skip the two-site figure.

The reader assumes ONC's CSV export format — a `## END HEADER` line followed by four
positional columns (`time, value, qc_flag, count`), ISO-8601 UTC timestamps, hourly
temperature. Another ONC station works unchanged; a different provider needs its own
reader, though everything downstream of `read_csv` still applies.

### Calling the library directly

```python
import onc_folger as onc

df    = onc.inspect("../folger/<file>.csv")   # loads, prints the report, returns the frame
daily = onc.to_daily(df, min_hours=18)
mon   = onc.to_monthly(daily, min_days=15)    # drops the partial trailing month
clim  = onc.climatology(mon)
anom  = onc.anomalies(mon, clim)
onc.plot_anomalies(anom, path="out.png", dpi=200)
```

Every function takes a path or a frame; none hardcodes a station.
