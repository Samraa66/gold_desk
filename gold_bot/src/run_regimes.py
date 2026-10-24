"""Stage 2b: the SAME rule, with the settings picked on 2025, run unchanged on every year 2018-2026."""
import itertools
import numpy as np
import pandas as pd
from src.baseline import bars_15m, trades

PICKED = (96, 1.0, 4.0)
m1 = pd.read_parquet("data/xauusd_m1_histdata.parquet")
b = bars_15m(m1)

def yearly(tr):
    yrs = tr["t"].astype("datetime64[Y]").astype(int) + 1970
    rows = []
    for y in range(2018, 2027):
        t = tr[yrs == y]
        if len(t) == 0:
            continue
        p = t["pnl"]; cum = np.cumsum(p)
        rows.append({"year": y, "trades": len(t), "win%": round(100 * (p > 0).mean(), 1),
                     "avg_pts": round(p.mean(), 2), "total_pts": round(p.sum()),
                     "total_%_of_price": round(100 * (p / t["entry"]).sum(), 1),
                     "max_dd_pts": round((np.maximum.accumulate(cum) - cum).max())})
    return pd.DataFrame(rows)

for spread in (0.6, 1.0):
    n, k, m = PICKED
    tr = trades(m1, b, n, k, m, spread)
    print(f"\n=== picked rule N={n}, stop {k}xATR, target {m}xATR, spread {spread} ===")
    d = yearly(tr); print(d.to_string(index=False))
    print(f"profitable years: {int((d.total_pts > 0).sum())} of {len(d)}")
    if spread == 0.6:
        d.to_csv("results/stage2b_picked_by_year.csv", index=False)

print("\n=== all 8 settings, total % of price by year (spread 0.6) ===")
grid = {}
for n, k, m in itertools.product((48, 96), (1.0, 2.0), (2.0, 4.0)):
    grid[f"N{n} s{k} t{m}"] = yearly(trades(m1, b, n, k, m, 0.6)).set_index("year")["total_%_of_price"]
print(pd.DataFrame(grid).T.to_string())
