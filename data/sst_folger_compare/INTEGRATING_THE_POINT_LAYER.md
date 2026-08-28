<!--
Authors: Anais Gentilhomme and Claude (Anthropic)
Last modified: 2026-08-28
-->

# Adding the Folger comparison point to the map app

For whoever owns the app. One clickable marker at Folger Passage; clicking it opens a
four-panel temperature figure. You need **one file**:

```
data/folger_compare_points.geojson     the marker and all three series     98 kB
```

You do not need anything else from `data/sst_folger_compare/` — no pandas, no xarray,
no import from this folder. The file carries its own data, its own colours, and its own
captions.

This is the same pattern as `data/sst/INTEGRATING_THE_LAYER.md`, and the same three
marimo rules apply. **Read that document first if you have not** — the constraints it
records about `map` never re-running are not repeated here in full.

If something below disagrees with the file, trust the file.

---

## What is in it

One GeoJSON `FeatureCollection` with **one Point feature**, at the midpoint of the two
Ocean Networks Canada instruments in Folger Passage:

```
[-125.28114, 48.81103]
```

Its `properties.series` is a **list of three**, in draw order:

| `key` | `label` | What it is |
|---|---|---|
| `satellite` | Satellite skin SST | the 5 km cell covering both stations, 2019– |
| `pinnacle` | Folger Pinnacle (25 m) | ONC in-water sensor, 2011– |
| `deep` | Folger Deep (98 m) | ONC in-water sensor, 2016– |

Each carries four ready-made fields. **Nothing needs recomputing:**

| Field | Shape |
|---|---|
| `daily` | `[{date, value_C}, ...]` — the raw line, thinned to weekly |
| `monthly` | `[{month, mean_C, n, ok, clim_C, anom_C, partial}, ...]` |
| `climatology` | `[{calendar_month, clim_C, std_C, n_years}, ...]` |
| `anomaly_thresholds` | `{"90": 0.7, "95": 0.84, "99": 1.01}` — recomputed each run, so read them |

plus `color` (a validated hex, see below), `label`, `depth_m`, `record`, `n_days`.

**It is a list, not three named fields, on purpose.** Loop it. Panel 1 overlays every
series' `daily`; then one anomaly panel per series, in order. A fourth depth later is a
data change, not an app change.

### The collection's own `properties`

Renderers ignore it. It is there so you never guess at styling or captions:

| Key | For |
|---|---|
| `title` | the figure heading |
| `palette` | `ink`, `muted`, `surface`, `bar`, `p90`, `p95`, `p99` — see "Colours" |
| `panels` | the panel order, as data |
| `series_order` | `["satellite", "pinnacle", "deep"]` |
| `anomaly_y_shared` / `anomaly_y_note` | **read this before scaling anything** |
| `gap_note` | **read this before drawing the raw lines** |
| `partial_note` | **read this before drawing the anomaly bars** |
| `baseline_caveat`, `depth_caveat`, `cell_caveat`, `source_caveat`, `sampling`, `threshold_caveat` | ready-made sentences for the figure |
| `supersedes` | see "Relationship to the existing point layer" |

---

## The marker

### 1. Load it

```python
import json
from pathlib import Path

# Anchor to this file, NOT the working directory -- the hub launches marimo from
# /home/jovyan, so a bare Path("data/...") resolves wrong. Same reason glider_lib.py
# and the sst_data cell both do this.
_path = Path(__file__).resolve().parent.parent / "data" / "folger_compare_points.geojson"
folger_layer = json.loads(_path.read_text())
folger_meta = folger_layer["properties"]
folger_feature = folger_layer["features"][0]
```

### 2. Add one source and one layer

In the cell that builds the map style. **After the SST fill in the layer list** — the
fill is opaque-ish and would bury a marker drawn under it.

```python
from maplibre.layer import Layer, LayerType
from maplibre.sources import GeoJSONSource

_folger_layer_spec = Layer(
    id="folger-compare",
    type=LayerType.CIRCLE,
    source="folger-compare-src",
    paint={"circle-radius": 7, "circle-color": "#ffffff",
           "circle-stroke-width": 2, "circle-stroke-color": "#0b1a2b"},
)

_basemap_style = construct_basemap_style(
    layers=[_esri_layer, _sst_fill, _glider_layer, _glider_point_layer,
            _folger_layer_spec],                      # <-- last: on top of everything
    sources={
        "esri-ocean": _esri_source.to_dict(),
        "sst-src": GeoJSONSource(data=sst_layer).to_dict(),
        "glider-track": ...,
        "glider-points": ...,
        "folger-compare-src": GeoJSONSource(data=folger_layer).to_dict(),
    },
    name="esri-ocean-basemap",
)
```

Baked in at construction, like everything else — `add_source()` / `add_layer()` after
construction are transient comm messages that do not survive a page reload.

---

## The click — this is the part that needs care

**`click_plot` currently cannot tell layers apart.** As written it takes
`map_ui.value["clicked"]`, scans `glider_records` inside a **0.05° box**, and takes the
**first deployment within tolerance**. It has no concept of which layer was hit.

0.05° is roughly 5.5 km. Any glider track passing within that of Folger Passage will
win the click before the marker is ever considered. So this is not an additive change —
it is a real edit to a cell smcclish and BLimer own. **Agree it with them first.**

The minimal version is to test the marker *before* the glider scan and return early:

```python
@app.cell(hide_code=True)
def click_plot(glider_records, map_ui, set_plot_closed, folger_feature):
    _clicked = (map_ui.value or {}).get("clicked") or {}
    _click_lon, _click_lat = _clicked.get("lng"), _clicked.get("lat")
    _TOLERANCE_DEG = 0.05

    def _near(lon, lat, lon2, lat2, tol=_TOLERANCE_DEG):
        return lon is not None and abs(lon - lon2) < tol and abs(lat - lat2) < tol

    # Marker first: it is a single point and a much smaller target than a track that
    # may cross the whole box. Tested at a tighter tolerance so it only wins an actual
    # click on the dot, and checked before the glider scan so a track passing within
    # 5 km of Folger cannot swallow it.
    _folger_lon, _folger_lat = folger_feature["geometry"]["coordinates"]
    folger_clicked = _near(_click_lon, _click_lat, _folger_lon, _folger_lat, tol=0.012)

    selected_glider_record = None
    if not folger_clicked:
        for _rec in glider_records:
            ...                                   # unchanged
    ...
    return selected_glider_record, folger_clicked
```

`0.012°` is about 1.3 km — comfortably larger than the drawn marker at any usable zoom,
comfortably smaller than the glider tolerance it now pre-empts.

If they would rather not touch that cell, the fallback is a **separate control** — a
checkbox or a button in the sidebar that opens the figure — and no click handling at
all. Less elegant, zero risk to their code, and it can ship first.

---

## Drawing the four panels

**Port `preview_compare_points.py` in this folder. Do not reverse-engineer the file.**

That script draws the exact figure from the GeoJSON alone — it imports nothing from this
repository, no `onc_folger`, no `sst_anomalies`, no pandas. If it runs, the layer is
sufficient; that is what it is for. `draw(feature, meta, path)` is the whole thing.

Four rules it follows that you must too:

### Nulls in `daily` are breaks, not values to skip

```python
xs = [d["date"] for d in s["daily"]]
ys = [float("nan") if d["value_C"] is None else d["value_C"] for d in s["daily"]]
```

`daily` carries explicit `value_C: null` entries wherever a record has a real outage.
Pinnacle has six, including **2017-06 to 2019-10 — 860 days**. Filter the nulls out and
the line joins across it, drawing two and a half years of water that was never measured.
In matplotlib, NaN breaks the line automatically. This is what `gap_note` says.

### One shared y-scale across all anomaly panels

```python
every = [m["anom_C"] for s in series for m in s["monthly"] if m["anom_C"] is not None]
lim = max(abs(min(every)), abs(max(every))) * 1.15
```

The satellite's anomalies really are smaller than the stations' — its 90th percentile is
+0.70 °C against Pinnacle's +0.94 °C. Autoscaling each panel independently would hide
that and make three different magnitudes look identical. `anomaly_y_shared` is `true` in
the file for this reason.

### `partial: true` is the in-progress month — draw it differently

```python
solid = [i for i, m in enumerate(rows) if not m.get("partial")]
part  = [i for i, m in enumerate(rows) if m.get("partial")]
# ...solid bars filled; partial bars hatched, facecolor="none"
```

Exactly one month per series carries `partial: true` — the one that had not finished
when the file was written. It is a third of a month and it creeps upward daily. Drawn
filled like the rest, a third of August reads as a finished August.

It is **shown but does not count**: excluded from the climatology and from the
percentile thresholds, and its `anom_C` is measured against a baseline it played no part
in setting. That last point is the reason this layer's satellite anomalies differ very
slightly (0.01 °C, two months) from `sst_barkley_points.geojson` — the older file lets
its partial August into the August bin, giving that bin `n_years: 8` where every other
month has 7.

Note that a partial month often has `mean_C: null` anyway — both ONC stations' trailing
months fall short of the 15-day rule, so only the satellite's actually plots.

### Thresholds are per-series

Each series carries its own `anomaly_thresholds`. Do not compute one set and apply it to
all three — the three distributions genuinely differ.

---

## Colours

Take them from the file: `series[i]["color"]` for the lines, `properties.palette` for
everything else.

They are Taylor Borgfeldt's, and they were **validated rather than chosen by eye** —
worst adjacent colour-vision-deficiency separation ΔE 16.3, worst normal-vision ΔE 19.6
(OKLab ×100, against floors of 8 and 15). Her `../folger_taylor/METHODS.md` decision 6
records the check.

Two consequences: don't substitute colours by eye, and **keep the numeric threshold
labels** — `p95` and `p99` fall below 3:1 contrast on the light surface, so colour must
never carry the meaning alone.

---

## What to say on the figure

These are ready-made sentences in `properties`. They matter more than usual here,
because three series on one axis invites a comparison the data does not support:

- **`depth_caveat`** — three different quantities sharing a location and a unit. The
  satellite is skin temperature; the stations sit at 23 m and ~96 m.
- **`baseline_caveat`** — each series is on its **own** baseline (satellite 2019–,
  Pinnacle 2011–, Deep 2016–), not a common one. A difference between panels may partly
  be the different baseline periods rather than the water.
- **`cell_caveat`** — one 5.6 × 3.7 km satellite cell covers both stations; its centre is
  ~2 km from the marker.
- **`threshold_caveat`** — the fixed percentiles are set mostly by autumn–winter
  variability. **Zero exceedances fall in Jun/Jul/Aug in any of the three series.** That
  is a property of the threshold, not evidence that summer marine heatwaves do not occur
  here.
- **`sampling`** — raw lines are weekly; the monthly means behind the anomaly panels use
  every daily value.

At minimum put `baseline_caveat` under the title, as `preview_compare_points.py` does.

---

## Relationship to the existing point layer

This **supersedes `data/sst_barkley_points.geojson`**. It carries that file's satellite
`daily` / `monthly` / `climatology` / `anomaly_thresholds` unchanged, and adds the same
four for both ONC stations.

**Integrate one or the other, not both.** They sit about 2 km apart and would render as
two markers on top of each other at any useful zoom, telling two versions of one story.

The older two-panel layer was never wired into the app, so there is nothing to remove —
just don't add it as well.

---

## Rebuilding

```bash
cd data/sst_folger_compare
python export_compare_points.py       # rewrites the .geojson from local files only
python preview_compare_points.py      # renders the reference figure from that .geojson
```

Neither touches the network. Inputs are the two ONC CSVs in `../folger/` and the
satellite history in `../sst/`, all already in the repo.

Unlike `sst_barkley_layer.geojson`, this is **not** on a refresh workflow — the ONC
exports are static files, so it only changes when someone re-downloads them or the
satellite history is extended.

---

## Gotchas

- **`value_C` can be `null`** in `daily`, and **`mean_C` / `clim_C` / `anom_C` can be
  `null`** in `monthly` where a month lacked coverage. `ok` tells you. Do not assume a
  number is there.
- **`month` is `"2026-08"`**, a string, not a date. `calendar_month` is an int 1–12.
- **Coordinates are `[lon, lat]`**, per the GeoJSON spec — the reverse of how you say it.
- **The panels do not span the same period.** Satellite starts 2019, Deep 2016, Pinnacle
  2011. On a shared axis the upper panels are empty on the left. That is deliberate;
  cropping to the shortest record would discard eight years of Pinnacle.
- **98 kB.** Fine baked into a style. Larger than the old point layer because it carries
  three series instead of one.
- **Don't autoscale the anomaly panels.** See above.
