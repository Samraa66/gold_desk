from __future__ import annotations

import pandas as pd

from . import features as F
from . import journal as J
from .agents import chart, liquidity, macro, master, risk
from .config import Config, rules_hash
from . import instruments as I
from .context import build_context


def decide_at(m1_all: pd.DataFrame, as_of, cfg: Config, *, llm=None, macro_df: pd.DataFrame | None = None,
              events: list | None = None, prior_entries: list[dict] | None = None) -> dict:
    """Run every agent as of `as_of` and return the call (not yet written). Pure given its inputs."""
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    # Risk state needs only calls that can still be open (expiry window) or closed today; older ones cannot change it.
    horizon = as_of - pd.Timedelta(hours=cfg.expiry_hours) - pd.Timedelta(days=1)
    prior = [e for e in (prior_entries or []) if horizon <= pd.Timestamp(e["as_of"]) < as_of]
    state = J.state_at(J.score_entries(prior, m1_all.loc[: as_of - pd.Timedelta(minutes=1)], cfg, as_of), as_of) if prior else \
        {"open_calls": 0, "realised_r_today": 0.0, "last_call_by_side": {}}
    ctx = build_context(m1_all, as_of, cfg, macro_df, events, state)

    reports = {"chart": chart.run(ctx, llm), "macro": macro.run(ctx, llm), "liquidity": liquidity.run(ctx)}
    reports["risk"], plans, blocked = risk.run(ctx)
    decision, reason, plan, source = master.decide(ctx, reports, plans, blocked, llm)

    # Baseline: always follow the H4 trend with the same stop and target, ignoring every veto. If the agents'
    # vetoes and judgement do not beat this, they are not earning their keep.
    trend = F.trend_sign(ctx.tf["H4"])
    baseline = None
    if trend != 0:
        d = "BUY" if trend > 0 else "SELL"
        p, _ = risk.size_plan(ctx, d)
        baseline = {"direction": d, "plan": p.to_dict()} if p else None

    # Shadow strategies (added 2026-10-24, scoring only; no rule or config value changed, so rules_hash is the same).
    # Scored on every slot, PASS or not, so a PASS no longer hides what the chart was leaning toward:
    #   chart_lean   the chart's lean with every veto, macro and risk block ignored: what the chart alone is worth
    #   chart_macro  the same lean only when macro does not lean hard against it: what the macro check adds
    # master vs chart_lean shows whether the desk's filtering helps. Neither is ever a call or a notification.
    lean = _lean(reports["chart"], plans)
    if lean:
        d, p = lean
        baseline_extra = {"chart_lean": {"direction": d, "plan": p.to_dict()}}
        if reports["macro"].score * (1 if d == "BUY" else -1) > -cfg.macro_oppose:
            baseline_extra["chart_macro"] = {"direction": d, "plan": p.to_dict()}
    else:
        baseline_extra = {}

    mode = "llm" if llm is not None else "rules"
    h = rules_hash(cfg)
    return {
        "id": f"{as_of.isoformat()}|{mode}|{h}", "as_of": as_of.isoformat(), "mode": mode, "rules_hash": h,
        "decided_by": source, "decision": decision, "reason": reason, "price": round(ctx.price, I.of(cfg).dp), "instrument": I.of(cfg).oanda,
        "plan": plan.to_dict() if plan else None,
        "reports": {k: v.to_dict() for k, v in reports.items()},
        "baselines": {"trend_h4": baseline, **baseline_extra},
    }


def _lean(chart_report, plans: dict):
    """(direction, plan) the chart leans toward and the risk agent could size, else None."""
    if chart_report.score == 0.0:
        return None
    d = "BUY" if chart_report.score > 0 else "SELL"
    return (d, plans[d]) if plans.get(d) else None


def watch_text(call: dict) -> str | None:
    """A 'watch' message for a PASS where the chart still leans one way. Not a call and never scored as one.
    Silent when liquidity vetoed (weekend, event window, wide spread): there is nothing to watch for then."""
    if call["decision"] != "PASS" or call["reports"]["liquidity"]["veto"]:
        return None
    b = (call.get("baselines") or {}).get("chart_lean")
    if not b:
        return None
    p = b["plan"]
    spec = I.get(call.get("instrument"))
    f = lambda x: f"{x:.{spec.dp}f}"
    return "\n".join([
        f"WATCH {spec.label} {call['as_of'][:16].replace('T', ' ')} UTC  ·  chart leans {b['direction']}, desk passed",
        f"If you took it anyway: entry ~{f(p['entry'])}   SL {f(p['stop'])}   TP1 {f(p['tp1'])}",
        f"Why the desk passed: {call['reason']}",
        "Not a trade call. The lean is scored in the log as 'chart lean' so we learn whether passing was right."])


def card(call: dict) -> str:
    """Phone-sized text for a Telegram message. Research output, not advice."""
    spec = I.get(call.get("instrument"))
    f = lambda x: f"{x:.{spec.dp}f}"
    head = f"{spec.label} {call['as_of'][:16].replace('T', ' ')} UTC  ·  {call['decision']}  ({call['mode']})"
    if call["decision"] == "PASS":
        return f"{head}\n{call['reason']}"
    p = call["plan"]
    return "\n".join([
        head, f"Entry ~{f(p['entry'])}   SL {f(p['stop'])}   TP1 {f(p['tp1'])}   TP2 {f(p['tp2'])}",
        f"Size {p['lots']} lots, risk ${p['risk_usd']:.0f} (demo sizing)", call["reason"],
        "Research only: logged to the forward test, no order placed."])
