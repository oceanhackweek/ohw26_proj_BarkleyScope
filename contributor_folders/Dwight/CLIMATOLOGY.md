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
* The deep canyon sites have a very small seasonal cycle (0.14-0.28 C) relative to
  their sub-seasonal variability, so day-of-year climatology matters less there than
  at the shelf sites -- but the sd is also tiny, so small absolute anomalies still
  score as large z.
* `check_latest.py` prints a warning when the value being checked differs from the
  last archived value by more than 0.1 C, which usually means the reading came from
  the live dashboard and the archive has not caught up (or the wrong sensor/depth).
