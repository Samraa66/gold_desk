"""Find the export's time zone: the offset (hours from UTC) at which signal prices sit
inside the candle of the minute they were posted. Uses only signals that quote a price."""
import sys
import numpy as np
import pandas as pd

def calibrate(signals: pd.DataFrame, candles: pd.DataFrame, offsets=range(-12, 15)):
    sig = signals.dropna(subset=["entry_lo"]).copy()
    mid = ((sig.entry_lo + sig.entry_hi) / 2).values
    idx = candles.index.tz_convert("UTC").tz_localize(None).values.astype("datetime64[m]")
    lo = np.minimum(candles.low_bid.values, candles.low_ask.values)
    hi = np.maximum(candles.high_bid.values, candles.high_ask.values)
    scores = {}
    for off in offsets:
        t = (sig.ts_local - pd.Timedelta(hours=off)).values.astype("datetime64[m]")
        j = np.searchsorted(idx, t)
        ok = j < len(idx)
        j = np.minimum(j, len(idx) - 1)
        near = ok & ((idx[j] - t) <= np.timedelta64(2, "m"))
        inside = near & (mid >= lo[j] - 2.0) & (mid <= hi[j] + 2.0)
        scores[off] = (int(inside.sum()), int(near.sum()))
    return scores

if __name__ == "__main__":
    sig = pd.read_parquet(sys.argv[1]); cdl = pd.read_parquet(sys.argv[2])
    s = calibrate(sig, cdl)
    best = sorted(s.items(), key=lambda kv: -kv[1][0])[:4]
    print("offset(hours): (signals inside candle, signals with data nearby)")
    for off, v in best: print(f"  UTC{off:+d}: {v}")
