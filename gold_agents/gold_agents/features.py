"""Plain numbers computed from closed bars. No judgement here; agents decide what they mean."""
from __future__ import annotations

import numpy as np
import pandas as pd


def atr(bars: pd.DataFrame, n: int = 14) -> float | None:
    """Wilder ATR of the last `n` bars, in price units."""
    if len(bars) < n + 1:
        return None
    prev_close = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev_close).abs(),
                    (bars["low"] - prev_close).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def atr_series(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev_close).abs(),
                    (bars["low"] - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def ema_pair(bars: pd.DataFrame, fast: int = 50, slow: int = 200) -> tuple[float, float] | None:
    if len(bars) < slow:
        return None
    c = bars["close"]
    return float(c.ewm(span=fast, adjust=False).mean().iloc[-1]), float(c.ewm(span=slow, adjust=False).mean().iloc[-1])


def trend_sign(bars: pd.DataFrame) -> int:
    """+1 when the 50 EMA is above the 200 EMA and price is above the 50, -1 mirrored, else 0."""
    pair = ema_pair(bars)
    if pair is None:
        return 0
    fast, slow = pair
    price = float(bars["close"].iloc[-1])
    if fast > slow and price > fast:
        return 1
    if fast < slow and price < fast:
        return -1
    return 0


def efficiency_ratio(bars: pd.DataFrame, n: int = 48) -> float | None:
    """Kaufman: net move / total path over `n` bars. Near 1 = clean trend, near 0 = chop."""
    if len(bars) < n + 1:
        return None
    c = bars["close"].iloc[-(n + 1):]
    path = c.diff().abs().sum()
    return float(abs(c.iloc[-1] - c.iloc[0]) / path) if path else 0.0


def atr_percentile(bars: pd.DataFrame, n: int = 14, lookback: int = 24 * 90) -> float | None:
    """Where the current ATR sits in its own last ~90 days (0..1)."""
    s = atr_series(bars, n).dropna()
    if len(s) < 100:
        return None
    window = s.iloc[-lookback:]
    return float((window < window.iloc[-1]).mean())


def breakout_position(d1: pd.DataFrame, n: int = 20) -> float | None:
    """Close within the prior `n`-day range, scaled to -1 (at the low) .. +1 (at the high)."""
    if len(d1) < n + 1:
        return None
    prior = d1.iloc[-(n + 1):-1]
    hi, lo = float(prior["high"].max()), float(prior["low"].min())
    if hi == lo:
        return 0.0
    return float(np.clip((float(d1["close"].iloc[-1]) - lo) / (hi - lo) * 2 - 1, -1.2, 1.2))


def momentum_atr(h1: pd.DataFrame, hours: int = 24) -> float | None:
    """Change over `hours` in units of H1 ATR, so a quiet and a wild week read on the same scale."""
    a = atr(h1)
    if a is None or len(h1) < hours + 1:
        return None
    return float((h1["close"].iloc[-1] - h1["close"].iloc[-1 - hours]) / (a * np.sqrt(hours)))


def key_levels(d1: pd.DataFrame, h1: pd.DataFrame, round_step: float = 50.0) -> dict:
    out: dict = {}
    if len(d1) >= 2:
        out["prev_day_high"] = float(d1["high"].iloc[-1])
        out["prev_day_low"] = float(d1["low"].iloc[-1])
    if len(d1) >= 5:
        out["week_high"] = float(d1["high"].iloc[-5:].max())
        out["week_low"] = float(d1["low"].iloc[-5:].min())
    if len(h1):
        px = float(h1["close"].iloc[-1])
        out["nearest_round_50"] = round(round(px / round_step) * round_step, 6)
    return out
