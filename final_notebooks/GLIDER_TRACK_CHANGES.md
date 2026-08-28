# Glider track changes — what the map draws, and what it refuses to draw

Five changes to how `Real-Time_Glider_WebApp.py` represents glider tracks and the fixed
sites beside them, plus the blank-page problem that used to block testing them — now
diagnosed and fixed. `REALTIME_WEBAPP_SUMMARY.md` describes
the app itself; this covers only what changed and why, with the measurements behind each
decision.

The first three land in `glider_lib.load_active_gliders()` and the app's
`map`/`glider_highlight` cells; the last two are in the app's `map` cell alone.

---

## Status: the blank page in the hub is diagnosed and fixed (2026-08-28)

Both apps came up blank when opened through the hub's marimo tile. The cause was not the
map, the widget, or the network: **`maplibre`, `anywidget` and `plotly` were missing from
the environment the kernel runs in**, so `nb_imports` raised `ModuleNotFoundError` and
every cell downstream of it — `map` included — never ran.

The reason that kept coming back after each server restart, and the reason installing them
"fixed it" only until the next one: the launcher runs `marimo edit --sandbox`, but both
apps' PEP-723 headers pin `[tool.marimo.venv] path = "/home/.pixi/envs/default"`, and
marimo 0.24 gives a configured venv precedence over an ephemeral sandbox. That env is the
shared conda base env, it sits on the **container overlay** (rebuilt from the image on
every restart), and marimo treats a configured venv as read-only, so it will not install
anything into it either.

Fix: install into the persistent user site, which is on the NFS home volume.

```bash
python -m pip install --user maplibre==0.3.6 anywidget plotly
```

A second, independent blank page was hiding behind that one, for anyone running without the
venv pin: the header's `dependencies` list was missing `requests`, `netCDF4`, `xarray` and
`gsw` — pulled in one module deeper by `glider_lib` → `data/cproof_https.py` →
`data/cproof_glider.py`, so nothing in the app file names them. `marimo export html
--sandbox` died with `No module named 'requests'` in `glider_data` and "An ancestor raised
an exception" in every cell after it. The header now lists them.

Both paths were then re-run and export clean, with no failed cells. Full write-up in
`MARIMO_APP_STATUS.md`, "Running it".

`Web_App_test.py` remains broken for its own separate, already-known reason: it reads
`NE_San_Diego_Trough_Aug_2022.csv`, which is gitignored and absent from a clean checkout,
so `ctd_data` raises `FileNotFoundError`. A fix for that sits in a local `git stash` and
has not been applied.

---

## 1. Tracks stop at the edge of the window they claim

`ACTIVE_DAYS` only ever decided *which deployments* to show. `snapshot()` then returned
each qualifying deployment's entire history, so a map labelled "active in the last day"
drew three weeks of track:

```
before  dfo-eva035-20260826   8,093 obs   08-06 16:58 .. 08-27 16:39   (21 days)
after   dfo-eva035-20260826     547 obs   08-26 20:48 .. 08-27 16:39   (~20 h)
```

The sharper version of the same bug: `dfo-hal1002-20260817` was still reporting, but its
newest fix *inside the study box* was 08-22 — it had since moved to (-128.18, 48.11), about
100 km west of the box. The map drew the five-day-old line anyway, and its endpoint read as
"the glider is here."

`load_active_gliders()` now cuts observations to `now - active_days` in every mode.
(`read_archive()` already did this; `snapshot()` did not — the two sources disagreed.)

**Consequence to expect:** a deployment with nothing inside the window drops off the map
rather than leaving a stale line. At `ACTIVE_DAYS=1` that means **one** glider, not two.
Widen to 7 and both return, each trimmed:

```
active_days=7   dfo-eva035-20260826   2,273 obs   08-21 04:36 .. 08-27 16:39
                dfo-hal1002-20260817  2,704 obs   08-20 20:43 .. 08-22 18:57
```

## 2. The selected track is highlighted

Every track was the same orange, so with two gliders in the water nothing indicated which
one the sidebar curtain plot belonged to. Unselected tracks are now slate
(`LINE_COLOR: "#37474f"`) and the selection is magenta (`SELECTED_COLOR: "#e5308f"`).

The selection colour was that same orange until 2026-08-28, when it was measured against
the basemap it is drawn on: `#f4a261` clears only **1.20:1** against the Esri tiles' own
water (`#a8c9e8`), so a selected track barely separated from the sea. `#e5308f` clears
**2.37:1** — the bar the historical ramp was built to — and is a different hue from that
ramp, which matters in the legend where the two swatches sit two lines apart.

The mechanism matters because **the `map` cell must never re-run** — rebuilding it forces a
new widget into a live browser session and breaks the mount. So the highlight is a
data-driven MapLibre paint expression keyed on the `deployment` property every feature
already carries:

```python
["case", ["==", ["get", "deployment"], selected], SELECTED_COLOR, LINE_COLOR]
```

It is baked into the initial style with `selected = ""`, a sentinel matching nothing. A new
`glider_highlight` cell — downstream of `click_plot`, so reading `map_widget` does not
re-run `map` — pushes an updated expression via `set_paint_property` on each click, for both
the line layer and the segment markers.

Keying on the deployment name means **clicking any segment lights the whole transect**, not
just the piece under the cursor.

*Known limit:* those calls go out as transient comm messages rather than synced widget
state, so after a full page reload nothing is highlighted until the next click. It degrades
to "no highlight", never to a broken map.

## 3. Frozen positions are not plotted at all

A glider only gets a real fix when it surfaces, so the same coordinates repeating across the
samples of one dive is ordinary — those runs last a couple of minutes. A position repeating
*identically* for hours is something else: the position has stopped being reported. A land
or bench simulation, a recovered glider still emitting its last fix, a stuck GPS. The
coordinates no longer say where anything is, and plotting them puts a convincing marker
where nothing was measured.

The two cases separate cleanly. Across the four C-PROOF deployments in the Barkley box over
30 days (measured 2026-08-27):

| hold duration | runs | observations |
|---|---|---|
| ≤ 0.25 h | 27,392 | 27,398 |
| 0.25–24 h | **0** | 0 |
| > 24 h | 1 | 3,897 |

That single outlier is `dfo-eva035-20260713` repeating one fix for **141.35 h** across 3,897
observations, 07-29 18:39 → 08-04 16:00. Nothing at all falls in between, so the 8 h default
(`MAX_HOLD_HOURS`) sits in a two-order-of-magnitude empty band and its exact value is not
delicate.

New `glider_lib.mask_held_positions()`, applied **before** the window trim — a stuck fix is
diagnosed from how long it runs in the record as a whole, and trimming first would show only
the tail of a long hold and could leave it looking short enough to keep.

**Only zero movement is masked.** A glider drifting at the surface still moves with the
current — 0.13–0.16 km/h over 9–14 h stretches in this same record — which is a real
observation and is deliberately kept.

**Consequence to expect:** at `ACTIVE_DAYS=30`, `dfo-eva035-20260713` disappears entirely.
Every one of the 3,897 observations it contributes to a 30-day window *is* the frozen fix,
so there is nothing left to draw.

## 4. The live deployment is drawn as points, not a line (2026-08-28)

Same reasoning as the historical layer: a line has to decide what happened between two
fixes, and nothing in this product says. The live frame is 30-second observations whose
positions are dead-reckoned between GPS fixes — roughly 20 m apart — so at map zoom the
points still read as a continuous trail, and zooming in shows what was actually sampled
instead of a drawn-in path.

Retiring the line also retired `MAX_GAP_DEG`. It existed only to stop a LineString
drawing a straight connector across a real gap — a line that looked clickable but had no
data near it. Points cannot draw a connector, so there is no threshold left to tune.

**These are not surfacings.** The live timeseries does carry `profile_index`, but
`snapshot()` returns exactly `cproof_glider.COLUMNS` — an invariant it shares with the
archive path — so the frame has no profile key by the time the app sees it. Picking
surfacings by a shallow-depth cut was measured instead, and rejected: on
`dfo-eva035-20260826`'s last day it gives

| cut | surfacing events |
|---|---|
| ≤ 1 m | 4 |
| ≤ 2 m | 8 |
| ≤ 3 m | 9 |
| ≤ 5 m | 10 |
| ≤ 10 m | 9 |

— not even monotonic in the threshold, because a deeper cut merges adjacent events. A
knob that quietly changes what the map claims is the thing points were chosen to avoid.

## 5. Folger sites are greyed live, black historical (2026-08-28)

The two ONC sites now change colour with the view: grey (`#9aa3ab`) over the real-time
view, where a reporting glider is the subject, and black (`#0b0b0b`) over the historical
one, where the moorings are the only continuously-present instruments on the map. It is a
`circle-color` paint property, pushed from `historical_toggle_visibility` exactly like the
glider highlight.

They were briefly drawn as anchor-shaped DOM markers instead. That failed in the browser
and is worth recording, because it rules out a whole class of ideas here.

**The app's own CSS cannot reach anything inside the map widget.** marimo renders its UI
plugins into a shadow root, so a `.folger-anchor` rule in the `map` cell's `<style>` never
matched the marker elements MapLibre creates inside that root — not the mask, not the
colour, not the rule hiding MapLibre's default pin. The markers rendered as MapLibre's own
blue teardrops in both views. The Python side was correct and the export looked right;
only a real browser showed it.

So anything drawn on this map has to be coloured by MapLibre itself — layer paint
properties, or a Marker's own `color` option. And an *icon* is out of reach separately: a
symbol layer needs `glyphs` (text) or `sprite` (icons) in the style, both URLs to files
this app has nowhere to serve from, and the anchor character U+2693 = 9875 is absent from
the only glyph server reachable from here (`tiles.openfreemap.org` carries two font
stacks; 54 glyphs in the 9728–9983 range, no 9875). A missing glyph draws nothing at all,
silently.

---

## Verified

Run, not assumed:

- App runs clean as a script; `marimo run` and `marimo edit` both serve 200 with no errors.
  (Not verified in the hub — see Status above.)
- The `["case", ...]` expression survives `Layer` construction and `construct_basemap_style`
  unmangled; `set_paint_property` emits `setPaintProperty` for both layers; deselecting
  sends the match-nothing form.
- Every rendered feature's `deployment` value matches a loaded record, so no click can fail
  to highlight. Selecting `dfo-eva035-20260826` lights all 3 of its gap-split segments.
- Masking on live data removes exactly the 141 h hold (3,897 observations) and nothing else;
  the other three deployments lose zero rows, and the 0.133 km/h drift on 08-16 survives.
  Longest surviving hold anywhere afterwards: 0.03 h.
- `mask_held_positions` edge cases: empty frame passes through, `max_hold_hours=None`
  disables, a 7 h hold is kept while a 24 h one is fully removed, deployments are isolated
  from each other, and a duplicated index does not mask unrelated rows.
- Gap-splitting still holds after trimming — no drawn step exceeds `MAX_GAP_DEG`.
- PR #11's curtain-plot latitude fix is intact and exercised on this branch: a curtain built
  through the app's own path returns `camera.eye = (1.25, -1.25, 1.25)`.

## Still open

Found during review, deliberately not addressed here:

1. **`MODE="realtime"`/`"delayed"` skips mission collapsing.** Those branches call
   `read_archive()` directly, which never collapses recovered-and-redeployed directories. At
   `active_days=60` the archive returns both `dfo-eva035-20260713T0000` and
   `dfo-eva035-20260806T0000`, sharing **7,007 identical positions** drawn one on top of the
   other. `MODE="live"` is correct — `snapshot()` → `available_now()` → `collapse_missions()`.
2. **The gap split is spatial only.** A segment can span a 79.8 h internal time gap and still
   be drawn as one unbroken line, because the glider drifted less than `MAX_GAP_DEG` across
   it. The geometry is nearly right; the implied "we observed this continuously" is not.
3. **`click_plot` resolves to the first deployment in range, not the nearest.** Where two
   tracks overlap near the Barkley mouth, clicks always resolve to whichever sorts first.
4. **Flat-degree thresholds are anisotropic.** Both `MAX_GAP_DEG` and `_TOLERANCE_DEG` are
   5.57 km north–south but 3.69 km east–west at 48.5°N. Observed max steps are 3.9–5.5 km,
   right on that boundary, so this is active rather than theoretical.
5. **The tracked archive double-counts.** `data/cproof_glider_realtime.nc` holds 5,391 rows
   duplicated between the two eva035 deployment IDs; the dedup in `data/cproof_glider.py` is
   keyed on `["deployment", "time", "depth"]` and cannot catch a cross-deployment duplicate.
   Affects anything reading that archive, not just this app.

6. **Highlight, view switch and site colour do not survive a page reload.** All three are
   post-render sends, which the widget does not replay. There is another path — calls made
   before render with `use_message_queue(False)` land in the synced `calls` trait, which
   the front-end replays on every `map.on("load")` — but using it for state that *changes*
   would mean rewriting the whole `calls` list on each change rather than appending. Not a
   one-liner, and left alone. All three degrade to the baked-in default, which is the
   real-time view, so a reload lands somewhere coherent.
