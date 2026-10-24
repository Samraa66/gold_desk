"""Do the trader's recap claims match what the candles say happened to the same signals?"""
import re
import numpy as np
import pandas as pd
from src.histdata import with_spread
from src.score import Candles

TZ = -5
LINE = re.compile(r"(BUY|SELL)\s*(\d{3,5})\s*[–\-−]\s*(\d{3,5})\s*[→>\-]+\s*(?:TP\s*(\d)\s*)?([+\-–−])\s*(\d+)\s*PIPS", re.I)
H = 24 * 60

def claims(msgs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in msgs[msgs.text.str.contains("recap|summary", case=False) & msgs.text.str.contains("pips", case=False)].itertuples():
        for m in LINE.finditer(r.text):
            sign = -1 if m.group(5) in "-–−" else 1
            lo, hi = sorted((float(m.group(2)), float(m.group(3))))
            rows.append({"recap_ts": r.ts_local, "direction": m.group(1).lower(), "entry_lo": lo, "entry_hi": hi,
                         "claimed_tp": int(m.group(4)) if m.group(4) else None, "claimed_pips": sign * int(m.group(6))})
    return pd.DataFrame(rows)

def my_outcome(sig, c: Candles):
    i = c.at_or_after(pd.Timestamp(sig.ts_local) - pd.Timedelta(hours=TZ))
    if i is None: return None
    buy = sig.direction == "buy"
    end = min(len(c.idx), i + 1 + H)
    hi = (c.bid_hi if buy else c.ask_hi)[i + 1:end]; lo = (c.bid_lo if buy else c.ask_lo)[i + 1:end]
    stop = lo <= sig.sl if buy else hi >= sig.sl
    s_i = int(stop.argmax()) if stop.any() else None
    reached = 0
    for n, level in enumerate(sorted(sig.tps, reverse=not buy), 1):
        m = hi >= level if buy else lo <= level
        t_i = int(m.argmax()) if m.any() else None
        if t_i is not None and (s_i is None or t_i < s_i): reached = n
    return {"my_tp_reached": reached, "my_stopped_first": s_i is not None and reached == 0}

if __name__ == "__main__":
    msgs = pd.read_parquet("data/messages_export_a.parquet")
    sig = pd.read_parquet("data/signals_export_a.parquet"); sig = sig[sig.tps.str.len() > 0]
    c = Candles(with_spread(pd.read_parquet("data/xauusd_m1_histdata.parquet"), 0.6))
    cl = claims(msgs)
    print(len(cl), "claimed trades in", cl.recap_ts.nunique(), "recaps")
    out = []
    for r in cl.itertuples():
        cand = sig[(sig.direction == r.direction) & (sig.entry_lo == r.entry_lo) & (sig.entry_hi == r.entry_hi)
                   & (sig.ts_local <= r.recap_ts) & (sig.ts_local >= r.recap_ts - pd.Timedelta(days=7))]
        if len(cand) != 1: continue                      # none or ambiguous: skip, never guess
        o = my_outcome(next(cand.itertuples()), c)
        if o: out.append({**r._asdict(), **o})
    d = pd.DataFrame(out)
    print(len(d), "claimed trades matched to exactly one signal and replayed\n")
    d["claimed_win"] = d.claimed_pips > 0
    d["my_win"] = d.my_tp_reached > 0
    print("claimed win rate:", round(d.claimed_win.mean(), 3), "| candles say:", round(d.my_win.mean(), 3))
    print("agree on win/loss:", round((d.claimed_win == d.my_win).mean(), 3))
    both = d[d.claimed_win & d.claimed_tp.notna()]
    print("\nwhere they claimed a numbered TP:",
          "\n  candles reached AT LEAST that TP:", round((both.my_tp_reached >= both.claimed_tp).mean(), 3),
          "\n  candles reached EXACTLY that TP: ", round((both.my_tp_reached == both.claimed_tp).mean(), 3),
          "\n  candles reached NO target (stop first):", round((both.my_tp_reached == 0).mean(), 3))
    print("\nclaimed a win but candles show the stop first:", int((d.claimed_win & (d.my_tp_reached == 0)).sum()),
          "of", int(d.claimed_win.sum()))
    print("claimed a loss but candles show a target first:", int((~d.claimed_win & (d.my_tp_reached > 0)).sum()),
          "of", int((~d.claimed_win).sum()))
    d.to_parquet("data/recap_vs_replay.parquet")
