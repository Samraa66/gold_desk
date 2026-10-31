"""Macro analyst: dollar, US 10-year yield, risk appetite and silver, from daily closes BEFORE the as-of day.

Rules mode is a small placeholder heuristic (a stronger dollar and rising yields lean against gold). It is
deliberately weak; the point of this agent is the model's reading of the context. With no data it says so and
returns score 0. Real yields (FRED) are not used yet because no key is configured.
"""
from __future__ import annotations

import math

import pandas as pd

from .. import instruments as I
from ..context import Context
from ..types import Report
from .base import ask, clamp, refine
from ..calendar import next_events

ROLE = "Macro analyst. Judge what the dollar, yields, risk appetite and the scheduled releases imply for gold over the next day or two."
SCHEMA = '{"score": -1..1 (negative = bearish gold), "confidence": 0..1, "summary": "<=3 sentences"}'


def _chg(s: pd.Series, days: int, pct: bool = True):
    s = s.dropna()
    if len(s) <= days:
        return None
    a, b = float(s.iloc[-1]), float(s.iloc[-1 - days])
    return round((a / b - 1) * 100, 3) if pct else round(a - b, 3)


def facts(ctx: Context) -> dict:
    m, n = ctx.macro, ctx.cfg.macro_lookback_days
    if m is None or m.empty:
        return {"data": "unavailable"}
    y = m["us10y"].dropna()
    y_level = float(y.iloc[-1]) if len(y) else None
    if y_level is not None and y_level > 20:      # some Yahoo history reports yield x10
        y = y / 10
    return {
        "as_of_data_day": str(m.index[-1].date()),
        "dxy_level": _r(m["dxy"].dropna().iloc[-1]) if m["dxy"].notna().any() else None,
        f"dxy_change_{n}d_pct": _chg(m["dxy"], n),
        "us10y_level_pct": _r(y.iloc[-1]) if len(y) else None,
        f"us10y_change_{n}d_pp": _chg(y, n, pct=False),
        "vix_level": _r(m["vix"].dropna().iloc[-1]) if m["vix"].notna().any() else None,
        f"vix_change_{n}d": _chg(m["vix"], n, pct=False),
        **({"real_yield_10y_pct": _r(m["real10y"].dropna().iloc[-1]),
            f"real_yield_change_{n}d_pp": _chg(m["real10y"], n, pct=False)}
           if "real10y" in m and m["real10y"].notna().any() else {}),
        f"spx_change_{n}d_pct": _chg(m["spx"], n),
        f"silver_change_{n}d_pct": _chg(m["silver"], n),
        "upcoming_events_48h": [{"in_hours": round((e["time"] - ctx.as_of.to_pydatetime()).total_seconds() / 3600, 1),
                                 "name": e["name"]} for e in next_events(ctx.as_of.to_pydatetime(), 48, ctx.events)],
    }


def _r(x):
    return None if x is None else round(float(x), 3)


def rules_score(f: dict, n: int, w: dict | None = None) -> float:
    if f.get("data") == "unavailable":
        return 0.0
    g = lambda k: f.get(k) or 0.0
    w = w or {"dxy": -0.4, "us10y": -0.4, "silver": 0.1, "vix": 0.1, "spx": 0.0}     # default = gold, unchanged
    s = (w["dxy"] * math.tanh(g(f"dxy_change_{n}d_pct") / 1.0)
         + w["us10y"] * math.tanh(g(f"us10y_change_{n}d_pp") / 0.25)
         + w["silver"] * math.tanh(g(f"silver_change_{n}d_pct") / 3.0)
         + w["vix"] * math.tanh(g(f"vix_change_{n}d") / 5.0)
         + w.get("spx", 0.0) * math.tanh(g(f"spx_change_{n}d_pct") / 2.0))
    return clamp(s)


def run(ctx: Context, llm=None) -> Report:
    f = facts(ctx)
    if f.get("data") == "unavailable":
        return Report("macro", 0.0, 0.0, "no macro data available; abstaining", facts=f)
    score = rules_score(f, ctx.cfg.macro_lookback_days, I.of(ctx.cfg).macro_weights)
    report = Report("macro", score=score, confidence=0.3,
                    summary=f"rules heuristic: dollar and yield moves lean {'bullish' if score > 0 else 'bearish' if score < 0 else 'neutral'} for {I.of(ctx.cfg).label}",
                    facts=f)
    if llm is not None:
        refine(report, ask(llm, ctx.cfg.quick_model, ROLE, SCHEMA, {**f, "rule_score": round(score, 3)}, ctx.cfg.max_tokens, ctx.cfg, agent="macro"),
               ctx.cfg.quick_model)
    return report
