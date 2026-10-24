"""How much evidence does a 'pass' need? Coin-flip entries (random side at random slots) through the REAL plan sizing and
scorer, per instrument, on real bars. Gives the null case: win rate, average R after costs, spread of R, how many calls
expire unresolved at 48h vs shorter, and how many resolved calls are needed to see an edge of +0.15R.
Run:  .venv/bin/python scripts/sample_size.py [slots_per_instrument]   (research only; writes nothing)"""
import dataclasses
import math
import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gold_agents import instruments as I          # noqa: E402
from gold_agents import journal as J              # noqa: E402
from gold_agents.agents import risk               # noqa: E402
from gold_agents.context import build_context     # noqa: E402
from gold_agents.data import load_m1              # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
EXPIRIES = (12, 24, 48)
rng = random.Random(7)
Z = 1.645 + 0.842          # one-sided 5% test, 80% power
rows = []
for name in I.INSTRUMENTS:
    spec = I.get(name)
    cfg = spec.config()
    m1 = load_m1(instrument=name)
    end = m1.index[-1] - pd.Timedelta(hours=60)
    slots = [t for t in pd.date_range(end - pd.Timedelta(days=60), end, freq="4h", tz="UTC") if t.weekday() < 5]
    rng.shuffle(slots)
    plans = []
    for t in slots[:N]:
        try:
            ctx = build_context(m1, t, cfg, None, [], None)
        except ValueError:
            continue
        d = rng.choice(("BUY", "SELL"))
        plan, _ = risk.size_plan(ctx, d)
        if plan:
            plans.append((d, plan.to_dict(), t))
    for h in EXPIRIES:
        c = dataclasses.replace(cfg, expiry_hours=float(h))
        res = [J.score_plan(d, p, t, m1, c, m1.index[-1] + pd.Timedelta(minutes=1)) for d, p, t in plans]
        res = [r for r in res if r["outcome"] in ("win", "loss", "expired")]
        rs = [r["r"] for r in res]
        if len(rs) < 10:
            continue
        mean = sum(rs) / len(rs)
        sd = (sum((x - mean) ** 2 for x in rs) / (len(rs) - 1)) ** 0.5
        rows.append((name, h, len(rs), sum(r["outcome"] == "win" for r in res) / len(rs),
                     sum(r["outcome"] == "expired" for r in res) / len(rs), mean, sd, math.ceil((Z * sd / 0.15) ** 2)))
print(f"{'instrument':9s} {'expiry':>6s} {'n':>4s} {'win%':>6s} {'expired%':>9s} {'avg R':>7s} {'sd R':>6s} {'calls to see +0.15R':>20s}")
for r in rows:
    print(f"{r[0]:9s} {r[1]:>5d}h {r[2]:>4d} {r[3]*100:>5.0f}% {r[4]*100:>8.0f}% {r[5]:>+7.3f} {r[6]:>6.2f} {r[7]:>20d}")
print("\ncoin-flip entries; 'calls to see +0.15R' = independent resolved calls for 80% power at a one-sided 5% test.")
