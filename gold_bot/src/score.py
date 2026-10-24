"""Replay each parsed signal through real bid/ask 1-minute candles.

Conservative rules, all stated so the result can be argued with:
- Entry: market, at the post minute's close: buys pay the ASK, sells get the BID.
  (A zone the trader quotes is not assumed to fill at its best edge.)
- Exits are checked on the side a real order would use: a buy closes on the BID, a sell on the ASK.
- A minute that touches both the stop and a target counts as the STOP (worst case).
- Positions not resolved within HORIZON_MIN are closed at that minute's close.
- Result unit: price points (1.00 = $1 move on one ounce = 10 "pips" as this channel counts them).
Variants for how the trade is run:
  tp1     all-in: exit at TP1 or the stop.
  split   equal legs, one per numbered TP, stop fixed for every leg.
  split_be  like split, but after TP1 is hit the stop for the remaining legs moves to entry.
"""
import numpy as np
import pandas as pd

HORIZON_MIN = 12 * 60


class Candles:
    def __init__(self, df: pd.DataFrame):
        self.idx = df.index.values.astype("datetime64[m]")
        self.bid_hi, self.bid_lo, self.bid_cl = (df[f"{c}_bid"].values for c in ("high", "low", "close"))
        self.ask_hi, self.ask_lo, self.ask_cl = (df[f"{c}_ask"].values for c in ("high", "low", "close"))

    def at_or_after(self, ts_utc: pd.Timestamp):
        t = np.datetime64(ts_utc.tz_localize(None) if ts_utc.tzinfo else ts_utc, "m")
        i = int(np.searchsorted(self.idx, t))
        if i >= len(self.idx) or (self.idx[i] - t) > np.timedelta64(10, "m"):
            return None                 # no market data near this post (weekend/gap)
        return i


def _first(mask: np.ndarray):
    return int(mask.argmax()) if mask.any() else None


def replay(sig, c: Candles, tz_offset_hours: float, variant: str, entry_mode: str = "market", spread: float = 0.0):
    ts = pd.Timestamp(sig.ts_local) - pd.Timedelta(hours=tz_offset_hours)
    i = c.at_or_after(ts)
    if i is None:
        return None
    buy = sig.direction == "buy"
    end = min(len(c.idx), i + 1 + HORIZON_MIN)
    if entry_mode == "zone":
        # "as claimed": the quoted zone's midpoint, plus the spread on a buy. Optimistic upper bound.
        if sig.entry_lo is None or pd.isna(sig.entry_lo):
            return None
        mid = (sig.entry_lo + sig.entry_hi) / 2
        entry = mid + spread if buy else mid
    else:
        entry = c.ask_cl[i] if buy else c.bid_cl[i]
    # exit side: a buy leaves on the bid, a sell on the ask
    hi = (c.bid_hi if buy else c.ask_hi)[i + 1:end]
    lo = (c.bid_lo if buy else c.ask_lo)[i + 1:end]
    close = (c.bid_cl if buy else c.ask_cl)[end - 1] if end - 1 > i else entry
    sgn = 1 if buy else -1
    tps = sorted(sig.tps, reverse=not buy)
    if not tps:
        return None
    stop_hit = lo <= sig.sl if buy else hi >= sig.sl
    s_i = _first(stop_hit)

    def hit(level):
        m = hi >= level if buy else lo <= level
        return _first(m)

    tp_i = [hit(t) for t in tps]
    legs = [tps[0]] if variant == "tp1" else tps
    legs_i = tp_i[:1] if variant == "tp1" else tp_i
    stop_pts = sgn * (sig.sl - entry)
    results = []
    be_from = None
    if variant == "split_be" and tp_i[0] is not None and (s_i is None or tp_i[0] < s_i):
        be_from = tp_i[0]
    for level, t_i in zip(legs, legs_i):
        tgt = sgn * (level - entry)
        if variant == "split_be" and be_from is not None:
            # after TP1 the stop is at entry: find a return to entry after TP1
            back = (lo[be_from + 1:] <= entry) if buy else (hi[be_from + 1:] >= entry)
            b_i = _first(back)
            b_i = None if b_i is None else b_i + be_from + 1
            if t_i is not None and (b_i is None or t_i <= be_from or t_i < b_i):
                results.append(tgt)
            elif b_i is not None:
                results.append(0.0)
            else:
                results.append(sgn * (close - entry))
            continue
        if t_i is not None and (s_i is None or t_i < s_i):
            results.append(tgt)                      # target first (a same-minute tie goes to the stop)
        elif s_i is not None:
            results.append(stop_pts)
        else:
            results.append(sgn * (close - entry))
    return {"msg_id": sig.msg_id, "ts_utc": ts, "direction": sig.direction, "entry": entry,
            "legs": len(results), "points": float(np.mean(results)),
            "stopped": s_i is not None and (not tp_i or tp_i[0] is None or s_i <= tp_i[0])}


def run(signals: pd.DataFrame, candles: pd.DataFrame, tz_offset_hours: float, variant: str,
        entry_mode: str = "market", spread: float = 0.0) -> pd.DataFrame:
    c = Candles(candles)
    out = [r for r in (replay(s, c, tz_offset_hours, variant, entry_mode, spread) for s in signals.itertuples()) if r]
    return pd.DataFrame(out)


def summarize(res: pd.DataFrame) -> dict:
    if res.empty:
        return {"n": 0}
    p = res["points"].values
    cum = np.cumsum(p)
    dd = float((np.maximum.accumulate(cum) - cum).max())
    streak = best = 0
    for x in p:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    return {"n": int(len(p)), "win_rate": round(float((p > 0).mean()), 3),
            "avg_points": round(float(p.mean()), 2), "total_points": round(float(p.sum()), 1),
            "max_drawdown_points": round(dd, 1), "worst_losing_streak": int(best),
            "avg_win": round(float(p[p > 0].mean()), 2) if (p > 0).any() else 0.0,
            "avg_loss": round(float(p[p < 0].mean()), 2) if (p < 0).any() else 0.0}
