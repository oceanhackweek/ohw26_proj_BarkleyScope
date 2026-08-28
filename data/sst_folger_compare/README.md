<!--
Authors: Anais Gentilhomme and Claude (Anthropic)
Last modified: 2026-08-28
-->

# Satellite SST against the two Folger depths

One figure. Satellite skin temperature over Folger Passage, plotted against the two Ocean
Networks Canada stations in the same 5 km cell — **Folger Pinnacle** (25 m, 2011–2026) and
**Folger Deep** (98 m, 2016–2026).

The question it answers is what the satellite does and does not tell you about the water
column beneath it.

```bash
python make_comparison.py                  # writes the figure into this folder
python make_comparison.py --outdir /tmp/x
```

## The figure

`sst_vs_folger_four_panel.png` — four panels, one shared time axis:

| Panel | Contents |
|---|---|
| 1 | raw daily temperature, all three series overlaid |
| 2 | monthly anomalies, satellite |
| 3 | monthly anomalies, Folger Pinnacle (25 m) |
| 4 | monthly anomalies, Folger Deep (98 m) |

The three anomaly panels share one symmetric y-scale, so their amplitudes are directly
comparable and an event in panel 1 can be read straight down into all three. Each panel's
90th/95th/99th percentile rules are computed from **its own** distribution — the three
distributions genuinely differ, so imposing one set would be wrong.

## Nothing here is new code

Both libraries are imported read-only; **neither file is modified**:

| Imported | From | Provides |
|---|---|---|
| `onc_folger.py` | `../folger_taylor/` (Taylor Borgfeldt and Claude) | the ONC reader, the aggregation chain, every plot function |
| `sst_anomalies.py` | `../sst/` | a documented fork of the above, adapted for a satellite series |

`plot_combined(series, panels)` already accepted N series and N anomaly panels, so the
four-panel figure needed no change to it — Taylor's three-panel
`folger_timeseries_and_anomalies.png` is the same call with one fewer of each.

Because `sst_anomalies.py` is a **fork rather than a reimplementation**, the arithmetic
behind all three anomaly panels is identical: `daily → monthly → climatology → anomaly`,
the same functions in the same order. That is what makes the panels comparable rather than
merely similar-looking.

## What the figure shows

**The three depths converge in winter and fan apart in summer.** All three sit near 8 °C in
midwinter. By late summer the satellite reads 16–17 °C, Pinnacle 12–15 °C, and Deep stays
near 8–10 °C. The surface–to–98 m spread is a seasonal quantity, not a fixed offset, which
is the clearest possible statement of why the satellite cannot stand in for a depth sensor.

**The satellite's anomalies are smaller than either station's.** Its 90th percentile sits at
+0.70 °C against Pinnacle's +0.94 °C. On the shared scale its panel reads visibly flatter.
That is a real property of the series, not a plotting artefact — but note the satellite's
baseline is 7 years to Pinnacle's 15, so some of the difference is baseline length.

**A fixed threshold detects no summer event in any of the three.**

| Series | usable months | 90th | exceedances | in Jun/Jul/Aug |
|---|---|---|---|---|
| Satellite skin | 84 | +0.70 °C | 9 | **0** |
| Pinnacle (25 m) | 141 | +0.94 °C | 14 | **0** |
| Deep (98 m) | 116 | +0.63 °C | 12 | **0** |

Taylor's `METHODS.md` limitation 3 argues that a whole-record percentile is set almost
entirely by autumn–winter variability and therefore cannot fire in summer. This figure is an
independent check on that claim: the satellite is a **different instrument at a different
depth on a different baseline**, and it reproduces the same result. Its own anomaly SD runs
0.40 °C in July against 0.75 °C in November — the same seasonal structure, milder.

So the summer blindness is a property of the **method**, not of the ONC sensors. It still
must not be read as "Folger Passage has no summer marine heatwaves." Detecting those needs a
seasonally varying threshold (the Hobday approach), which none of these three use.

## Limitations

Taylor's `METHODS.md` limitations apply unchanged to panels 3 and 4. Four more are specific
to putting the satellite alongside them:

**1. The baselines are not common.** Each series sits on its own full record — satellite
2019–2026, Pinnacle 2011–2026, Deep 2016–2026. A three-way common baseline would be capped
by the satellite's 2019 start and would discard eight years of Pinnacle, so the trade was
made the other way. **A difference between panels may therefore partly reflect different
baseline periods rather than the water.** This differs from
`folger_timeseries_and_anomalies.png`, which does rebaseline its two stations onto their 89
common months.

**2. The satellite series is weekly, not daily.** `data/sst_barkley_realtime.nc` holds only
the rolling 7-day window; the full history exists locally as one file,
`../sst/folger_point_daily.csv` — 380 values over 2,592 days, written at stride 7. So panel
1's satellite line is weekly through the record and daily only for the last week, and each
satellite month rests on ~4 values rather than ~30. Monthly means are unbiased either way,
but less precise. Densifying means re-running `backfill_point_history.py` at stride 1:
roughly 2,600 ERDDAP requests against a service that asks for pauses between them.
Deliberately not done.

**3. The satellite is not measuring the stations.** It is a skin-temperature L4 *analysis* —
partly modelled, about two days behind — over a 5.5 × 3.7 km cell whose centre falls on
neither instrument. The two stations are 611 m apart and both inside that one cell. Panel 1
is a comparison of three different quantities that happen to share a location and a unit.

**4. Panels do not span the same period.** The shared axis runs 2011–2026, so the satellite
panel is empty for its left ~45% and Deep's for its left ~30%. Left visible rather than
cropped, matching `plot_combined`'s own behaviour: cropping to the shortest record would
discard eight years of Pinnacle to make the figure tidier.

## Files

| File | Role |
|---|---|
| `make_comparison.py` | the driver — reads three sources, builds the figure |
| `sst_vs_folger_four_panel.png` | the output; regenerated by the above, safe to delete |
| `export_compare_points.py` | writes `../folger_compare_points.geojson`, the map layer |
| `preview_compare_points.py` | draws the same four panels **from the GeoJSON alone** |
| `preview_compare_points.png` | that output; safe to delete |
| `INTEGRATING_THE_POINT_LAYER.md` | for whoever wires the marker into the map app |
| `README.md` | this file |

## The map layer

`export_compare_points.py` packages the same three series into a single clickable point:

```bash
python export_compare_points.py     # -> ../folger_compare_points.geojson  (98 kB)
python preview_compare_points.py    # renders the figure back out of it
```

The GeoJSON carries the data, the validated colours, and the captions, so the app needs
no reader and imports nothing from this folder. `preview_compare_points.py` is the proof
of that — it imports **nothing from this repository**, only `json` and `matplotlib`. If
it runs, the layer is self-sufficient.

**`INTEGRATING_THE_POINT_LAYER.md` is the hand-off document.** It follows
`../sst/INTEGRATING_THE_LAYER.md`'s structure, and flags the one part that is not a
simple addition: `click_plot` cannot currently tell layers apart, so making the marker
clickable means editing a cell someone else owns.

This layer **supersedes `../sst_barkley_points.geojson`** — same satellite fields, plus
both stations. Integrate one or the other, not both.

Inputs are all local and already in the repo: the two ONC CSVs in `../folger/` and the
backfilled satellite series in `../sst/`. Nothing here fetches from the network.
