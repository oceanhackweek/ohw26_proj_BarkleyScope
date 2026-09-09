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
# Same dependency-header rules as Latest_Month_App.py: netCDF4 and xarray are
# pulled in one module deeper (enso_context -> latest_month -> onc_climatology)
# and must stay listed even though nothing here imports them, or an ephemeral
# venv build fails where the hub kernel would have succeeded. See
# final_notebooks/MARIMO_APP_STATUS.md.

import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import sys
    from pathlib import Path

    import marimo as mo

    try:
        _here = mo.notebook_dir()
    except Exception:
        _here = Path(__file__).parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))

    import numpy as np
    import pandas as pd

    import enso_context as ec

    return ec, mo, np, pd


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        # Is ENSO showing up at Barkley?

        `Latest_Month_App.py` asks whether this month is unusual for the time of
        year. This asks a different and harder question: whether it is unusual
        **because of the tropical Pacific**.

        A warm month is not evidence of a teleconnection. Every site here was
        warm in 2015 and warm again in 2019, and only one of those had an El Nino
        behind it. So nothing on this page reports "El Nino is happening at
        Barkley Canyon". It reports how strongly each site has tracked the ONI in
        the past, at what lag, with what confidence given a handful of events, and
        how far the present sits from what that relationship predicts.
        """
    )
    return


@app.cell(hide_code=True)
def _(ec, mo):
    live_toggle = mo.ui.switch(
        value=True, label="Extend the archives with the live ONC API",
    )
    days_slider = mo.ui.slider(
        start=7, stop=90, step=1, value=30, label="Live window (days)", show_value=True,
    )
    refresh_toggle = mo.ui.switch(value=False, label="Re-fetch the ENSO index")
    run_button = mo.ui.run_button(label="Run the analysis")

    mo.vstack([
        mo.hstack([live_toggle, days_slider], justify="start", gap=2),
        mo.hstack([refresh_toggle, run_button], justify="start", gap=2),
        mo.md(
            f"Index and cached anomalies live in `{ec.ENSO_DIR.name}/`. Rebuilding "
            "every site's climatology from the archives takes a minute or so; the "
            "run is gated on the button so a slider does not trigger it."
        ).callout(kind="neutral"),
    ])
    return days_slider, live_toggle, refresh_toggle, run_button


@app.cell
def _(days_slider, ec, live_toggle, mo, refresh_toggle, run_button):
    mo.stop(not run_button.value,
            mo.md("Set the options above, then **Run the analysis**.").callout())

    with mo.status.spinner(title="Building anomalies and scoring against ONI..."):
        if refresh_toggle.value:
            ec.load_oni(refresh=True, quiet=True)
        try:
            res = ec.analyse(live=bool(live_toggle.value),
                             days=int(days_slider.value), quiet=True)
            error = None
        except SystemExit as exc:
            res, error = None, str(exc)

    mo.stop(error is not None, mo.md(f"**Could not run.** {error}").callout(kind="danger"))
    oni = res["oni"]
    anoms = res["anomalies"]
    summary = res["summary"].copy()
    summary["robust"] = summary.apply(ec._robust, axis=1)
    summary["signal"] = summary.apply(ec._signal, axis=1)
    fp = res["fingerprint"]
    return anoms, fp, oni, res, summary


@app.cell(hide_code=True)
def _(mo, oni):
    _last = oni.index[-1]
    _now = float(oni.iloc[-1])
    _state = ("El Nino conditions" if _now >= 0.5
              else "La Nina conditions" if _now <= -0.5
              else "neutral")
    mo.md(
        f"""
        ## Where ENSO is right now

        **{oni.attrs.get('source', 'index')}, {_last:%B %Y}: {_now:+.2f} C** — {_state}.
        The trailing year ran
        {', '.join(f'{v:+.2f}' for v in oni.iloc[-12:])}.
        """
    )
    return


@app.cell(hide_code=True)
def _(ec, mo, oni):
    # Inline SVG rather than marimo's default raster rendering of a figure:
    # these panels get read closely -- a lag scan is a dozen points and a curve
    # -- and vector keeps them sharp at any zoom. ec.as_svg namespaces each
    # figure's element ids, without which several SVGs on one page resolve each
    # other's clip paths and lose content.
    mo.Html(ec.as_svg(ec.plot_oni(oni)))
    return


@app.cell(hide_code=True)
def _(ec, mo, oni, pd):
    _ev = ec.events(oni)
    _recent = _ev[_ev["end"] >= pd.Timestamp("2009-01-01")]
    mo.vstack([
        mo.md(
            """
            ### Episodes overlapping the observations

            CPC's definition: five consecutive overlapping three-month seasons at
            or beyond +/-0.5. A bare per-month threshold would count every brief
            excursion and inflate the event count, which is the main way analyses
            like this one overstate their confidence.
            """
        ),
        mo.ui.table(
            _recent.assign(
                start=_recent["start"].dt.strftime("%Y-%m"),
                end=_recent["end"].dt.strftime("%Y-%m"),
                peak_month=_recent["peak_month"].dt.strftime("%Y-%m"),
            ),
            selection=None, page_size=12,
        ),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        ## What each site's record supports

        For every site: the lag at which its monthly anomaly correlates most
        strongly with ONI, and the El Nino minus La Nina composite difference.

        Three columns do the work of keeping this honest.

        * **p_adj** is Bonferroni over the thirteen lags searched. Taking the
          largest of thirteen correlations and quoting its nominal p is how a
          teleconnection gets manufactured; the adjusted value is what decides
          the `signal` column.
        * **n_eff** is the autocorrelation-corrected sample size. Monthly ocean
          temperature carries months of memory, so 160 months may be worth 25
          independent ones — without this an r of 0.5 looks overwhelming when it
          is merely suggestive.
        * **gap_excl_hw** repeats the composite with 2014–2016 removed. That
          marine heatwave is not an ENSO signal but sits inside the strongest El
          Nino in the record, so a result that does not survive its removal is
          not a result. `robust` summarises whether it did.
        """
    )
    return


@app.cell(hide_code=True)
def _(mo, summary):
    mo.ui.table(
        summary[["site", "months", "lag", "r", "p_adj", "n_eff", "slope",
                 "nino", "nina", "gap", "gap_excl_hw", "robust", "signal"]]
        .round(3),
        selection=None, page_size=10,
    )
    return


@app.cell(hide_code=True)
def _(mo, summary):
    _shelf = summary[summary["depth"] < 150]
    _deep = summary[summary["depth"] >= 150]
    mo.md(
        f"""
        Read down the depth column rather than across the rows. The shelf sites
        ({', '.join(_shelf['site'])}) and the slope and canyon sites
        ({len(_deep)} of them, 398–983 m) do not merely differ in strength — they
        differ in **sign and in lag**, which is what makes the pattern worth
        taking seriously as something other than "warm years are warm".
        """
    )
    return


@app.cell(hide_code=True)
def _(mo, summary):
    site_picker = mo.ui.dropdown(
        options={r["site"]: r["key"] for _, r in summary.iterrows()},
        value=summary.iloc[0]["site"],
        label="Site detail",
    )
    site_picker
    return (site_picker,)


@app.cell(hide_code=True)
def _(anoms, ec, mo, oni, res, site_picker):
    mo.stop(site_picker.value is None)
    _key = site_picker.value
    _z = anoms[_key].dropna()
    _z.attrs["label"] = anoms.attrs["labels"][_key]
    _comp, _comp_ex = res["composites"][_key]
    mo.Html(ec.as_svg(ec.plot_site(_key, _z, oni, res["scans"][_key], _comp,
                                   _comp_ex, res["lags"][_key])))
    return


@app.cell(hide_code=True)
def _(mo, np, res, site_picker):
    _key = site_picker.value
    _comp, _comp_ex = res["composites"][_key]
    _lo, _hi = _comp["ci"]
    _ci = (f"95% CI {_lo:+.2f} to {_hi:+.2f} from the spread across events"
           if np.isfinite(_lo) else "too few events on one side for an interval")
    mo.md(
        f"""
        **{res['anomalies'].attrs['labels'][_key]}** — composite gap
        {_comp['difference']:+.2f} sd across {_comp['n_nino_events']} El Nino and
        {_comp['n_nina_events']} La Nina episodes ({_ci}; block-bootstrap
        p = {_comp['p']:.3f}). Excluding 2014–2016: {_comp_ex['difference']:+.2f} sd.

        The El Nino and La Nina means sit near-symmetrically about zero because
        the day-of-year climatology they are measured against was itself built
        from a record containing these same events. The difference between the
        phases is the statistic that survives that; neither mean alone is
        meaningful on its own.
        """
    ).callout(kind="neutral")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        ## Does the present look like ENSO?

        Each site's own regression is applied to the ONI value that leads it,
        giving an expected anomaly. Comparing the observed pattern across sites
        to that expected one gives two numbers answering different halves of the
        question:

        * **amplitude** — the scaling of expected onto observed. 1.0 means the
          sites are doing exactly what their history says they should for this
          ONI; 0 means no response; above 1 means more warmth than ENSO alone
          accounts for.
        * **agreement** — the cosine between the two vectors: whether the *shape*
          across depth matches, regardless of size. A warm month that warms the
          deep canyon as much as the shelf is not an ENSO pattern, however warm
          it is.

        Both are placed against the same scores computed for every past
        ENSO-active month, because an amplitude of 0.6 means nothing until you
        know that past events scattered between 0.2 and 1.8.
        """
    )
    return


@app.cell(hide_code=True)
def _(ec, fp, mo, np):
    _cov = fp.get("coverage") or {}
    _worst = min(_cov.values()) if _cov else float("nan")
    _note = (f" Thinnest site coverage this month is {_worst:.0%}."
             if np.isfinite(_worst) and _worst < 0.9 else "")
    _pct = (f" Amplitude sits at the {fp['amplitude_pct']:.0f}th percentile of "
            f"{fp['reference_n']} past ENSO-active months, agreement at the "
            f"{fp['agreement_pct']:.0f}th."
            if np.isfinite(fp.get("amplitude_pct", np.nan)) else "")
    mo.md(
        f"### {fp['month']:%B %Y}\n\n{ec.interpret(fp)}{_pct}{_note}"
    ).callout(kind="info")
    return


@app.cell(hide_code=True)
def _(anoms, ec, fp, mo):
    mo.Html(ec.as_svg(ec.plot_fingerprint(fp, anoms.attrs["labels"],
                                          anoms.attrs["depths"])))
    return


@app.cell(hide_code=True)
def _(anoms, fp, mo, pd):
    _rows = [{
        "site": anoms.attrs["labels"][k],
        "observed (sd)": round(fp["observed"][k], 2),
        "expected from ONI (sd)": round(fp["expected"][k], 2),
        "driving ONI": round(fp["driver_oni"][k], 2),
        "coverage": f"{fp['coverage'].get(k, float('nan')):.0%}",
    } for k in sorted(fp["sites"],
                      key=lambda k: anoms.attrs["depths"].get(k) or 0)]
    _dropped = [{"site": anoms.attrs["labels"].get(k, k),
                 "observed (sd)": None, "expected from ONI (sd)": None,
                 "driving ONI": None, "coverage": f"not scored: {why}"}
                for k, why in fp.get("dropped", {}).items()]
    mo.vstack([
        mo.ui.table(pd.DataFrame(_rows + _dropped), selection=None, page_size=10),
        mo.md(
            "A site whose expected value is near zero while its observation is "
            "not is saying something specific: whatever is moving it, the "
            "tropical Pacific is not it — at least not through the lagged "
            "relationship its own record supports."
        ).callout(kind="neutral"),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        """
        ---

        ### What this cannot tell you

        * **n is tiny.** Five El Nino and five La Nina episodes overlap the
          observations, and the shorter records see fewer. Every composite is an
          estimate from single digits and the intervals are wide on purpose.
        * **The baseline contains the events.** Anomalies are relative to the
          record's own day-of-year mean, and that mean includes 2015–16.
        * **Correlation at a lag is not a mechanism.** The deep-site relationship
          is coherent across four independent moorings and survives removing the
          marine heatwave, which is a reason to investigate it, not a reason to
          believe a particular physical story about it.
        * **La Perouse Bank is absent.** A DFO/MEDS buoy with no ONC location
          code, so it cannot come through this API — and its record ends in 2022.
        """
    )
    return


if __name__ == "__main__":
    app.run()
