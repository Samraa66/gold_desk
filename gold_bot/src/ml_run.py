"""Stage 2c: train on 2018-2022, choose the cut-off on 2023-2024, look at 2025-2026 ONCE.

Model: a small gradient-boosted tree (shallow, strongly regularised), one per side.
Trades: take the side whose predicted win chance is higher if it clears the cut-off; one position at a time.
All numbers are points of price (1.00 = $1 on an ounce), after costs, same-minute tie = stop.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

d = pd.read_parquet("data/ml_dataset.parquet")
FEATS = [c for c in d.columns if c not in ("close", "atr") and not c.startswith(("pnl_", "win_", "held_"))]
tr = d[d.index < "2023-01-01"]
va = d[(d.index >= "2023-01-01") & (d.index < "2025-01-01")]
te = d[d.index >= "2025-01-01"]
print(f"train {len(tr):,} bars (2018-22) | validate {len(va):,} (2023-24) | test {len(te):,} (2025-26, locked)")
print("features:", len(FEATS))

def fit(side):
    m = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05, min_samples_leaf=500,
                                       l2_regularization=5.0, random_state=0)
    return m.fit(tr[FEATS], tr[f"win_{side}"])

models = {s: fit(s) for s in ("long", "short")}
def score(df):
    out = df[["pnl_long", "pnl_short", "held_long", "held_short"]].copy()
    out["p_long"] = models["long"].predict_proba(df[FEATS])[:, 1]
    out["p_short"] = models["short"].predict_proba(df[FEATS])[:, 1]
    return out
S = {"train": score(tr), "val": score(va), "test": score(te)}
for name, df in (("val", va), ("test", te)):
    print(f"AUC {name}: long {roc_auc_score(df.win_long, S[name].p_long):.3f}  short {roc_auc_score(df.win_short, S[name].p_short):.3f}  (0.500 = no skill)")

def trade(s, cut):
    pnl, busy = [], -1
    ts = s.index.values
    for k in range(len(s)):
        r = s.iloc[k]
        if k <= busy:
            continue
        side = "long" if r.p_long >= r.p_short else "short"
        p = r[f"p_{side}"]
        if p < cut:
            continue
        pnl.append((ts[k], r[f"pnl_{side}"]))
        busy = k + max(1, int(np.ceil(r[f"held_{side}"] / 15)))
    return pd.DataFrame(pnl, columns=["t", "pnl"])

def stats(t):
    if len(t) == 0:
        return dict(n=0, win=np.nan, avg=np.nan, total=0.0, dd=0.0)
    p = t.pnl.values; cum = np.cumsum(p)
    return dict(n=len(p), win=round((p > 0).mean(), 3), avg=round(p.mean(), 3), total=round(p.sum(), 0),
                dd=round((np.maximum.accumulate(cum) - cum).max(), 0))

print("\ncut-off sweep on VALIDATION (2023-24):")
rows = []
for cut in (0.30, 0.34, 0.38, 0.42, 0.46, 0.50):
    rows.append({"cutoff": cut, **stats(trade(S["val"], cut))})
sw = pd.DataFrame(rows); print(sw.to_string(index=False))
ok = sw[sw.n >= 100]
best = ok.sort_values("total", ascending=False).iloc[0] if len(ok) else None
if best is None or best.total <= 0:
    print("\nNo cut-off makes money on validation -> by the pass rules the model FAILS before the locked test is opened.")
    cut = float(sw.sort_values("total", ascending=False).iloc[0].cutoff)
else:
    cut = float(best.cutoff)
    print(f"\npicked cut-off {cut} on validation")

print(f"\nLOCKED TEST (2025-26) at cut-off {cut} -- looked at once:")
t = trade(S["test"], cut); print(stats(t))
t["yr"] = pd.to_datetime(t.t).dt.year
print(t.groupby("yr").pnl.agg(trades="size", total="sum", avg="mean").round(2).to_string())
print("\nfor reference, trading EVERY bar at random-side would be:",
      round(S["test"][["pnl_long", "pnl_short"]].mean().mean(), 3), "pts/trade")
