"""Stage 2: a plain breakout baseline, setting chosen on everything before 2026 (2018-2025), judged on 2026.

Signal (15-minute bars): close breaks the highest high / lowest low of the last N bars -> enter next minute.
Risk:    stop = K x ATR(14), target = M x ATR(14); one position at a time; closed at 24h if neither hits.
Costs:   buy at ask, sell at bid, exits on the side a real order uses; a minute touching both stop and
         target counts as the STOP. Spread is a fixed assumption (HistData has none).
Few parameters on purpose: every extra knob is another way to fit the past.
"""
import itertools
import numpy as np
import pandas as pd

from src.engine import resolve_position

HORIZON = 24 * 60
TRAIN_END = pd.Timestamp("2026-01-01", tz="UTC")


def bars_15m(m1: pd.DataFrame) -> pd.DataFrame:
    b = m1.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    tr = pd.concat([b.high - b.low, (b.high - b.close.shift()).abs(), (b.low - b.close.shift()).abs()], axis=1).max(axis=1)
    b["atr"] = tr.rolling(14).mean()
    return b


def trades(m1: pd.DataFrame, b: pd.DataFrame, n: int, k: float, mult: float, spread: float) -> np.ndarray:
    hh = b.high.rolling(n).max().shift(1).values
    ll = b.low.rolling(n).min().shift(1).values
    close = b.close.values; atr = b.atr.values
    t15 = b.index.values.astype("datetime64[m]")
    t1 = m1.index.values.astype("datetime64[m]")
    bid_hi, bid_lo, bid_cl = m1.high.values, m1.low.values, m1.close.values
    out, busy_until = [], -1
    for i in range(n + 15, len(b) - 1):
        if np.isnan(atr[i]) or np.isnan(hh[i]):
            continue
        side = 1 if close[i] > hh[i] else (-1 if close[i] < ll[i] else 0)
        if side == 0:
            continue
        j = int(np.searchsorted(t1, t15[i] + np.timedelta64(15, "m")))      # first minute after the bar closes
        if j >= len(t1) - 2 or j <= busy_until:
            continue
        a = atr[i]
        if side == 1:                              # buy: pay ask, leave on bid
            entry = bid_cl[j] + spread; stop = entry - k * a; tgt = entry + mult * a
        else:                                      # sell: hit bid, leave on ask
            entry = bid_cl[j]; stop = entry + k * a; tgt = entry - mult * a
        pnl, end_i, _ = resolve_position(side, entry, stop, tgt, bid_hi, bid_lo, bid_cl, spread,
                                         j + 1, min(j + 1 + HORIZON, len(t1)))
        busy_until = end_i
        out.append((t1[j], pnl, entry))
    return np.array(out, dtype=[("t", "datetime64[m]"), ("pnl", "f8"), ("entry", "f8")])


def stats(tr: np.ndarray) -> dict:
    if len(tr) == 0:
        return {"n": 0}
    p = tr["pnl"]; cum = np.cumsum(p)
    return {"n": len(p), "win": round(float((p > 0).mean()), 3), "avg": round(float(p.mean()), 2),
            "total": round(float(p.sum()), 0), "max_dd": round(float((np.maximum.accumulate(cum) - cum).max()), 0)}


if __name__ == "__main__":
    m1 = pd.read_parquet("data/xauusd_m1_histdata.parquet")
    b = bars_15m(m1)
    split = np.datetime64(TRAIN_END.tz_localize(None), "m")
    for spread in (0.6, 1.0):
        print(f"\n=== spread {spread} ===")
        rows = []
        for n, k, mult in itertools.product((48, 96), (1.0, 2.0), (2.0, 4.0)):
            tr = trades(m1, b, n, k, mult, spread)
            a, c = tr[tr["t"] < split], tr[tr["t"] >= split]
            rows.append({"N": n, "stop_xATR": k, "target_xATR": mult,
                         **{f"train_{x}": y for x, y in stats(a).items()}, **{f"test_{x}": y for x, y in stats(c).items()}})
        d = pd.DataFrame(rows).sort_values("train_total", ascending=False)
        print(d[["N", "stop_xATR", "target_xATR", "train_n", "train_win", "train_avg", "train_total",
                 "test_n", "test_win", "test_avg", "test_total", "test_max_dd"]].to_string(index=False))
        best = d.iloc[0]
        print(f"\nPICKED ON 2018-2025 -> N={int(best.N)}, stop {best.stop_xATR}xATR, target {best.target_xATR}xATR: "
              f"2018-2025 total {best.train_total:+.0f} pts, then 2026 (unseen) total {best.test_total:+.0f} pts over {int(best.test_n)} trades")
