"""Stage 5 runner (protocol as stage 4): `dev` never loads 2024+; `test --rr 2.0` opens it once, behind a lock."""
import argparse
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

from src.h4 import H4Params, run
from src.pullback import stats, drop_top
from src.run_pullback import fmt, yearly, R_END, V_END

RES = Path("results")
LOCK = RES / "stage5_test_opened.lock"
BASE = H4Params()
STRESS = replace(BASE, spread=1.00, extra=0.60)


def dev(m1):
    m1 = m1[m1.index < V_END]
    tb, ts = run(m1, BASE), run(m1, STRESS)
    r, v = tb[tb.t < R_END], tb[tb.t >= R_END]
    sr, sv = stats(r), stats(v)
    c1 = all(s["net_r"] > 0 and s["pf"] >= 1.15 for s in (sr, sv))
    c2 = sr["n"] >= 60 and sv["n"] >= 30
    out = ["# Stage 5 dev results (research 2018-21, validation 2022-23). Spec: results/stage5_h4_spec.md", "",
           f"- research:   {fmt(sr)}", f"- validation: {fmt(sv)}", f"- stress (all dev): {fmt(stats(ts))}",
           f"- criterion 1: {'PASS' if c1 else 'FAIL'}; criterion 2 counts: {'PASS' if c2 else 'FAIL'}", "", *yearly(tb), "",
           f"## Verdict at dev: {'CONTINUE to the one-time test run' if c1 and c2 else 'FAIL. The test years stay unopened.'}", "",
           "## Diagnostic (information only): costs", "| Costs | n | Net R | PF |", "|---|---|---|---|"]
    for name, p in (("zero", replace(BASE, spread=0, extra=0)), ("spread only", replace(BASE, extra=0)), ("base", BASE)):
        s = stats(run(m1, p)); out.append(f"| {name} | {s['n']} | {s['net_r']:+.1f} | {s['pf']} |")
    out += ["", "## Informational: sensitivity (research + validation, base costs)", "| Variant | n | Net R | PF |", "|---|---|---|---|"]
    for name, p in [("as specified", BASE), ("lookback 10", replace(BASE, lookback=10)), ("lookback 40", replace(BASE, lookback=40)),
                    ("stop 1.5 ATR", replace(BASE, stop_atr=1.5)), ("stop 3.0 ATR", replace(BASE, stop_atr=3.0)),
                    ("RR 1.5", replace(BASE, rr=1.5)), ("RR 3.0", replace(BASE, rr=3.0))]:
        s = stats(run(m1, p)); out.append(f"| {name} | {s['n']} | {s['net_r']:+.1f} | {s['pf']} |")
    (RES / "stage5_dev.md").write_text("\n".join(out) + "\n"); print("\n".join(out))
    return 0


def test(m1):
    if LOCK.exists():
        print(f"REFUSED: test years already opened ({LOCK.read_text().strip()})."); return 2
    f = RES / "stage5_dev.md"
    if not f.exists() or "CONTINUE to the one-time test run" not in f.read_text():
        print("REFUSED: dev did not pass. The test years stay closed."); return 2
    LOCK.write_text(f"opened {pd.Timestamp.now('UTC')}\n")
    tb, ts = run(m1, BASE), run(m1, STRESS)
    st = stats(tb[tb.t >= V_END]); yrs = tb.groupby(tb.t.dt.year).r.sum()
    far = pd.Timestamp("2100-01-01", tz="UTC")
    dd = [stats(tb[(tb.t >= a) & (tb.t < b)])["max_dd%"] for a, b in ((pd.Timestamp("2018-01-01", tz="UTC"), R_END), (R_END, V_END), (V_END, far))]
    checks = [("2 test trades >= 40", st["n"] >= 40), ("3 test net R>0, PF>=1.15", st["net_r"] > 0 and st["pf"] >= 1.15),
              ("4 stress total net R>0", ts.r.sum() > 0), ("5 >=6 of 9 years positive", (yrs > 0).sum() >= 6),
              ("6 positive without best 5%", drop_top(tb).r.sum() > 0), ("7 max DD <= 10% each period", max(dd) <= 10)]
    out = ["# Stage 5 test results (opened once)", "", f"- test (2024+): {fmt(st)}", f"- stress, whole sample: {fmt(stats(ts))}",
           f"- without best 5%: netR={drop_top(tb).r.sum():+.1f}", f"- max DD by period: {dd}", "", *yearly(tb), ""]
    out += [f"- {n}: {'PASS' if ok else 'FAIL'}" for n, ok in checks]
    out += ["", f"## Verdict: {'PASSES the backtest criteria. Earns the forward call log only; not proof of an edge.' if all(o for _, o in checks) else 'FAILS. Not allowed to go to demo.'}"]
    (RES / "stage5_test.md").write_text("\n".join(out) + "\n"); print("\n".join(out)); return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("stage", choices=["dev", "test"]); a = ap.parse_args()
    m1 = pd.read_parquet("data/xauusd_m1_histdata.parquet")
    sys.exit(dev(m1) if a.stage == "dev" else test(m1))
