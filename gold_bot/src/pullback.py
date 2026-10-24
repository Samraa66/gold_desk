"""Stage 4: H1 trend + M15 pullback. Rules are fixed in results/stage4_pullback_spec.md (written before any run).

Pure functions: bars -> features -> signals -> trades. Nothing here reads the future: every feature at a bar
uses only that bar and earlier ones, the H1 trend is joined from the last H1 bar that had CLOSED, and entries
happen at the open of the first minute after the signal bar closes.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.engine import resolve_position


@dataclass(frozen=True)
class Params:
    ema_fast: int = 50
    ema_slow: int = 200
    pull_ema: int = 20
    touch_bars: int = 4          # touch within bars i-3..i
    swing: int = 10
    atr_n: int = 14
    min_stop_atr: float = 1.0
    max_stop_atr: float = 3.0
    hour_from: int = 7
    hour_to: int = 19
    horizon_min: int = 12 * 60
    rr: float = 2.0
    spread: float = 0.60
    extra: float = 0.30          # commission + slippage, points per trade


def make_bars(m1: pd.DataFrame, freq: str) -> pd.DataFrame:
    b = m1.resample(freq, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    b["end"] = b.index + pd.Timedelta(freq)
    return b


def m15_features(m1: pd.DataFrame, p: Params) -> pd.DataFrame:
    m15, h1 = make_bars(m1, "15min"), make_bars(m1, "60min")
    m15["ema"] = m15.close.ewm(span=p.pull_ema, adjust=False).mean()
    tr = pd.concat([m15.high - m15.low, (m15.high - m15.close.shift()).abs(),
                    (m15.low - m15.close.shift()).abs()], axis=1).max(axis=1)
    m15["atr"] = tr.rolling(p.atr_n).mean()
    m15["swing_lo"] = m15.low.rolling(p.swing).min()
    m15["swing_hi"] = m15.high.rolling(p.swing).max()
    e_f = h1.close.ewm(span=p.ema_fast, adjust=False).mean()
    e_s = h1.close.ewm(span=p.ema_slow, adjust=False).mean()
    h = pd.DataFrame({"end": h1["end"], "gap": (e_f - e_s)})
    h.loc[np.arange(len(h)) < p.ema_slow, "gap"] = np.nan       # not enough history yet
    # the H1 bar is usable from its END; each M15 bar takes the last H1 bar that ended at or before its own end
    j = pd.merge_asof(m15[["end"]].reset_index(), h.sort_values("end"), on="end", direction="backward")
    m15["trend_gap"] = j["gap"].values
    return m15


def signals(f: pd.DataFrame, p: Params) -> np.ndarray:
    """+1 long signal, -1 short signal, 0 none, per M15 bar (evaluated at that bar's close)."""
    touch_l = (f.low <= f.ema).astype(float).rolling(p.touch_bars).max() > 0
    touch_s = (f.high >= f.ema).astype(float).rolling(p.touch_bars).max() > 0
    long_ = touch_l & (f.close > f.ema) & (f.close > f.open) & (f.close > f.high.shift()) & (f.trend_gap > 0)
    short = touch_s & (f.close < f.ema) & (f.close < f.open) & (f.close < f.low.shift()) & (f.trend_gap < 0)
    ok = f.atr.notna() & f.swing_lo.notna()
    hr, dow = f["end"].dt.hour, f["end"].dt.dayofweek
    ok &= (hr >= p.hour_from) & (hr < p.hour_to) & (dow < 5)
    return np.where(ok & long_, 1, np.where(ok & short, -1, 0))


def run(m1: pd.DataFrame, p: Params = Params(), feats: pd.DataFrame = None) -> pd.DataFrame:
    f = m15_features(m1, p) if feats is None else feats
    sig = signals(f, p)
    idx = m1.index.values.astype("datetime64[m]")
    op, hi, lo, cl = (m1[c].values for c in ("open", "high", "low", "close"))
    ends = f["end"].values.astype("datetime64[m]")
    atr, s_lo, s_hi = f.atr.values, f.swing_lo.values, f.swing_hi.values
    rows, busy = [], -1
    for i in np.flatnonzero(sig):
        j = int(np.searchsorted(idx, ends[i]))
        if j >= len(idx) - 1 or j <= busy or idx[j] - ends[i] > np.timedelta64(2, "m"):
            continue
        side, a, bid = int(sig[i]), atr[i], op[j]
        if side == 1:
            level = min(s_lo[i], bid - p.min_stop_atr * a)
            if bid - level > p.max_stop_atr * a:
                continue
            entry, stop = bid + p.spread, level
            risk = entry - stop
            tgt = entry + p.rr * risk
        else:
            level = max(s_hi[i], bid + p.min_stop_atr * a)
            if level - bid > p.max_stop_atr * a:
                continue
            entry, stop = bid, level + p.spread
            risk = stop - entry
            tgt = entry - p.rr * risk
        end = min(j + p.horizon_min, len(idx))
        pnl, k, why = resolve_position(side, entry, stop, tgt, hi, lo, cl, p.spread, j, end)
        busy = k
        net = pnl - p.extra
        rows.append((pd.Timestamp(idx[j], tz="UTC"), pd.Timestamp(idx[k], tz="UTC"), side, entry, stop, risk, net,
                     net / risk, why, a, f.trend_gap.values[i]))
    return pd.DataFrame(rows, columns=["t", "exit_t", "side", "entry", "stop", "risk", "pnl", "r", "why", "atr", "trend_gap"])


def stats(tr: pd.DataFrame, risk_pct: float = 0.0025) -> dict:
    if tr.empty:
        return {"n": 0, "net_r": 0.0, "pf": 0.0, "win%": 0.0, "exp_r": 0.0, "max_dd%": 0.0, "max_loss_streak": 0}
    r = tr.r.values
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    eq = np.cumprod(1 + risk_pct * r)
    dd = float(((np.maximum.accumulate(eq) - eq) / np.maximum.accumulate(eq)).max())
    streak = best = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    return {"n": len(r), "net_r": round(float(r.sum()), 1), "pf": round(float(gw / gl), 2) if gl else float("inf"),
            "win%": round(100 * float((r > 0).mean()), 1), "exp_r": round(float(r.mean()), 3),
            "ret%": round(100 * float(eq[-1] - 1), 1), "max_dd%": round(100 * dd, 1), "max_loss_streak": best}


def drop_top(tr: pd.DataFrame, frac: float = 0.05) -> pd.DataFrame:
    k = int(np.ceil(len(tr) * frac))
    return tr.drop(tr.r.nlargest(k).index)
