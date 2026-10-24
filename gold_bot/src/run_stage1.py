"""Stage 1: do the channel's own signals make money on real candles, after costs?"""
import sys
import pandas as pd
from src.histdata import with_spread
from src.score import run, summarize

TZ = 0   # signal times are converted to true UTC below (the export clock is New York wall time, DST included)
bars = pd.read_parquet("data/xauusd_m1_histdata.parquet")
sig = pd.read_parquet("data/signals_export_a.parquet")
sig = sig[sig.tps.str.len() > 0].reset_index(drop=True)
_ny = pd.to_datetime(sig.ts_local).dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
sig = sig[_ny.notna().values].reset_index(drop=True)
sig["ts_local"] = _ny[_ny.notna()].dt.tz_convert("UTC").dt.tz_localize(None).values   # now naive UTC      # fully specified: entry, stop, numbered targets
# Drop posts whose quoted levels are impossible next to the live price (typos like SL 3140 at 4140).
from src.score import Candles
_c = Candles(with_spread(bars, 0.6)); keep = []
for r in sig.itertuples():
    i = _c.at_or_after(pd.Timestamp(r.ts_local) - pd.Timedelta(hours=TZ))
    if i is None:
        keep.append(False); continue
    px = _c.bid_cl[i]
    levels = [r.sl] + list(r.tps) + ([r.entry_lo, r.entry_hi] if pd.notna(r.entry_lo) else [])
    keep.append(all(abs(v - px) <= 40 for v in levels))
dropped = len(sig) - sum(keep); sig = sig[keep].reset_index(drop=True)
print(f"dropped {dropped} posts with a level more than $40 from the live price (typos)")
print(f"{len(sig)} fully specified signals, {sig.ts_local.min().date()} -> {sig.ts_local.max().date()}\n")

rows = []
for entry_mode in ("zone", "market"):
    for spread in (0.6, 1.0):
        cdl = with_spread(bars, spread)
        for variant in ("tp1", "split", "split_be"):
            res = run(sig, cdl, TZ, variant, entry_mode, spread)
            s_ = summarize(res); s_.update(entry=entry_mode, spread=spread, variant=variant)
            rows.append(s_)
            if spread == 0.6 and variant == "split_be":
                res.to_parquet(f"data/results_{entry_mode}_split_be_060.parquet")
out = pd.DataFrame(rows)[["entry", "spread", "variant", "n", "win_rate", "avg_points", "total_points",
                          "avg_win", "avg_loss", "max_drawdown_points", "worst_losing_streak"]]
print(out.to_string(index=False))
print("\nentry 'zone' = as the trader claims (optimistic). 'market' = what a follower gets after the post.")
print("points: 1.00 = $1 move on an ounce = 10 'pips' as the channel counts them")
