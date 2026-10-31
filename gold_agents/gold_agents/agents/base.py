from __future__ import annotations

import json

from ..types import Report

DESK = ("You are one analyst on a small gold (XAUUSD) trading desk. Use ONLY the facts supplied below; "
        "do not use memory of past prices or events, and do not invent data. If the facts do not support "
        "a view, say neutral. Reply with one JSON object and nothing else.")


def localise(text: str, cfg) -> str:
    """Prompt text is written for gold; for another instrument swap the name in. Gold's text is returned untouched."""
    name = (getattr(cfg, "extra", None) or {}).get("instrument", "XAU_USD")
    if name == "XAU_USD":
        return text
    label = cfg.extra.get("label", name)
    return text.replace("gold (XAUUSD)", label).replace("gold", label)


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


def ask(llm, model: str, role: str, schema: str, facts: dict, max_tokens: int, cfg=None, agent: str = "") -> dict:
    system = localise(f"{DESK}\nYour role: {role}\nJSON schema: {schema}", cfg) if cfg is not None else f"{DESK}\nYour role: {role}\nJSON schema: {schema}"
    user = "FACTS:\n" + json.dumps(facts, indent=1, default=str)
    return llm.complete_json(model=model, system=system, user=user, max_tokens=max_tokens, agent=agent)


def refine(report: Report, reply: dict, model: str) -> Report:
    """Let a model's judgement replace the rule score, bounded and labelled. The rule facts stay on the report."""
    report.facts["rules_score"] = report.score
    report.score = clamp(reply.get("score", 0.0))
    report.confidence = clamp(reply.get("confidence", 0.0), 0.0, 1.0)
    report.summary = str(reply.get("summary", ""))[:600]
    if reply.get("invalidation") is not None:
        report.facts["invalidation"] = reply["invalidation"]
    report.source = model
    return report
