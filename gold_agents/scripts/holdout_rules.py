"""Rules-only holdout over older history, scored per calendar year against the H4-trend baseline.

Same frozen Config as the live log (rules_hash printed). No model, no tuning: the output is a verdict on the
rules, not a place to adjust them. Macro data exists only for the last year (Yahoo cache), so the macro agent
abstains before then; the chart, liquidity and risk agents are the full rules. The result says nothing about the
model version (it would be leaky on past dates).

    .venv/bin/python scripts/holdout_rules.py --start 2022-12-01 --end 2026-08-15 --step-hours 4
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gold_agents import journal as J  # noqa: E402
from gold_agents.config import Config, rules_hash  # noqa: E402
from gold_agents.data import load_m1  # noqa: E402
from gold_agents.runner import decide_at  # noqa: E402

WINDOW_DAYS = 60   # the agents use at most ~25 days of bars; 60 keeps each step fast without changing a decision


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--step-hours", type=int, default=4)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "journal" / "holdout_rules.jsonl")
    a = ap.parse_args()

    cfg, m1 = Config(), load_m1()
    start, end = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC")
    steps = list(pd.date_range(start, end, freq=f"{a.step_hours}h"))
    entries, t0 = [], time.time()
    for i, t in enumerate(steps):
        if t.dayofweek >= 5:      # weekends: market closed, the liquidity agent would veto anyway
            continue
        bars = m1.loc[t - pd.Timedelta(days=WINDOW_DAYS): t]
        if bars.empty:
            continue
        entries.append(decide_at(bars, t, cfg, macro_df=None, prior_entries=entries))
        if i % 500 == 0:
            print(f"  step {i}/{len(steps)}  {time.time() - t0:.0f}s", file=sys.stderr)

    a.out.unlink(missing_ok=True)
    scored = J.score_entries(entries, m1, cfg, end + pd.Timedelta(days=3))
    for e in scored:
        J.append({k: v for k, v in e.items() if k != "scores"}, a.out)

    print(f"rules_hash {rules_hash(cfg)}   {len(entries)} weekday steps {start.date()} -> {end.date()}, every {a.step_hours}h")
    by_year = {}
    for e in scored:
        by_year.setdefault(pd.Timestamp(e["as_of"]).year, []).append(e)
    for label, group in [("ALL", scored)] + [(str(y), g) for y, g in sorted(by_year.items())]:
        s = J.summarize(group)
        line = f"{label:>5}  steps {s['runs']:5d} pass {s['passes']:5d}"
        for name in ("master", "trend_h4"):
            v = s.get(name)
            if v:
                line += (f" | {name}: n={v['resolved']:4d} W{v['wins']} L{v['losses']} x{v['expired']} "
                         f"total {v['total_r']:+.1f}R avg {v['avg_r']}")
        print(line)
    print("Pass bar from the README: avg R after costs > +0.15 and > trend_h4 by 0.15R. Rules stay frozen whatever this says.")


if __name__ == "__main__":
    main()
