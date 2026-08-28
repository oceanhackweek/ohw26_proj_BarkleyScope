<!--
Authors: Anais Gentilhomme and Claude (Anthropic)
Last modified: 2026-08-28
-->

# How to open the app

Two paths. **Path A** if you are on the OceanHackWeek JupyterHub. **Path B** if you are
on your own laptop, or the hub no longer exists.

Both need a terminal, once, to start the app. There is no way around that: this is a live
Python app, not a web page. GitHub can show you the files and the figures, but it cannot
run it.

> **Just want to see the science, not the app?** The figure is on GitHub and renders in the
> browser with no setup:
> `data/sst_folger_compare/sst_vs_folger_four_panel.png`

---

## Path A — on the JupyterHub

### What you need

- A login for `hub.cryointhecloud.com`
- Nothing installed on your own computer

### Steps

**1. Log in and start your server.**
Go to <https://hub.cryointhecloud.com> and sign in. If it asks, click **Start My Server**
and wait for JupyterLab to load.

**2. Open a terminal.**
In JupyterLab: **File → New → Terminal**. (Or the **Terminal** tile on the Launcher page.)

**3. Get the repository, if you do not have it.**

```bash
cd ~
git clone https://github.com/oceanhackweek/ohw26_proj_BarkleyScope.git
```

If the folder already exists, just update it instead:

```bash
cd ~/ohw26_proj_BarkleyScope && git pull
```

**4. Install the packages.** Only needed the first time, or after the hub has been
restarted and they have vanished:

```bash
python -m pip install --user marimo maplibre==0.3.6 anywidget plotly pandas numpy pyarrow
```

`--user` matters: it installs into `/home/jovyan/.local`, which survives a server restart.
Without it, packages go into the environment that gets wiped.

**5. Start the app.**

```bash
cd ~/ohw26_proj_BarkleyScope/contributor_folders/Anais
./serve_folger_app.sh
```

It prints a URL and then sits there. **Leave that terminal open** — closing it or pressing
Ctrl-C stops the app.

**6. Open it in your browser.** Replace `<you>` with your own hub username:

```
https://hub.cryointhecloud.com/user/<you>/proxy/absolute/2719/
```

For Anais that is:
`https://hub.cryointhecloud.com/user/agentilhomme/proxy/absolute/2719/`

> **The username must be yours.** These addresses are per-person. You cannot open a
> colleague's link, and they cannot open yours — same port number, different machines.

### To stop it

Press **Ctrl-C** in that terminal. Or, from any other terminal:

```bash
pkill -f BarkleyScope_folger
```

It also stops on its own whenever your hub server shuts down.

---

## Path B — on your own computer

Use this if the hub is gone, or you would rather work locally.

### What you need

- **Python 3.11 or newer** (built and tested on 3.14). Check with `python3 -V`.
- **git**
- A terminal: Terminal on macOS/Linux, PowerShell or Windows Terminal on Windows
- About 200 MB of disk for the repository

### Steps

**1. Clone the repository.**

```bash
git clone https://github.com/oceanhackweek/ohw26_proj_BarkleyScope.git
cd ohw26_proj_BarkleyScope
```

**2. Make a virtual environment.** Keeps these packages out of your system Python:

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows PowerShell
```

Your prompt should now start with `(.venv)`.

**3. Install the packages.**

```bash
pip install marimo maplibre==0.3.6 anywidget plotly pandas numpy pyarrow
```

Pin `maplibre==0.3.6`. Later versions change the layer API this app is written against.

**4. Start the app.** Note this is a *different command* from Path A — `serve_folger_app.sh`
adds a URL prefix that only makes sense behind the hub's proxy:

```bash
cd contributor_folders/Anais
marimo run BarkleyScope_folger.py --port 2719 --no-token
```

**5. Open it in your browser:**

```
http://localhost:2719
```

### To stop it

Press **Ctrl-C** in that terminal.

---

## Which packages, and why

Seven, and only seven. The app is frozen, so nothing that fetches data is required.

| Package | Needed for |
|---|---|
| `marimo` | the notebook/app runtime itself |
| `maplibre==0.3.6` | the map |
| `anywidget` | how the map talks to the browser |
| `plotly` | the 3D glider curtain plot |
| `pandas`, `numpy` | the data tables |
| `pyarrow` | reading `glider_frozen.parquet` |

**Not needed:** `xarray`, `netCDF4`, `gsw`, `requests`. Those are only used by the live
C-PROOF path, which this copy never calls. The team's app in `final_notebooks/` does need
them.

---

## If something goes wrong

**Clicking does nothing — no plots, no panels.**
Your page is stale: the app restarted and the connection behind it is dead. The map still
draws because it is already-delivered graphics. **Hard-refresh: Ctrl-Shift-R** (Cmd-Shift-R
on a Mac). This is the most common problem and it looks alarming.

**`ModuleNotFoundError: No module named 'maplibre'`** (or marimo, plotly, pyarrow)
The install step did not run, or ran into a different Python than the one starting the app.
On the hub, re-run step 4 with `--user`. Locally, check your prompt says `(.venv)`.

**The page will not load at all.**
Check the app is actually running — `pgrep -af marimo` should list it. If it is not, the
terminal running it was closed. On the hub, also check your hub server is still up.

**`Address already in use`.**
Something is already on that port. Use another: `./serve_folger_app.sh 2720`, then change
`2719` to `2720` in the URL.

**The map is blank/grey but dots still show.**
No internet. The background map tiles come from Esri over the network — the only thing this
app fetches. All the data still draws on top.

**The glider tracks look out of date.**
They are, deliberately. This copy reads a snapshot frozen 2026-08-28 and makes no network
requests. See `README.md` in this folder to refresh it.

---

## What next

- **`GUIDE.md`** (this folder) — what every dot on the map means, and how to reach the
  Folger comparison figure: switch to **Historical**, click **Folger Pinnacle** or
  **Folger Deep**, then the **vs. satellite** tab.
- **`README.md`** (this folder) — how this copy differs from the team's app.
- **The team's live app** — `final_notebooks/serve_app.sh`, port 2718. Same steps, but it
  fetches current glider data and has no comparison tab.
