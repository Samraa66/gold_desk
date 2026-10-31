"""Plain-rules check of desk v3.1's re-entry idea on older gold bars: ONE run with the frozen `V31` numbers, printed.

A plumbing and sanity check, never evidence for the model (the model layer can only be tested forward), and no number changes
because of it. If it shows the plumbing is broken, fix the plumbing only.

The rule: every 15 minutes in desk hours (New York time), read the move (`moves.current`, no calls). When a move gains a leg
(its second or later: a re-entry after a pullback failed or a fresh break), trade it at market the move's way with v3.1's rules
baseline numbers: stop `rules_stop_atr_m5` x the M5 ATR, TP1 `min_rr` R (a full exit), hold `default_hold_hours`, flat by the
Friday close. The post-event block (FOMC and payrolls, the built-in list), the no-fade rules, the 0.01-lot ceiling and
"one open call per side" apply. Scored with the live scorer and its costs.

    .venv/bin/python scripts/rules_reentry_check.py --start 2022-12-01 --end 2026-08-31
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gold_agents import calendar as cal  # noqa: E402
from gold_agents import desk_v31 as D31  # noqa: E402
from gold_agents import features as F  # noqa: E402
from gold_agents import journal as J  # noqa: E402
from gold_agents import moves  # noqa: E402
from gold_agents import structure as S  # noqa: E402
from gold_agents.data import TF, resample  # noqa: E402

STEP = pd.Timedelta(minutes=15)


def _closed(bars: pd.DataFrame, tf: str, t: pd.Timestamp, n: int) -> pd.DataFrame:
    """The last `n` bars of timeframe `tf` that had closed by `t`."""
    end = bars.index.searchsorted(t - pd.Timedelta(TF[tf]), side="right")
    return bars.iloc[max(0, end - n):end]


def run(m1: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, v31: D31.V31 = D31.V31_DEFAULT, cfg=None) -> tuple[list[dict], dict]:
    """-> (trades, skipped counts). Each trade: as_of, direction, plan, score."""
    cfg = cfg or D31.config()
    last = end + pd.Timedelta(days=4)
    m1 = m1.loc[start - pd.Timedelta(days=40): last]
    tfs = {name: resample(m1, name, last) for name in ("M5", "M15", "H1", "D1")}
    budget = cfg.equity * cfg.risk_pct / 100
    trades, skipped, legs_seen, open_until = [], {}, {}, {"BUY": None, "SELL": None}
    skip = lambda why: skipped.__setitem__(why, skipped.get(why, 0) + 1)
    for t in pd.date_range(start, end, freq=STEP):
        if cal.desk_window(t.to_pydatetime())[0] not in ("open", "thin"):
            continue
        h1, m15, m5, d1 = (_closed(tfs["H1"], "H1", t, 200), _closed(tfs["M15"], "M15", t, 600), _closed(tfs["M5"], "M5", t, 400),
                           _closed(tfs["D1"], "D1", t, 30))
        if len(h1) < 50 or len(m5) < 50 or m5.index[-1] < t - pd.Timedelta(minutes=30):
            continue
        mv = moves.current({"H1": h1, "M15": m15}, t, F.atr(d1), [])
        if mv["direction"] == "none":
            continue
        key, before = mv["started_at"], legs_seen.get(mv["started_at"], 0)
        legs_seen[key] = mv["legs"]
        if not (mv["legs"] >= 2 and mv["legs"] > before):
            continue
        d = "SELL" if mv["direction"] == "down" else "BUY"
        if open_until[d] is not None and open_until[d] > t:
            skip("same side still open")
            continue
        if cal.blocking_event(t.to_pydatetime(), 0, int(v31.post_event_hours * 60),
                              cal.builtin_events(t.to_pydatetime() - pd.Timedelta(days=1), t.to_pydatetime())):
            skip("post-event block")
            continue
        seq = S.short_term(S.swings(m5.iloc[-288:], k=2))
        if (seq["rising_lows"] >= v31.counter_run and seq["falling_highs"] >= 1) or \
                (d == "SELL" and seq["rising_lows"] >= v31.counter_run) or (d == "BUY" and seq["falling_highs"] >= v31.counter_run):
            skip("no-fade rule")
            continue
        atr_m5 = F.atr(m5)
        if not atr_m5:
            continue
        risk_ = v31.rules_stop_atr_m5 * atr_m5
        if risk_ * 1.0 > budget:                               # 0.01 lot = 1 oz: the ceiling is the budget in dollars
            skip("stop too wide to size at 0.01 lot")
            continue
        px = float(m1.loc[: t - pd.Timedelta(minutes=1), "close"].iloc[-1])
        sign = 1 if d == "BUY" else -1
        plan = {"direction": d, "entry_type": "market", "entry": px, "stop": px - sign * risk_, "tp1": px + sign * v31.min_rr * risk_,
                "tp2": px + sign * 3 * risk_, "max_hold_hours": v31.default_hold_hours,
                "flat_by": str(pd.Timestamp(cal.next_friday_close(t.to_pydatetime())))}
        score = J.score_plan(d, plan, t, m1.loc[t: t + pd.Timedelta(days=4)], cfg, t + pd.Timedelta(days=4))
        if score.get("closed_at"):
            open_until[d] = pd.Timestamp(score["closed_at"])
        trades.append({"as_of": str(t), "direction": d, "legs": mv["legs"], "plan": plan, "score": score})
    return trades, skipped


def summary(trades: list[dict]) -> dict:
    res = [x["score"] for x in trades if x["score"].get("outcome") in ("win", "loss", "expired") and x["score"].get("r") is not None]
    tot = round(sum(s["r"] for s in res), 2)
    return {"trades": len(trades), "resolved": len(res), "wins": sum(s["outcome"] == "win" for s in res),
            "losses": sum(s["outcome"] == "loss" for s in res), "expired": sum(s["outcome"] == "expired" for s in res),
            "total_r": tot, "avg_r": round(tot / len(res), 3) if res else None}


def main():
    from gold_agents.data import load_m1
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-12-01")
    ap.add_argument("--end", default="2026-08-31")
    a = ap.parse_args()
    t0 = time.time()
    trades, skipped = run(load_m1(), pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC"))
    print(f"v31_hash {D31.v31_hash(D31.config())}   {a.start} -> {a.end}   {time.time() - t0:.0f}s")
    by_year = {}
    for x in trades:
        by_year.setdefault(x["as_of"][:4], []).append(x)
    for label, group in [("ALL", trades)] + sorted(by_year.items()):
        s = summary(group)
        print(f"{label:>5}  trades {s['trades']:5d} resolved {s['resolved']:5d} W{s['wins']} L{s['losses']} x{s['expired']} "
              f"total {s['total_r']:+.1f}R avg {s['avg_r']}")
    print("skipped:", skipped)
    print("PLUMBING AND SANITY CHECK ONLY. Not evidence for the model, and no V31 number changes because of it.")


if __name__ == "__main__":
    main()
