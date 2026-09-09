# Is ENSO showing up in the Barkley records?

`onc_climatology.py` says whether a reading is unusual for the day of year.
`enso_context.py` asks the harder question: whether it is unusual *because of*
the tropical Pacific. `ENSO_App.py` is the same thing as a marimo app.

The distinction is the whole point of the module. A warm month is not evidence
of a teleconnection — every site here was warm in 2015 and warm again in 2019,
and only one of those had an El Nino behind it. So nothing in the output says
"El Nino is happening at Barkley Canyon". It says how strongly each site has
tracked the ONI in the past, at what lag, with what confidence given a handful
of events, and how far the present sits from what that relationship predicts.

## Use

```bash
python enso_context.py --summary --live       # lag + composite table, every site
python enso_context.py --fingerprint --live   # score the latest complete month
python enso_context.py --events               # ENSO episodes, CPC definition
python enso_context.py --plots --live         # figures + csv into enso/
python enso_context.py --refresh-oni          # force an index re-fetch
marimo edit ENSO_App.py                       # the app, in the editor
./serve.sh                                    # the app, served for a browser
```

`serve.sh` runs a marimo app in *app* mode -- no code cells, no editor chrome --
and prints a URL reachable from outside the container. It takes an app name and
an optional port (`./serve.sh Latest_Month_App.py`, `./serve.sh ENSO_App.py
2750`), defaulting to `ENSO_App.py` on 2719 so it can run alongside
`final_notebooks/serve_app.sh` on 2718.

It is that script generalised, and repeats its two proxy rules because both are
invisible until they bite: bind to `127.0.0.1` rather than `0.0.0.0` or `::1`,
because jupyter-server-proxy's readiness probe reaches localhost over IPv4 while
`getaddrinfo` reports `::1` first in this container; and use the
`/proxy/absolute/<port>/` route with a matching `--base-url`, because the plain
`/proxy/<port>/` route strips the prefix and marimo then 404s every request.

The app is gated on its **Run the analysis** button, so a slider does not trigger
a minute of work. That first run rebuilds every site's climatology from the
archives, which is roughly how long it takes.

`--live` extends the archived records with the ONC API so the current month is
scored; without it the analysis stops wherever the archives stop, which at the
moment is weeks back and at a different date per site.

## The index

CPC's operational ONI, cached in `enso/oni.csv` and re-fetched when the cache
passes 20 days. PSL's Nino 3.4 is a fallback if CPC is unreachable; it is *not*
the same index — no shifting 30-year base — so which one produced the cache is
recorded in `enso/oni_source.json` and printed in the figures.

Episodes use CPC's own rule: five consecutive overlapping three-month seasons
at or beyond +/-0.5. A bare per-month threshold counts every brief excursion as
an event, which is the main way an analysis like this overstates its
confidence. The rule reproduces CPC's published episode list, 1950 to present.

ONI seasons are three-month means labelled by their **centre** month: DJF
centres on January of the labelled year, NDJ on December of it. Getting this
wrong shifts every lag by up to two months, which is the entire quantity of
interest here.

## What the record supports

Monthly-mean anomaly in sd units per site, correlated against ONI led by 0-12
months. As of 2026-09-09, with the live tail:

| site | months | lag | r | p_adj | n_eff | El Nino | La Nina | gap | excl. 14-16 | signal |
|------|-------:|----:|--:|------:|------:|--------:|--------:|----:|------------:|--------|
| Folger Pinnacle, 25 m | 146 | 2 | +0.55 | 0.020 | 29 | +0.73 | -0.52 | **+1.25** | +0.75 | clear |
| Folger Deep, 98 m | 117 | 2 | +0.56 | 0.051 | 24 | +0.57 | -0.88 | **+1.45** | +1.30 | suggestive |
| China Creek Underwater Network, 109 m | 80 | 9 | +0.77 | 1.000 | 5.7 | +0.93 | -1.10 | +2.03 | n/a | not resolved |
| Barkley Upper Slope, 398 m | 162 | 8 | -0.46 | 0.008 | 52 | -0.36 | +0.21 | **-0.57** | -0.61 | clear |
| Barkley Node, 643 m | 87 | 0 | +0.41 | 0.436 | 27 | +0.22 | -0.21 | +0.43 | +0.43 | not resolved |
| Barkley Canyon Hydrates, 871 m | 119 | 7 | -0.52 | 0.003 | 46 | -0.50 | +0.15 | **-0.64** | -0.54 | clear |
| Barkley Canyon Mid-East, 900 m | 170 | 7 | -0.57 | 0.000 | 66 | -0.44 | +0.17 | **-0.61** | -0.50 | clear |
| Barkley Canyon Axis, 983 m | 179 | 6 | -0.58 | 0.036 | 24 | -0.50 | +0.37 | **-0.87** | -0.72 | clear |

Read down the depth column, not across the rows. The two shelf sites and the
five slope-and-canyon sites differ in **sign and in lag**, not merely in
strength: the shelf warms about two months behind the tropical index, and the
deeper sites cool six to eight months behind it. That split is what makes the
pattern worth taking seriously as something other than "warm years are warm" —
a common-mode warm bias would push every row the same way.

Two sites the record cannot resolve, for the same reason in different guises.
Barkley Node has the shortest series (87 months, from 2018) and covers only two
El Nino episodes.

China Creek is the more instructive one, because on the raw numbers it looks
like the strongest result in the table: r = +0.77, the largest composite gap of
any site at +2.03 sd, and a bootstrap p of 0.000. It is not a result. Its
`n_eff` is **5.7** -- the series is so smooth that 80 months carry fewer than
six independent samples -- and once the thirteen-lag search is accounted for its
p_adj is 1.000. Three guards, three chances to be misled, and the site would
have been reported as the headline finding without them.

The `n/a` in its exclusion column is the same point from another angle: the
record begins in 2019-12 and never overlaps the marine heatwave, so removing
2014-2016 removes nothing and reproduces the full-record number exactly.
Reporting that as "holds" would be corroboration the record cannot supply. The
same applies to Barkley Node, from 2018.

### Keeping the table honest

Three columns exist because the obvious version of this analysis is wrong in
three specific ways.

* **`p_adj`** is Bonferroni over the thirteen lags searched. Taking the largest
  of thirteen correlations and quoting its nominal p is how a teleconnection
  gets manufactured. It is conservative, because neighbouring lags are far from
  independent — which is the right direction to err in here.
* **`n_eff`** is the Bretherton et al. (1999) effective sample size. Monthly
  ocean temperature carries months of memory, so 162 months at Upper Slope is
  worth about 52 independent ones and 179 at Axis only about 24. Without the
  correction an r of 0.5 looks overwhelming when it is merely suggestive.
* **`excl. 14-16`** repeats the composite with the marine heatwave removed. The
  heatwave is not an ENSO signal but sits inside the strongest El Nino in the
  record, so a result that does not survive its removal is not a result. Every
  gap above survives; the Pinnacle gap loses about 40 % of its size doing so,
  which is worth remembering when quoting that particular number.

The composite also carries a block bootstrap (12-month blocks, respecting the
autocorrelation) and a 95 % interval taken from the spread *across episodes*.
The second is usually the binding constraint and the more honest one: with five
El Nino and five La Nina episodes overlapping the observations, and fewer at
the shorter sites, the question is less "could noise fake this" than "do the
events even agree with each other".

## The fingerprint

Each site's own regression is applied to the ONI value that leads it, giving an
expected anomaly per site. The observed cross-site vector is then compared to
the expected one:

* **amplitude** — the least-squares scaling of expected onto observed. 1.0 means
  the sites are doing exactly what their history says they should for this ONI;
  0 means no response; above 1 means more than ENSO alone accounts for.
* **agreement** — the cosine between the vectors: whether the *shape across
  depth* matches, regardless of size. A warm month that warms the deep canyon as
  much as the shelf is not an ENSO pattern however warm it is.

Both are reported against the same two scores computed for every past
ENSO-active month, because an amplitude of 0.6 means nothing until you know
past events scattered between 0.2 and 1.8.

Only sites whose lagged relationship survived the lag search (`p_adj < 0.2`,
the same threshold behind the `signal` column) get a vote. This is not
housekeeping: the largest regression slope in the table belongs to China Creek,
the site with the least evidence behind it, and letting an unresolved
relationship into the projection let that one term swamp the six resolved ones
-- it moved August 2026 from "about the expected response" to "no measurable
response". A slope fitted to noise is unconstrained in size, so it cannot be
allowed to weigh against slopes that are constrained. Excluded sites are named
in the output with their p_adj and n_eff.

The scored month defaults to the most recent one where at least half the
reporting sites have 80 % of the month. A live pull's final month is a few days
long, and scoring a nine-day "month" against a monthly composite compares
unlike things. Sites that cannot be scored are listed with the reason rather
than silently dropped — a fingerprint over three of seven sites is a different
claim from one over all seven.

### August 2026

Amplitude 1.25, agreement +0.60 — the 58th and 47th percentiles of 127 past
ENSO-active months. Unremarkable as a *match*, but the site-by-site breakdown
is where the interest is:

| site | observed | expected from ONI | driving ONI |
|------|---------:|------------------:|------------:|
| Folger Pinnacle, 25 m | +0.44 | +0.72 | +1.39 |
| Barkley Upper Slope, 398 m | +1.35 | +0.22 | -0.60 |
| Barkley Canyon Hydrates, 871 m | +0.46 | +0.15 | -0.39 |
| Barkley Canyon Mid-East, 900 m | +0.68 | +0.13 | -0.39 |
| Barkley Canyon Axis, 983 m | +0.03 | +0.09 | -0.21 |

The shelf is doing roughly what the 2026 El Nino predicts, slightly under. The
deeper sites are warm while their lagged driver says they should be near zero —
the ONI values reaching them at six to eight months' lag are from early 2026,
when the tropics were still neutral to weakly cool. Whatever is warming the
slope and canyon right now, this analysis does not attribute it to the tropical
Pacific.

The genuine test is still ahead. ONI went from -0.39 in DJF 2026 to +1.80 in
JJA 2026 and will not peak until around DJF 2027, so the deep sites' predicted
response — cooling, at six to eight months' lag — is driven by ONI values that
have not happened yet. Re-run this from spring 2027.

## Figures

Both CLIs write **SVG** by default; `--format png` is still there if something
downstream needs raster. Vector because these panels get read closely -- a lag
scan is a dozen points and a fitted curve -- and because it is smaller: the
`enso/` figures went from 1.46 MB of PNG to 811 KB of SVG for the same content,
which also matters for what is reasonable to commit.

The apps render inline SVG rather than marimo's default raster, through
`latest_month.as_svg`. Two details in that helper are not cosmetic:

* **Element ids are namespaced per figure.** Matplotlib names its clip paths and
  glyph definitions the same way in every figure -- two panels on one page share
  63 ids in practice, all the `DejaVuSans-*` glyph defs plus clip rectangles.
  Left alone they resolve each other's references and a panel silently loses
  content to a neighbour's clip path. Every id is prefixed with a hash of the
  figure, and every internal `url(#...)` and `href="#..."` is rewritten to match.
* **The absolute `width`/`height` are stripped** so the `viewBox` drives sizing
  and the figure scales to whatever column it lands in.

Text is embedded as glyph outlines, matplotlib's default, so rendering does not
depend on the viewer having DejaVu Sans installed. That costs bytes against
`svg.fonttype: none`, which would be far smaller but would re-flow the labels on
any machine lacking the font.

## Caveats

* **n is tiny.** Five El Nino and five La Nina episodes overlap the
  observations; the shorter records see fewer. Every composite is an estimate
  from single digits and the intervals are wide on purpose.
* **The baseline contains the events.** Day-of-year anomalies are relative to
  the record's own mean, and that mean includes 2015-16. El Nino and La Nina
  composites are therefore near-symmetric about zero by construction, so the
  *difference* is the meaningful statistic and neither mean alone is.
* **Correlation at a lag is not a mechanism.** The deep-site relationship is
  coherent across four independent moorings and survives removing the marine
  heatwave, which is a reason to investigate it — not a reason to believe any
  particular physical story about it. Nothing here tests one.
* **La Perouse Bank is absent**, as in `latest_month.py`: a DFO/MEDS buoy with
  no ONC location code, and its record ends in 2022 regardless.
* **Folger Deep has been silent since 2026-07-18** — an instrument outage, so it
  drops out of any current-month scoring.
* Everything in `CLIMATOLOGY.md`'s own caveats section still applies.
