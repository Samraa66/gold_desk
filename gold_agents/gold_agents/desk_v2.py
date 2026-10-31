"""Desk v2 (2026-10-28): the chart agent reads the chart, and a call is a setup at a level, not a market order on a clock.

Why: v1's chart agent got ten summary numbers and no candles. Its lean was 0 wins / 16 losses from 2026-10-26 to
10-28 (one correlated bet: SELL into a support that held three times while gold bounced from 3,975 to 4,070), and in
its own words it saw the support, then leaned short because three of four inputs were lagging trend signs and the
rule score was handed to it as an anchor. v2 changes three things and nothing else:

1. The chart agent gets candles (D1, H4, H1, M15) plus `structure.summary` (swings, tested zones, the swing pattern,
   position in range). No rule score in its prompt.
2. Its answer is a SETUP: market, limit (at a zone) or stop (beyond a level), with a stop beyond structure, TP1/TP2
   and how many hours the order stays valid. "none" is a normal answer.
3. Risk checks the setup (right side of price, stop distance limits, TP1 >= `min_rr` R) and sizes it; the scorer fills
   a pending order only if price reaches it (`journal.score_plan`).

v1 keeps running untouched and is the comparison. v2 has its own rules hash and its own logs (`calls_v2*.jsonl`).
Macro and liquidity agents are v1's, unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace

import pandas as pd

from . import features as F
from . import instruments as I
from . import journal as J
from . import structure as S
from .agents import liquidity, macro
from .agents.base import DESK, clamp, localise
from .config import Config, rules_hash as v1_hash
from .context import Context, build_context
from .types import Report

VERSION = "2-structure"


@dataclass(frozen=True)
class V2:
    """Every v2-only number. Part of the v2 hash; changing one starts a new record."""
    min_rr: float = 1.5               # TP1 must be at least this many R from entry
    max_valid_hours: float = 24.0     # a pending order is cancelled after this
    default_valid_hours: float = 12.0
    max_entry_atr_d1: float = 1.0     # a pending entry further than this x D1 ATR from price is not a setup for now
    stop_pad_atr_h1: float = 0.5      # rules setup: stop this far beyond the zone edge
    zone_floor_touches: int = 2       # rules: a zone touched this often is a floor/ceiling we do not trade into
    floor_gap_atr_h1: float = 1.0     # ... when price is within this x H1 ATR of it
    lookback_days: int = 60
    chart_max_tokens: int = 2500
    # Added 2026-10-28 (a short at resistance stopped out an hour after FOMC by a market making higher lows):
    min_stop_atr_h1: float = 1.0      # a stop closer than this x H1 ATR sits inside normal noise
    post_event_hours: float = 3.0     # no new setup this long after a high-impact release: the first moves whipsaw
    counter_run: int = 2              # no SELL after this many rising M5 lows in a row (buyers stepping in), no BUY
                                      # after this many falling M5 highs in a row; a squeeze blocks both


V2_DEFAULT = V2()


def v2_hash(cfg: Config, v2: V2 = V2_DEFAULT) -> str:
    payload = {"v1": v1_hash(cfg), "v2": asdict(v2), "version": VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]


def journal_path(spec: I.Instrument):
    return spec.journal_path.with_name(spec.journal.replace("calls", "calls_v2", 1))


def dashboard_path(spec: I.Instrument):
    return spec.dashboard_path.with_name(spec.dashboard.replace("dashboard", "dashboard_v2", 1))


# ---------------------------------------------------------------- chart agent
ROLE = ("Chart analyst who trades from price structure, like a discretionary trader reading the chart. You get the "
        "candles (D1, H4, H1, M15) and computed structure: swing highs/lows in order, support/resistance zones built from "
        "swing points with how many times each was touched, and where price sits between support and resistance. "
        "Read the structure first, then the trend. Rules of the trade: never enter in the middle of a range (no edge, "
        "bad risk:reward); do not sell into a support that has held several times or buy into a resistance that has "
        "capped several times; prefer a LIMIT order at a zone in the direction of the structure, or a STOP order beyond "
        "a level for a confirmed break; put the stop beyond the structure that proves you wrong (beyond the zone or the "
        "last swing), not at an arbitrary distance; TP1 at the next opposing zone and at least {min_rr}R away. A trend "
        "that is weeks old and stretched into a tested floor is not a reason to sell. Read the SEQUENCE of the last "
        "swings on M5 (short_sequence): lows rising one after another mean buyers keep stepping in higher, so do not "
        "sell into resistance against that; highs falling one after another mean sellers keep capping lower, so do not "
        "buy into support against that; both at once is a squeeze, wait for the break and trade it with a stop order "
        "or not at all. The stop must be at least {min_stop}x the H1 ATR away (atr.h1) so normal noise cannot reach "
        "it. Within {post_event}h after a high-impact release (FOMC, CPI, payrolls) propose no setup: the first moves "
        "whipsaw both ways. If there is no clean setup, entry_type is \"none\". That is the normal answer.")
SCHEMA = ('{"bias": -1..1 (negative = bearish), "confidence": 0..1, "read": "<=4 sentences: structure, key zones, '
          'where price is, what would change your mind", "setup": {"direction": "BUY"|"SELL"|null, "entry_type": '
          '"market"|"limit"|"stop"|"none", "entry": <price or null>, "stop": <price or null>, "tp1": <price or null>, '
          '"tp2": <price or null>, "valid_hours": <1..24>, "why": "<=2 sentences"}}')


def chart_facts(ctx: Context, v2: V2) -> tuple[dict, str]:
    dp = I.of(ctx.cfg).dp
    from .data import resample
    m5 = resample(ctx.m1.loc[ctx.as_of - pd.Timedelta(days=2):], "M5", ctx.as_of)
    st = S.summary(ctx.tf, ctx.price, v2.lookback_days, dp, m5=m5)
    candles = "\n\n".join(f"{name} last {n}:\n{S.bars_text(ctx.tf[name], n, dp)}"
                          for name, n in (("D1", 30), ("H4", 60), ("H1", 48), ("M15", 32)))
    return st, candles


def rules_setup(ctx: Context, st: dict, v2: V2) -> dict:
    """Deterministic v2 setup, the comparison for the model: trade the H4 swing pattern at a zone, never into one."""
    bias = st["h4_pattern"]["bias"]
    a1 = F.atr(ctx.tf["H1"]) or 0.0
    none = {"direction": None, "entry_type": "none", "entry": None, "stop": None, "tp1": None, "tp2": None,
            "valid_hours": v2.default_valid_hours}
    if bias == 0 or not a1:
        return {**none, "why": "H4 swings are mixed (no lower highs + lower lows, or higher highs + higher lows)"}
    d = "BUY" if bias > 0 else "SELL"
    floor = st["nearest_support"] if d == "SELL" else st["nearest_resistance"]
    if floor and floor["touches"] >= v2.zone_floor_touches and floor["distance"] <= v2.floor_gap_atr_h1 * a1 + (floor["hi"] - floor["lo"]) / 2:
        return {**none, "why": f"{d} would run into a zone touched {floor['touches']} times right next to price"}
    zone = st["nearest_resistance"] if d == "SELL" else st["nearest_support"]
    if st["price_inside_zone"] is not None:
        zone = st["price_inside_zone"]
    if zone is None:
        return {**none, "why": f"no zone to {('sell from' if d == 'SELL' else 'buy from')}"}
    sign = 1 if d == "BUY" else -1
    entry = zone["lo"] if d == "SELL" else zone["hi"]
    entry_type = "limit"
    if (d == "SELL" and entry <= ctx.price) or (d == "BUY" and entry >= ctx.price):
        entry, entry_type = ctx.price, "market"              # price is already inside the zone
    stop = (zone["hi"] if d == "SELL" else zone["lo"]) - sign * v2.stop_pad_atr_h1 * a1
    risk_ = abs(entry - stop)
    target = st["nearest_support"] if d == "SELL" else st["nearest_resistance"]
    tp1 = (target["hi"] if d == "SELL" else target["lo"]) if target else entry + sign * 2 * risk_
    if abs(tp1 - entry) < v2.min_rr * risk_:
        tp1 = entry + sign * v2.min_rr * risk_
    return {"direction": d, "entry_type": entry_type, "entry": entry, "stop": stop, "tp1": tp1,
            "tp2": entry + sign * max(3 * risk_, abs(tp1 - entry) * 1.5), "valid_hours": v2.default_valid_hours,
            "why": f"H4 {st['h4_pattern']['highs']} + {st['h4_pattern']['lows']}; {entry_type} at the zone {zone['lo']}-{zone['hi']}"}


def chart_run(ctx: Context, v2: V2, llm=None) -> Report:
    st, candles = chart_facts(ctx, v2)
    setup = rules_setup(ctx, st, v2)
    bias = float(st["h4_pattern"]["bias"])
    rep = Report("chart", score=bias if setup["entry_type"] != "none" else 0.0, confidence=0.5 if setup["entry_type"] != "none" else 0.0,
                 summary=f"rules v2: {setup['why']}", facts={"structure": st, "setup": setup, "rules_setup": setup})
    if llm is None:
        return rep
    system = localise(f"{DESK}\nYour role: {ROLE.format(min_rr=v2.min_rr, min_stop=v2.min_stop_atr_h1, post_event=v2.post_event_hours)}\nJSON schema: {SCHEMA}", ctx.cfg)
    user = f"AS OF {ctx.as_of:%Y-%m-%d %H:%M} UTC ({ctx.as_of:%A})\nSTRUCTURE:\n{json.dumps(st, indent=1, default=str)}\n\nCANDLES (closed bars only):\n{candles}"
    reply = llm.complete_json(model=ctx.cfg.deep_model, agent="chart", system=system, user=user, max_tokens=v2.chart_max_tokens)
    s = reply.get("setup") or {}
    setup = {"direction": s.get("direction"), "entry_type": str(s.get("entry_type") or "none").lower(), "entry": s.get("entry"),
             "stop": s.get("stop"), "tp1": s.get("tp1"), "tp2": s.get("tp2"),
             "valid_hours": s.get("valid_hours") or v2.default_valid_hours, "why": str(s.get("why", ""))[:400]}
    rep.score = clamp(reply.get("bias", 0.0))
    rep.confidence = clamp(reply.get("confidence", 0.0), 0.0, 1.0)
    rep.summary = str(reply.get("read", ""))[:800]
    rep.facts["setup"] = setup
    rep.source = ctx.cfg.deep_model
    return rep


# ---------------------------------------------------------------- risk: check and size the setup
def setup_filters(ctx: Context, d: str, risk_: float, st: dict | None, v2: V2) -> str | None:
    """The 2026-10-28 rules, in code so they hold whatever the model says. -> why the setup is refused, or None."""
    from . import calendar as cal
    t = ctx.as_of.to_pydatetime()
    ev = cal.blocking_event(t, 0, int(v2.post_event_hours * 60), ctx.events)
    if ev:
        return f"within {v2.post_event_hours:g}h after {ev['name']}: the first moves whipsaw"
    a1 = F.atr(ctx.tf["H1"])
    if a1 and risk_ < v2.min_stop_atr_h1 * a1:
        return f"stop {risk_:.2f} is inside normal noise (under {v2.min_stop_atr_h1:g}x the H1 ATR of {a1:.2f})"
    seq = (st or {}).get("short_sequence") or {}
    tfn = seq.get("timeframe", "M5")
    up, down = seq.get("rising_lows", 0), seq.get("falling_highs", 0)
    if up >= v2.counter_run and down >= 1:
        return f"{tfn} squeeze (lows rising {seq.get('lows')}, highs falling {seq.get('highs')}): wait for the break"
    if d == "SELL" and up >= v2.counter_run:
        return f"{tfn} lows have risen {up} times in a row {seq.get('lows')}: buyers keep stepping in, no sell against that"
    if d == "BUY" and down >= v2.counter_run:
        return f"{tfn} highs have fallen {down} times in a row {seq.get('highs')}: sellers keep capping, no buy against that"
    return None


def check_setup(ctx: Context, setup: dict, v2: V2, st: dict | None = None, filters: bool = True) -> tuple[dict | None, str | None]:
    """-> (plan dict, None) or (None, why not). The plan carries entry_type and valid_until for the scorer.
    `filters=False` skips `setup_filters` (used only to score a refused setup as it was proposed)."""
    cfg = ctx.cfg
    spec = I.of(cfg)
    dp = spec.dp
    d, et = setup.get("direction"), setup.get("entry_type")
    if et == "none" or d not in ("BUY", "SELL"):
        return None, "no setup"
    if et not in ("market", "limit", "stop"):
        return None, f"unknown entry type {et!r}"
    try:
        entry = ctx.price if et == "market" else float(setup["entry"])
        stop, tp1 = float(setup["stop"]), float(setup["tp1"])
        tp2 = float(setup["tp2"]) if setup.get("tp2") is not None else None
    except (TypeError, ValueError, KeyError):
        return None, "setup is missing a price"
    sign = 1 if d == "BUY" else -1
    px = ctx.price
    if et == "limit" and not ((d == "BUY" and entry < px) or (d == "SELL" and entry > px)):
        return None, f"a {d} limit must sit {'below' if d == 'BUY' else 'above'} price ({px:.{dp}f}); got {entry:.{dp}f}"
    if et == "stop" and not ((d == "BUY" and entry > px) or (d == "SELL" and entry < px)):
        return None, f"a {d} stop entry must sit {'above' if d == 'BUY' else 'below'} price ({px:.{dp}f}); got {entry:.{dp}f}"
    a_d1 = F.atr(ctx.tf["D1"])
    if et != "market" and a_d1 and abs(entry - px) > v2.max_entry_atr_d1 * a_d1:
        return None, f"entry {entry:.{dp}f} is more than {v2.max_entry_atr_d1:g} daily ATR from price"
    if (stop - entry) * sign >= 0:
        return None, "stop is on the wrong side of the entry"
    if (tp1 - entry) * sign <= 0:
        return None, "TP1 is on the wrong side of the entry"
    risk_ = abs(entry - stop)
    if risk_ < cfg.min_stop:
        return None, f"stop {risk_:.{dp}f} is tighter than the {cfg.min_stop:g} noise floor"
    if risk_ > cfg.max_stop:
        return None, f"stop {risk_:.{dp}f} is wider than the {cfg.max_stop:g} limit"
    rr = abs(tp1 - entry) / risk_
    if rr < v2.min_rr - 1e-9:
        return None, f"TP1 is only {rr:.2f}R away (need {v2.min_rr:g}R)"
    if filters:
        why = setup_filters(ctx, d, risk_, st, v2)
        if why:
            return None, why
    if tp2 is None or (tp2 - tp1) * sign <= 0:
        tp2 = entry + sign * max(abs(tp1 - entry) * 1.5, 3 * risk_)
    risk_per_lot = risk_ * I.CONTRACT[spec.oanda]
    budget = cfg.equity * cfg.risk_pct / 100
    lots = math.floor(budget / risk_per_lot / 0.01) * 0.01
    if lots < 0.01:
        return None, f"even 0.01 lot risks ${0.01 * risk_per_lot:.0f}, over the ${budget:.0f} budget"
    hours = clamp(float(setup.get("valid_hours") or v2.default_valid_hours), 1.0, v2.max_valid_hours)
    valid_until = None if et == "market" else str(ctx.as_of + pd.Timedelta(hours=hours))
    return {"direction": d, "entry_type": et, "entry": round(entry, dp), "stop": round(stop, dp), "tp1": round(tp1, dp),
            "tp2": round(tp2, dp), "valid_until": valid_until, "risk_per_lot": round(risk_per_lot, 2),
            "lots": round(lots, 2), "risk_usd": round(round(lots, 2) * risk_per_lot, 2), "rr_tp1": round(rr, 2)}, None


def journal_block(ctx: Context, d: str) -> str | None:
    cfg, j = ctx.cfg, ctx.journal
    if j.get("realised_r_today", 0.0) <= -cfg.daily_loss_limit_r:
        return f"daily loss limit reached ({j['realised_r_today']:+.1f}R today)"
    if j.get("open_calls", 0) >= cfg.max_open_calls:
        return f"{j['open_calls']} calls already open or waiting (limit {cfg.max_open_calls})"
    last = j.get("last_call_by_side", {}).get(d)
    if last is not None and (ctx.as_of - last).total_seconds() / 3600 < cfg.same_side_cooldown_h:
        return f"a {d} call was made {(ctx.as_of - last).total_seconds() / 3600:.1f} h ago (cooldown {cfg.same_side_cooldown_h:g} h)"
    return None


# ---------------------------------------------------------------- master
MASTER_ROLE = ("Master trader. The chart analyst read the chart and proposed a setup (or none); the risk manager checked "
               "and sized it; macro and liquidity reports are attached. Decide PLACE (put the proposed order on exactly as "
               "sized) or PASS. You cannot change the prices. PASS when the setup fights a strong macro lean, sits into a "
               "binary event, or the read does not support it. Vetoes are final.")
MASTER_SCHEMA = '{"decision": "PLACE"|"PASS", "confidence": 0..1, "reason": "<=4 sentences"}'


def master_decide(ctx: Context, reports: dict, plan: dict | None, why_not: str | None, llm=None) -> tuple[str, str, dict | None, str]:
    cfg = ctx.cfg
    liq, mac = reports["liquidity"], reports["macro"]
    if liq.veto:
        return "PASS", liq.summary, None, "rules"
    if plan is None:
        return "PASS", f"chart: {reports['chart'].facts['setup'].get('why') or 'no setup'}" + (f" ({why_not})" if why_not and why_not != "no setup" else ""), None, "rules"
    blk = journal_block(ctx, plan["direction"])
    if blk:
        return "PASS", f"risk: {blk}", None, "rules"
    sign = 1 if plan["direction"] == "BUY" else -1
    if llm is None:
        if mac.score * sign <= -cfg.macro_oppose:
            return "PASS", f"setup {plan['direction']} but macro leans against it ({mac.score:+.2f})", None, "rules"
        return plan["direction"], f"{plan['entry_type']} {plan['direction']} at {plan['entry']}: {reports['chart'].facts['setup'].get('why', '')}", plan, "rules"
    facts = {"as_of": str(ctx.as_of), "price": ctx.price, "plan": plan,
             "chart": {"bias": reports["chart"].score, "confidence": reports["chart"].confidence, "read": reports["chart"].summary,
                       "setup_why": reports["chart"].facts["setup"].get("why")},
             "macro": {"score": mac.score, "confidence": mac.confidence, "summary": mac.summary},
             "liquidity": {"summary": liq.summary, "next_events_48h": liq.facts.get("next_events_48h")}}
    system = localise(f"{DESK}\nYour role: {MASTER_ROLE}\nJSON schema: {MASTER_SCHEMA}", cfg)
    reply = llm.complete_json(model=cfg.deep_model, agent="master", system=system, user="FACTS:\n" + json.dumps(facts, indent=1, default=str),
                              max_tokens=cfg.max_tokens)
    why = str(reply.get("reason", ""))[:700]
    conf = clamp(reply.get("confidence", 0.0), 0.0, 1.0)
    if str(reply.get("decision", "PASS")).upper() != "PLACE":
        return "PASS", why or "master passed", None, cfg.deep_model
    if conf < cfg.master_min_confidence:
        return "PASS", f"master confidence {conf:.2f} below {cfg.master_min_confidence:g}: {why}", None, cfg.deep_model
    return plan["direction"], why, plan, cfg.deep_model


# ---------------------------------------------------------------- one decision
def decide_at(m1_all: pd.DataFrame, as_of, cfg: Config, *, llm=None, macro_df=None, events=None,
              prior_entries: list[dict] | None = None, v2: V2 = V2_DEFAULT) -> dict:
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    horizon = as_of - pd.Timedelta(hours=cfg.expiry_hours + v2.max_valid_hours) - pd.Timedelta(days=1)
    prior = [e for e in (prior_entries or []) if horizon <= pd.Timestamp(e["as_of"]) < as_of]
    state = J.state_at(J.score_entries(prior, m1_all.loc[: as_of - pd.Timedelta(minutes=1)], cfg, as_of), as_of) if prior else \
        {"open_calls": 0, "realised_r_today": 0.0, "last_call_by_side": {}}
    ctx = build_context(m1_all, as_of, cfg, macro_df, events, state)
    reports = {"chart": chart_run(ctx, v2, llm), "macro": macro.run(ctx, llm), "liquidity": liquidity.run(ctx)}
    st = reports["chart"].facts["structure"]
    plan, why_not = check_setup(ctx, reports["chart"].facts["setup"], v2, st)
    reports["chart"].facts["setup_check"] = why_not or "ok"
    decision, reason, chosen, source = master_decide(ctx, reports, plan, why_not, llm)
    # Shadows, scored on every slot: what the chart's own setup is worth with no master, and the rules setup the model
    # is compared against (the same in rules mode).
    rules_plan, _ = check_setup(ctx, reports["chart"].facts["rules_setup"], v2, st)
    baselines = {"chart_setup": {"direction": plan["direction"], "plan": plan} if plan else None,
                 "rules_setup": {"direction": rules_plan["direction"], "plan": rules_plan} if rules_plan else None}
    # A setup the risk check refused (too little R, stop too wide or tight, entry too far) is scored as proposed, so we
    # see whether the check throws away winners. Scoring only: it never becomes a call.
    if plan is None and why_not not in (None, "no setup"):
        loose = replace(ctx, cfg=replace(ctx.cfg, min_stop=0.0, max_stop=float("inf")))
        raw, _ = check_setup(loose, reports["chart"].facts["setup"], replace(v2, min_rr=0.0, max_entry_atr_d1=float("inf")), st, filters=False)
        if raw:
            baselines["rejected_setup"] = {"direction": raw["direction"], "plan": raw, "rejected_because": why_not}
    mode = "llm" if llm is not None else "rules"
    h = v2_hash(cfg, v2)
    return {"id": f"{as_of.isoformat()}|{mode}|{h}", "as_of": as_of.isoformat(), "desk": "v2", "mode": mode, "rules_hash": h,
            "decided_by": source, "decision": decision, "reason": reason, "price": round(ctx.price, I.of(cfg).dp),
            "instrument": I.of(cfg).oanda, "plan": chosen, "reports": {k: v.to_dict() for k, v in reports.items()},
            "baselines": baselines}


def card(call: dict) -> str:
    spec = I.get(call.get("instrument"))
    f = lambda x: f"{x:.{spec.dp}f}"
    head = f"{spec.label} {call['as_of'][:16].replace('T', ' ')} UTC  ·  v2 {call['decision']}  ({call['mode']})"
    if call["decision"] == "PASS":
        return f"{head}\n{call['reason']}"
    p = call["plan"]
    kind = {"market": "at market", "limit": "LIMIT", "stop": "STOP (on the break)"}[p["entry_type"]]
    until = f"   order valid until {p['valid_until'][:16].replace('T', ' ')} UTC" if p.get("valid_until") else ""
    return "\n".join([
        head, f"{p['direction']} {kind} {f(p['entry'])}{until}",
        f"SL {f(p['stop'])}   TP1 {f(p['tp1'])} ({p['rr_tp1']}R)   TP2 {f(p['tp2'])}",
        f"Size {p['lots']} lots, risk ${p['risk_usd']:.0f} (demo sizing)", call["reason"],
        "Research only: logged to the v2 forward test, no order placed."])
