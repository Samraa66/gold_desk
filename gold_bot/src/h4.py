"""Stage 5: H4 Donchian breakout. Rules fixed in results/stage5_h4_spec.md (written before any run)."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.engine import resolve_position
from src.pullback import make_bars


@dataclass(frozen=True)
class H4Params:
    lookback: int = 20
    atr_n: int = 14
    stop_atr: float = 2.0
    rr: float = 2.0
    horizon_min: int = 5 * 24 * 60
    spread: float = 0.60
    extra: float = 0.30


def h4_features(m1: pd.DataFrame, p: H4Params) -> pd.DataFrame:
    b = make_bars(m1, "240min")
    tr = pd.concat([b.high - b.low, (b.high - b.close.shift()).abs(), (b.low - b.close.shift()).abs()], axis=1).max(axis=1)
    b["atr"] = tr.rolling(p.atr_n).mean()
    b["hh"] = b.high.rolling(p.lookback).max().shift(1)     # previous N bars only, never the signal bar
    b["ll"] = b.low.rolling(p.lookback).min().shift(1)
    return b


def signals(f: pd.DataFrame) -> np.ndarray:
    ok = f.atr.notna() & f.hh.notna()
    return np.where(ok & (f.close > f.hh), 1, np.where(ok & (f.close < f.ll), -1, 0))


def trade_plan(side: int, bid: float, atr: float, p: H4Params):
    """(entry, stop, target, risk) for a fill at bid price `bid`. Stop/target follow the engine's ask/bid convention."""
    if side == 1:
        entry, stop = bid + p.spread, bid - p.stop_atr * atr
        risk = entry - stop
        return entry, stop, entry + p.rr * risk, risk
    entry, stop = bid, bid + p.stop_atr * atr + p.spread
    risk = stop - entry
    return entry, stop, entry - p.rr * risk, risk


def run(m1: pd.DataFrame, p: H4Params = H4Params(), feats: pd.DataFrame = None) -> pd.DataFrame:
    f = h4_features(m1, p) if feats is None else feats
    sig = signals(f)
    idx = m1.index.values.astype("datetime64[m]")
    op, hi, lo, cl = (m1[c].values for c in ("open", "high", "low", "close"))
    ends, atr = f["end"].values.astype("datetime64[m]"), f.atr.values
    rows, busy = [], -1
    for i in np.flatnonzero(sig):
        j = int(np.searchsorted(idx, ends[i]))
        if j >= len(idx) - 1 or j <= busy or idx[j] - ends[i] > np.timedelta64(2, "m"):
            continue
        side = int(sig[i])
        entry, stop, tgt, risk = trade_plan(side, op[j], atr[i], p)
        pnl, k, why = resolve_position(side, entry, stop, tgt, hi, lo, cl, p.spread, j, min(j + p.horizon_min, len(idx)))
        busy = k
        net = pnl - p.extra
        rows.append((pd.Timestamp(idx[j], tz="UTC"), pd.Timestamp(idx[k], tz="UTC"), side, entry, stop, risk, net, net / risk, why))
    return pd.DataFrame(rows, columns=["t", "exit_t", "side", "entry", "stop", "risk", "pnl", "r", "why"])
