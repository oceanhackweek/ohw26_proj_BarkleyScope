<!--
Authors: Anais Gentilhomme and Claude (Anthropic)
Last modified: 2026-08-28
-->

# How to read this map

You have opened a map of **Barkley Sound, British Columbia** covering longitude
−126.8 to −124.5 and latitude 47.85 to 49.36. It shows ocean temperature from three
very different kinds of instrument at once, and the whole point of it is the comparison.

Start here: **there are two views, and they show different things.** The switch is at
the top-centre of the map.

| View | Shows | Click gives you |
|---|---|---|
| **Real-time** (opens here) | gliders moving through the water in the last two weeks | a 3D "curtain" plot of that glider's track |
| **Historical** | 26 past glider deployments + 8 fixed instrument sites | that site's temperature plots |

If you click something and nothing happens, you are probably in the wrong view. Sites are
only clickable in Historical; glider tracks only in Real-time.

---

## Every dot on the screen

### The blue-grey background

Not data. It is a basemap image — Esri's "Ocean" tiles, the same kind of thing Google
Maps draws — showing coastline and bathymetry so the data has somewhere to sit. It is the
only thing in this app fetched from the internet, and your browser fetches it, not Python.

### The big translucent squares — satellite temperature

The coloured grid over the water is **satellite sea surface temperature**, one square per
5 km cell, from NOAA CoastWatch's geo-polar blended product.

- **Colour = temperature**, on a fixed scale of **10 °C to 20 °C**. Dark navy `#042333` is
  cold, pale yellow-green `#e8fa5b` is warm, through purple and orange in between.
- **The scale never rescales.** A colour means the same temperature on every date, so days
  can be compared by eye.
- **Pick the date** in the "Sea Surface Temperature" box on the left. Seven days are
  available, 2026-08-20 to 2026-08-26.
- **Faded cells** are water not reachable from the open Pacific across this grid — the
  Strait of Georgia, behind Vancouver Island. Real values, different water body.
- **Squares are clipped to the coastline**, but each value is still a full 5 km measurement.

Two things it is not: it is a **skin** temperature — the top millimetre, not a depth — and
it is a **near-real-time L4 analysis**, roughly two days behind and partly modelled rather
than a direct measurement.

### Small dark dots in a trail — a glider, now

`#37474f`, radius 2.2. Each dot is **one observation** from a C-PROOF ocean glider: an
autonomous vehicle that dives and surfaces in a sawtooth as it travels, measuring on the
way. A trail of them is one deployment's track.

**Click a track** and you get the curtain plot: a 3D section coloured by temperature,
showing the water column the glider actually flew through. The clicked track turns
**magenta** `#e5308f`.

Below the plot are two sliders — one thins the points if the plot is sluggish, one narrows
the time window.

### A red dot at the end of a trail

`#e02020`, radius 7. The glider's **last recorded position** — where it was when its most
recent fix came in. Click it for the timestamp. Deliberately a different colour from
everything else, because "where it is now" is a different fact from "where it went".

### Small orange dots, in Historical view

Radius 2.2, on an orange ramp from `#e35e27` (older) to `#7a2a04` (newer). These are
**26 past glider deployments** — 28,452 profile positions in total — on the Southern Line
and SVI Shelf line, coloured by deployment date. Orange rather than blue because the
basemap is blue and a blue ramp would vanish into the water.

They are drawn as points, not lines, on purpose: the gliders sample anywhere from every
9 minutes to every hour, so a connecting line would either invent a path across a real gap
or shred a sparse transit into dashes.

### Circled dots that do not move — fixed instruments

Two sets, both radius 6 with a white outline:

- **The two Folger Passage instruments** — grey `#9aa3ab` in Real-time, black `#0b0b0b` in
  Historical. Ocean Networks Canada sensors that sit on the seafloor and never move.
  **Folger Pinnacle** at 25 m and **Folger Deep** at 98 m, about 650 m apart.
- **Six more sites**, black, visible in Historical only: five in Barkley Canyon (Upper
  Slope 398 m, Node 643 m, Hydrates 871 m, Mid-East 900 m, Axis 983 m) and the
  **La Perouse Bank** buoy C46206 at the surface.

**Click any of them in Historical view** for its day-of-year temperature climatology.

> **Zoom in before clicking in Barkley Canyon.** Hydrates, Mid-East and Axis sit within
> 0.016° of each other — at low zoom they are one dot, and you will get whichever is
> nearest your click.

---

## The Folger comparison — the reason this version exists

This is a private copy of the team's app with one thing added. In **Historical** view,
click **Folger Pinnacle** or **Folger Deep** and the panel has **two tabs**:

```
┌────────────────────────────────┐
│ Folger Pinnacle          25 m  │
│ ┌────────────┬───────────────┐ │
│ │ Climatology│ vs. satellite │ │
│ └────────────┴───────────────┘ │
│      [the selected figure]     │
└────────────────────────────────┘
```

- **Climatology** (the default) — Dwight's plot: the day-of-year mean with 1 and 2 standard
  deviation bands, pooled over ±7 days across all years, with the current year overlaid.
- **vs. satellite** — the four-panel comparison figure. Panel 1 overlays all three series;
  panels 2–4 are monthly anomalies for the satellite, Pinnacle and Deep in turn.

Both markers give the same comparison figure, because it is about the pair plus the
satellite cell covering both, not about one depth.

**The "?" in the top-right corner of either figure** explains what you are looking at.
Hover it, or Tab to it and it opens from the keyboard.

### What the comparison figure shows, and what it does not

**Shows:** the three depths converge in winter — all near 8 °C midwinter — and fan apart in
summer, satellite reaching 16–17 °C while Deep stays at 8–10 °C. The surface-to-98 m spread
is seasonal, not a fixed offset. That is the clearest statement of why a satellite cannot
stand in for a depth sensor.

**Does not show:** that Folger Passage has no summer marine heatwaves. Zero anomaly
exceedances fall in June, July or August in *any* of the three series — but that is a
property of using a fixed percentile threshold, which is set mostly by autumn–winter
variability. Detecting summer events needs a seasonally varying threshold, which none of
these use.

Also: the three series sit on **their own baselines** (satellite 2019–, Pinnacle 2011–,
Deep 2016–), not a common one, so a difference between panels may partly be the different
baseline periods rather than the water.

---

## Reading the rest of the screen

- **Legend, bottom-left** — the dot colours. It hides itself when a plot panel opens,
  because the panel docks over that corner.
- **SST scale, bottom-right** — the temperature ramp and its fixed 10–20 °C ends.
- **"i" button, right edge, vertically centred** — data sources and credits.
- **Panels open on the left**, with a ✕ to close. Only one thing is ever selected at a
  time, and switching views clears the selection.

---

## What is different about this copy

It lives in `contributor_folders/Anais/` and is served on **port 2719**, alongside the
team's app on 2718. Two differences:

1. **The Folger comparison tab**, described above. The team's app does not have it.
2. **It makes no network requests.** Glider data comes from `glider_frozen.parquet`, a
   snapshot taken 2026-08-28 holding three deployments and 10,452 observations. The team's
   app reads the live C-PROOF feed and will show different, fresher gliders. Verified by
   running the whole app with every outbound socket blocked: zero connection attempts.
   (The basemap tiles are the exception — the browser fetches those.)

To run it:

```bash
cd contributor_folders/Anais && ./serve_folger_app.sh
```

then open `https://hub.cryointhecloud.com/user/<you>/proxy/absolute/2719/`.

**If clicking stops working, hard-refresh the page** (Ctrl-Shift-R). The map keeps
rendering after the server restarts, but the connection behind it is dead, so clicks
silently do nothing. This is the single most confusing failure mode here.

---

## Where the numbers come from

| On the map | Source | Built by |
|---|---|---|
| Satellite squares | NOAA CoastWatch geo-polar blended SST | `data/sst/` → `data/sst_barkley_layer.geojson` |
| Live glider dots | C-PROOF, frozen 2026-08-28 | `glider_frozen.parquet` (this folder) |
| Historical orange dots | C-PROOF delayed-mode, gridded | `data/build_historical_tracks.py` |
| Folger + canyon markers | Ocean Networks Canada | `data/build_climatology_sites.py` |
| Climatology plots | ONC records | `contributor_folders/Dwight/onc_climatology.py` |
| The comparison figure | satellite + both ONC sensors | `data/sst_folger_compare/make_comparison.py` |

Deeper detail: `data/README.md` for the archives, `data/sst_folger_compare/README.md` for
the comparison's full limitations, `README.md` in this folder for how this copy was built.
