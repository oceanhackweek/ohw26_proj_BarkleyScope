<!--
Authors: Anais Gentilhomme and Claude (Anthropic)
Last modified: 2026-08-28
-->

# Working locally without breaking anyone else

**Short answer: nothing you change on your own machine can reach a collaborator until you
run `git push` AND they run `git pull`. Editing the app locally is safe. Your own running
server will not even notice.**

This note exists because "will my edit break the app for everyone?" is the question that
stops people experimenting, and the answer is always no — but the reasons are worth seeing
laid out once.

---

## The three islands

Everyone runs their own copy of everything. The only thing that connects them is git.

```
  YOUR HUB ACCOUNT                     GITHUB                  A COLLABORATOR'S ACCOUNT
  /user/agentilhomme                                           /user/smcclish
 ┌────────────────────────────┐   ┌────────────────┐   ┌────────────────────────────┐
 │ ~/ohw26_proj_BarkleyScope  │   │  main          │   │ ~/ohw26_proj_BarkleyScope  │
 │   final_notebooks/         │   │                │   │   final_notebooks/         │
 │     Real-Time_Glider_      │   │  the clone     │   │     Real-Time_Glider_      │
 │       WebApp.py   ← EDIT   │   │  source        │   │       WebApp.py            │
 │   data/                    │   │                │   │   data/                    │
 │                            │   │                │   │        ↑ THEIR copy,       │
 │  marimo server  :2718      │   │                │   │  marimo   never touched    │
 │                            │   │                │   │    server  :2718           │
 └────────────────────────────┘   └────────────────┘   └────────────────────────────┘
              │                           ▲                          │
              └───── git push ───────────►│◄───── git pull ──────────┘
                        ▲                                  ▲
                  the ONLY way out                  the ONLY way in
```

Their `:2718` is **not** your `:2718`. Same port number, different container. Each hub user
gets their own singleuser server, and the proxy URL carries the username:

```
https://hub.cryointhecloud.com/user/agentilhomme/proxy/absolute/2718/
                                    ^^^^^^^^^^^^
                                    yours only — nobody else can reach it,
                                    and you cannot collide with theirs
```

---

## Your running server does not re-read the file

This surprises people. `marimo run` loads the notebook **once, at server start**, and holds
it in memory. Verified in marimo's own source — `_server/session_manager.py:129`:

```python
source_code = None if mode == SessionMode.EDIT else _get_code()
```

`RUN` mode captures the code at construction. Not per browser tab, not per session.

```
 server start   ./serve_app.sh 2718
                    │
                    ├── reads Real-Time_Glider_WebApp.py ──► held in memory ──┐
                    │                                                          │
                    └── serving ──────────────────────────────────────────────►│
                                                                               │
 later          you edit the .py on disk  ───✗─── never re-read ───────────────┘
                                                 (serve_app.sh passes no --watch)
```

So while a server is up you can rewrite the whole app and it will carry on serving exactly
what you last saw working. **Only a restart picks up Python changes.**

### The one asterisk: data files

Python source is read once, but the *cells* run per session — so a fresh browser session
re-executes the data cells and re-reads whatever is on disk.

| You change… | Running server shows it? |
|---|---|
| `final_notebooks/Real-Time_Glider_WebApp.py` | **No.** Restart required. |
| `data/*.geojson`, a committed `.png` | **Yes**, on a new browser session |

Still only your server, your checkout. No route to anyone else either way.

---

## Running the original and your version side by side

`serve_app.sh` hardcodes the app filename — only the port is an argument:

```bash
PORT="${1:-2718}"
APP="$HERE/Real-Time_Glider_WebApp.py"
```

So two servers started from the same folder serve the *same file*. To get a genuine
before/after, check out a second copy with `git worktree` and serve that:

```bash
git worktree add ../barkley-main main
../barkley-main/final_notebooks/serve_app.sh 2719   # pristine main,  port 2719
final_notebooks/serve_app.sh 2718                   # your edits,     port 2718
```

`serve_app.sh` resolves the app relative to its own location, so each serves its own
checkout. Clean up later with `git worktree remove ../barkley-main`.

```
 ┌──────────────────────────────┐        ┌──────────────────────────────┐
 │ ~/ohw26_proj_BarkleyScope    │        │ ~/barkley-main               │
 │   your branch, your edits    │        │   main, untouched            │
 │        :2718                 │        │        :2719                 │
 └──────────────────────────────┘        └──────────────────────────────┘
        both live at once, both only reachable by you
```

---

## What is actually on `main` right now

Being precise matters here — "I pushed something" is not the same as "I changed the app".

| Pushed by the sst_folger_compare work | On main? |
|---|---|
| `data/sst_folger_compare/` — scripts, docs, 2 figures | yes |
| `data/folger_compare_points.geojson` | yes |
| doc edits to `data/sst/INTEGRATING_THE_LAYER.md` | yes |
| **`final_notebooks/Real-Time_Glider_WebApp.py`** | **no — byte-identical to main** |

PR #18 was 8 files, none under `final_notebooks/`. Files were added *next to* the app; the
app itself was not modified. Anyone pulling gets a new folder and an unchanged app.

---

## Checking any of this yourself

```bash
# Have I actually changed the app, or only added files next to it?
git diff --quiet origin/main HEAD -- final_notebooks/Real-Time_Glider_WebApp.py \
  && echo "identical to main" || echo "differs from main"

# What would a collaborator receive if they pulled right now?
git diff --name-only origin/main HEAD

# Is anything of mine unpushed?
git status -sb            # "ahead N" = N commits only you have

# Which app file is the running server actually serving?
ps -o pid,etime,args -p "$(pgrep -f 'marimo run' | head -1)"
```

The habit worth keeping: **`git diff --name-only origin/main HEAD` before you worry.** If
the file you are anxious about is not in that list, it cannot affect anybody.

---

## Rules of thumb

- **Edit freely.** Local edits are invisible to everyone, including your own running server.
- **A push is the moment it becomes real.** Nothing before that point is shared.
- **Pushing a branch is not merging.** `git push origin <branch>` publishes a branch nobody
  is running. Only merging to `main` puts it in the path of collaborators' next pull.
- **Prefer a branch over a private copy of someone else's file.** A copy of a file under
  active development diverges within a day and can never be merged; a branch produces a
  reviewable diff. Use a worktree when you want to see both versions running.
- **Restart the server after Python edits.** Ctrl-C and re-run `serve_app.sh`; no `--watch`.
