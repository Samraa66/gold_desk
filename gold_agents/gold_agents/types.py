from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Report:
    """What one agent hands the master. `score` is a lean from -1 (short) to +1 (long); 0 for agents that
    do not take a side (risk, liquidity). `veto` is a hard stop only the risk and liquidity agents may raise."""
    agent: str
    score: float = 0.0
    confidence: float = 0.0
    summary: str = ""
    veto: bool = False
    facts: dict[str, Any] = field(default_factory=dict)
    source: str = "rules"          # "rules" or the model name that wrote the judgement

    @property
    def side(self) -> str:
        return "long" if self.score > 0 else "short" if self.score < 0 else "neutral"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Plan:
    """A concrete trade the risk agent sized. Prices are XAUUSD bid-side price units."""
    direction: str                 # "BUY" or "SELL"
    entry: float
    stop: float
    tp1: float
    tp2: float
    risk_per_lot: float            # USD lost per 1.00 lot at the stop
    lots: float
    risk_usd: float

    def to_dict(self) -> dict:
        return asdict(self)
