"""Desk v3.1 (2026-10-31): several legs of one move, stops and targets from the market, woken by gold, other markets or news.

Why (spec: docs/superpowers/specs/2026-10-31-desk-v3-1-design.md): on 2026-10-30 gold fell $135 and v3, built for isolated
scalps with a fixed $15 stop, had no memory of its own calls and counted the rules baseline's calls against the model's limit
("3 calls open, limit 2" at 19:46). What changes, all of it on top of v3 the way v3 sits on v2:

1. Limits count only the desk's own mode (`prior_for`): a rules call never fills the model's slots, or its loss limit.
2. A new call on a side waits until the previous call on that side has closed (`side_open`); the 1 h clock goes.
3. No dollar figures: the stop is at least 1x the M5 ATR and at most what 0.01 lot can size on the $75 budget. The model sets
   stop, targets, order validity and holding time (`max_hold_hours`) and justifies each. A win exits in full at TP1.
4. Flat by the Friday close (`flat_by` on every plan, read by the scorer). Hours are New York time (`calendar.desk_window`).

Vetoes, the post-event rule and the no-fade rules are v2's, in code. Own hash (`v31_hash`), own logs (`calls_v31.jsonl` and
its sidecars). v1, v2 and v3 keep their code, hashes and logs.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace

import pandas as pd

from . import calendar as cal
from . import desk_v2 as V
from . import desk_v3 as V3
from . import instruments as I
from . import journal as J
from .agents import liquidity
from .agents.base import ask, clamp
from .config import Config, rules_hash as v1_hash
from .context import Context, build_context

VERSION = "3.1-legs"
JOURNAL = I.get("XAU_USD").journal_path.with_name("calls_v31.jsonl")
OUTCOMES = J.sidecar(JOURNAL, "outcomes")          # outcomes_v31.jsonl
PROMPTS = J.sidecar(JOURNAL, "prompts")            # prompts_v31.jsonl
DASHBOARD = JOURNAL.with_name("dashboard_v31.html")
WATCH_LOG = JOURNAL.with_name("watch_v31.jsonl")
WATCH_STATE = JOURNAL.with_name("watch_state_v31.json")
BRIEF_LOG = JOURNAL.with_name("brief_v31.jsonl")
OPEN_LOOKBACK = pd.Timedelta(days=8)               # a v3.1 trade can live from Sunday's reopen to Friday's close


@dataclass(frozen=True)
class V31:
    """Every v3.1-only number. Part of the v3.1 hash; changing one starts a new record."""
    min_rr: float = 1.5               # TP1 at least this many R away
    max_valid_hours: float = 12.0     # a pending order is cancelled after this (and never after the Friday close)
    default_valid_hours: float = 1.0
    default_hold_hours: float = 4.0   # when the model gives no usable holding time
    max_entry_atr_d1: float = 0.25    # a pending entry sits near price
    min_stop_atr_m5: float = 1.0      # the noise floor: a stop closer than the normal M5 bar is refused
    rules_stop_atr_m5: float = 1.5    # the rules baseline's stop
    post_event_hours: float = 3.0     # v2's rule, unchanged
    counter_run: int = 2              # v2's rule, unchanged: no fades into rising lows or falling highs
    lookback_days: int = 60
    chart_max_tokens: int = 3000


V31_DEFAULT = V31()


def config() -> Config:
    """The $5,000 research demo at 1.5% ($75 a trade), so 0.01 lot (1 oz) can carry a $75 stop. Scored in R, so the demo size
    does not distort the record. No dollar stop limits: the M5 floor and the 0.01-lot ceiling replace them."""
    return replace(I.get("XAU_USD").config(), equity=5000.0, risk_pct=1.5, min_stop=0.0, max_stop=float("inf"),
                   daily_loss_limit_r=3.0, max_open_calls=2, same_side_cooldown_h=0.0, master_min_confidence=0.5,
                   expiry_hours=24.0)


def v31_hash(cfg: Config, v31: V31 = V31_DEFAULT) -> str:
    payload = {"v1": v1_hash(cfg), "v31": asdict(v31), "version": VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode()).hexdigest()[:8]


def _v2(v31: V31) -> V.V2:
    """v2's setup check under v3.1's numbers. Its H1 noise floor is off: the M5 one in `check` replaces it."""
    return V.V2(min_rr=v31.min_rr, max_valid_hours=v31.max_valid_hours, default_valid_hours=v31.default_valid_hours,
                max_entry_atr_d1=v31.max_entry_atr_d1, min_stop_atr_h1=0.0, post_event_hours=v31.post_event_hours,
                counter_run=v31.counter_run, lookback_days=v31.lookback_days)


def _v3(v31: V31) -> V3.V3:
    return V3.V3(min_rr=v31.min_rr, max_valid_hours=v31.max_valid_hours, default_valid_hours=v31.default_valid_hours,
                 max_entry_atr_d1=v31.max_entry_atr_d1, min_stop_atr_m5=v31.min_stop_atr_m5, rules_stop_atr_m5=v31.rules_stop_atr_m5,
                 post_event_hours=v31.post_event_hours, counter_run=v31.counter_run, lookback_days=v31.lookback_days,
                 chart_max_tokens=v31.chart_max_tokens)


# ---------------------------------------------------------------- the desk's own record
def prior_for(entries: list[dict], mode: str) -> list[dict]:
    """Only this mode's own calls. Bug 2 in v3: the rules baseline's calls counted toward the model's open-call limit and loss limit."""
    return [e for e in entries if e.get("mode") == mode]


OPEN = ("open", "pending", "waiting")


def side_open(scored: list[dict], direction: str) -> bool:
    """Is a call on this side still open or waiting to fill? Legs follow one another; they never stack."""
    return any(e["decision"] == direction and (e["scores"].get("master") or {}).get("outcome") in OPEN for e in scored)


def journal_block(ctx: Context, d: str) -> str | None:
    blk = V.journal_block(ctx, d)              # loss limit and open calls; the cooldown is 0 h, so it never fires
    if blk:
        return blk
    if d in ctx.journal.get("open_sides", ()):
        return f"a {d} call is still open or waiting; the next leg waits for it to close"
    return None


def state_for(prior: list[dict], mode: str, m1_all: pd.DataFrame, as_of: pd.Timestamp, cfg: Config) -> tuple[dict, list[dict]]:
    """-> (journal state, this mode's scored calls) from closed bars only."""
    mine = [e for e in prior_for(prior, mode) if as_of - OPEN_LOOKBACK <= pd.Timestamp(e["as_of"]) < as_of]
    if not mine:
        return {"open_calls": 0, "realised_r_today": 0.0, "last_call_by_side": {}, "open_sides": []}, []
    scored = J.score_entries(mine, m1_all.loc[: as_of - pd.Timedelta(minutes=1)], cfg, as_of)
    state = J.state_at(scored, as_of)
    state["open_sides"] = [d for d in ("BUY", "SELL") if side_open(scored, d)]
    return state, scored


# ---------------------------------------------------------------- risk: check and size
def normal_hold(value, v31: V31 = V31_DEFAULT) -> float:
    """The model's holding time in hours, or the default when it is missing, zero, negative, not a number or infinite. A huge
    value stands: the Friday close (`flat_by`) cuts it."""
    if isinstance(value, bool):
        return v31.default_hold_hours
    try:
        h = float(value)
    except (TypeError, ValueError):
        return v31.default_hold_hours
    return h if math.isfinite(h) and h > 0 else v31.default_hold_hours


def check(ctx: Context, setup: dict, v31: V31, st: dict | None, atr_m5: float, filters: bool = True) -> tuple[dict | None, str | None]:
    """v2's check under v3.1's numbers, then the M5 noise floor. The ceiling is the sizing: a stop 0.01 lot can not carry on the
    budget is refused there ("even 0.01 lot risks ..."). The plan carries `max_hold_hours` and `flat_by` for the scorer."""
    plan, why = V.check_setup(ctx, setup, _v2(v31), st, filters=filters)
    if plan is None:
        return None, why
    risk_ = abs(plan["entry"] - plan["stop"])
    if filters and atr_m5 and risk_ < v31.min_stop_atr_m5 * atr_m5:
        return None, f"stop {risk_:.2f} is inside M5 noise (under {v31.min_stop_atr_m5:g}x the M5 ATR of {atr_m5:.2f})"
    flat_by = pd.Timestamp(cal.next_friday_close(ctx.as_of.to_pydatetime()))
    if plan.get("valid_until") and pd.Timestamp(plan["valid_until"]) > flat_by:
        plan["valid_until"] = str(flat_by)
    plan["max_hold_hours"] = normal_hold(setup.get("max_hold_hours"), v31)
    plan["flat_by"] = str(flat_by)
    return plan, None


def loose_check(ctx: Context, setup: dict, v31: V31, st: dict | None) -> dict | None:
    """A refused setup as proposed (no R floor, no distance cap, no filters, no sizing ceiling), for scoring only."""
    loose = replace(ctx, cfg=replace(ctx.cfg, min_stop=0.0, max_stop=float("inf"), equity=1e12))
    raw, _ = check(loose, setup, replace(v31, min_rr=0.0, max_entry_atr_d1=float("inf")), st, 0.0, filters=False)
    return raw


# ---------------------------------------------------------------- master
def master_decide(ctx: Context, reports: dict, plan: dict | None, why_not: str | None, live: dict, llm=None,
                  brief: dict | None = None) -> tuple[str, str, dict | None, str]:
    cfg, liq, mac = ctx.cfg, reports["liquidity"], reports["macro"]
    if liq.veto:
        return "PASS", liq.summary, None, "rules"
    if plan is None:
        setup_why = reports["chart"].facts["setup"].get("why") or "no setup"
        return "PASS", f"chart: {setup_why}" + (f" ({why_not})" if why_not and why_not != "no setup" else ""), None, "rules"
    blk = journal_block(ctx, plan["direction"])
    if blk:
        return "PASS", f"risk: {blk}", None, "rules"
    sign = 1 if plan["direction"] == "BUY" else -1
    if llm is None:
        if mac.score * sign <= -cfg.macro_oppose:
            return "PASS", f"setup {plan['direction']} but macro leans against it ({mac.score:+.2f})", None, "rules"
        return plan["direction"], f"{plan['entry_type']} {plan['direction']} at {plan['entry']}: {reports['chart'].facts['setup'].get('why', '')}", plan, "rules"
    chart, news = reports["chart"], reports["news"]
    facts = {"as_of": str(ctx.as_of), "price": ctx.price, "plan": plan,
             "chart": {"bias": chart.score, "confidence": chart.confidence, "read": chart.summary, "setup_why": chart.facts["setup"].get("why"),
                       "day_type": chart.facts.get("day_type"), "day_direction": chart.facts.get("day_direction")},
             "macro": {"score": mac.score, "confidence": mac.confidence, "summary": mac.summary},
             "news": {"score": news.score, "confidence": news.confidence, "summary": news.summary, "driver": news.facts.get("driver"),
                      "risk_flag": news.facts.get("risk_flag")},
             "liquidity": {"summary": liq.summary, "next_events_48h": liq.facts.get("next_events_48h"),
                           "positions": live.get("positions"), "volume_vs_normal": live.get("volume_ratio")}}
    if brief:
        facts["daily_brief"] = brief_facts(brief)
    reply = ask(llm, cfg.deep_model, MASTER_ROLE, V.MASTER_SCHEMA, facts, cfg.max_tokens, cfg, agent="master")
    why, conf = str(reply.get("reason", ""))[:700], clamp(reply.get("confidence", 0.0), 0.0, 1.0)
    if str(reply.get("decision", "PASS")).upper() != "PLACE":
        return "PASS", why or "master passed", None, cfg.deep_model
    if conf < cfg.master_min_confidence:
        return "PASS", f"master confidence {conf:.2f} below {cfg.master_min_confidence:g}: {why}", None, cfg.deep_model
    return plan["direction"], why, plan, cfg.deep_model


MASTER_ROLE = ("Master trader. The chart trader read the chart and proposed a trade with its own stop, target and holding time; the "
               "risk manager checked and sized it; the news, cross-asset and liquidity reports are attached. Decide PLACE (exactly "
               "as sized) or PASS. You cannot change the prices. Pass for a stated reason: news or other markets hard against the "
               "trade, fresh headline risk, a release due inside the trade's life, or a read that does not support it. Do not pass "
               "merely because nothing is certain: a clean setup at fair risk is the job. Vetoes are final.")


def brief_facts(brief: dict) -> dict:
    """What the master, news and macro agents see of the daily brief: its view, never prices to trade."""
    return {k: brief.get(k) for k in ("at", "drivers", "trend", "levels", "risks")}


# ---------------------------------------------------------------- one decision
def decide_at(m1_all: pd.DataFrame, as_of, cfg: Config, *, llm=None, macro_df=None, events=None, prior_entries: list[dict] | None = None,
              v31: V31 = V31_DEFAULT, trigger: dict | None = None, live: dict | None = None, brief: dict | None = None) -> dict:
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    live = live or {}
    mode = "llm" if llm is not None else "rules"
    state, _ = state_for(prior_entries or [], mode, m1_all, as_of, cfg)
    ctx = build_context(m1_all, as_of, cfg, macro_df, events, state)
    m5 = V3.m5_bars(ctx)
    reports = {"chart": V3.chart_run(ctx, _v3(v31), m5, trigger, live, llm), "macro": V3.macro_run(ctx, live, llm),
               "news": V3.news_run(ctx, live, llm), "liquidity": liquidity.run(ctx, window=cal.desk_window)}
    chart = reports["chart"]
    st, atr_m5 = chart.facts["structure"], chart.facts["structure"]["atr"]["m5"]
    plan, why_not = check(ctx, chart.facts["setup"], v31, st, atr_m5)
    chart.facts["setup_check"] = why_not or "ok"
    decision, reason, chosen, source = master_decide(ctx, reports, plan, why_not, live, llm, brief)
    rules_plan, _ = check(ctx, chart.facts["rules_setup"], v31, st, atr_m5)
    baselines = {"chart_setup": {"direction": plan["direction"], "plan": plan} if plan else None,
                 "rules_setup": {"direction": rules_plan["direction"], "plan": rules_plan} if rules_plan else None}
    if plan is None and why_not not in (None, "no setup"):        # scored as proposed, so the record shows what the checks refuse
        raw = loose_check(ctx, chart.facts["setup"], v31, st)
        if raw:
            baselines["rejected_setup"] = {"direction": raw["direction"], "plan": raw, "rejected_because": why_not}
    h = v31_hash(cfg, v31)
    return {"id": f"{as_of.isoformat()}|{mode}|{h}", "as_of": as_of.isoformat(), "desk": "v31", "mode": mode, "rules_hash": h,
            "decided_by": source, "decision": decision, "reason": reason, "price": round(ctx.price, I.of(cfg).dp),
            "instrument": I.of(cfg).oanda, "trigger": trigger, "plan": chosen, "reports": {k: r.to_dict() for k, r in reports.items()},
            "baselines": baselines}


# ---------------------------------------------------------------- the card
def card(call: dict) -> str:
    """The Telegram card. Shows the stop distance and the dollar risk at 0.01 lot (1 oz), so the owner can size a real trade
    against their own account or skip it; the desk never stores the owner's balance."""
    spec = I.get(call.get("instrument"))
    f = lambda x: f"{x:.{spec.dp}f}"
    head = f"{spec.label} {call['as_of'][:16].replace('T', ' ')} UTC  ·  v3.1 {call['decision']}  ({call['mode']})"
    t = call.get("trigger")
    woke = [f"Woken by: {t['kind']} {t.get('name') or ''}".rstrip()] if t else []
    if call["decision"] == "PASS":
        return "\n".join([head, *woke, call["reason"]])
    p = call["plan"]
    kind = {"market": "at market", "limit": "LIMIT", "stop": "STOP (on the break)"}[p["entry_type"]]
    until = f"   order valid until {p['valid_until'][:16].replace('T', ' ')} UTC" if p.get("valid_until") else ""
    dist = abs(p["entry"] - p["stop"])
    flat = f", flat by {p['flat_by'][:16].replace('T', ' ')} UTC" if p.get("flat_by") else ""
    return "\n".join([
        head, *woke, f"{p['direction']} {kind} {f(p['entry'])}{until}",
        f"SL {f(p['stop'])}   TP1 {f(p['tp1'])} ({p['rr_tp1']}R, exit in full)   TP2 {f(p['tp2'])} (for information)",
        f"Stop distance {dist:.2f}. At 0.01 lot: risk ${dist:.2f}",
        f"Hold up to {p.get('max_hold_hours', 0):g} h{flat}",
        call["reason"],
        "Research only: logged to the v3.1 forward test, no order placed."])
