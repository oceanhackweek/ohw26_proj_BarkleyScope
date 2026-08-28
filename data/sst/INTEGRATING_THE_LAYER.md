# Adding the satellite SST layer to the map app

For whoever owns the app. You need **two files** and about twenty lines. You do not need
anything else from `data/sst/` — no xarray, no netCDF reader, no import from this folder.

```
data/sst_barkley_layer.geojson     the temperature cells      2.1 MB
data/sst_barkley_points.geojson    one clickable marker        23 kB
```

The cells are the main event and come first. **The point layer is optional** — the map
works fine without it — so if you only want the temperature field, stop after "Captioning"
and ignore the last section.

Everything below is about that file. If something here disagrees with the file, trust the
file — it carries its own metadata.

---

## What is in it

One GeoJSON `FeatureCollection`, ~2.1 MB, holding **every day at once**. Currently 8,428
features: 1,204 cells × 7 days.

Each feature is one satellite cell, already clipped to the coastline:

```json
{
  "type": "Feature",
  "geometry": {"type": "MultiPolygon", "coordinates": [...]},
  "properties": {
    "sst": 15.68,          // degrees C
    "lat": 48.825,         // cell centre
    "lon": -125.275,
    "flagged": false,      // see "Flagged cells" below
    "date": "2026-08-25"   // which day this feature belongs to
  }
}
```

`date` on every feature is the important part: **one source, one layer, filtered by date** —
rather than seven sources you have to swap between.

The collection also has a top-level `properties` object that renderers ignore. It is there
so you do not have to guess at styling or captions:

| Key | What it is for |
|---|---|
| `maplibre_fill_color` | A ready-made MapLibre `interpolate` expression. Paste it in. |
| `color_range` | `[10.0, 20.0]` °C — fixed year-round, deliberately not autoscaled |
| `dates` | Every date present, ascending |
| `default_date` | The newest — what to show on load |
| `flag_note` | What `flagged` means and how to render it |
| `source_caveat` | The caption this data must carry |
| `geometry_note` | Why the cells are shaped the way they are |

---

## Minimal integration

### 1. Load it

```python
import json
from pathlib import Path

SST_LAYER = Path("data/sst_barkley_layer.geojson")
sst_layer = json.loads(SST_LAYER.read_text())
sst_meta = sst_layer["properties"]
```

### 2. Add one source and one layer

In whichever cell builds the map style. Note the layer is added **before** the glider
track and markers — it is a filled polygon and will bury anything drawn under it.

```python
from maplibre.layer import Layer, LayerType
from maplibre.sources import GeoJSONSource

sst_source = GeoJSONSource(data=sst_layer).to_dict()

sst_fill = Layer(
    id="sst",
    type=LayerType.FILL,
    source="sst-src",
    # Show one day. Without this you get all seven stacked on top of each other.
    filter=["==", ["get", "date"], sst_meta["default_date"]],
    paint={
        "fill-color": sst_meta["maplibre_fill_color"],
        # Flagged cells are real water, just not the water this map is about.
        # Faded rather than hidden -- visibly present, visibly not part of the story.
        "fill-opacity": ["case", ["get", "flagged"], 0.16, 0.72],
    },
)

style = construct_basemap_style(
    layers=[basemap_layer, sst_fill, *your_existing_layers],
    sources={"esri-ocean": ..., "sst-src": sst_source, **your_existing_sources},
    name="esri-ocean-basemap",
)
```

### 3. Let the user change the day

```python
date_picker = mo.ui.dropdown(
    options=sst_meta["dates"],
    value=sst_meta["default_date"],
    label="SST date",
)
```

and, **in a cell downstream of the one that builds the map**:

```python
map_widget.set_filter("sst", ["==", ["get", "date"], date_picker.value])
```

That is the whole integration.

---

## Two constraints this app already has

Both are already documented in `final_notebooks/MARIMO_APP_STATUS.md`. They are repeated
here because ignoring either produces a bug that looks like something else.

**1. Bake the source and layer in at construction.** The widget's post-construction
`add_source()` / `add_layer()` are transient comm messages that do **not** survive a page
reload. A layer added that way is there until someone refreshes, then silently gone. Pass
it to `construct_basemap_style(...)` instead, as above.

**2. Never re-run the cell that builds the map.** Forcing a fresh `MapWidget` into a live
session can black-screen the map. This is why the date picker is read in a *downstream*
cell calling `set_filter()`, and why the map cell above references
`sst_meta["default_date"]` rather than `date_picker.value` — referencing the picker there
would make the map cell depend on it and re-run on every change.

---

## Flagged cells

21 features have `flagged: true`. They are real water at ~19 °C in the north-east corner —
but Strait of Georgia water, on the **far side of Vancouver Island**, not reachable from
the open Pacific across this grid. Drawn at full strength they read as a hot patch in the
study area.

The `fill-opacity` expression above fades them to 0.16. Do not filter them out: they are
data, and hiding them silently is worse than showing them muted.

---

## Captioning

This is a satellite **analysis**, not a measurement of the water. Put
`sst_meta["source_caveat"]` somewhere visible — a legend footnote is enough. It reads:

> Near-real-time L4 analysis, about two days behind. Every step is labelled 'final'
> because the product publishes once, not because it has been quality-controlled.

Two more things worth a line in the legend if you have room:

- **The colour scale is fixed at 10–20 °C year-round**, deliberately. Autoscaling per day
  would repaint the map as the user scrubbed dates, making unchanged water appear to change
  temperature.
- **Cells are ~5.6 × 3.7 km.** The value is a 5 km measurement even though the shape now
  follows the coastline.

---

## Where the file comes from

`.github/workflows/refresh-sst.yml` rebuilds it daily and commits it, so the copy on `main`
is current. To rebuild by hand:

```bash
python data/sst/export_layer.py
```

If your app is not Python — or is not in this repo — read it straight from GitHub:

```
https://raw.githubusercontent.com/oceanhackweek/ohw26_proj_BarkleyScope/main/data/sst_barkley_layer.geojson
```

---

## Gotchas

- **`date` is a string**, `"2026-08-25"`. Compare as a string in the filter.
- **Geometry is `MultiPolygon`**, not `Polygon` — cells are clipped to the coastline, so a
  coastal cell is several pieces. Fine for a fill layer; matters if you hand the geometry to
  something that assumes single polygons.
- **Do not autoscale the colours.** See above.
- **Do not assume seven days forever.** Read `sst_meta["dates"]`; the window is a rolling
  count of the newest *available* steps, and the product occasionally skips a day.
- **The file is ~2.1 MB.** Fine baked into a style; worth knowing if you are shipping it to
  a browser over a slow link.
- **Coordinates are `[lon, lat]`**, per the GeoJSON spec — the reverse of how you say it out
  loud.

---

## The clickable point — `sst_barkley_points.geojson`

Optional, and independent of everything above. One Point feature at **Folger Passage**,
carrying its own history. 23 kB.

### Draw the marker

```python
points = json.loads(Path("data/sst_barkley_points.geojson").read_text())

points_source = GeoJSONSource(data=points).to_dict()

points_layer = Layer(
    id="sst-points",
    type=LayerType.CIRCLE,
    source="points-src",
    paint={"circle-radius": 6, "circle-color": "#ffffff",
           "circle-stroke-width": 2, "circle-stroke-color": "#0b1a2b"},
)
```

Add it **after** the SST fill in the layer list, or the fill will cover it.

### What the popup shows

The feature's properties hold two ready-made series. Nothing needs recomputing:

| Field | Feeds | Shape |
|---|---|---|
| `daily` | **Plot A**, raw SST | `[{date, sst_C}, ...]` — ~373 points |
| `monthly` | **Plot B**, anomalies | `[{month, mean_C, n, ok, clim_C, anom_C, partial}, ...]` |
| `climatology` | Plot B's baseline | `[{calendar_month, clim_C, std_C, n_years}, ...]` |
| `anomaly_thresholds` | Plot B's dashed rules | `{"90": …, "95": …, "99": …}` — recomputed each refresh, so read them rather than hardcoding |

Two stacked panels sharing an x-axis: raw SST on top, `anom_C` as bars below. A worked
example is `preview_points.py` in this folder — it draws exactly these two panels from
exactly these fields, so read it rather than reverse-engineering the file.

### Four things to say on the figure

These are in the collection's `properties` as ready-made sentences. They matter more than
usual here, because a time series invites conclusions a single map does not:

- **`cell_caveat`** — one 5 km cell covers *both* Folger stations, which are 611 m apart.
  The marker sits at the cell centre, on neither instrument.
- **`depth_caveat`** — this is skin temperature. The stations sit at 23 m and ~96 m. It is
  **not** a proxy for what they record.
- **`baseline_caveat`** — the climatology spans 6–8 years, not the 30 a standard baseline
  assumes. Anomalies are indicative of this record, not of the climate.
- **`sampling`** — older months rest on ~4 weekly samples, recent ones on ~30 daily.
  Unbiased either way, but less precise; each month's `n` says which it is.

### Gotchas specific to the point layer

- **`partial: true`** marks the current, incomplete month. It creeps upward all month.
  Render it distinctly — hatched, faded, whatever — or a half-month reads as a finished one.
- **`mean_C`, `clim_C`, `anom_C` can be `null`** where a month lacked coverage. `ok` tells
  you; do not assume a number is there.
- **`daily` is deliberately sub-sampled** — weekly through the record, daily for the last
  7 days. That is not a bug, and it is why the recent end looks denser.
- **The series is not continuous with the cells layer.** The point covers 2019 → now; the
  cell layer covers the last 7 days. They answer different questions.

## If something looks wrong

Run the checks before assuming the layer is at fault:

```bash
python data/sst/verify_sst.py
```

59 checks, including that the exported file still matches the archive it came from. If they
pass and the map still looks wrong, the problem is in the integration rather than the data,
and `data/sst/preview_map.py` renders the same cells with the same colours into a standalone
HTML file you can compare against.
