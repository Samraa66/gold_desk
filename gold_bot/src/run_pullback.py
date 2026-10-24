"""Stage 4 runner. Protocol enforced in code (see results/stage4_pullback_spec.md):

  python -m src.run_pullback dev              research 2018-21 + validation 2022-23 only; the test years are never loaded into a result
  python -m src.run_pullback test --rr 1.5    opens 2024+ ONCE, only if dev passed for that RR; writes a lock file
"""
import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from src.pullback import Params, run, stats, drop_top

RES = Path("results")
LOCK = RES / "stage4_test_opened.lock"
R_END, V_END = pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")
BASE = Params()
STRESS = replace(BASE, spread=1.00, extra=0.60)


def fmt(s: dict) -> str:
    return f"n={s['n']} netR={s['net_r']:+.1f} PF={s['pf']} win={s['win%']}% exp={s['exp_r']:+.3f}R ret={s.get('ret%', 0)}% maxDD={s['max_dd%']}%"


def yearly(tr: pd.DataFrame) -> list:
    out = ["| Year | Trades | Win % | Net R | PF | Max DD % |", "|---|---|---|---|---|---|"]
    for y, g in tr.groupby(tr.t.dt.year):
        s = stats(g)
        out.append(f"| {y} | {s['n']} | {s['win%']} | {s['net_r']:+.1f} | {s['pf']} | {s['max_dd%']} |")
    return out


def dev_checks(tr_base: pd.DataFrame) -> dict:
    r, v = tr_base[tr_base.t < R_END], tr_base[(tr_base.t >= R_END) & (tr_base.t < V_END)]
    sr, sv = stats(r), stats(v)
    return {"research": sr, "validation": sv,
            "c1": sr["net_r"] > 0 and sr["pf"] >= 1.15 and sv["net_r"] > 0 and sv["pf"] >= 1.15,
            "c2": sr["n"] >= 300 and sv["n"] >= 150}


def dev(m1: pd.DataFrame) -> int:
    m1 = m1[m1.index < V_END]                                # the test years are cut off here, physically
    out = ["# Stage 4 dev results (research 2018-21, validation 2022-23). Spec: results/stage4_pullback_spec.md", ""]
    picks = {}
    for rr in (1.5, 2.0):
        tb, ts = run(m1, replace(BASE, rr=rr)), run(m1, replace(STRESS, rr=rr))
        c = dev_checks(tb)
        picks[rr] = (c, tb, ts)
        out += [f"## RR {rr}", f"- base research:   {fmt(c['research'])}", f"- base validation: {fmt(c['validation'])}",
                f"- stress (all dev): {fmt(stats(ts))}",
                f"- criterion 1 (net R>0 and PF>=1.15 in BOTH periods): {'PASS' if c['c1'] else 'FAIL'};"
                f" criterion 2 trade counts: {'PASS' if c['c2'] else 'FAIL'}", "", *yearly(tb), ""]
    best = max(picks, key=lambda k: stats(picks[k][1])["net_r"])
    c, tb, _ = picks[best]
    ok = c["c1"] and c["c2"]
    out += [f"## Pick: RR {best} (higher base net R over research + validation)",
            f"## Verdict at dev: {'CONTINUE to the one-time test run' if ok else 'FAIL. The test years stay unopened. Strategy rejected.'}", ""]
    out += ["## Informational: sensitivity (research + validation, base costs, RR %s). One good setting among bad ones = overfit." % best,
            "| Variant | n | Net R | PF |", "|---|---|---|---|"]
    for name, p in [("as specified", BASE), ("pull EMA 10", replace(BASE, pull_ema=10)), ("pull EMA 30", replace(BASE, pull_ema=30)),
                    ("swing 5", replace(BASE, swing=5)), ("swing 20", replace(BASE, swing=20)),
                    ("min stop 0.75 ATR", replace(BASE, min_stop_atr=0.75)), ("min stop 1.5 ATR", replace(BASE, min_stop_atr=1.5))]:
        s = stats(run(m1, replace(p, rr=best)))
        out.append(f"| {name} | {s['n']} | {s['net_r']:+.1f} | {s['pf']} |")
    out += ["", "## Informational: regimes (terciles at entry, research + validation, base costs)",
            "| Regime | n | Net R | PF |", "|---|---|---|---|"]
    tb = tb.assign(strength=tb.trend_gap.abs() / tb.atr)
    for col, label in (("strength", "trend strength"), ("atr", "volatility")):
        q = pd.qcut(tb[col], 3, labels=["low", "mid", "high"])
        for k in ("low", "mid", "high"):
            s = stats(tb[q == k])
            out.append(f"| {label} {k} | {s['n']} | {s['net_r']:+.1f} | {s['pf']} |")
    (RES / "stage4_dev.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


def test(m1: pd.DataFrame, rr: float) -> int:
    if LOCK.exists():
        print(f"REFUSED: the test years were already opened ({LOCK.read_text().strip()}). Not running again.")
        return 2
    dev_md = (RES / "stage4_dev.md")
    if not dev_md.exists():
        print("REFUSED: run `dev` first."); return 2
    text = dev_md.read_text()
    if "CONTINUE to the one-time test run" not in text or f"## Pick: RR {rr}" not in text:
        print("REFUSED: dev did not pass for this RR (or a different RR was picked). The test years stay closed."); return 2
    LOCK.write_text(f"opened {pd.Timestamp.now('UTC')} with RR {rr}\n")
    tb, ts = run(m1, replace(BASE, rr=rr)), run(m1, replace(STRESS, rr=rr))
    test_b = tb[tb.t >= V_END]
    st = stats(test_b)
    yrs = tb.groupby(tb.t.dt.year).r.sum()
    c3 = st["n"] >= 200 and st["net_r"] > 0 and st["pf"] >= 1.15
    c4 = ts.r.sum() > 0
    c5 = (yrs > 0).sum() >= 6
    c6 = drop_top(tb).r.sum() > 0
    dd = [stats(tb[(tb.t >= a) & (tb.t < b)])["max_dd%"] for a, b in ((pd.Timestamp("2018-01-01", tz="UTC"), R_END), (R_END, V_END), (V_END, pd.Timestamp("2100-01-01", tz="UTC")))]
    c7 = max(dd) <= 10
    checks = [("3 test net R>0, PF>=1.15, n>=200", c3), ("4 stress total net R>0", c4), ("5 >=6 of 9 years positive", c5),
              ("6 positive without best 5% of trades", c6), ("7 max DD <= 10% in every period", c7)]
    out = [f"# Stage 4 test results (opened once, RR {rr})", "", f"- test (2024+) base: {fmt(st)}",
           f"- stress, whole sample: {fmt(stats(ts))}", f"- whole sample without best 5%: netR={drop_top(tb).r.sum():+.1f}",
           f"- max DD by period (research, validation, test): {dd}", "", *yearly(tb), "", "## Criteria (1 and 2 from dev)"]
    out += [f"- {n}: {'PASS' if ok else 'FAIL'}" for n, ok in checks]
    ok_all = all(ok for _, ok in checks)
    out += ["", f"## Verdict: {'PASSES the backtest criteria. Earns a demo forward test only; not proof of an edge.' if ok_all else 'FAILS. Not allowed to go to demo.'}"]
    (RES / "stage4_test.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("stage", choices=["dev", "test"]); ap.add_argument("--rr", type=float)
    a = ap.parse_args()
    m1 = pd.read_parquet("data/xauusd_m1_histdata.parquet")
    sys.exit(dev(m1) if a.stage == "dev" else test(m1, a.rr))
