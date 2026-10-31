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
from . import features as F
from . import instruments as I
from . import journal as J
from . import moves
from . import watcher as W
from .agents import liquidity
from .agents.base import DESK, ask, clamp, localise
from .config import Config, rules_hash as v1_hash
from .context import Context, build_context
from .types import Report

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


def v31_hash(cfg: Config, v31: V31 = V31_DEFAULT, watch: W.WatchV31 = W.WATCH_V31) -> str:
    payload = {"v1": v1_hash(cfg), "v31": asdict(v31), "watch": W.params(watch), "version": VERSION}
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


# ---------------------------------------------------------------- inputs: each with its age, or "unavailable"
POSITIONS_NOTE = ("omitted from every v3.1 prompt: OANDA's client positions read 70.9% long on all six runs on 2026-10-30 while "
                  "the timestamp moved, and the cause has not been found yet (README, desk v3.1). Logged here so it can be.")


def _age_min(now: pd.Timestamp, t) -> float | None:
    try:
        return round((now - pd.Timestamp(t)).total_seconds() / 60, 1)
    except (TypeError, ValueError):
        return None


def live_inputs(now: pd.Timestamp, oanda=None, bars: pd.DataFrame | None = None, cross: dict | None = None, session=None) -> dict:
    """Everything v3.1 reads besides its candles, fetched once per wake and stored on the call. Every value carries its age or
    is the string "unavailable"; a dead source is never filled in."""
    import requests
    from . import live_data as D
    from . import macro_data, news_v31
    session = session or requests
    oanda = oanda or D.Oanda()
    out = {"cross": {}, "book": "unavailable", "positions": "unavailable", "volume_ratio": None}
    try:
        b = bars if bars is not None else oanda.m5()
        out["volume_ratio"] = D.volume_ratio(b)
        price = float(b["close"].iloc[-1])
        book = D.parse_book(oanda._json(f"{D.GOLD}/orderBook"), price, 60.0)
        out["book"] = {**book, "age_min": _age_min(now, book.get("time"))}
        pos = D.parse_positions(oanda._json(f"{D.GOLD}/positionBook"))
        out["positions"] = {**pos, "age_min": _age_min(now, pos.get("time")), "note": POSITIONS_NOTE}
    except Exception as e:
        print(f"gold book unavailable: {e}")
    for inst, meaning in D.CROSS.items():
        try:
            cb = (cross or {}).get(inst)
            cb = cb if cb is not None and len(cb) else oanda.m5(inst, 60)
            out["cross"][inst] = {"meaning": meaning, **D.changes(cb), "age_min": _age_min(now, cb.index[-1] + pd.Timedelta(minutes=5))}
        except Exception as e:
            print(f"{inst} unavailable: {e}")
            out["cross"][inst] = "unavailable"
    heads = news_v31.sources(now, session)
    out["news"] = news_v31.for_desk(heads)
    out["headline_lag_min"] = news_v31.headline_lag(out["news"])
    out["real_yield"] = macro_data.real_yield(now, session)
    out["cot"] = macro_data.cot_gold(now, session)
    out["etf_flows"] = macro_data.etf_flows(now)
    return out


def inputs_record(ctx: Context, live: dict) -> dict:
    """One line per input on the call: its age, or "unavailable", so every input can be judged later."""
    def age(v, key="age_min"):
        if v in (None, "unavailable") or (isinstance(v, (list, dict)) and not v):
            return "unavailable"
        return {key: v.get(key)} if isinstance(v, dict) and key in v else "present"

    heads, pos = live.get("news") or [], live.get("positions")
    macro_day = ctx.macro.index[-1] if ctx.macro is not None and len(ctx.macro) else None
    cross = live.get("cross") or {}
    return {
        "gold_bars": {"age_min": round((ctx.as_of - ctx.last_bar_end).total_seconds() / 60, 1)},
        "news": {"headlines": len(heads), "lag": live.get("headline_lag_min", "unavailable")} if heads else "unavailable",
        "headline_lag_min": live.get("headline_lag_min", "unavailable"),
        "cross": {k: age(v) for k, v in cross.items()} or "unavailable",
        "order_book": age(live.get("book")),
        "positions": {"age_min": pos.get("age_min"), "in_prompts": False} if isinstance(pos, dict) else "unavailable",
        "volume_ratio": "present" if live.get("volume_ratio") is not None else "unavailable",
        "macro_daily": {"age_days": round((ctx.as_of - macro_day).total_seconds() / 86400, 1)} if macro_day is not None else "unavailable",
        "real_yield": age(live.get("real_yield"), "age_days"),
        "cot": age(live.get("cot"), "age_days"),
        "etf_flows": age(live.get("etf_flows"), "age_days"),
        "calendar": {"events_file_age_days": cal.events_file_age_days(cal.EVENTS_V31_FILE)} if cal.EVENTS_V31_FILE.exists() else
                    {"events_file_age_days": cal.events_file_age_days(), "note": "events_v31.csv missing; v1-v3's events.csv only"},
    }


def default_events(as_of: pd.Timestamp) -> list[dict]:
    """FOMC and payrolls built in, plus events.csv (v1-v3's list) and events_v31.csv (the wider one), each event once. Only
    `high` rows block (`calendar.blocking_event`); medium rows are shown to the agents."""
    t = as_of.to_pydatetime()
    pool = cal.builtin_events(t - pd.Timedelta(days=2), t + pd.Timedelta(days=2)) + cal.file_events(cal.EVENTS_FILE) + cal.file_events(cal.EVENTS_V31_FILE)
    seen, out = set(), []
    for e in pool:
        k = (e["time"], e["name"])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def news_run(ctx: Context, live: dict, llm=None, brief: dict | None = None) -> Report:
    """v3's news agent and role, plus the measured headline lag (and, from Task 9, the daily brief). Headlines reach the model
    only inside the JSON facts block, never in its role text."""
    heads = live.get("news") or []
    rep = Report("news", 0.0, 0.0, "no headlines available; abstaining" if not heads else "headlines not read in rules mode",
                 facts={"headlines": heads, "headline_lag_min": live.get("headline_lag_min", "unavailable")})
    if llm is None or not heads:
        return rep
    facts = {"as_of": str(ctx.as_of), "headline_lag_min": live.get("headline_lag_min"), "headlines": heads}
    if brief:
        facts["daily_brief"] = brief_facts(brief)
    from .agents.base import refine
    reply = ask(llm, ctx.cfg.quick_model, V3.NEWS_ROLE, V3.NEWS_SCHEMA, facts, ctx.cfg.max_tokens, ctx.cfg, agent="news")
    refine(rep, reply, ctx.cfg.quick_model)
    rep.facts.update(driver=str(reply.get("driver", ""))[:80], risk_flag=bool(reply.get("risk_flag")))
    return rep


def macro_run(ctx: Context, live: dict, llm=None, brief: dict | None = None) -> Report:
    """v1's daily macro plus v3's intraday markets, and v3.1's real yield, COT, ETF flows and the wider calendar, each with
    its age or "unavailable"."""
    from .agents import macro
    from .agents.base import refine
    rep = macro.run(ctx, None)
    t = ctx.as_of.to_pydatetime()
    rep.facts.update(intraday=live.get("cross") or {}, real_yield=live.get("real_yield", "unavailable"),
                     cot=live.get("cot", "unavailable"), etf_flows=live.get("etf_flows", "unavailable"),
                     calendar_48h=[{"in_hours": round((e["time"] - t).total_seconds() / 3600, 1), "name": e["name"], "impact": e["impact"]}
                                   for e in cal.next_events(t, 48, ctx.events)])
    if brief:
        rep.facts["daily_brief"] = brief_facts(brief)
    if llm is not None:
        refine(rep, ask(llm, ctx.cfg.quick_model, V3.MACRO_ROLE, V3.MACRO_SCHEMA, rep.facts, ctx.cfg.max_tokens, ctx.cfg, agent="macro"),
               ctx.cfg.quick_model)
    return rep


# ---------------------------------------------------------------- chart agent
# Replaces v3's "quick trades" and "$5-15" text: the model reads the day and the move, and sets stop, target, validity and
# holding time from the market, justifying each. The no-fade, squeeze and post-event sentences are v3's.
ROLE = ("Chart trader who trades the legs of an intraday move from price structure. You were woken because of TRIGGER (null = a "
        "routine check; a gap, cross_move or news trigger carries no direction and is only a reason to look). State the day type "
        "first, from H4, H1 and MOVE: trending (one way, legs with shallow pullbacks), ranging, or unclear, and its direction. "
        "On a trending day the main setups are a re-entry with the move after a pullback fails (it stalls and turns back the "
        "move's way) and a fresh break of the last leg's extreme; one trade per leg, closed at its target, the next only after "
        "confirmation. MOVE lists the desk's own calls on this move and what is open now. On a ranging day trade only from a "
        "range edge, or nothing. Judge every number from current structure and volatility and justify each in why: the stop "
        "beyond the M5 or M15 structure that proves the trade wrong, at least {m5:g}x the M5 ATR away; TP1 at least {min_rr}R "
        "away, at the next level or where the move's legs suggest, and a full exit; how long the order stays valid "
        "(valid_hours, at most {max_valid:g}); the most hours the trade may stay open (max_hold_hours). TP2 is for "
        "information. Never chase: after a long leg with no pullback, wait for one. Never fade a momentum leg: no sell against "
        "rising M5 lows, no buy against falling M5 highs, and a squeeze waits for the break. Within {post_event}h after a "
        "high-impact release propose nothing. The setup must agree with your day read, or say why not. Say entry_type \"none\" "
        "when the chart gives nothing clean; that is a normal answer.")
SCHEMA = ('{"day_type": "trending"|"ranging"|"unclear", "day_direction": "up"|"down"|"none", "bias": -1..1 (negative = '
          'bearish), "confidence": 0..1, "read": "<=4 sentences: day type, the move so far, key levels, what would change your '
          'mind", "setup": {"direction": "BUY"|"SELL"|null, "entry_type": "market"|"limit"|"stop"|"none", "entry": <price or '
          'null>, "stop": <price or null>, "tp1": <price or null>, "tp2": <price or null>, "valid_hours": <hours>, '
          '"max_hold_hours": <hours>, "why": "<=3 sentences: the setup, and why this stop, target, validity and holding time"}}')
DAY_TYPES, DAY_DIRECTIONS = ("trending", "ranging", "unclear"), ("up", "down", "none")


def _pick(value, allowed: tuple) -> str:
    v = str(value or "").strip().lower()
    return v if v in allowed else "unclear"


def chart_run(ctx: Context, v31: V31, m5: pd.DataFrame, trigger: dict | None, live: dict, move: dict, llm=None) -> Report:
    st, candles = V3.chart_facts(ctx, _v3(v31), m5, live)
    st.pop("positions", None)                                     # see POSITIONS_NOTE: not trusted until its cause is found
    setup = V3.rules_setup(ctx, st, trigger, _v3(v31), st["atr"]["m5"])
    live_setup = setup["entry_type"] != "none"
    rep = Report("chart", score=float(st["h1_pattern"]["bias"]) if live_setup else 0.0, confidence=0.5 if live_setup else 0.0,
                 summary=f"rules v3.1: {setup['why']}", facts={"structure": st, "move": move, "setup": setup, "rules_setup": setup})
    if llm is None:
        return rep
    role = ROLE.format(m5=v31.min_stop_atr_m5, min_rr=v31.min_rr, max_valid=v31.max_valid_hours, post_event=v31.post_event_hours)
    system = localise(f"{DESK}\nYour role: {role}\nJSON schema: {SCHEMA}", ctx.cfg)
    user = (f"AS OF {ctx.as_of:%Y-%m-%d %H:%M} UTC ({ctx.as_of:%A})\nTRIGGER:\n{json.dumps(trigger, default=str)}\n\n"
            f"MOVE:\n{json.dumps(move, indent=1, default=str)}\n\n"
            f"STRUCTURE:\n{json.dumps(st, indent=1, default=str)}\n\nCANDLES (closed bars only):\n{candles}")
    reply = llm.complete_json(model=ctx.cfg.deep_model, agent="chart", system=system, user=user, max_tokens=v31.chart_max_tokens)
    s = reply.get("setup") or {}
    rep.facts["setup"] = {"direction": s.get("direction"), "entry_type": str(s.get("entry_type") or "none").lower(), "entry": s.get("entry"),
                          "stop": s.get("stop"), "tp1": s.get("tp1"), "tp2": s.get("tp2"),
                          "valid_hours": s.get("valid_hours") or v31.default_valid_hours,
                          "max_hold_hours": normal_hold(s.get("max_hold_hours"), v31), "why": str(s.get("why", ""))[:600]}
    rep.facts["day_type"], rep.facts["day_direction"] = _pick(reply.get("day_type"), DAY_TYPES), _pick(reply.get("day_direction"), DAY_DIRECTIONS)
    rep.score, rep.confidence = clamp(reply.get("bias", 0.0)), clamp(reply.get("confidence", 0.0), 0.0, 1.0)
    rep.summary, rep.source = str(reply.get("read", ""))[:800], ctx.cfg.deep_model
    return rep


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
                           "volume_vs_normal": live.get("volume_ratio")}}
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
    state, scored = state_for(prior_entries or [], mode, m1_all, as_of, cfg)
    ctx = build_context(m1_all, as_of, cfg, macro_df, default_events(as_of) if events is None else events, state)
    m5 = V3.m5_bars(ctx)
    move = moves.current(ctx.tf, as_of, F.atr(ctx.tf["D1"]), scored)
    reports = {"chart": chart_run(ctx, v31, m5, trigger, live, move, llm), "macro": macro_run(ctx, live, llm, brief),
               "news": news_run(ctx, live, llm, brief), "liquidity": liquidity.run(ctx, window=cal.desk_window)}
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
            "baselines": baselines, "inputs": inputs_record(ctx, live),
            "positions_raw": live.get("positions", "unavailable")}


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


def day_text(scored: list[dict], day: str, wakes: int = 0) -> str:
    """The end-of-day line for Telegram: v3's, labelled v3.1."""
    return V3.day_text(scored, day, wakes).replace("Gold v3 ", "Gold v3.1 ", 1)


# ---------------------------------------------------------------- the daily brief's facts
BRIEF_MAX_AGE = pd.Timedelta(hours=24)       # an older brief is not shown to the desk


def current_brief(as_of: pd.Timestamp, path=None) -> dict | None:
    """The latest brief if it is under a day old, else None."""
    from . import brief as B
    b = B.latest(path or BRIEF_LOG)
    if b and pd.Timestamp(b["at"]) <= as_of and as_of - pd.Timestamp(b["at"]) < BRIEF_MAX_AGE:
        return b
    return None


def open_call(scored: list[dict]) -> dict | None:
    """The model desk's most recent call still open or waiting to fill, for the brief's last line."""
    live = [e for e in scored if e["decision"] in ("BUY", "SELL") and (e["scores"].get("master") or {}).get("outcome") in OPEN]
    return max(live, key=lambda e: e["as_of"]) if live else None


def brief_facts_at(m1_all: pd.DataFrame, as_of: pd.Timestamp, cfg: Config, live: dict, prior: list[dict],
                   events: list[dict] | None = None) -> dict:
    """What the brief is written from: the move and structure (as the chart sees them, without candles), the news, other markets,
    real yield, positioning, the next day's calendar, and the desk's current call. Closed bars only."""
    from . import structure as S
    state, scored = state_for(prior, "llm", m1_all, as_of, cfg)
    ctx = build_context(m1_all, as_of, cfg, None, default_events(as_of) if events is None else events, state)
    m5 = V3.m5_bars(ctx)
    st = S.summary(ctx.tf, ctx.price, V31_DEFAULT.lookback_days, I.of(cfg).dp, m5=m5)
    t = as_of.to_pydatetime()
    return {"as_of": str(as_of), "price": round(ctx.price, 2),
            "move": moves.current(ctx.tf, as_of, F.atr(ctx.tf["D1"]), scored),
            "structure": {k: st[k] for k in ("atr", "h4_pattern", "h1_pattern", "d1_pattern", "nearest_support", "nearest_resistance",
                                             "zones_nearest")},
            "key_levels": [{"name": x["name"], "price": round(x["price"], 2)} for x in S.key_levels(m5)],
            "headlines": (live.get("news") or [])[:12], "headline_lag_min": live.get("headline_lag_min", "unavailable"),
            "other_markets": live.get("cross") or "unavailable", "real_yield": live.get("real_yield", "unavailable"),
            "cot": live.get("cot", "unavailable"), "etf_flows": live.get("etf_flows", "unavailable"),
            "calendar_24h": [{"time_utc": str(e["time"])[:16], "in_hours": round((e["time"] - t).total_seconds() / 3600, 1),
                              "name": e["name"], "impact": e["impact"]} for e in cal.next_events(t, 24, ctx.events)],
            "open_call": open_call(scored)}
