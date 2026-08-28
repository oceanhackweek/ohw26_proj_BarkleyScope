<!--
Authors: Anais Gentilhomme and Claude (Anthropic)
Last modified: 2026-08-28
-->

# Anais's version of the map app

A private copy of the team's marimo app with **one thing added**: clicking either Folger
marker now offers the SST comparison figure as a second tab, next to Dwight's climatology.

**This is a demo version, not a fork intended for merging.** It is deliberately separate:
nothing here edits `final_notebooks/`, and nothing in `final_notebooks/` can break it.

## Running it

```bash
./serve_folger_app.sh          # port 2719 by default
```

Then open `https://hub.cryointhecloud.com/user/<you>/proxy/absolute/2719/`.

Port **2719**, not 2718, so this runs alongside the team's app without colliding. The link
is live only while that command runs and only for you — it is proxied through your own
hub server, not public. See `data/WORKING_LOCALLY.md`.

## What's in the folder

| File | Role |
|---|---|
| `BarkleyScope_folger.py` | the app — a copy of `final_notebooks/Real-Time_Glider_WebApp.py` plus the change below |
| `glider_lib.py` | copy of the team's helper, so this folder is self-contained |
| `glider_frozen.parquet` | the glider data, frozen 2026-08-28 — see "Frozen data" |
| `serve_folger_app.sh` | starts the app on 2719 |
| `GUIDE.md` | **how to read the map** — every dot, both views, what the figure does and does not show |
| `README.md` | this file |

Copied from `origin/main` at commit `3fec0ed`. Both `.py` files were byte-identical to the
team's at that point; the diff since is only what is described here.

## The change

**Before:** click a Folger marker in the Historical view → Dwight's day-of-year climatology.

**After:** the same click → a two-tab panel.

```
┌──────────────────────────────┐
│ Folger Pinnacle        25 m  │
│ ┌────────────┬─────────────┐ │
│ │ Climatology│ vs.satellite│ │   Climatology is the default
│ └────────────┴─────────────┘ │
│    [the selected figure]     │
└──────────────────────────────┘
```

The second tab is `data/sst_folger_compare/sst_vs_folger_four_panel.png` — satellite skin
SST against both ONC depths, four panels. Both Folger markers show the same figure, because
it is about the pair plus the satellite cell covering both, not about one depth.

Four edits, all in `BarkleyScope_folger.py`:

1. `config` — two new `CONFIG_MAP["HISTORICAL"]` entries pointing at the figure and the
   layer its caveat sentences come from.
2. `folger_compare_data` — a new cell that resolves the figure path and parses the caveats.
   A cell of its own because `map` depends on `historical_data`, and `map` must never re-run.
3. `site_panel` — the tabbed branch, for `group == "folger"` only. Six of eight sites keep
   the panel exactly as it was.
4. `plot_overlay` — one line: the dock width now comes from `site_panel`.

`click_plot` is **not** touched. It already resolves both Folger markers to `selected_site`
with `group == "folger"`; nothing about the hit-test needed to change.

## Three things that are load-bearing

Each of these was found by reading marimo's source, and each will look like a pointless
detail until it breaks.

- **The second tab is lazy, and `mo.lazy` is given a *callable*.** `mo.ui.tabs` renders every
  tab's HTML at construction, so a pre-built figure would base64 the 461 kB PNG on every
  Folger click whether or not the tab is opened — 901 kB against 286 kB. Measured both ways.
  `mo.ui.tabs(lazy=True)` does **not** help: it wraps already-built objects.
- **The `<style>` block is a sibling of the tabs, never inside one.** marimo unmounts the
  inactive tab's content entirely, so CSS living in tab 1 disappears when you open tab 2, and
  the second figure renders unstyled with its "?" text expanded inline.
- **The tabs element is named `_tabs`, privately, and nothing reads `_tabs.value`.** marimo
  ignores single-underscore names when working out which cells refer to a UI element, so a
  tab click re-runs nothing. A public name would silently re-encode both PNGs on every click.

## Frozen data

**This app never touches the network.** The team's version calls `load_active_gliders(mode="live")`,
which fetches from C-PROOF's server on every cold start. This one reads `glider_frozen.parquet` —
a snapshot taken once, on **2026-08-28**, holding 3 deployments and 10,452 observations, newest
2026-08-28 18:18 UTC.

Verified by running the whole app with every outbound socket blocked: **0 connection attempts**.

Note `MODE: "realtime"` in `CONFIG_MAP` is now inert for the live view — `glider_data` reads the
frozen file regardless. It was tried first and rejected: that mode reads the committed archive
`data/cproof_glider_realtime.nc`, whose newest observation was 5 days old, so it showed one stale
deployment where the live feed had three current ones.

**The one exception is the basemap.** Map tiles come from `server.arcgisonline.com`, fetched by the
browser, not by Python. With no internet the map renders on a blank background with all the data
still drawn on top.

### Refreshing the freeze

This is a network fetch. From this folder:

```python
import sys; sys.path.insert(0, ".")
from glider_lib import load_active_gliders
import pandas as pd

recs = load_active_gliders(mode="live", active_days=14)
frames = []
for r in recs:
    df = r["df"].copy()
    df["deployment"], df["glider"] = r["deployment"], r["glider"]
    frames.append(df)
pd.concat(frames, ignore_index=True).to_parquet("glider_frozen.parquet", index=False)
```

`active_days=14`, not 1: the held-position mask drops a glider that sat still for 45 h, and at
1, 3 or 7 days the result came back empty.

## Path differences from the original

This file sits two directories deep instead of one, so every anchor shifted:

| | `final_notebooks/` | here |
|---|---|---|
| repo root | `__file__.parent.parent` | `__file__.parents[2]` |
| data paths in `CONFIG_MAP` | `"../data/..."` | `"data/..."` |

Same convention as `contributor_folders/Dwight/onc_climatology.py`, which is at the same depth.

## Keeping up with the team app

Not automatic, and not intended to be. To see what has changed since the copy:

```bash
diff <(git show origin/main:final_notebooks/Real-Time_Glider_WebApp.py) BarkleyScope_folger.py
```

That diff shows both their changes and mine mixed together — which is the price of a copy,
and was the accepted trade for total independence.
