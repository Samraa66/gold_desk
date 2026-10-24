"""Every number that shapes a decision lives here, so the rule set can be hashed and frozen.

RULES_VERSION and these defaults are fixed BEFORE any result is looked at (see README, "Pass criteria").
Changing a value changes `rules_hash()`, so a call is always tied to the exact rules that made it, and
results under different hashes are never pooled.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

RULES_VERSION = "1"

# Gold: 100 oz per 1.00 lot, so a $1 move is $100 per lot. Do NOT trust the server's tick_value (see
# ../gold_bot/mt5/README.md: it reports 0.1 where contract size implies 1.0).
CONTRACT_OZ = 100.0


@dataclass(frozen=True)
class Config:
    # --- chart agent ---
    chart_min_score: float = 0.45          # |score| needed to lean long or short
    chart_weights: tuple = (0.35, 0.20, 0.25, 0.20)   # H4 trend, H1 trend, D1 breakout position, 24h momentum
    # --- risk agent ---
    equity: float = 10_000.0               # demo-sized; only used to size lots
    risk_pct: float = 0.5                  # % of equity risked per call
    stop_atr_mult: float = 1.5             # stop distance = this x H1 ATR(14)
    tp1_r: float = 2.0
    tp2_r: float = 3.0
    min_stop: float = 3.0                  # price units: a tighter stop is noise
    max_stop: float = 60.0                 # wider than this is not a trade we can size sensibly
    daily_loss_limit_r: float = 2.0        # stop calling trades after losing this many R in a UTC day
    max_open_calls: int = 2
    same_side_cooldown_h: float = 4.0
    # --- liquidity agent ---
    spread_assumed: float = 0.60           # price units, round-trip assumptions from the research (not the demo's 0.21)
    slippage_assumed: float = 0.30
    max_spread_vs_normal: float = 2.0      # veto when live spread is this many times the median
    event_before_min: int = 30
    event_after_min: int = 30
    # --- macro agent ---
    macro_lookback_days: int = 10
    # --- master / scoring ---
    macro_oppose: float = 0.3              # rules master passes when macro leans this hard against the chart
    master_min_confidence: float = 0.6     # model master: below this a BUY/SELL is downgraded to PASS
    expiry_hours: float = 48.0
    # --- model use (only when an API key is present) ---
    quick_model: str = "claude-sonnet-5-5"
    deep_model: str = "claude-opus-5-5"
    max_tokens: int = 1200
    extra: dict = field(default_factory=dict)


def rules_hash(cfg: Config) -> str:
    """Short stable id of the rules in force; stored on every logged call."""
    payload = {k: v for k, v in asdict(cfg).items() if k not in ("quick_model", "deep_model", "max_tokens", "extra")}
    payload["rules_version"] = RULES_VERSION
    if cfg.extra.get("instrument", "XAU_USD") != "XAU_USD":      # gold's hash must stay what it was
        payload["instrument"] = cfg.extra["instrument"]
    blob = json.dumps(payload, sort_keys=True, default=list)
    return hashlib.sha256(blob.encode()).hexdigest()[:8]
