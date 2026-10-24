"""Forward call log: the frozen stage 5 rule makes buy/sell calls on data AFTER 2026-10-09; outcomes are scored later.

  python -m src.paper_calls log [--rebuild|--mt5]   append new calls (never edits or deletes a row); prints the current state
  python -m src.paper_calls score             resolve logged calls against market data that came after them

Honesty rules: a call depends only on the H4 bar that just closed. The log is append-only and keyed by rule hash (a rule
change starts a NEW file). Each row stores `logged_at` and `lag_hours`: a call logged days after its bar closed is not a
real-time call and is marked late. Judged only once at least MIN_CALLS calls have resolved.
"""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.engine import resolve_position
from src.h4 import H4Params, h4_features, signals, trade_plan

HERE = Path(__file__).resolve().parent.parent
FORWARD_START = pd.Timestamp("2026-10-10 00:00", tz="UTC")     # data ends 2026-10-09 21:58 UTC
MIN_CALLS = 30
LATE_HOURS = 6
COLS = ["bar_end", "side", "ref_price", "atr", "rule", "logged_at", "lag_hours", "late"]


def rule_hash(p: H4Params = H4Params()) -> str:
    spec = (HERE / "results" / "stage5_h4_spec.md").read_bytes()
    return hashlib.sha256(spec + repr(p).encode()).hexdigest()[:8]


def log_path(p: H4Params = H4Params()) -> Path:
    return HERE / "results" / f"paper_calls_{rule_hash(p)}.csv"


def new_calls(m1: pd.DataFrame, p: H4Params, start: pd.Timestamp) -> pd.DataFrame:
    f = h4_features(m1, p)
    sig = signals(f)
    ok = (sig != 0) & (f["end"].values >= start.to_datetime64().astype("datetime64[ns]"))
    # only a bar whose close is already in the data counts as closed
    ok &= f["end"].values <= (m1.index.max() + pd.Timedelta("1min")).to_datetime64().astype("datetime64[ns]")
    g = f[ok]
    return pd.DataFrame({"bar_end": g["end"], "side": sig[ok], "ref_price": g.close.values, "atr": g.atr.values})


def log_calls(m1: pd.DataFrame, p: H4Params = H4Params(), start: pd.Timestamp = FORWARD_START, now: pd.Timestamp = None,
              path: Path = None) -> int:
    path = path or log_path(p)
    now = now or pd.Timestamp.now("UTC")
    old = pd.read_csv(path, parse_dates=["bar_end"]) if path.exists() else pd.DataFrame(columns=COLS)
    have = set(pd.to_datetime(old.bar_end, utc=True)) if len(old) else set()
    c = new_calls(m1, p, start)
    c = c[~c.bar_end.isin(have)]
    if c.empty:
        return 0
    c = c.assign(rule=rule_hash(p), logged_at=now, lag_hours=((now - c.bar_end).dt.total_seconds() / 3600).round(1))
    c["late"] = c.lag_hours > LATE_HOURS
    out = pd.concat([old, c[COLS]], ignore_index=True) if len(old) else c[COLS]
    out.to_csv(path, index=False)
    return len(c)


def score(m1: pd.DataFrame, p: H4Params = H4Params(), path: Path = None) -> pd.DataFrame:
    path = path or log_path(p)
    cols = ["bar_end", "side", "status", "r", "late"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    calls = pd.read_csv(path, parse_dates=["bar_end"])
    idx = m1.index.values.astype("datetime64[m]")
    op, hi, lo, cl = (m1[c].values for c in ("open", "high", "low", "close"))
    rows, busy = [], -1
    for c in calls.itertuples():
        j = int(np.searchsorted(idx, np.datetime64(c.bar_end.tz_convert("UTC").tz_localize(None), "m")))
        if j >= len(idx) - 1 or j <= busy or idx[j] - np.datetime64(c.bar_end.tz_convert("UTC").tz_localize(None), "m") > np.timedelta64(2, "m"):
            rows.append((c.bar_end, c.side, "skipped" if j < len(idx) - 1 else "no data yet", np.nan, bool(c.late))); continue
        entry, stop, tgt, risk = trade_plan(int(c.side), op[j], c.atr, p)
        end = min(j + p.horizon_min, len(idx))
        pnl, k, why = resolve_position(int(c.side), entry, stop, tgt, hi, lo, cl, p.spread, j, end)
        if why == "time" and j + p.horizon_min > len(idx):
            rows.append((c.bar_end, c.side, "open", np.nan, bool(c.late))); continue     # outcome not known yet
        busy = k
        rows.append((c.bar_end, c.side, why, (pnl - p.extra) / risk, bool(c.late)))
    return pd.DataFrame(rows, columns=["bar_end", "side", "status", "r", "late"])


def summary(res: pd.DataFrame) -> str:
    late = int(res.late.sum())
    done = res[res.r.notna() & ~res.late.astype(bool)]            # only calls logged in time can count toward the verdict
    if done.empty:
        return f"{len(res)} calls logged ({late} late, never counted), 0 on-time calls resolved yet."
    r = done.r.values; gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    pf = gw / gl if gl else float("inf")
    msg = (f"{len(res)} calls, {len(done)} resolved, net {r.sum():+.1f} R, PF {pf:.2f}, win {100 * (r > 0).mean():.0f}%, "
           f"{late} logged late and not counted")
    if len(done) < MIN_CALLS:
        return msg + f". Too few to judge: need {MIN_CALLS} resolved calls, a streak of {len(done)} proves nothing."
    return msg + (". Meets the 30-call bar: " + ("PF >= 1.15 and net positive (still only a hint)" if pf >= 1.15 and r.sum() > 0 else "no edge shown"))


def current_state(m1: pd.DataFrame, p: H4Params = H4Params()) -> str:
    f = h4_features(m1, p)
    sig = signals(f)
    closed = f["end"].values <= (m1.index.max() + pd.Timedelta("1min")).to_datetime64().astype("datetime64[ns]")
    f, sig = f[closed], sig[closed]                              # a bar still forming is not a closed bar
    last = f.iloc[-1]
    s = int(sig[-1])
    call = {1: "BUY", -1: "SELL", 0: "no call"}[s]
    return f"Latest closed H4 bar ends {last['end']:%Y-%m-%d %H:%M} UTC, close {last.close:.2f}: {call}"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "log"
    if "--mt5" in sys.argv:
        from src.mt5_data import combined
        m1 = combined()                                     # HistData history + MT5 bars after it (run mt5/export_bars.py first)
    elif "--rebuild" in sys.argv:
        from src.histdata import load_bars
        m1 = load_bars(); m1.to_parquet(HERE / "data" / "xauusd_m1_histdata.parquet")
    else:
        m1 = pd.read_parquet(HERE / "data" / "xauusd_m1_histdata.parquet")
    print(f"data ends {m1.index.max():%Y-%m-%d %H:%M} UTC; rule {rule_hash()}")
    if mode == "log":
        print(f"logged {log_calls(m1)} new call(s) -> {log_path().name}")
        print(current_state(m1))
    print(summary(score(m1)))
