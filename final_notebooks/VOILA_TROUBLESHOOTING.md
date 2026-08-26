# Launching `Glider_Map_App.ipynb` with Voila — troubleshooting notes

Two URLs that look reasonable will 404. Both failures are explained below, along with the
two working options.

## What went wrong

**`http://localhost:8866/voila/render/final_notebooks/Glider_Map_App.ipynb`**
`localhost` only resolves inside the JupyterHub pod itself. A browser running outside the
pod (i.e. your actual laptop browser) has nothing listening on its own port 8866, so this
was never going to reach the server — it needs to go through the hub's proxy instead.

**`https://hub.cryointhecloud.com/user/blimersonalysts/voila/render/final_notebooks/Glider_Map_App.ipynb`**
Two separate bugs here:

1. **Wrong path.** The running Jupyter server's root directory is `/home/jovyan`
   (confirmed via `jupyter server list`), and the notebook lives at
   `ohw26_proj_BarkleyScope/final_notebooks/Glider_Map_App.ipynb` relative to that root —
   not `final_notebooks/Glider_Map_App.ipynb`.
2. **Voila's server extension isn't loaded into the live server process.** `voila` was
   `pip install`ed *after* the Jupyter server was already running, and Jupyter server
   extensions only load at server startup. Confirmed directly: even the bare
   `/voila/tree` endpoint 404s against the live server right now, despite
   `jupyter server extension list` reporting `voila.server_extension` as "enabled" in
   config. Config says it should load; the running process just hasn't picked it up yet.
   It needs a server restart.

## Fix 1 — use the existing standalone `voila` process (no restart needed)

There's already a `voila Glider_Map_App.ipynb` process running standalone on port 8866
(started from a terminal). Reach it through the hub's **generic port-proxy**, which is
already used elsewhere in this environment for the same reason — see
`DASK_DISTRIBUTED__DASHBOARD__LINK={JUPYTERHUB_SERVICE_PREFIX}proxy/{port}/status` in the
env, which follows the identical pattern for the Dask dashboard:

```
https://hub.cryointhecloud.com/user/blimersonalysts/proxy/8866/
```

**Important:** use the bare proxied root — do *not* append `/voila/render/Glider_Map_App.ipynb`.
`voila <notebook>` (single-notebook mode) serves the rendered app directly at `/`; the
`/voila/render/<path>` route is only meaningful for Voila's tree-mode server (Fix 2 below,
which serves a whole directory rather than one fixed notebook). Hitting
`/voila/render/Glider_Map_App.ipynb` against a single-notebook-mode process 302-redirects
to `/voila/files/voila/render/Glider_Map_App.ipynb` and 403s — confirmed directly against
the running process. This was wrong in an earlier version of this doc.

If that process isn't running anymore, restart it from a JupyterLab terminal — **with
`--base_url` set to the proxy path**, not just `voila notebook.ipynb`:

```bash
cd ~/ohw26_proj_BarkleyScope/final_notebooks
voila --no-browser --port=8866 --base_url=/user/blimersonalysts/proxy/8866/ Glider_Map_App.ipynb
```

Then use the same proxy URL above. If 8866 is taken, Voila will pick another port —
substitute that port into *both* the `--base_url` value and the URL you visit.

### Why `--base_url` matters (page loads, then hangs on "Executing N of N")

Without `--base_url`, Voila's page emits root-absolute asset links —
`src="/voila/static/voila.js"`, `href="/voila/templates/lab/static/index.css"`, etc.
Through the proxy, the browser requests those at
`https://hub.cryointhecloud.com/voila/static/voila.js` (the proxy prefix gets stripped
because the path starts with `/`), which 404s — that request never reaches port 8866 at
all. `voila.js` is the script that drives cell execution and the progress indicator, so
the page renders its static HTML shell, the execution counter ticks up as cells run
server-side, and then it hangs indefinitely once every cell is done, because the script
that would report completion and hand control to the live kernel never loaded. Confirmed
by diffing the served HTML's asset links with and without `--base_url` set — without it
they're `/voila/...`; with it they're correctly
`/user/blimersonalysts/proxy/8866/voila/...`.

## Fix 2 — restart the Jupyter server so Voila loads as a proper extension (cleaner long-term)

JupyterHub control panel → **Stop My Server** → start it again. This reloads the Jupyter
server process with `voila` registered as a server extension, after which the simpler,
no-manual-process URL works directly (full path from `/home/jovyan`, unlike Fix 1):

```
https://hub.cryointhecloud.com/user/blimersonalysts/voila/render/ohw26_proj_BarkleyScope/final_notebooks/Glider_Map_App.ipynb
```

**Caveat:** stopping/restarting your server kills the standalone `voila` process from
Fix 1 (PID tied to that terminal session), so after restarting, use this URL instead of
the `/proxy/8866/...` one.

https://hub.cryointhecloud.com/user/blimersonalysts/proxy/8866/
