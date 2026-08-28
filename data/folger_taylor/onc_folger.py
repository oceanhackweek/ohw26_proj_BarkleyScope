"""Read Ocean Networks Canada scalar time-series CSVs (Folger Passage, Barkley Sound).

ONC's "clean, averaged" CSV export carries a ``#``-prefixed preamble of provenance
-- station, instrument, every device deployment, declared sample counts -- and then
a bare data block with no column row. Everything here is keyed off that preamble
rather than off fixed line numbers or a station name, so the same two calls read
Folger Pinnacle (FGPPN, 25 m, ADCP) and Folger Deep (FGPD, 98 m, CTD) unchanged.

Nothing in this module cleans, fills, or resamples. NaNs and QC flags arrive as ONC
wrote them, so downstream gap accounting describes the file and not a choice made here.

Authors: Taylor Borgfeldt and Claude (Anthropic)
Last modified: 2026-08-27
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

COLUMNS = ["time", "temperature_C", "qc_flag", "count"]

# ONC flag meanings, from the preamble's own legend line.
QC_FLAGS = {
    0: "no QC", 1: "good", 2: "probably good", 3: "probably bad", 4: "bad",
    6: "bad down-sampling", 7: "averaged value", 8: "interpolated", 9: "missing (NaN)",
}


def read_header(path: str | Path) -> dict:
    """Parse the ``#`` preamble into a dict, plus ``_data_start`` (0-based row of first datum)."""
    meta: dict = {}
    with open(path) as fh:
        for i, line in enumerate(fh):
            if line.startswith("## END HEADER"):
                meta["_data_start"] = i + 1
                break
            if not line.startswith("#") or ":" not in line:
                continue
            key, _, rest = line[1:].partition(":")
            if not key.strip().isupper():          # skip prose/legend lines
                continue
            value = rest.split("  /")[0].strip().strip('"')
            meta[key.strip()] = value
    return meta


def read_csv(path: str | Path) -> pd.DataFrame:
    """Load one ONC scalar CSV as a time-indexed frame. No cleaning of any kind."""
    meta = read_header(path)
    df = pd.read_csv(
        path, skiprows=meta["_data_start"], names=COLUMNS,
        skipinitialspace=True, na_values=["NaN"],
    )
    df["time"] = pd.to_datetime(df["time"], format="ISO8601", utc=True)
    return df.set_index("time")


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


def _section(title: str) -> None:
    print(f"\n{title}\n" + "-" * len(title))


def inspect(path: str | Path, column: str = "temperature_C",
            min_days: float = 7.0, max_steps: int = 8) -> pd.DataFrame:
    """Load one ONC export, print a first-look report, and return the frame.

    Run this before any analysis. The checks are the ones that actually caught
    problems in the Folger records, so they are automated rather than remembered:
    the declared-count cross-check catches a broken parse, and the duplicate-stamp
    check catches an index that would silently corrupt a later join.

    Preamble parsing is specific to ONC's CSV export; a different provider needs
    its own reader, though everything downstream of :func:`read_csv` still applies.
    """
    meta = read_header(path)
    df = read_csv(path)
    n_valid = int(df[column].notna().sum())
    n_nan = len(df) - n_valid

    _section("STATION")
    for key, label in [("STNNAME", "station"), ("STNCODE", "code"),
                       ("LATITUDE", "latitude"), ("LONGITUDE", "longitude"),
                       ("DEPTH", "depth (m)"), ("DEVCAT", "device"),
                       ("DEVTOT", "deployments"), ("RESAMPPRD", "resample (s)"),
                       ("RESAMPTYP", "resample type"), ("DPOPTQC", "QC option")]:
        if meta.get(key):
            print(f"  {label:<14} {meta[key]}")

    _section("COLUMNS")
    print(df.dtypes.to_string())
    print()
    print(df.head(3).to_string())
    print("\n  QC flags present:")
    for flag, n in df["qc_flag"].value_counts().sort_index().items():
        print(f"    {int(flag)} = {QC_FLAGS.get(int(flag), '?'):<20}"
              f"{n:>9,}  ({n / len(df) * 100:5.1f}%)")

    _section("TIME RANGE")
    span = df.index[-1] - df.index[0]
    print(f"  first timestamp  {df.index[0]}")
    print(f"  last  timestamp  {df.index[-1]}")
    print(f"  span             {span.days:,} days ({span.days / 365.25:.1f} yr)")
    valid_idx = df.index[df[column].notna()]
    if len(valid_idx):
        print(f"  first valid      {valid_idx[0]}")
        print(f"  last  valid      {valid_idx[-1]}")
    else:
        print("  first/last valid (no valid values in file)")

    _section("INTEGRITY")
    print(f"  rows in file     {len(df):>9,}   preamble TOTSMPEXP {meta.get('TOTSMPEXP', '?'):>8}")
    print(f"  valid values     {n_valid:>9,}   preamble TOTSAMPLE {meta.get('TOTSAMPLE', '?'):>8}")
    print(f"  NaN              {n_nan:>9,}   ({n_nan / len(df) * 100:.1f}%)")
    dups = int(df.index.duplicated().sum())
    print(f"  duplicate stamps {dups:>9,}" + ("   <-- will corrupt joins" if dups else ""))
    for t in df.index[df.index.duplicated(keep=False)].unique():
        print(f"        {t}")
    print(f"  monotonic        {str(df.index.is_monotonic_increasing):>9}")

    _section("SAMPLING REGULARITY")
    print("  spacing of all timestamps:")
    print(sampling_regularity(df).to_string())
    print("\n  spacing between valid values only:")
    reg = sampling_regularity(df[df[column].notna()])
    print(reg.head(max_steps).to_string())
    if len(reg) > max_steps:
        print(f"  ... {len(reg)} distinct steps in total, largest {reg.index.max()}")

    _section(f"GAPS LONGER THAN {min_days:g} DAYS")
    gaps = gap_table(df, column=column, min_days=min_days)
    if gaps.empty:
        print("  (none)")
    else:
        show = gaps.assign(
            gap_start=gaps["gap_start"].dt.strftime("%Y-%m-%d %H:%M"),
            gap_end=gaps["gap_end"].dt.strftime("%Y-%m-%d %H:%M"),
            days=gaps["days"].round(1),
        )
        print(show.to_string(index=False))
        lost = int(gaps["missing_hours"].sum())
        pct = f" = {lost / n_nan * 100:.1f}% of all {n_nan:,} missing hours" if n_nan else ""
        print(f"\n  {lost:,} h lost in these gaps{pct}")
    print()
    return df


def to_daily(df: pd.DataFrame, column: str = "temperature_C", min_hours: int = 18) -> pd.DataFrame:
    """Hourly -> daily mean, requiring ``min_hours`` valid hours in the day.

    Under-threshold days keep their count and are flagged ``ok=False`` with a NaN
    mean, rather than being dropped -- coverage plots need the zeros.
    """
    g = df[column].resample("1D")
    out = pd.DataFrame({"temperature_C": g.mean(), "n": g.count()})
    out["ok"] = out["n"] >= min_hours
    out.loc[~out["ok"], "temperature_C"] = pd.NA
    return out


def to_monthly(daily: pd.DataFrame, min_days: int = 15,
               drop_partial_end: bool = True) -> pd.DataFrame:
    """Daily -> monthly mean, requiring ``min_days`` valid days in the month.

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


# Two-line series palette: categorical slots 1 and 2. Validated on the light
# surface -- CVD dE 24.7, normal-vision dE 33.6, both clear 3:1 contrast.
_SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")


def _draw_daily(ax, series: dict) -> list:
    """Daily lines for one or more stations on an existing axis; returns span labels.

    Gaps stay NaN so the line breaks rather than interpolating across an outage --
    with records of unequal coverage a continuous line would invent data.
    """
    ax.set_facecolor(_SURFACE)
    spans = []
    for (label, daily), colour in zip(series.items(), _SERIES):
        v = daily["temperature_C"].astype(float)
        ax.plot(daily.index, v, lw=0.7, color=colour, label=label, zorder=3)
        ok = v.dropna()
        spans.append(f"{label}: {ok.index[0]:%Y-%m} – {ok.index[-1]:%Y-%m} "
                     f"({len(ok):,} days)")
    ax.grid(axis="y", color="#e1e0d9", lw=0.8, zorder=0)
    return spans


def _series_xlim(series: dict):
    """Widest span across all stations, padded -- the shared time axis."""
    lo = min(d.index[0] for d in series.values())
    hi = max(d.index[-1] for d in series.values())
    return lo - pd.Timedelta(days=60), hi + pd.Timedelta(days=60)


def plot_daily_series(series: dict, title: str = "", subtitle: str = "",
                      ylabel: str = "temperature (°C)", path=None, dpi: int = 200):
    """Daily means for one or more stations on a single shared axis.

    Gaps are left as NaN so the line breaks rather than interpolating across an
    outage -- with records of unequal coverage, a continuous line would invent data.
    One y-axis always: every series is the same quantity in the same units.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(15, 5), facecolor=_SURFACE)
    spans = _draw_daily(ax, series)

    ax.set_ylabel(ylabel, color=_MUTED, fontsize=9)
    _time_axis(ax, next(iter(series.values())))
    ax.set_xlim(*_series_xlim(series))

    ax.set_title(title, color=_INK, fontsize=12.5, loc="left", pad=22)
    ax.text(0, 1.035, subtitle or "   ·   ".join(spans), transform=ax.transAxes,
            color=_MUTED, fontsize=9.5)
    ax.legend(frameon=False, fontsize=9.5, labelcolor=_MUTED,
              loc="upper right", ncol=len(series))

    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=dpi, facecolor=_SURFACE, bbox_inches="tight")
    return fig, ax


def plot_combined(series: dict, panels: list, title: str = "", subtitle: str = "",
                  percentiles=(90, 95, 99), path=None, dpi: int = 200):
    """Daily means above one anomaly panel per station, on a single shared time axis.

    ``panels`` is [(label, anom_frame), ...] top-to-bottom beneath the daily panel.
    The anomaly panels share a symmetric y-scale so their amplitudes are directly
    comparable, and the whole figure shares one x-axis so an event in the daily
    record can be read straight down into both anomaly series.

    The daily panel spans each station's full record while the anomaly panels may be
    narrower (a common baseline covers only the overlap) -- that mismatch is left
    visible rather than papered over by cropping the daily data.
    """
    import matplotlib.pyplot as plt

    n = 1 + len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(15, 4.4 * n), sharex=True, facecolor=_SURFACE,
                             gridspec_kw={"height_ratios": [1.2] + [1] * len(panels)})

    spans = _draw_daily(axes[0], series)
    axes[0].set_ylabel("temperature (°C)", color=_MUTED, fontsize=9)
    axes[0].legend(frameon=False, fontsize=9, labelcolor=_MUTED,
                   loc="upper right", ncol=len(series))

    v = pd.concat([a["anom_C"] for _, a in panels]).dropna()
    lim = float(max(abs(v.min()), abs(v.max()))) * 1.15   # one scale for every anomaly panel

    out = []
    for ax, (label, anom) in zip(axes[1:], panels):
        out.append(_draw_anomaly(ax, anom, percentiles, ylim=lim))
        ax.set_ylabel("anomaly (°C)", color=_MUTED, fontsize=9)
        ax.text(0.002, 0.97, label, transform=ax.transAxes, color=_INK, fontsize=10.5,
                va="top", ha="left", zorder=7,
                bbox=dict(facecolor=_SURFACE, edgecolor="none", pad=2.5))

    for ax in axes:
        _time_axis(ax, next(iter(series.values())))
    axes[0].set_xlim(*_series_xlim(series))          # sharex propagates to the rest
    for ax in axes[:-1]:
        ax.tick_params(axis="x", labelbottom=False)

    # Both anchored va="top": mixing suptitle's default with fig.text's baseline
    # puts them on the same line.
    fig.suptitle(title, color=_INK, fontsize=13, x=0.011, y=0.998, ha="left", va="top")
    fig.text(0.011, 0.9765, subtitle or "   ·   ".join(spans),
             color=_MUTED, fontsize=9.5, ha="left", va="top")
    fig.subplots_adjust(top=0.955, hspace=0.13)
    if path:
        fig.savefig(path, dpi=dpi, facecolor=_SURFACE, bbox_inches="tight")
    return fig, axes, out
