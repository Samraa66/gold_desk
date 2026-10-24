"""Master agent: reads every report and decides BUY, SELL or PASS.

Hard limits the master cannot override, in code and not in a prompt: a liquidity veto, a risk block on that
direction, a missing plan. Within those, rules mode is a small fixed procedure and model mode is a judgement.
PASS is the expected answer most of the time and is logged like any other decision.
"""
from __future__ import annotations

import json

from .. import instruments as I
from ..context import Context
from ..types import Plan, Report
from .base import DESK, clamp, localise

ROLE = ("Master trader. You receive reports from a chart analyst, a macro analyst, a liquidity monitor and a risk "
        "manager. Decide BUY, SELL or PASS for the next 48 hours. PASS is correct whenever the case is weak, "
        "conflicted, or you are not clearly better than a coin flip. Risk and liquidity vetoes are final.")
SCHEMA = '{"decision": "BUY"|"SELL"|"PASS", "confidence": 0..1, "reason": "<=4 sentences naming which reports drove it"}'


def _brief(r: Report) -> dict:
    keep = {k: v for k, v in r.facts.items() if k in ("plans", "blocked", "market", "session", "spread_now",
                                                      "spread_normal", "next_events_48h", "levels", "invalidation")}
    return {"score": round(r.score, 2), "confidence": round(r.confidence, 2), "veto": r.veto, "summary": r.summary, "key_facts": keep}


def rules_decide(reports: dict, plans: dict, blocked: dict, ctx: Context):
    cfg = ctx.cfg
    chart, macro, liq = reports["chart"], reports["macro"], reports["liquidity"]
    if liq.veto:
        return "PASS", liq.summary, None
    if chart.score == 0.0:
        return "PASS", "chart analyst sees no clear lean", None
    direction = "BUY" if chart.score > 0 else "SELL"
    sign = 1 if direction == "BUY" else -1
    if macro.score * sign <= -cfg.macro_oppose:
        return "PASS", f"chart leans {direction} but macro leans against it ({macro.score:+.2f})", None
    if blocked.get(direction):
        return "PASS", f"risk: {blocked[direction]}", None
    return direction, f"chart {chart.score:+.2f}, macro {macro.score:+.2f}, conditions ok", plans[direction]


def decide(ctx: Context, reports: dict, plans: dict, blocked: dict, llm=None) -> tuple[str, str, Plan | None, str]:
    """-> (decision, reason, plan, source). `source` is "rules" or the model name."""
    cfg = ctx.cfg
    liq = reports["liquidity"]
    if liq.veto:
        return "PASS", liq.summary, None, "rules"
    if llm is None:
        d, why, plan = rules_decide(reports, plans, blocked, ctx)
        return d, why, plan, "rules"
    if all(blocked.values()):
        return "PASS", "risk: " + "; ".join(f"{k}: {v}" for k, v in blocked.items()), None, "rules"
    facts = {"price": round(ctx.price, I.of(cfg).dp), "as_of": str(ctx.as_of), "reports": {k: _brief(v) for k, v in reports.items()}}
    system = localise(f"{DESK}\nYour role: {ROLE}\nJSON schema: {SCHEMA}", cfg)
    reply = llm.complete_json(model=cfg.deep_model, system=system, user="FACTS:\n" + json.dumps(facts, indent=1, default=str),
                              max_tokens=cfg.max_tokens)
    decision = str(reply.get("decision", "PASS")).upper()
    conf = clamp(reply.get("confidence", 0.0), 0.0, 1.0)
    why = str(reply.get("reason", ""))[:700]
    if decision not in ("BUY", "SELL"):
        return "PASS", why or "master passed", None, cfg.deep_model
    if conf < cfg.master_min_confidence:
        return "PASS", f"master confidence {conf:.2f} below {cfg.master_min_confidence:g}: {why}", None, cfg.deep_model
    if blocked.get(decision) or plans.get(decision) is None:
        return "PASS", f"master wanted {decision} but risk blocks it: {blocked.get(decision)}", None, cfg.deep_model
    return decision, why, plans[decision], cfg.deep_model
