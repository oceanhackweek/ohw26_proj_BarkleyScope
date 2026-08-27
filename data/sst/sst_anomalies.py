"""Monthly means, climatology and anomalies for a satellite SST time series.

PROVENANCE
    Forked from data/folger_taylor/onc_folger.py (Taylor Borgfeldt and Claude,
    2026-08-27). That file is untouched -- this is a copy, not an edit, so their ONC
    pipeline keeps working and the two can diverge without either breaking the other.

    The arithmetic is theirs, unchanged. daily -> monthly -> climatology -> anomaly is
    the same whether the input is an hourly ONC sensor or a satellite cell, so only the
    front of the chain differs, and that is all that was touched.

WHAT WAS REMOVED, AND WHY
    read_header(), read_csv()   Parsed ONC's "#" CSV preamble. Our input is a netCDF
                                grid, read through barkley_sst.
    to_daily()                  Resampled hourly samples down to days. The SST archive
                                is already one value per day, so there is nothing to
                                average and its min_hours=18 threshold is meaningless.

WHAT CHANGED
    to_monthly()'s min_days default, 15 -> 3. Not a casual loosening -- see the note on
    that function. The backfilled part of our series is sampled weekly, so a month holds
    about four values and the original threshold would reject every one of them.

WHAT WAS KEPT VERBATIM
    to_monthly(), climatology(), anomalies(), common_baseline(), gap_table(),
    sampling_regularity(), and all the plotting. Verified against satellite-shaped
    input before any of the above was changed.

USAGE
    import sst_anomalies as sa

    daily   = sa.daily_frame(dates, values)   # the frame to_monthly() expects
    monthly = sa.to_monthly(daily)
    anom    = sa.anomalies(monthly)           # adds clim_C and anom_C

Authors: Taylor Borgfeldt and Claude (Anthropic); adapted for satellite SST 2026-08-27.
"""

from __future__ import annotations

import pandas as pd


def sampling_regularity(df: pd.DataFrame) -> pd.DataFrame:
    """Value-count the spacing between consecutive timestamps."""
    d = df.index.to_series().diff().dropna()
    out = d.value_counts().sort_index().rename("n").to_frame()
    out["pct"] = out["n"] / len(d) * 100
    out.index.name = "step"
    return out


def gap_table(df: pd.DataFrame, column: str = "temperature_C", min_days: float = 7.0) -> pd.DataFrame:
    """Runs of missing *valid* data longer than ``min_days``.

    Measured on non-NaN values, not on the index: ONC pads the export onto a
    complete hourly grid, so an index-based gap search finds nothing even where
    the instrument was out of the water.
    """
    t = df.index[df[column].notna()]
    gap = t.to_series().diff()
    hits = gap[gap > pd.Timedelta(days=min_days)]
    out = pd.DataFrame({
        "gap_start": [t[t.get_loc(i) - 1] for i in hits.index],  # last good sample
        "gap_end": hits.index,                                   # first good sample after
        "days": hits.dt.total_seconds().values / 86400,
    })
    out["missing_hours"] = (out["days"] * 24).round().astype(int) - 1
    return out.sort_values("days", ascending=False).reset_index(drop=True)


def daily_frame(dates, values) -> pd.DataFrame:
    """One value per day -> the frame ``to_monthly()`` expects.

    Replaces Taylor's ``to_daily()``, which averaged hourly ONC samples down to days.
    The satellite archive is already daily, so there is nothing to average: each day
    contributes exactly one number, and ``n`` is 1 wherever that number exists.

    ``ok`` marks days that carry a real value. Land, or a gap the analysis left, arrives
    as NaN and is excluded from the monthly mean rather than counted as a zero -- the
    same treatment ``to_daily()`` gave an under-sampled day.

    Days are not filled in. If the series skips from Monday to the following Monday --
    which the backfilled years do by design, being sampled weekly -- the gap simply is
    not there, and the monthly ``n`` reports four rather than thirty.
    """
    index = pd.to_datetime(pd.Index(list(dates)), utc=True)
    out = pd.DataFrame(
        {"temperature_C": pd.Series(list(values), dtype="float64").to_numpy()},
        index=index,
    )
    out.index.name = "time"
    out["n"] = out["temperature_C"].notna().astype(int)
    out["ok"] = out["temperature_C"].notna()
    return out.sort_index()


def to_monthly(daily: pd.DataFrame, min_days: int = 3,
               drop_partial_end: bool = True) -> pd.DataFrame:
    """Daily -> monthly mean, requiring ``min_days`` valid days in the month.

    ``min_days`` is 3 where Taylor's original is 15, and that is not a casual loosening.
    His input is an hourly sensor: a month holds ~30 daily values and 15 is a real
    majority. Ours is mixed. The backfilled years are sampled **weekly** -- about four
    values a month -- because an unstrided point request over this product times out on
    NOAA's server (see backfill_point_history.py for the measurements). A threshold of 15
    would reject every backfilled month and leave the climatology with nothing to average.

    So 3 is doing much less work than 15 did. It keeps out a month with essentially no
    coverage and nothing more. **Read ``n`` alongside the mean rather than treating
    ``ok`` as a quality stamp** -- a month built from 4 weekly samples carries roughly
    0.19 degC of noise on its mean against 0.07 degC for a fully sampled one.

    ``drop_partial_end`` removes a trailing month the record does not cover to its
    last day -- the in-progress month at the time of download. Detected by comparing
    the record end to the month end, never hardcoded, so a refreshed file or a
    different station self-corrects.
    """
    valid = daily.loc[daily["ok"], "temperature_C"]
    g = valid.resample("MS")
    out = pd.DataFrame({"temperature_C": g.mean(), "n": g.count()})
    out = out.reindex(pd.date_range(daily.index[0].normalize().replace(day=1),
                                    daily.index[-1], freq="MS"))
    out["n"] = out["n"].fillna(0).astype(int)
    out["ok"] = out["n"] >= min_days
    out.loc[~out["ok"], "temperature_C"] = pd.NA
    out.index.name = "month"
    if drop_partial_end and len(out):
        last_day = daily.index[-1]
        # Complete only if tomorrow falls in a different month. Avoids to_period(),
        # which silently drops the tz on a tz-aware index.
        if (last_day + pd.Timedelta(days=1)).month == last_day.month:
            out = out.iloc[:-1]
    return out


# Palette: dataviz reference instance -- categorical slot 1 (blue) and status
# "serious" (orange). Adjacent CVD dE 23.3, normal-vision dE 32.3, both clear.
# Orange is 2.57:1 on the light surface, so the relief rule applies: this figure
# ships with direct labels and a companion table view.
_BLUE, _ORANGE, _TRACK = "#2a78d6", "#ec835a", "#e1e0d9"
_INK, _MUTED, _SURFACE = "#0b0b0b", "#898781", "#fcfcfb"


def plot_coverage(monthly: pd.DataFrame, min_days: int = 15, title: str = "", path=None):
    """Bar chart of valid days per month -- coverage, before any climatology."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.transforms as transforms

    fig, ax = plt.subplots(figsize=(15, 4.6), facecolor=_SURFACE)
    ax.set_facecolor(_SURFACE)
    w = 24  # bar width in days; slightly under a month leaves the 2px surface gap

    ax.bar(monthly.index, 31, width=w, color=_TRACK, zorder=1)      # empty slot = no data
    ok, short = monthly[monthly["ok"]], monthly[~monthly["ok"] & (monthly["n"] > 0)]
    ax.bar(ok.index, ok["n"], width=w, color=_BLUE, zorder=3)
    ax.bar(short.index, short["n"], width=w, color=_ORANGE, zorder=3)

    ax.axhline(min_days, color=_INK, lw=1, ls=(0, (4, 3)), zorder=4)
    # Label in the right margin -- gap widths vary by station, so no in-plot
    # placement heuristic is collision-free for both.
    tf = transforms.blended_transform_factory(ax.transAxes, ax.transData)
    ax.text(1.008, min_days, f"{min_days}-day threshold", transform=tf,
            color=_INK, fontsize=8.5, va="center", ha="left")

    ax.set_ylim(0, 31); ax.set_yticks([0, 15, 31])
    ax.set_ylabel("valid days in month", color=_MUTED, fontsize=9)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(colors=_MUTED, labelsize=9)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.set_title(title, color=_INK, fontsize=12, loc="left", pad=14)

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (_BLUE, _ORANGE, _TRACK)]
    ax.legend(handles, [f"month usable (>={min_days} days)",
                        f"short of threshold (1-{min_days - 1} days)", "no data"],
              frameon=False, fontsize=9, labelcolor=_MUTED,
              loc="lower left", bbox_to_anchor=(0, -0.30), ncol=3)

    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=160, facecolor=_SURFACE, bbox_inches="tight")
    return fig, ax


def climatology(monthly: pd.DataFrame) -> pd.DataFrame:
    """Mean/std/n per calendar month, from usable months only."""
    use = monthly[monthly["ok"]]
    g = use.groupby(use.index.month)["temperature_C"]
    clim = pd.DataFrame({"clim_C": g.mean(), "std_C": g.std(), "n_years": g.size()})
    clim.index.name = "calendar_month"
    return clim.reindex(range(1, 13))


def anomalies(monthly: pd.DataFrame, clim: pd.DataFrame | None = None) -> pd.DataFrame:
    """Monthly anomaly vs the calendar-month climatology. Unusable months stay NaN."""
    clim = climatology(monthly) if clim is None else clim
    out = monthly.copy()
    out["clim_C"] = out.index.month.map(clim["clim_C"])
    out["anom_C"] = out["temperature_C"] - out["clim_C"]
    return out


# Exceedance fills, ascending severity. Validated as a set on the light surface:
# adjacent CVD dE 16.3, normal-vision dE 19.6. Pink (2.62:1) and yellow (2.11:1)
# are sub-3:1, so the thresholds carry direct labels and a CSV table ships with it.
_P90, _P95, _P99, _BAR = "#4a3aa7", "#e87ba4", "#eda100", "#b8b6ae"


def _draw_anomaly(ax, anom, percentiles=(90, 95, 99), thr=None, ylim=None):
    """Bars + zero line + labelled percentile rules on an existing axis.

    Shared by the single-site figure and the two-site comparison so both carry
    identical marks. Pass ``thr`` to impose thresholds from elsewhere.
    """
    import matplotlib.transforms as transforms

    v = anom["anom_C"].dropna()
    thr = {p: v.quantile(p / 100) for p in percentiles} if thr is None else thr
    colors = dict(zip(sorted(thr), (_P90, _P95, _P99)))

    ax.set_facecolor(_SURFACE)
    fill = pd.Series(_BAR, index=anom.index)
    for p in sorted(thr):                              # ascending: severest wins
        fill[anom["anom_C"] > thr[p]] = colors[p]
    ax.bar(anom.index, anom["anom_C"].astype(float), width=24, color=fill, zorder=3)
    ax.axhline(0, color=_INK, lw=1.1, zorder=4)

    # Threshold labels in the right margin: x in axes fraction, y in data units.
    tf = transforms.blended_transform_factory(ax.transAxes, ax.transData)
    for p in sorted(thr):
        ax.axhline(thr[p], color=colors[p], lw=1.2, ls=(0, (5, 3)), zorder=5)
        ax.text(1.008, thr[p], f"{p}th  {thr[p]:+.2f}", transform=tf, color=colors[p],
                fontsize=8.5, va="center", ha="left", zorder=6)

    lim = ylim or float(max(abs(v.min()), abs(v.max()))) * 1.15
    ax.set_ylim(-lim, lim)
    return thr


def _time_axis(ax, anom):
    """Year ticks, no spines, zero line drawn separately."""
    import matplotlib.dates as mdates

    ax.set_xlim(anom.index[0] - pd.Timedelta(days=45), anom.index[-1] + pd.Timedelta(days=45))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(colors=_MUTED, labelsize=9)
    for sp in ("top", "right", "left", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="x", length=0, pad=6)


def plot_anomalies(anom: pd.DataFrame, baseline: str = "", station: str = "",
                   percentiles=(90, 95, 99), path=None, dpi: int = 200):
    """Monthly anomalies as bars, with fixed warm-percentile exceedance thresholds.

    Styled after the NOAA PSL marine-heatwave time series. Thresholds are
    percentiles of the whole anomaly distribution, not seasonally varying.
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.transforms as transforms

    fig, ax = plt.subplots(figsize=(15, 5.2), facecolor=_SURFACE)
    thr = _draw_anomaly(ax, anom, percentiles)
    _time_axis(ax, anom)
    ax.set_ylabel("temperature anomaly (°C)", color=_MUTED, fontsize=9)

    ax.set_title(station, color=_INK, fontsize=12.5, loc="left", pad=22)
    ax.text(0, 1.035, baseline, transform=ax.transAxes, color=_MUTED, fontsize=9.5)

    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=dpi, facecolor=_SURFACE, bbox_inches="tight")
    return fig, ax, thr


def common_baseline(monthly_a: pd.DataFrame, monthly_b: pd.DataFrame):
    """Restrict two sites to months usable at BOTH, then rebaseline each there.

    Identical month sets on both sides, so any difference between the resulting
    anomaly series is a difference between the sites and not between their sampling.
    """
    lo, hi = max(monthly_a.index[0], monthly_b.index[0]), min(monthly_a.index[-1], monthly_b.index[-1])
    a, b = monthly_a.loc[lo:hi].copy(), monthly_b.loc[lo:hi].copy()
    both = a["ok"] & b["ok"]
    a["ok"], b["ok"] = both, both
    a.loc[~both, "temperature_C"] = pd.NA
    b.loc[~both, "temperature_C"] = pd.NA
    return anomalies(a), anomalies(b), int(both.sum())


def plot_comparison(anom_a, anom_b, label_a: str, label_b: str, title: str = "",
                    baseline: str = "", percentiles=(90, 95, 99), path=None, dpi: int = 200):
    """Two sites, stacked panels, shared x and a shared symmetric y-scale."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(15, 8), sharex=True, facecolor=_SURFACE)
    v = pd.concat([anom_a["anom_C"], anom_b["anom_C"]]).dropna()
    lim = float(max(abs(v.min()), abs(v.max()))) * 1.15   # one scale for both panels

    out = []
    for ax, anom, lab in zip(axes, (anom_a, anom_b), (label_a, label_b)):
        out.append(_draw_anomaly(ax, anom, percentiles, ylim=lim))
        _time_axis(ax, anom)
        ax.set_ylabel("anomaly (°C)", color=_MUTED, fontsize=9)
        ax.text(0.002, 0.97, lab, transform=ax.transAxes, color=_INK,
                fontsize=10.5, va="top", ha="left", zorder=7,
                bbox=dict(facecolor=_SURFACE, edgecolor="none", pad=2.5))

    axes[0].tick_params(axis="x", labelbottom=False)
    fig.suptitle(title, color=_INK, fontsize=12.5, x=0.011, y=0.985, ha="left")
    fig.text(0.011, 0.952, baseline, color=_MUTED, fontsize=9.5, ha="left")
    fig.subplots_adjust(top=0.90, hspace=0.16)
    if path:
        fig.savefig(path, dpi=dpi, facecolor=_SURFACE, bbox_inches="tight")
    return fig, axes, out
