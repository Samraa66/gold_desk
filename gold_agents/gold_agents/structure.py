"""Price structure from closed bars: swings, tested zones, the swing pattern, where price sits in its range.

Added 2026-10-28 for the v2 desk. The v1 chart agent saw ten summary numbers (EMA-cross trend signs, a breakout
position, momentum, ATR, five levels) and no candles, so it could not see that 3,975-4,000 had held three times or
that price sat mid-range; it kept leaning SELL into a floor while gold bounced $70. This module computes what a
person reads off the chart, and `bars_text` hands the model the candles themselves. Plain numbers, no judgement.
"""
from __future__ import annotations

import pandas as pd

from . import features as F


def swings(bars: pd.DataFrame, k: int = 2) -> list[dict]:
    """Fractal swing points: a high (low) higher (lower) than the `k` closed bars on each side. Oldest first.
    The last `k` bars cannot be confirmed yet, so a swing is only reported once `k` later bars have closed."""
    out = []
    hi, lo = bars["high"].to_numpy(), bars["low"].to_numpy()
    for i in range(k, len(bars) - k):
        if hi[i] == max(hi[i - k:i + k + 1]) and hi[i] > max(hi[i - k:i]) and hi[i] >= max(hi[i + 1:i + k + 1]):
            out.append({"time": bars.index[i], "kind": "H", "price": float(hi[i])})
        if lo[i] == min(lo[i - k:i + k + 1]) and lo[i] < min(lo[i - k:i]) and lo[i] <= min(lo[i + 1:i + k + 1]):
            out.append({"time": bars.index[i], "kind": "L", "price": float(lo[i])})
    return out


def pattern(sw: list[dict], dp: int = 2) -> dict:
    """The last two swing highs and lows compared: HH/LH and HL/LL, and the bias they make together."""
    highs = [s["price"] for s in sw if s["kind"] == "H"][-2:]
    lows = [s["price"] for s in sw if s["kind"] == "L"][-2:]
    hs = None if len(highs) < 2 else ("higher_high" if highs[1] > highs[0] else "lower_high")
    ls = None if len(lows) < 2 else ("higher_low" if lows[1] > lows[0] else "lower_low")
    bias = 1 if (hs, ls) == ("higher_high", "higher_low") else -1 if (hs, ls) == ("lower_high", "lower_low") else 0
    return {"highs": hs, "lows": ls, "bias": bias,
            "last_highs": [round(h, dp) for h in highs], "last_lows": [round(x, dp) for x in lows]}


def short_term(sw: list[dict], dp: int = 2, n: int = 4) -> dict:
    """The last few swings on a fast timeframe, read in sequence: how many times in a row the lows rose and the highs
    fell. Added 2026-10-28 after a short at resistance was stopped out by a market making higher lows every dip
    (4,024 -> 4,033 -> 4,049 after FOMC) while its highs fell (4,067.7 -> 4,062.2): a squeeze that broke up.
    `squeeze` = both at once, the market coiling before a break that can go either way."""
    lows = [s["price"] for s in sw if s["kind"] == "L"][-n:]
    highs = [s["price"] for s in sw if s["kind"] == "H"][-n:]

    def run(xs, up: bool) -> int:
        k = 0
        for a, b in zip(reversed(xs[:-1]), reversed(xs[1:])):
            if (b > a) if up else (b < a):
                k += 1
            else:
                break
        return k

    rising, falling = run(lows, True), run(highs, False)
    return {"lows": [round(x, dp) for x in lows], "highs": [round(x, dp) for x in highs],
            "rising_lows": rising, "falling_highs": falling, "squeeze": rising >= 2 and falling >= 1}


def zones(points: list[dict], tol: float, price: float, min_touches: int = 1, dp: int = 2) -> list[dict]:
    """Cluster swing prices that sit within `tol` of each other into zones. Each zone: lo/hi edge, touches, the last
    time it was touched, and whether it is support (below price) or resistance (above). Nearest to price first."""
    pts = sorted(points, key=lambda p: p["price"])
    clusters: list[list[dict]] = []
    for p in pts:
        if clusters and p["price"] - clusters[-1][-1]["price"] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    out = []
    for c in clusters:
        if len(c) < min_touches:
            continue
        lo, hi = min(p["price"] for p in c), max(p["price"] for p in c)
        mid = (lo + hi) / 2
        side = "inside" if lo <= price <= hi else "support" if hi < price else "resistance"
        out.append({"lo": round(lo, dp), "hi": round(hi, dp), "touches": len(c), "side": side,
                    "last_touch": str(max(p["time"] for p in c))[:16], "distance": round(abs(mid - price), dp)})
    return sorted(out, key=lambda z: z["distance"])


def summary(tf: dict, price: float, lookback_days: int = 60, dp: int = 2, m5: pd.DataFrame | None = None) -> dict:
    """Everything the v2 chart agent gets besides the candles."""
    h1, h4, d1 = tf["H1"], tf["H4"], tf["D1"]
    a_h1, a_h4, a_d1 = F.atr(h1), F.atr(h4), F.atr(d1)
    start = h4.index[-1] - pd.Timedelta(days=lookback_days) if len(h4) else None
    sw_h4 = swings(h4.loc[start:] if start is not None else h4)
    sw_d1 = swings(d1.iloc[-lookback_days:], k=2)
    sw_h1 = swings(h1.iloc[-96:], k=3)
    # The swing SEQUENCE is read on M5: an M15 swing needs two more closed M15 bars (30 min) to confirm, and on
    # 2026-10-28 that lag hid the last two higher lows of a post-FOMC squeeze from it. Falls back to M15.
    fast = m5.iloc[-288:] if m5 is not None and len(m5) else tf["M15"].iloc[-96:] if "M15" in tf else None
    sw_fast = swings(fast, k=2) if fast is not None else []
    tol = 0.5 * a_h4 if a_h4 else 0.0
    zs = zones(sw_h4 + sw_d1, tol, price, min_touches=1, dp=dp) if tol else []
    sup = next((z for z in zs if z["side"] == "support"), None)
    res = next((z for z in zs if z["side"] == "resistance"), None)
    inside = next((z for z in zs if z["side"] == "inside"), None)
    pos = None
    if sup and res and res["lo"] > sup["hi"]:
        pos = round((price - sup["hi"]) / (res["lo"] - sup["hi"]), 3)
    return {
        "price": round(price, dp),
        "atr": {"h1": _r(a_h1, dp + 1), "h4": _r(a_h4, dp + 1), "d1": _r(a_d1, dp + 1)},
        "h4_pattern": pattern(sw_h4, dp), "h1_pattern": pattern(sw_h1, dp), "d1_pattern": pattern(sw_d1, dp),
        "short_sequence": {**short_term(sw_fast, dp), "timeframe": "M5" if m5 is not None and len(m5) else "M15"},
        "h4_swings_recent": [{"t": str(s["time"])[:16], "kind": s["kind"], "price": round(s["price"], dp)} for s in sw_h4[-10:]],
        "zones_nearest": zs[:8],
        "nearest_support": sup, "nearest_resistance": res, "price_inside_zone": inside,
        "position_between_support_and_resistance": pos,    # 0 = on support, 1 = at resistance, ~0.5 = mid-range
    }


def bars_text(bars: pd.DataFrame, n: int, dp: int = 2) -> str:
    """The last `n` closed bars as compact lines: time open high low close."""
    rows = [f"{t:%m-%d %H:%M} {r.open:.{dp}f} {r.high:.{dp}f} {r.low:.{dp}f} {r.close:.{dp}f}"
            for t, r in bars.iloc[-n:].iterrows()]
    return "time(UTC) open high low close\n" + "\n".join(rows)


def _r(x, nd: int = 3):
    return None if x is None else round(float(x), nd)
