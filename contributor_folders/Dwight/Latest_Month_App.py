# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "marimo>=0.24.0",
#     "matplotlib==3.11.1",
#     "netCDF4==1.7.4",
#     "numpy==2.5.2",
#     "onc==2.6.0",
#     "pandas==3.0.5",
#     "xarray==2025.9.0",
# ]
# [tool.marimo.venv]
# path = "/home/.pixi/envs/default"
# ///
#
# netCDF4 and xarray are not imported here directly -- they come in one module
# deeper, through latest_month -> onc_climatology, which reads the archived .nc
# downloads to get each site's depth, label and station position. Leaving them
# out of this list is invisible in the hub (whose kernel runs the configured
# conda env below, which has them) and fatal anywhere marimo builds an ephemeral
# venv from this list instead. That failure mode is documented at length in
# final_notebooks/MARIMO_APP_STATUS.md; this header exists so it cannot recur.
#
# [tool.marimo.venv].path pins the kernel to the hub's shared conda env. marimo
# treats a configured venv as read-only and will NOT install into it, so
# anything missing there has to go on the persistent user site:
#
#     python -m pip install --user <package>

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import sys
    from pathlib import Path

    import marimo as mo

    # latest_month.py and onc_climatology.py sit beside this file; marimo does
    # not put the notebook's own directory on sys.path.
    try:
        _here = mo.notebook_dir()
    except Exception:
        _here = Path(__file__).parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))

    import latest_month as lm

    return lm, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        # Latest month vs climatology

        Pulls the most recent window of seawater temperature from the **ONC API**
        for each Barkley Canyon and Folger Passage mooring, and scores every hour
        of it against that site's own day-of-year climatology.

        The climatology is the one built by `onc_climatology.py` from the archived
        downloads; the scoring is its `classify_series`, unchanged. What is new
        here is that a whole window is fetched live, so the comparison is a curve
        against an envelope rather than a single reading against a band.
        """
    )
    return


@app.cell(hide_code=True)
def _(lm, mo):
    sites = {k: v for k, v in lm.discover_sites().items() if k not in lm.NOT_ON_ONC}

    site_picker = mo.ui.multiselect(
        options=sorted(sites), value=sorted(sites), label="Sites",
    )
    days_slider = mo.ui.slider(
        start=3, stop=90, step=1, value=30, label="Window (days)", show_value=True,
    )
    offline_toggle = mo.ui.switch(value=False, label="Offline (score the archive tail instead)")
    fetch_button = mo.ui.run_button(label="Fetch and score")

    mo.vstack([
        mo.hstack([site_picker, days_slider], justify="start", gap=2),
        mo.hstack([offline_toggle, fetch_button], justify="start", gap=2),
        mo.md(
            "La Perouse Bank is not listed: it is a DFO/MEDS buoy, not an ONC "
            "station, so it has no ONC location code and cannot be fetched here."
        ).callout(kind="neutral"),
    ])
    return days_slider, fetch_button, offline_toggle, site_picker


@app.cell
def _(days_slider, fetch_button, lm, mo, offline_toggle, site_picker):
    # Gated on the button so that moving a slider does not fire a round of API
    # calls: a full pull is seven requests and takes a few seconds.
    mo.stop(not fetch_button.value, mo.md("Set the window above, then **Fetch and score**.").callout())

    with mo.status.spinner(title="Fetching from ONC..."):
        try:
            frames, summary = lm.run(
                keys=list(site_picker.value),
                days=int(days_slider.value),
                offline=bool(offline_toggle.value),
            )
            error = None
        except SystemExit as exc:
            # read_token() raises SystemExit when no token is configured; in a
            # notebook that would otherwise kill the kernel with no explanation.
            frames, summary, error = {}, None, str(exc)

    mo.stop(
        error is not None,
        mo.md(f"**Could not fetch.**\n\n```\n{error}\n```").callout(kind="danger"),
    )

    # the range columns the summary figure needs
    summary["min_z"] = [frames[k]["z"].min() if len(frames[k]) else float("nan")
                        for k in summary["key"]]
    summary["max_z"] = [frames[k]["z"].max() if len(frames[k]) else float("nan")
                        for k in summary["key"]]
    return frames, summary


@app.cell(hide_code=True)
def _(mo, summary):
    flagged = summary[summary["verdict"] != "normal"]
    headline = (
        mo.md(
            "**"
            + "**, **".join(f"{r['site']}: {r['verdict']}" for _, r in flagged.iterrows())
            + "**"
        ).callout(kind="warn")
        if len(flagged)
        else mo.md("Every site averages within 1 sd of its day-of-year climatology.").callout(kind="success")
    )
    headline
    return


@app.cell(hide_code=True)
def _(mo, summary):
    mo.ui.table(
        summary[["site", "n", "mean_temp", "mean_z", "max_abs_z",
                 "pct_outside_1sd", "pct_outside_2sd", "verdict"]].round(2),
        selection=None,
    )
    return


@app.cell(hide_code=True)
def _(lm, mo, summary):
    # Inline SVG rather than marimo's default raster rendering: vector stays
    # sharp at any zoom, and lm.as_svg namespaces each figure's element ids so
    # that two SVGs on one page cannot resolve each other's clip paths.
    mo.Html(lm.as_svg(lm.plot_summary(summary)))
    return


@app.cell(hide_code=True)
def _(mo, summary):
    detail_picker = mo.ui.dropdown(
        options={r["site"]: r["key"] for _, r in summary.iterrows()},
        value=summary.iloc[0]["site"],
        label="Site detail",
    )
    detail_picker
    return (detail_picker,)


@app.cell(hide_code=True)
def _(detail_picker, frames, lm, mo, summary):
    key = detail_picker.value
    row = summary[summary["key"] == key].iloc[0]
    mo.stop(frames[key].empty, mo.md(f"No data returned for {row['site']}.").callout(kind="warn"))
    mo.Html(lm.as_svg(lm.plot_site(key, row["site"], frames[key])))
    return


if __name__ == "__main__":
    app.run()
