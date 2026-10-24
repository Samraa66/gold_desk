"""Stage 2c data: features and outcome labels for every 15-minute bar.

Decision happens at a bar's close; the trade enters at the next minute. For BOTH sides the label is
what actually happened with a fixed ruler measured in ATR: stop K x ATR, target M x ATR, 24h limit,
bid/ask costs (a buy pays the ask and exits on the bid; a sell the reverse), same-minute tie = stop.
Features use only information available at the bar's close (no lookahead).
"""
import numpy as np
import pandas as pd

K, M, SPREAD, HORIZON = 1.0, 2.0, 0.6, 24 * 60


def make_bars(m1: pd.DataFrame) -> pd.DataFrame:
    b = m1.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    tr = pd.concat([b.high - b.low, (b.high - b.close.shift()).abs(), (b.low - b.close.shift()).abs()], axis=1).max(axis=1)
    b["atr"] = tr.rolling(14).mean()
    return b


def features(b: pd.DataFrame) -> pd.DataFrame:
    a, c = b["atr"], b["close"]
    f = pd.DataFrame(index=b.index)
    for n in (1, 4, 16, 64, 256):
        f[f"ret_{n}"] = (c - c.shift(n)) / a
    f["atr_pct"] = a / c
    f["vol_ratio"] = a / a.rolling(200).mean()
    f["dist_hi96"] = (b.high.rolling(96).max() - c) / a
    f["dist_lo96"] = (c - b.low.rolling(96).min()) / a
    f["gap_sma96"] = (c - c.rolling(96).mean()) / a
    f["gap_sma384"] = (c - c.rolling(384).mean()) / a
    hh, ll = b.high.rolling(16).max(), b.low.rolling(16).min()
    f["pos_4h"] = (c - ll) / (hh - ll).replace(0, np.nan)
    hour = b.index.hour + b.index.minute / 60
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    f["dow"] = b.index.dayofweek
    return f


def outcomes(m1: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    t1 = m1.index.values.astype("datetime64[m]")
    close_t = (b.index + pd.Timedelta(minutes=15)).values.astype("datetime64[m]")
    j_all = np.searchsorted(t1, close_t)
    hi, lo, cl = m1.high.values, m1.low.values, m1.close.values
    atr = b["atr"].values
    n = len(b)
    out = {k: np.full(n, np.nan) for k in ("pnl_long", "pnl_short", "win_long", "win_short", "held_long", "held_short")}
    for i in range(n):
        j = j_all[i]
        if np.isnan(atr[i]) or j >= len(t1) - 2 or (t1[j] - close_t[i]) > np.timedelta64(5, "m"):
            continue
        a = atr[i]
        H = slice(j + 1, j + 1 + HORIZON)
        h, l = hi[H], lo[H]
        last = cl[min(j + HORIZON, len(cl) - 1)]
        # long: pay ask, exit on bid
        e = cl[j] + SPREAD; st, tg = e - K * a, e + M * a
        s_i = int((l <= st).argmax()) if (l <= st).any() else None
        t_i = int((h >= tg).argmax()) if (h >= tg).any() else None
        if s_i is not None and (t_i is None or s_i <= t_i):
            out["pnl_long"][i], out["win_long"][i], out["held_long"][i] = -K * a, 0, s_i
        elif t_i is not None:
            out["pnl_long"][i], out["win_long"][i], out["held_long"][i] = M * a, 1, t_i
        else:
            out["pnl_long"][i], out["win_long"][i], out["held_long"][i] = last - e, 0, len(h)
        # short: sell at bid, exit on ask (= bid + spread)
        e = cl[j]; st, tg = e + K * a, e - M * a
        hs, ls = h + SPREAD, l + SPREAD
        s_i = int((hs >= st).argmax()) if (hs >= st).any() else None
        t_i = int((ls <= tg).argmax()) if (ls <= tg).any() else None
        if s_i is not None and (t_i is None or s_i <= t_i):
            out["pnl_short"][i], out["win_short"][i], out["held_short"][i] = -K * a, 0, s_i
        elif t_i is not None:
            out["pnl_short"][i], out["win_short"][i], out["held_short"][i] = M * a, 1, t_i
        else:
            out["pnl_short"][i], out["win_short"][i], out["held_short"][i] = e - (last + SPREAD), 0, len(h)
    return pd.DataFrame(out, index=b.index)


if __name__ == "__main__":
    m1 = pd.read_parquet("data/xauusd_m1_histdata.parquet")
    b = make_bars(m1)
    f, o = features(b), outcomes(m1, b)
    d = pd.concat([b[["close", "atr"]], f, o], axis=1).dropna()
    d.to_parquet("data/ml_dataset.parquet")
    print(len(d), "labelled bars", d.index.min(), "->", d.index.max())
    print("long  win rate", round(d.win_long.mean(), 3), "| avg pnl pts", round(d.pnl_long.mean(), 3))
    print("short win rate", round(d.win_short.mean(), 3), "| avg pnl pts", round(d.pnl_short.mean(), 3))
    print("break-even win rate for R:R", M, "before costs:", round(K / (K + M), 3))
