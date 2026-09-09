"""Does the ENSO state show up in the Barkley temperature records?

`onc_climatology.py` says whether a reading is unusual for the day of year.
That is a different question from whether it is unusual *because of* El Nino,
and this module is the bridge between the two: it puts each site's anomaly
history next to the tropical Pacific index, measures the lagged relationship
the record actually supports, and scores the present against it.

The distinction matters because a warm month is not evidence of a
teleconnection. Every site in this record was warm in 2015 and warm again in
2019, but only one of those was an El Nino response; the other was the tail of
a marine heatwave with no tropical cause. So nothing here reports "El Nino is
happening at Barkley Canyon". It reports how strongly this site has tracked
ONI in the past, at what lag, with what confidence given three or four events,
and how far the present sits from what that relationship predicts.

Three caveats are structural rather than incidental, and the output repeats
them because they bound every number the module produces:

* **n is tiny.** The ONC record covers four El Nino winters and six La Nina
  winters. A composite difference is an estimate from single digits, and the
  bootstrap intervals here are wide on purpose.
* **The baseline contains the events.** Day-of-year anomalies are relative to
  the record's own mean, and that mean includes 2015-16. El Nino and La Nina
  composites are therefore near-symmetric about zero by construction, so the
  *difference* between them is the meaningful statistic, not either alone.
* **The 2014-16 marine heatwave is not ENSO** but overlaps the strongest El
  Nino in the record. Every composite is reported twice, with and without
  those years, and a result that does not survive the exclusion is not a
  result.

Usage
-----
    python enso_context.py --summary                 # lag + composite, every site
    python enso_context.py --site pinnacle --plots
    python enso_context.py --fingerprint             # score the present window
    python enso_context.py --refresh-oni             # re-fetch the index
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

import latest_month as lm
from onc_climatology import (
    build_climatology, classify_series, discover_sites, load_series, site_label,
)

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

HERE = Path(__file__).parent
ENSO_DIR = HERE / "enso"
ONI_CACHE = ENSO_DIR / "oni.csv"
ANOM_CACHE = ENSO_DIR / "monthly_anomaly.csv"

# CPC publishes the operational ONI; PSL's Nino 3.4 is the fallback if CPC is
# unreachable. They are not the same index -- ONI is a 3-month running mean on a
# shifting 30-year base -- so which one was used is recorded in the cache.
ONI_SOURCES = (
    ("CPC ONI", "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"),
    ("PSL Nino3.4", "https://psl.noaa.gov/data/correlation/nina34.data"),
)
ONI_MAX_AGE_DAYS = 20          # CPC updates monthly; refetch once a cache is stale

# CPC's own event definition: five consecutive overlapping seasons at or beyond
# the threshold. A bare per-month threshold would count every brief excursion as
# an event, which is what inflates n in casual analyses of this kind.
EVENT_THRESHOLD = 0.5
EVENT_MIN_SEASONS = 5

MAX_LAG_MONTHS = 12
MIN_MONTHS_FOR_LAG = 60        # 5 years; below this a lag correlation is noise
BLOCK_MONTHS = 12              # moving-block bootstrap block length
N_BOOT = 2000

# The marine heatwave. Not an ENSO signal, and inside the strongest El Nino in
# the record -- see the module docstring.
HEATWAVE = ("2014-01-01", "2016-12-31")

# Shared with latest_month so both sets of figures read as one family.
as_svg = lm.as_svg          # re-exported: the apps render inline SVG
BAND_2, BAND_1 = lm.BAND_2, lm.BAND_1
MEAN_C, OBS_C, FLAG_C = lm.MEAN_C, lm.OBS_C, lm.FLAG_C
INK, INK_2, GRID, SURFACE = lm.INK, lm.INK_2, lm.GRID, lm.SURFACE
WARM_C, COOL_C = "#c1442e", "#2e6fa7"


# --------------------------------------------------------------------------
# The index
# --------------------------------------------------------------------------

# ONI seasons are 3-month means labelled by their centre month: DJF centres on
# January of the labelled year, NDJ on December of it. Getting this wrong shifts
# every lag by up to two months, which is the whole quantity of interest here.
_SEASON_CENTRE = {s: i + 1 for i, s in enumerate(
    ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
)}


def _parse_cpc(text: str) -> pd.Series:
    rows = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) != 4 or parts[0] not in _SEASON_CENTRE:
            continue
        seas, year, _total, anom = parts
        rows.append((pd.Timestamp(int(year), _SEASON_CENTRE[seas], 1), float(anom)))
    if not rows:
        raise ValueError("no ONI rows parsed")
    s = pd.Series(dict(rows)).sort_index()
    s.index.name = "month"
    return s


def _parse_psl(text: str) -> pd.Series:
    """PSL's fixed-width monthly grid: a year per line, twelve values after it."""
    lines = text.splitlines()
    first, last = (int(x) for x in lines[0].split()[:2])
    missing = None
    rows = {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) == 1 and missing is None:
            missing = float(parts[0])
            continue
        if len(parts) != 13:
            continue
        year = int(parts[0])
        if not first <= year <= last:
            continue
        for month, value in enumerate(parts[1:], start=1):
            v = float(value)
            if missing is None or abs(v - missing) > 1e-6:
                rows[pd.Timestamp(year, month, 1)] = v
    if not rows:
        raise ValueError("no PSL rows parsed")
    s = pd.Series(rows).sort_index()
    # PSL publishes absolute SST; centre it so it is comparable to an anomaly
    # index. This is a fallback, not an equivalent -- flagged in the cache.
    s = s - s.loc["1991":"2020"].mean()
    s = s.rolling(3, center=True).mean().dropna()
    s.index.name = "month"
    return s


def load_oni(refresh: bool = False, quiet: bool = False) -> pd.Series:
    """The ENSO index as a monthly series, cached beside the script.

    Cached because every figure and every lag scan wants it, and because a
    network failure should degrade to yesterday's index rather than to no
    analysis at all.
    """
    ENSO_DIR.mkdir(parents=True, exist_ok=True)
    fresh_enough = (
        ONI_CACHE.is_file()
        and (pd.Timestamp.now() - pd.Timestamp(ONI_CACHE.stat().st_mtime, unit="s")).days
        < ONI_MAX_AGE_DAYS
    )
    if not refresh and fresh_enough:
        s = pd.read_csv(ONI_CACHE, index_col=0, parse_dates=True)["oni"]
        s.attrs["source"] = json.loads((ENSO_DIR / "oni_source.json").read_text())["source"]
        return s

    errors = []
    for name, url in ONI_SOURCES:
        try:
            with urllib.request.urlopen(url, timeout=30) as fh:
                text = fh.read().decode("utf-8", "replace")
            s = _parse_cpc(text) if "cpc" in url else _parse_psl(text)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            errors.append(f"{name}: {type(exc).__name__}")
            continue
        s.name = "oni"
        s.to_frame().to_csv(ONI_CACHE)
        (ENSO_DIR / "oni_source.json").write_text(
            json.dumps({"source": name, "url": url,
                        "retrieved": str(pd.Timestamp.now().round("s")),
                        "last_month": str(s.index[-1].date())}, indent=2))
        s.attrs["source"] = name
        if not quiet:
            print(f"ONI: {name}, through {s.index[-1]:%Y-%m} ({len(s)} months)")
        return s

    if ONI_CACHE.is_file():
        if not quiet:
            print(f"index fetch failed ({'; '.join(errors)}); using the cached copy")
        s = pd.read_csv(ONI_CACHE, index_col=0, parse_dates=True)["oni"]
        s.attrs["source"] = json.loads((ENSO_DIR / "oni_source.json").read_text())["source"]
        return s
    raise SystemExit("could not fetch an ENSO index and no cache exists: "
                     + "; ".join(errors))


def events(oni: pd.Series, threshold: float = EVENT_THRESHOLD,
           min_seasons: int = EVENT_MIN_SEASONS) -> pd.DataFrame:
    """El Nino and La Nina episodes, by CPC's consecutive-seasons rule."""
    out = []
    for sign, name in ((1, "El Nino"), (-1, "La Nina")):
        over = (oni * sign) >= threshold
        group = (over != over.shift()).cumsum()
        for _, block in oni.groupby(group):
            mask = (oni.loc[block.index] * sign) >= threshold
            if not mask.all() or len(block) < min_seasons:
                continue
            peak = block.max() if sign > 0 else block.min()
            out.append({"phase": name, "start": block.index[0], "end": block.index[-1],
                        "months": len(block), "peak": float(peak),
                        "peak_month": block.idxmax() if sign > 0 else block.idxmin()})
    if not out:
        return pd.DataFrame(columns=["phase", "start", "end", "months", "peak", "peak_month"])
    return pd.DataFrame(out).sort_values("start").reset_index(drop=True)


def phase_series(oni: pd.Series, threshold: float = EVENT_THRESHOLD) -> pd.Series:
    """Per-month phase label, using the episode rule rather than a bare threshold."""
    phase = pd.Series("Neutral", index=oni.index, name="phase")
    for _, e in events(oni, threshold=threshold).iterrows():
        phase.loc[e["start"]:e["end"]] = e["phase"]
    return phase


# --------------------------------------------------------------------------
# Site anomalies
# --------------------------------------------------------------------------

def site_monthly_anomaly(key: str, path: Path, live: bool = False,
                         days: int = 30, onc=None, cache=None,
                         min_hours: int = 200) -> pd.Series:
    """Monthly-mean anomaly in sd units for one site, over its whole record.

    `min_hours` drops months assembled from a handful of surviving hours: a
    month with 20 good values is not a monthly mean, and at these sites a
    partial month is usually a partial *deployment*, which biases warm or cool
    depending on when the gap fell.
    """
    obs = load_series(path=path)
    if live:
        tail = lm.fetch_series(key, path, days, onc, cache)
        if len(tail):
            # The archive and the API overlap by weeks; the API is the more
            # recent authority for shared timestamps.
            obs = pd.concat([obs[obs.index < tail.index[0]], tail])
            obs.attrs.update(load_series(path=path).attrs)

    clim = build_climatology(obs)
    scored = classify_series(clim, obs)
    z = scored["z"].replace([np.inf, -np.inf], np.nan)
    monthly = z.resample("MS").mean()
    counts = z.resample("MS").count()
    monthly = monthly.where(counts >= min_hours)
    keep = monthly.notna()
    monthly = monthly[keep]
    monthly.name = key
    monthly.attrs["label"] = site_label(obs)
    monthly.attrs["depth"] = obs.attrs.get("depth")
    # Fraction of the month's hours that survived QAQC. The final month of any
    # live pull is partial by definition, and a 9-day "month" should not be read
    # as one -- so the number travels with the anomaly rather than being lost.
    hours = monthly.index.days_in_month * 24
    monthly.attrs["coverage"] = (counts[keep] / hours).clip(upper=1.0)
    return monthly


def all_monthly_anomalies(live: bool = False, days: int = 30,
                          keys=None, quiet: bool = False) -> pd.DataFrame:
    sites = {k: v for k, v in discover_sites().items() if k not in lm.NOT_ON_ONC}
    if keys:
        sites = {k: v for k, v in sites.items() if k in keys}
    onc, cache = (lm.client(), lm._load_cache()) if live else (None, {})
    frames, labels, depths, coverage = {}, {}, {}, {}
    for key, path in sites.items():
        s = site_monthly_anomaly(key, path, live=live, days=days, onc=onc, cache=cache)
        frames[key] = s
        labels[key] = s.attrs["label"]
        depths[key] = s.attrs["depth"]
        coverage[key] = s.attrs["coverage"]
        if not quiet:
            last_cov = s.attrs["coverage"].iloc[-1] if len(s) else float("nan")
            tail = f"  (last month {last_cov:.0%} covered)" if last_cov < 0.9 else ""
            print(f"  {key:12s} {len(s):4d} months  "
                  f"{s.index.min():%Y-%m}..{s.index.max():%Y-%m}{tail}")
    out = pd.DataFrame(frames)
    out.attrs.update(labels=labels, depths=depths,
                     coverage=pd.DataFrame(coverage))
    return out


# --------------------------------------------------------------------------
# Lagged relationship
# --------------------------------------------------------------------------

def _lag1(x: np.ndarray) -> float:
    x = x - x.mean()
    denom = (x * x).sum()
    return float((x[:-1] * x[1:]).sum() / denom) if denom > 0 else 0.0


def effective_n(a: np.ndarray, b: np.ndarray) -> float:
    """Bretherton et al. (1999) effective sample size.

    Monthly ocean temperature is strongly autocorrelated, so the nominal n
    overstates the information by a factor of several. Without this correction
    an r of 0.5 on 150 months looks overwhelmingly significant when it rests on
    perhaps 20 independent samples.
    """
    r1, r2 = _lag1(a), _lag1(b)
    factor = (1 - r1 * r2) / (1 + r1 * r2)
    return max(3.0, len(a) * min(1.0, max(factor, 0.02)))


def _p_from_r(r: float, n_eff: float) -> float:
    """Two-sided p for a correlation, via the Fisher z transform."""
    if n_eff <= 3 or not np.isfinite(r) or abs(r) >= 1:
        return float("nan")
    from math import atanh, erfc, sqrt
    z = atanh(r) * sqrt(n_eff - 3)
    return float(erfc(abs(z) / sqrt(2)))


def lag_scan(z: pd.Series, oni: pd.Series, max_lag: int = MAX_LAG_MONTHS,
             exclude: tuple | None = None) -> pd.DataFrame:
    """Correlation of a site's monthly anomaly against ONI led by 0..max_lag months.

    Positive lag means ONI leads: the tropical index moves first and the site
    responds `lag` months later, which is the physically expected direction.
    """
    if exclude is not None:
        z = z[~((z.index >= exclude[0]) & (z.index <= exclude[1]))]
    rows = []
    for lag in range(max_lag + 1):
        j = pd.concat([z.rename("z"), oni.shift(lag).rename("oni")], axis=1, sort=True).dropna()
        if len(j) < MIN_MONTHS_FOR_LAG:
            continue
        r = float(j["z"].corr(j["oni"]))
        n_eff = effective_n(j["z"].to_numpy(), j["oni"].to_numpy())
        rows.append({"lag": lag, "r": r, "n": len(j), "n_eff": round(n_eff, 1),
                     "p": _p_from_r(r, n_eff)})
    return pd.DataFrame(rows)


def best_lag(scan: pd.DataFrame) -> dict:
    """The strongest |r| in the scan, with its p-value adjusted for the search.

    Taking the largest of thirteen correlations and quoting its nominal p is
    the classic way to manufacture a teleconnection. `p_adj` is a Bonferroni
    bound over the lags tried -- conservative, because neighbouring lags are
    far from independent, which is the safe direction here.
    """
    if scan.empty:
        return {"lag": np.nan, "r": np.nan, "p": np.nan, "p_adj": np.nan,
                "n": 0, "n_eff": np.nan}
    top = scan.loc[scan["r"].abs().idxmax()].to_dict()
    top["p_adj"] = min(1.0, top["p"] * len(scan)) if np.isfinite(top["p"]) else np.nan
    return top


def regression(z: pd.Series, oni: pd.Series, lag: int,
               exclude: tuple | None = None) -> dict:
    """Least squares of site anomaly on lagged ONI: the response per unit ONI."""
    if exclude is not None:
        z = z[~((z.index >= exclude[0]) & (z.index <= exclude[1]))]
    j = pd.concat([z.rename("z"), oni.shift(lag).rename("oni")], axis=1, sort=True).dropna()
    if len(j) < MIN_MONTHS_FOR_LAG:
        return {"slope": np.nan, "intercept": np.nan, "n": len(j)}
    slope, intercept = np.polyfit(j["oni"], j["z"], 1)
    return {"slope": float(slope), "intercept": float(intercept), "n": len(j)}


# --------------------------------------------------------------------------
# Composites
# --------------------------------------------------------------------------

def composite(z: pd.Series, oni: pd.Series, lag: int = 0,
              exclude: tuple | None = None, n_boot: int = N_BOOT,
              seed: int = 0) -> dict:
    """Mean site anomaly during El Nino vs La Nina months, and the gap between.

    The El Nino mean on its own is not very meaningful -- the climatology it is
    measured against was built from a record containing these same events, so
    the phases sit near-symmetrically about zero by construction. The
    difference is the statistic that survives that, and it is the one given a
    confidence interval and a null.
    """
    if exclude is not None:
        z = z[~((z.index >= exclude[0]) & (z.index <= exclude[1]))]
    phase = phase_series(oni).shift(lag)
    j = pd.concat([z.rename("z"), phase.rename("phase")], axis=1, sort=True).dropna()
    if j.empty:
        return {"n_nino": 0, "n_nina": 0, "nino": np.nan, "nina": np.nan,
                "difference": np.nan, "ci": (np.nan, np.nan), "p": np.nan,
                "n_nino_events": 0, "n_nina_events": 0}

    nino = j.loc[j["phase"] == "El Nino", "z"]
    nina = j.loc[j["phase"] == "La Nina", "z"]
    diff = float(nino.mean() - nina.mean()) if len(nino) and len(nina) else np.nan

    # Two independent statements about uncertainty, because they fail
    # differently. The block bootstrap answers "could autocorrelated noise fake
    # this?"; the per-event spread answers "do the events even agree?", which
    # with three or four of them is the more honest limit.
    rng = np.random.default_rng(seed)
    values, labels = j["z"].to_numpy(), j["phase"].to_numpy()
    n = len(values)
    null = np.empty(n_boot)
    n_blocks = int(np.ceil(n / BLOCK_MONTHS))
    for i in range(n_boot):
        starts = rng.integers(0, max(1, n - BLOCK_MONTHS), size=n_blocks)
        shuffled = np.concatenate([values[s:s + BLOCK_MONTHS] for s in starts])[:n]
        a = shuffled[labels == "El Nino"]
        b = shuffled[labels == "La Nina"]
        null[i] = a.mean() - b.mean() if len(a) and len(b) else np.nan
    null = null[np.isfinite(null)]
    p = float((np.abs(null) >= abs(diff)).mean()) if len(null) and np.isfinite(diff) else np.nan

    ev = events(oni)
    per_event = {}
    for _, e in ev.iterrows():
        window = z[(z.index >= e["start"] + pd.DateOffset(months=lag))
                   & (z.index <= e["end"] + pd.DateOffset(months=lag))]
        if len(window):
            per_event[f"{e['phase']} {e['start']:%Y-%m}"] = float(window.mean())
    nino_events = [v for k, v in per_event.items() if k.startswith("El Nino")]
    nina_events = [v for k, v in per_event.items() if k.startswith("La Nina")]

    ci = (np.nan, np.nan)
    if len(nino_events) > 1 and len(nina_events) > 1:
        se = np.sqrt(np.var(nino_events, ddof=1) / len(nino_events)
                     + np.var(nina_events, ddof=1) / len(nina_events))
        ci = (diff - 1.96 * se, diff + 1.96 * se)

    return {"n_nino": int(len(nino)), "n_nina": int(len(nina)),
            "nino": float(nino.mean()) if len(nino) else np.nan,
            "nina": float(nina.mean()) if len(nina) else np.nan,
            "difference": diff, "ci": ci, "p": p,
            "n_nino_events": len(nino_events), "n_nina_events": len(nina_events),
            "per_event": per_event}


# --------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------

def fingerprint(anoms: pd.DataFrame, oni: pd.Series, lags: dict,
                slopes: dict, when: pd.Timestamp | None = None) -> dict:
    """How closely does the present cross-site pattern match the ENSO response?

    The expected pattern is each site's own regression applied to the ONI value
    that leads it: `slope_site * ONI(t - lag_site)`. Comparing the observed
    vector to that expected one gives two numbers that answer different halves
    of the question:

    * **amplitude** -- the least-squares scaling of expected onto observed. 1.0
      means the sites are doing exactly what their history says they should for
      this ONI; 0 means no response; above 1 means more than ENSO alone
      accounts for.
    * **agreement** -- the cosine between the two vectors, which asks whether
      the *shape* across depth matches regardless of size. A warm month that
      warms the deep canyon as much as the shelf is not an ENSO pattern even
      though it is warm.

    Both are reported against the distribution of the same quantities over
    every past month with an active ENSO phase, because a bare amplitude of 0.6
    means nothing without knowing that past events scattered between 0.2 and 1.8.
    """
    if when is None:
        cov = anoms.attrs.get("coverage")
        complete = anoms.dropna(how="all").index
        if cov is not None and len(complete):
            # the most recent month where at least half the reporting sites have
            # most of the month; falls back to the last month with any data
            usable = [t_ for t_ in complete
                      if (cov.loc[t_].dropna() >= 0.8).sum()
                      >= max(1, int(0.5 * anoms.loc[t_].notna().sum()))]
            when = usable[-1] if usable else complete[-1]
        else:
            when = complete[-1]
    when = pd.Timestamp(when).to_period("M").to_timestamp()

    def vectors(t: pd.Timestamp, why: dict | None = None):
        obs, exp, keys = [], [], []
        for key in anoms.columns:
            lag = lags.get(key)
            slope = slopes.get(key)
            if lag is None or slope is None or not np.isfinite(slope):
                if why is not None:
                    why[key] = "no usable lagged relationship"
                continue
            driver = t - pd.DateOffset(months=int(lag))
            if t not in anoms.index or not np.isfinite(anoms.at[t, key]
                                                       if t in anoms.index else np.nan):
                if why is not None:
                    why[key] = f"no data for {t:%Y-%m}"
                continue
            if driver not in oni.index:
                if why is not None:
                    why[key] = (f"needs ONI for {driver:%Y-%m} at lag {lag}, "
                                f"index ends {oni.index[-1]:%Y-%m}")
                continue
            obs.append(float(anoms.at[t, key]))
            exp.append(float(slope * oni.loc[driver]))
            keys.append(key)
        return np.array(obs), np.array(exp), keys

    def score(obs, exp):
        if len(obs) < 3 or not np.isfinite(exp).all() or (exp * exp).sum() < 1e-9:
            return np.nan, np.nan
        amp = float((obs @ exp) / (exp @ exp))
        norm = np.linalg.norm(obs) * np.linalg.norm(exp)
        cos = float((obs @ exp) / norm) if norm > 1e-9 else np.nan
        return amp, cos

    dropped = {}
    obs, exp, keys = vectors(when, why=dropped)
    dropped = {k: v for k, v in dropped.items() if k not in keys}
    amp, cos = score(obs, exp)

    # The reference distribution: the same two scores at every past month where
    # an episode was under way. This is what makes the present number readable.
    phase = phase_series(oni)
    hist_amp, hist_cos = [], []
    for t in anoms.index:
        if t >= when:
            continue
        active = [phase.get(t - pd.DateOffset(months=int(lags[k])), "Neutral")
                  for k in keys if k in lags]
        if not any(p != "Neutral" for p in active):
            continue
        o, e, _ = vectors(t)
        a, c = score(o, e)
        if np.isfinite(a):
            hist_amp.append(a)
        if np.isfinite(c):
            hist_cos.append(c)

    def pct(value, pool):
        pool = np.asarray(pool, dtype=float)
        return float((pool <= value).mean() * 100) if len(pool) and np.isfinite(value) else np.nan

    driver_months = {k: (when - pd.DateOffset(months=int(lags[k]))) for k in keys}
    cov = anoms.attrs.get("coverage")
    return {
        "month": when, "sites": keys, "dropped": dropped,
        "coverage": ({k: float(cov[k].get(when, np.nan)) for k in keys}
                     if cov is not None else {}),
        "observed": dict(zip(keys, obs.round(3))),
        "expected": dict(zip(keys, exp.round(3))),
        "driver_oni": {k: float(oni.get(v, np.nan)) for k, v in driver_months.items()},
        "amplitude": amp, "agreement": cos,
        "amplitude_pct": pct(amp, hist_amp), "agreement_pct": pct(cos, hist_cos),
        "reference_n": len(hist_amp),
        "reference_amp": (float(np.nanpercentile(hist_amp, 10)),
                          float(np.nanpercentile(hist_amp, 90))) if len(hist_amp) > 4 else (np.nan, np.nan),
    }


def interpret(fp: dict) -> str:
    """A sentence for the fingerprint, deliberately hedged where the data are."""
    amp, cos = fp["amplitude"], fp["agreement"]
    if not np.isfinite(amp) or not np.isfinite(cos):
        return "not enough reporting sites this month to score a pattern"
    lo, hi = fp["reference_amp"]
    size = ("no measurable ENSO response" if amp < 0.25 else
            "a weak response" if amp < 0.75 else
            "about the expected response" if amp < 1.5 else
            "a stronger response than ENSO alone explains")
    shape = ("the pattern across depth matches" if cos > 0.6 else
             "the pattern across depth is a partial match" if cos > 0.25 else
             "the pattern across depth does not match")
    band = (f" Past ENSO months ran {lo:.2f}-{hi:.2f} on amplitude."
            if np.isfinite(lo) else "")
    return f"{size} (amplitude {amp:.2f}); {shape} (agreement {cos:+.2f}).{band}"


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------

def _shade_events(ax, oni, alpha=0.5):
    for _, e in events(oni).iterrows():
        ax.axvspan(e["start"], e["end"],
                   color=(WARM_C if e["phase"] == "El Nino" else COOL_C),
                   alpha=0.10 * (alpha / 0.5), lw=0, zorder=0)


def plot_oni(oni: pd.Series, out_path: Path | None = None):
    """The index itself, with episodes shaded and the present event called out."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.axhline(0, color=INK_2, lw=0.8)
    for level, colour in ((0.5, WARM_C), (-0.5, COOL_C)):
        ax.axhline(level, color=colour, lw=0.7, ls=":", alpha=0.8)
    ax.fill_between(oni.index, 0, oni.where(oni > 0), color=WARM_C, alpha=0.45, lw=0)
    ax.fill_between(oni.index, 0, oni.where(oni < 0), color=COOL_C, alpha=0.45, lw=0)
    ax.plot(oni.index, oni, color=INK, lw=1.0)
    ax.set_ylabel("ONI (C)")
    ax.set_title(f"{oni.attrs.get('source', 'ENSO index')}, "
                 f"through {oni.index[-1]:%Y-%m}: {oni.iloc[-1]:+.2f}", loc="left")
    ax.annotate(f"{oni.index[-1]:%b %Y}\n{oni.iloc[-1]:+.2f}",
                xy=(oni.index[-1], oni.iloc[-1]), xytext=(-8, 6),
                textcoords="offset points", ha="right", fontsize=9, color=INK)
    lm._style(ax, fig)
    return lm._finish(fig, out_path)


def plot_site(key: str, z: pd.Series, oni: pd.Series, scan: pd.DataFrame,
              comp: dict, comp_ex: dict, lag: int, out_path: Path | None = None):
    """One site: anomaly history against the index, the lag scan, the composite."""
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(11, 6.4))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.35, 1], hspace=0.42, wspace=0.26)
    ax = fig.add_subplot(gs[0, :])

    _shade_events(ax, oni)
    ax.axhline(0, color=INK_2, lw=0.8)
    for level in (1, -1):
        ax.axhline(level, color=INK_2, lw=0.6, ls=":", alpha=0.7)
    ax.plot(z.index, z, color=OBS_C, lw=1.3, label="site anomaly (sd)")
    ax2 = ax.twinx()
    ax2.plot(oni.index, oni.shift(lag), color=FLAG_C, lw=1.1, alpha=0.85,
             label=f"ONI, lagged {lag} mo")
    ax2.set_ylabel("ONI (C)", color=FLAG_C)
    ax2.tick_params(axis="y", colors=FLAG_C)
    ax2.spines["right"].set_visible(False)
    # ONI reaches back to 1950 and the moorings do not; without this the site
    # record is squeezed into the right-hand fifth of the panel.
    pad = pd.DateOffset(months=6)
    ax.set_xlim(z.index.min() - pad, max(z.index.max(), oni.index.max()) + pad)
    ax.set_ylabel("anomaly (sd)")
    ax.set_title(f"{z.attrs.get('label', key)} vs ENSO", loc="left")
    handles = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    labels = ax.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
    ax.legend(handles, labels, frameon=False, fontsize=8, loc="upper left")
    lm._style(ax, fig)

    axl = fig.add_subplot(gs[1, 0])
    if not scan.empty:
        axl.axhline(0, color=INK_2, lw=0.8)
        axl.plot(scan["lag"], scan["r"], color=MEAN_C, lw=1.4, marker="o", ms=3)
        sig = scan[scan["p"] < 0.05]
        axl.plot(sig["lag"], sig["r"], "o", color=FLAG_C, ms=6, zorder=3,
                 label="p < 0.05 (autocorrelation-corrected)")
        axl.legend(frameon=False, fontsize=7.5, loc="best")
    axl.set_xlabel("ONI leads by (months)")
    axl.set_ylabel("correlation")
    axl.set_title("lag scan", loc="left", fontsize=10)
    lm._style(axl, fig)

    axc = fig.add_subplot(gs[1, 1])
    axc.axhline(0, color=INK_2, lw=0.8)
    labels_c, values, colours = [], [], []
    for tag, c in (("El Nino", WARM_C), ("La Nina", COOL_C)):
        labels_c += [f"{tag}\nfull", f"{tag}\nno 14-16"]
        values += [c_["nino"] if tag == "El Nino" else c_["nina"]
                   for c_ in (comp, comp_ex)]
        colours += [c, c]
    axc.bar(range(len(values)), values, color=colours, alpha=0.85)
    axc.set_xticks(range(len(values)))
    axc.set_xticklabels(labels_c, fontsize=7.5)
    axc.set_ylabel("mean anomaly (sd)")
    d, dx = comp["difference"], comp_ex["difference"]
    axc.set_title(f"composite: gap {d:+.2f} sd (excl. {dx:+.2f})", loc="left", fontsize=10)
    lm._style(axc, fig)

    return lm._finish(fig, out_path)


def plot_fingerprint(fp: dict, labels: dict, depths: dict | None = None,
                     out_path: Path | None = None):
    """Observed against expected, site by site, for the scored month.

    Ordered by depth rather than by whatever order the sites were discovered in,
    because the claim being made is about the shape of the response *across
    depth* -- the shelf responding while the canyon does not is the whole point,
    and it is invisible if the rows are shuffled.
    """
    import matplotlib.pyplot as plt
    keys = fp["sites"]
    if depths:
        keys = sorted(keys, key=lambda k: (depths.get(k) is None, depths.get(k) or 0))
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(keys) + 2.6))
    y = np.arange(len(keys))
    ax.axvline(0, color=INK_2, lw=0.8)
    ax.barh(y + 0.18, [fp["expected"][k] for k in keys], height=0.34,
            color=BAND_1, label="expected from ONI")
    ax.barh(y - 0.18, [fp["observed"][k] for k in keys], height=0.34,
            color=OBS_C, label="observed")
    ax.set_yticks(y)
    ax.set_yticklabels([labels.get(k, k) for k in keys], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("anomaly (sd)")
    ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    ax.set_title(f"{fp['month']:%B %Y}: {interpret(fp)}", loc="left", fontsize=10,
                 wrap=True)
    lm._style(ax, fig)
    # Site labels are long; give them room rather than letting them clip.
    fig.subplots_adjust(left=0.30, top=0.84)
    return lm._finish(fig, out_path)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def analyse(live: bool = False, days: int = 30, keys=None,
            quiet: bool = False) -> dict:
    """Everything: index, per-site anomalies, lags, composites, fingerprint."""
    oni = load_oni(quiet=quiet)
    if not quiet:
        print("building monthly anomalies:")
    anoms = all_monthly_anomalies(live=live, days=days, keys=keys, quiet=quiet)

    rows, scans, comps, lags, slopes = [], {}, {}, {}, {}
    for key in anoms.columns:
        z = anoms[key].dropna()
        z.attrs["label"] = anoms.attrs["labels"][key]
        scan = lag_scan(z, oni)
        top = best_lag(scan)
        lag = int(top["lag"]) if np.isfinite(top["lag"]) else 0
        comp = composite(z, oni, lag=lag)
        comp_ex = composite(z, oni, lag=lag, exclude=HEATWAVE)
        reg = regression(z, oni, lag)
        scans[key], comps[key] = scan, (comp, comp_ex)
        lags[key], slopes[key] = lag, reg["slope"]
        rows.append({
            "key": key, "site": anoms.attrs["labels"][key],
            "depth": anoms.attrs["depths"][key], "months": int(len(z)),
            "lag": lag, "r": top["r"], "p": top["p"], "p_adj": top.get("p_adj"),
            "n_eff": top["n_eff"],
            "slope": reg["slope"],
            "nino": comp["nino"], "nina": comp["nina"], "gap": comp["difference"],
            "gap_p": comp["p"], "gap_excl_hw": comp_ex["difference"],
            "n_events": comp["n_nino_events"] + comp["n_nina_events"],
        })
    summary = pd.DataFrame(rows).sort_values("depth", na_position="first")
    fp = fingerprint(anoms, oni, lags, slopes)
    return {"oni": oni, "anomalies": anoms, "summary": summary, "scans": scans,
            "composites": comps, "lags": lags, "slopes": slopes, "fingerprint": fp}


def _robust(row) -> str:
    """Does the composite gap survive dropping the marine heatwave, and n?"""
    gap, ex, p = row["gap"], row["gap_excl_hw"], row["gap_p"]
    if not np.isfinite(gap) or not np.isfinite(ex):
        return "-"
    if np.sign(gap) != np.sign(ex):
        return "sign flips"
    if abs(ex) < 0.5 * abs(gap):
        return "halves"
    if np.isfinite(p) and p < 0.05:
        return "holds"
    return "holds, weak"


def _signal(row) -> str:
    """One word for whether the lagged correlation survives the lag search."""
    p_adj = row.get("p_adj")
    if not np.isfinite(row["r"]):
        return "-"
    if np.isfinite(p_adj) and p_adj < 0.05:
        return "clear"
    if np.isfinite(p_adj) and p_adj < 0.2:
        return "suggestive"
    return "not resolved"


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--site", action="append", help="site key; repeatable (default: all)")
    p.add_argument("--live", action="store_true",
                   help="extend the archives with the ONC API, so the current month is scored")
    p.add_argument("--days", type=int, default=30, help="live window length (default 30)")
    p.add_argument("--summary", action="store_true", help="lag and composite table")
    p.add_argument("--fingerprint", action="store_true", help="score the latest month")
    p.add_argument("--events", action="store_true", help="list ENSO episodes in the record")
    p.add_argument("--plots", action="store_true")
    p.add_argument("--format", choices=("svg", "png"), default="svg",
                   help="figure format (default svg: vector, and about half the "
                        "bytes of the equivalent png)")
    p.add_argument("--outdir", type=Path, default=ENSO_DIR)
    p.add_argument("--refresh-oni", action="store_true")
    args = p.parse_args(argv)

    if args.refresh_oni:
        load_oni(refresh=True)

    if args.events:
        oni = load_oni(quiet=True)
        ev = events(oni)
        print(ev.to_string(index=False))
        if not (args.summary or args.fingerprint or args.plots):
            return 0

    res = analyse(live=args.live, days=args.days, keys=args.site)
    summary, oni = res["summary"], res["oni"]
    summary["robust"] = summary.apply(_robust, axis=1)
    summary["signal"] = summary.apply(_signal, axis=1)

    if args.summary or not (args.fingerprint or args.plots):
        cols = ["site", "months", "lag", "r", "p", "p_adj", "n_eff", "slope",
                "nino", "nina", "gap", "gap_p", "gap_excl_hw", "robust", "signal"]
        print("\nLagged relationship with ONI, and the El Nino / La Nina composite.")
        print("'lag' is months by which ONI leads; 'p_adj' is Bonferroni over the")
        print("lags searched; 'gap' is the El Nino minus La Nina difference in sd")
        print("units, and 'gap_excl_hw' repeats it without 2014-2016.\n")
        print(summary[cols].round(3).to_string(index=False))
        span = res["anomalies"].dropna(how="all").index
        ev = events(oni)
        overlap = ev[(ev["end"] >= span.min()) & (ev["start"] <= span.max())]
        print(f"\nEpisodes overlapping the observations ({span.min():%Y-%m}"
              f"..{span.max():%Y-%m}): "
              f"{(overlap['phase'] == 'El Nino').sum()} El Nino, "
              f"{(overlap['phase'] == 'La Nina').sum()} La Nina. "
              "Every composite rests on that count, not on the length of the index.")
        print("A site's own record may cover fewer -- see 'months' and 'n_events'.")

    fp = res["fingerprint"]
    if args.fingerprint or not (args.summary or args.plots):
        print(f"\nFingerprint for {fp['month']:%B %Y}")
        if fp.get("coverage"):
            worst = min(fp["coverage"].values())
            if worst < 0.9:
                print(f"  note: thinnest site coverage this month is {worst:.0%}")
        print(f"  {interpret(fp)}")
        print(f"  scored against {fp['reference_n']} past ENSO-active months")
        if np.isfinite(fp["amplitude_pct"]):
            print(f"  amplitude sits at the {fp['amplitude_pct']:.0f}th percentile of those, "
                  f"agreement at the {fp['agreement_pct']:.0f}th")
        print(f"  {'site':32s} {'observed':>9s} {'expected':>9s} {'driving ONI':>12s}")
        for k in fp["sites"]:
            print(f"  {res['anomalies'].attrs['labels'][k]:32s} "
                  f"{fp['observed'][k]:+9.2f} {fp['expected'][k]:+9.2f} "
                  f"{fp['driver_oni'][k]:+12.2f}")
        for k, reason in fp.get("dropped", {}).items():
            print(f"  {res['anomalies'].attrs['labels'].get(k, k):32s} "
                  f"not scored: {reason}")

    if args.plots:
        args.outdir.mkdir(parents=True, exist_ok=True)
        plot_oni(oni, args.outdir / f"oni.{args.format}")
        for key in res["anomalies"].columns:
            z = res["anomalies"][key].dropna()
            z.attrs["label"] = res["anomalies"].attrs["labels"][key]
            comp, comp_ex = res["composites"][key]
            plot_site(key, z, oni, res["scans"][key], comp, comp_ex,
                      res["lags"][key], args.outdir / f"{key}_enso.{args.format}")
        plot_fingerprint(fp, res["anomalies"].attrs["labels"],
                         res["anomalies"].attrs["depths"],
                         args.outdir / f"fingerprint.{args.format}")
        summary.round(4).to_csv(args.outdir / "enso_summary.csv", index=False)
        res["anomalies"].round(4).to_csv(args.outdir / "monthly_anomaly.csv")
        print(f"\nwritten  {args.outdir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
