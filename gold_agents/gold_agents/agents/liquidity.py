"""Liquidity and conditions agent. Always rules, never a model: a veto must be predictable.

Spot gold has no public order book, so "liquidity" is what we can measure: is the market open, is the
spread normal, is a high-impact release about to hit, and are the bars fresh enough to trust.
"""
from __future__ import annotations

from .. import calendar as cal
from .. import instruments as I
from ..context import Context
from ..types import Report


def run(ctx: Context, window=cal.market_window) -> Report:
    """`window` decides the hours: v1-v3 use `calendar.market_window`, v3.1 passes `calendar.desk_window` (New York time),
    whose daily `break` is vetoed like `rollover`."""
    t = ctx.as_of.to_pydatetime()
    cfg = ctx.cfg
    state, why = window(t)
    event = cal.blocking_event(t, cfg.event_before_min, cfg.event_after_min, ctx.events)
    age_min = (ctx.as_of - ctx.last_bar_end).total_seconds() / 60
    facts = {
        "market": state, "session": cal.session(t),
        "spread_now": ctx.spread_now, "spread_normal": ctx.spread_normal,
        "bar_age_minutes": round(age_min, 1),
        "next_events_48h": [{"in_hours": round((e["time"] - t).total_seconds() / 3600, 1), "name": e["name"]}
                            for e in cal.next_events(t, 48, ctx.events)],
        "events_file_age_days": cal.events_file_age_days(),
    }
    reasons = []
    if state in ("closed", "rollover", "break"):
        reasons.append(why)
    if event:
        reasons.append(f"high-impact event window: {event['name']}")
    if state in ("open", "thin") and age_min > 30:      # any hour the market trades: old bars mean an old price
        reasons.append(f"bar data is {age_min:.0f} min old; refusing to act on a stale price")
    if ctx.spread_now is not None and ctx.spread_normal:
        if ctx.spread_now > cfg.max_spread_vs_normal * ctx.spread_normal:
            dp = max(2, I.of(cfg).dp)
            reasons.append(f"spread {ctx.spread_now:.{dp}f} is over {cfg.max_spread_vs_normal:g}x its normal {ctx.spread_normal:.{dp}f}")
    thin = state == "thin"
    summary = ("VETO: " + "; ".join(reasons)) if reasons else (
        "conditions ok" + (" (thin Asia hours, wider spread likely)" if thin else ""))
    return Report("liquidity", score=0.0, confidence=1.0, summary=summary, veto=bool(reasons), facts=facts)
