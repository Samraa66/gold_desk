"""Chart analyst: multi-timeframe trend, breakout position and momentum from closed bars.

Rules mode is a plain trend-follower. Our own tests (../gold_bot results) say plain chart rules on gold do not
clear costs, so this score is treated as one INPUT to the master, not as the edge.
"""
from __future__ import annotations

from .. import features as F
from .. import instruments as I
from ..context import Context
from ..types import Report
from .base import ask, clamp, refine

ROLE = "Chart analyst. Judge direction from price structure across timeframes."
SCHEMA = '{"score": -1..1 (negative = short), "confidence": 0..1, "summary": "<=3 sentences", "invalidation": <price or null>}'


def facts(ctx: Context) -> dict:
    h1, h4, d1 = ctx.tf["H1"], ctx.tf["H4"], ctx.tf["D1"]
    return {
        "price": round(ctx.price, 2),
        "h4_trend": F.trend_sign(h4), "h1_trend": F.trend_sign(h1),
        "d1_breakout_position_20d": _r(F.breakout_position(d1)),
        "momentum_24h_atr_units": _r(F.momentum_atr(h1)),
        "h1_atr": _r(F.atr(h1)), "d1_atr": _r(F.atr(d1)),
        "efficiency_ratio_48h": _r(F.efficiency_ratio(h1)),
        "atr_percentile_90d": _r(F.atr_percentile(h1)),
        "levels": F.key_levels(d1, h1, I.ROUND_STEP[I.of(ctx.cfg).oanda]),
    }


def _r(x):
    return None if x is None else round(float(x), 3)


def rules_score(f: dict, cfg) -> float:
    w_h4, w_h1, w_d1, w_mom = cfg.chart_weights
    bo = f["d1_breakout_position_20d"] or 0.0
    mom = f["momentum_24h_atr_units"] or 0.0
    s = w_h4 * f["h4_trend"] + w_h1 * f["h1_trend"] + w_d1 * clamp(bo) + w_mom * clamp(mom / 1.5)
    return clamp(s)


def run(ctx: Context, llm=None) -> Report:
    f = facts(ctx)
    score = rules_score(f, ctx.cfg)
    lean = "long" if score >= ctx.cfg.chart_min_score else "short" if score <= -ctx.cfg.chart_min_score else "neutral"
    # Below the threshold the rules abstain: a weak lean is not a view.
    report = Report("chart", score=score if lean != "neutral" else 0.0, confidence=min(1.0, abs(score)),
                    summary=f"rules: {lean} (score {score:+.2f}); H4 trend {f['h4_trend']:+d}, H1 trend {f['h1_trend']:+d}",
                    facts={**f, "raw_rules_score": round(score, 3)})
    if llm is not None:
        refine(report, ask(llm, ctx.cfg.quick_model, ROLE, SCHEMA, {**f, "rule_score": round(score, 3)}, ctx.cfg.max_tokens, ctx.cfg),
               ctx.cfg.quick_model)
    return report
