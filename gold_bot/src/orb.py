"""Stage 3: session opening-range breakout, rules fixed in results/stage3_orb_spec.md.

Run: python -m src.orb
"""
import numpy as np
import pandas as pd

from src.engine import resolve_position

SESSIONS = {"london": ("Europe/London", 8, 0), "newyork": ("America/New_York", 9, 30)}
RANGE_MIN, ENTRY_WINDOW_MIN, EXIT_MIN, RR = 30, 180, 240, 2.0   # defaults = variant set A


def session_trades(m1: pd.DataFrame, name: str, spread: float, range_min: int = RANGE_MIN,
                   exit_min: int = EXIT_MIN) -> pd.DataFrame:
    tzname, hh, mm = SESSIONS[name]
    days = m1.index.tz_convert(tzname).normalize().unique()
    hi_a, lo_a, cl_a = m1.high.values, m1.low.values, m1.close.values
    idx = m1.index.values.astype("datetime64[m]")
    rows = []
    for d in days:
        if d.dayofweek >= 5:
            continue
        open_local = d.tz_localize(None).replace(hour=hh, minute=mm)
        open_utc = pd.Timestamp(open_local).tz_localize(tzname, ambiguous="NaT", nonexistent="NaT")
        if pd.isna(open_utc):
            continue
        t0 = np.datetime64(open_utc.tz_convert("UTC").tz_localize(None), "m")
        i0 = int(np.searchsorted(idx, t0))
        i1 = int(np.searchsorted(idx, t0 + np.timedelta64(range_min, "m")))
        if i1 - i0 < range_min * 0.8 or i1 >= len(idx) - 1 or idx[i0] - t0 > np.timedelta64(5, "m"):
            continue                                            # session not present in the data
        rh, rl = hi_a[i0:i1].max(), lo_a[i0:i1].min()
        iend = int(np.searchsorted(idx, t0 + np.timedelta64(exit_min, "m")))
        ientry_end = int(np.searchsorted(idx, t0 + np.timedelta64(range_min + ENTRY_WINDOW_MIN, "m")))
        side, j = 0, None
        for k in range(i1 + 4, min(ientry_end, len(idx)), 5):  # 5-minute closes (bar of minutes k-4..k)
            c = cl_a[k]
            if c > rh:
                side, j = 1, k; break
            if c < rl:
                side, j = -1, k; break
        if side == 0:
            continue
        if side == 1:
            entry = cl_a[j] + spread; stop = rl; risk = entry - stop
            tgt = entry + RR * risk
        else:
            entry = cl_a[j]; stop = rh + spread; risk = stop - entry
            tgt = entry - RR * risk
        if risk <= 0:
            continue
        pnl, _, _ = resolve_position(side, entry, stop, tgt, hi_a, lo_a, cl_a, spread, j + 1, iend)
        rows.append((pd.Timestamp(idx[j], tz="UTC"), side, entry, risk, pnl))
    return pd.DataFrame(rows, columns=["t", "side", "entry", "risk", "pnl"])


def summarize(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n": 0}
    p = tr.pnl; gw, gl = p[p > 0].sum(), -p[p < 0].sum()
    cum = p.cumsum()
    return {"n": len(p), "win%": round(100 * (p > 0).mean(), 1), "total": round(p.sum(), 0),
            "pf": round(gw / gl, 2) if gl else np.inf, "max_dd": round((cum.cummax() - cum).max(), 0)}


def report(m1: pd.DataFrame, range_min: int = RANGE_MIN, exit_min: int = EXIT_MIN) -> str:
    out = []
    for name in SESSIONS:
        for spread in (0.60, 1.00):
            tr = session_trades(m1, name, spread, range_min, exit_min)
            tr["year"] = tr.t.dt.year
            out.append(f"\n## {name}, spread {spread:.2f}")
            out.append("| Year | Trades | Win % | Total pts | PF | Max DD |\n|---|---|---|---|---|---|")
            for y, g in tr.groupby("year"):
                s = summarize(g)
                out.append(f"| {y} | {s['n']} | {s['win%']} | {s['total']:+.0f} | {s['pf']} | {s['max_dd']:.0f} |")
            core = tr[tr.year <= 2024]; s = summarize(core)
            yrs = core.groupby("year").pnl.sum()
            out.append(f"\n2018-2024: n={s['n']} total={s['total']:+.0f} pf={s['pf']} positive years={(yrs > 0).sum()}/{len(yrs)}")
            ok = s["n"] >= 300 and s["total"] > 0 and s["pf"] >= 1.15 and (yrs > 0).sum() >= 5
            out.append(f"criteria 1-3 at this spread: {'PASS' if ok else 'FAIL'}")
    return "\n".join(out)


if __name__ == "__main__":
    m1 = pd.read_parquet("data/xauusd_m1_histdata.parquet")
    import sys
    print(report(m1, 60, 300) if "--b" in sys.argv else report(m1))
