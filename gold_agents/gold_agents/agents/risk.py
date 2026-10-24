"""Risk manager. Always rules, never a model. Sizes a plan for BUY and SELL and can veto either.

Lots come from contract size (100 oz), not the server's tick value (known to disagree; see gold_bot/mt5/README.md).
"""
from __future__ import annotations

import math

from .. import features as F
from .. import instruments as I
from ..context import Context
from ..types import Plan, Report


def size_plan(ctx: Context, direction: str) -> tuple[Plan | None, str | None]:
    cfg = ctx.cfg
    atr = F.atr(ctx.tf["H1"])
    if atr is None:
        return None, "not enough hourly history to measure volatility"
    dp = I.of(cfg).dp
    stop = cfg.stop_atr_mult * atr
    if stop > cfg.max_stop:
        return None, f"stop would be {stop:.{dp}f}, wider than the {cfg.max_stop:g} limit: volatility too high to size"
    stop = max(stop, cfg.min_stop)
    sign = 1 if direction == "BUY" else -1
    entry = ctx.price
    spec = I.of(cfg)
    dp = spec.dp
    risk_per_lot = stop * I.CONTRACT[spec.oanda]
    budget = cfg.equity * cfg.risk_pct / 100
    lots = math.floor(budget / risk_per_lot / 0.01) * 0.01
    if lots < 0.01:
        return None, f"even 0.01 lot risks ${0.01 * risk_per_lot:.0f}, over the ${budget:.0f} budget"
    lots = round(lots, 2)
    return Plan(direction, round(entry, dp), round(entry - sign * stop, dp), round(entry + sign * stop * cfg.tp1_r, dp),
                round(entry + sign * stop * cfg.tp2_r, dp), round(risk_per_lot, 2), lots, round(lots * risk_per_lot, 2)), None


def run(ctx: Context) -> tuple[Report, dict, dict]:
    """Returns (report, plans by direction, block reason by direction). A direction with a reason must not trade."""
    cfg, j = ctx.cfg, ctx.journal
    plans, blocked = {}, {}
    for d in ("BUY", "SELL"):
        plan, why = size_plan(ctx, d)
        plans[d] = plan
        blocked[d] = why
        if why is None:
            if j.get("realised_r_today", 0.0) <= -cfg.daily_loss_limit_r:
                blocked[d] = f"daily loss limit reached ({j['realised_r_today']:+.1f}R today)"
            elif j.get("open_calls", 0) >= cfg.max_open_calls:
                blocked[d] = f"{j['open_calls']} calls already open (limit {cfg.max_open_calls})"
            else:
                last = j.get("last_call_by_side", {}).get(d)
                if last is not None and (ctx.as_of - last).total_seconds() / 3600 < cfg.same_side_cooldown_h:
                    blocked[d] = f"a {d} call was made {(ctx.as_of - last).total_seconds() / 3600:.1f} h ago (cooldown {cfg.same_side_cooldown_h:g} h)"
    veto = all(v is not None for v in blocked.values())
    facts = {"blocked": blocked, "plans": {d: (p.to_dict() if p else None) for d, p in plans.items()},
             "journal": {k: (v if k != "last_call_by_side" else {s: str(t) for s, t in v.items()}) for k, v in j.items()}}
    summary = "VETO: " + "; ".join(f"{d}: {v}" for d, v in blocked.items() if v) if veto else (
        "sized: " + ", ".join(f"{d} {plans[d].lots} lots risking ${plans[d].risk_usd:.0f}, stop {abs(plans[d].entry - plans[d].stop):.1f}"
                              for d in plans if plans[d] and not blocked[d]))
    return Report("risk", 0.0, 1.0, summary, veto=veto, facts=facts), plans, blocked
