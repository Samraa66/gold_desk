"""Desk v3.1 (2026-10-31). Offline: no network, no key, no bars beyond the synthetic ones."""
import pandas as pd
import pytest

from gold_agents import desk_v2 as V2
from gold_agents import desk_v3 as V3
from gold_agents import instruments as I
from gold_agents.config import rules_hash

# Read once on 2026-10-31 from the code at the v3 baseline commit and pasted here. v3.1 must leave every one of them alone.
KNOWN_HASHES = {
    "v1": {"XAU_USD": "0eed0fd6", "XAG_USD": "d9bb2b05", "EUR_USD": "b87656d9", "GBP_USD": "1740076f"},
    "v2": {"XAU_USD": "80b98c11", "XAG_USD": "df6c1617", "EUR_USD": "969c1a3d", "GBP_USD": "f827a7ce"},
    "v3": "2bbfa4f5",
}


# ---------------- identity ----------------
def test_older_hashes_do_not_move():
    assert {k: rules_hash(s.config()) for k, s in I.INSTRUMENTS.items()} == KNOWN_HASHES["v1"]
    assert {k: V2.v2_hash(s.config()) for k, s in I.INSTRUMENTS.items()} == KNOWN_HASHES["v2"]
    assert V3.v3_hash(V3.config()) == KNOWN_HASHES["v3"]


# ---------------- Task 2: the scorer honours a plan's holding time and the Friday close ----------------
from gold_agents import journal as J  # noqa: E402
from gold_agents.config import Config  # noqa: E402


def minute_bars(spans):
    """spans = [(start, minutes, price)]: flat minute bars at `price`, 0.2 wide, with gaps wherever the spans leave them."""
    frames = []
    for start, n, px in spans:
        idx = pd.date_range(start, periods=n, freq="min", tz="UTC")
        frames.append(pd.DataFrame({"open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "spread": 0.2}, index=idx))
    return pd.concat(frames)


def sell(entry_type="market", **keys):
    p = {"direction": "SELL", "entry_type": entry_type, "entry": 4000.0, "stop": 4100.0, "tp1": 3800.0, "tp2": 3700.0, **keys}
    if entry_type == "limit":
        p["entry"], p["valid_until"] = 3999.95, "2026-10-14T18:00:00+00:00"
    return p


def test_plan_hold_overrides_expiry():
    bars = minute_bars([("2026-10-14T15:00:00Z", 240, 4000.0)])
    cfg = Config(expiry_hours=6.0)
    now = pd.Timestamp("2026-10-14T19:00:00Z")
    for et in ("market", "limit"):
        s = J.score_plan("SELL", sell(et, max_hold_hours=1.0), pd.Timestamp("2026-10-14T15:00:00Z"), bars, cfg, now)
        assert s["outcome"] == "expired", et
        assert pd.Timestamp(s["closed_at"]) == pd.Timestamp("2026-10-14T16:00:00Z"), et
    # without the key the 6 h config expiry still applies: nothing is closed after 4 h
    assert J.score_plan("SELL", sell(), pd.Timestamp("2026-10-14T15:00:00Z"), bars, cfg, now)["outcome"] == "open"


FRIDAY_WEEKEND = [("2026-10-30T19:00:00Z", 120, 3990.0), ("2026-11-01T23:00:00Z", 60, 3950.0)]   # Fri last bar 20:59, Sun reopen 23:00 UTC


def test_flat_by_ends_trade_before_weekend():
    bars = minute_bars(FRIDAY_WEEKEND)
    flat_by = "2026-10-30T21:00:00+00:00"
    for et, start in (("market", "2026-10-30T19:00:00Z"), ("limit", "2026-10-30T19:00:00Z")):
        plan = sell(et, max_hold_hours=24.0, flat_by=flat_by)
        if et == "limit":
            plan.update(entry=3989.95, valid_until="2026-10-31T01:00:00+00:00")
        s = J.score_plan("SELL", plan, pd.Timestamp(start), bars, Config(expiry_hours=24.0), pd.Timestamp("2026-11-02T00:00:00Z"))
        assert s["outcome"] == "expired", et
        assert pd.Timestamp(s["closed_at"]) <= pd.Timestamp(flat_by), et
        exit_px = 3990.0 + 0.6                                        # Friday's last bid close plus the spread, never Sunday's 3950
        fill = s["fill"]
        assert s["r"] == pytest.approx(round((fill - exit_px) / abs(plan["entry"] - plan["stop"]), 3)), et


def test_flat_by_with_no_bar_after_it_yet_still_closes():
    bars = minute_bars(FRIDAY_WEEKEND[:1])
    s = J.score_plan("SELL", sell(flat_by="2026-10-30T21:00:00+00:00"), pd.Timestamp("2026-10-30T19:00:00Z"), bars,
                     Config(expiry_hours=24.0), pd.Timestamp("2026-10-30T21:00:00Z"))
    assert s["outcome"] == "expired" and pd.Timestamp(s["closed_at"]) <= pd.Timestamp("2026-10-30T21:00:00Z")


def test_plan_without_new_keys_scores_as_before():
    """v1-v3 plans keep the old rule, Sunday open included: changing it would move their scores."""
    bars = minute_bars(FRIDAY_WEEKEND)
    s = J.score_plan("SELL", sell(), pd.Timestamp("2026-10-30T19:00:00Z"), bars, Config(expiry_hours=6.0),
                     pd.Timestamp("2026-11-02T00:00:00Z"))
    assert s["outcome"] == "expired" and s["closed_at"] == "2026-11-01 23:00:00+00:00"
    assert s["r"] == pytest.approx(round((3989.7 - 3950.6) / 100.0, 3))


# ---------------- Task 3: market hours in New York time ----------------
from datetime import datetime, timezone  # noqa: E402

from gold_agents import calendar as cal  # noqa: E402
from tests.conftest import make_m1  # noqa: E402


def utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_desk_window_clock_change():
    assert cal.desk_window(utc("2026-10-30T20:30"))[0] in ("open", "thin")     # Fri 16:30 New York (EDT): the last half hour trades
    assert cal.desk_window(utc("2026-10-30T21:00"))[0] == "closed"             # Fri 17:00 New York: the week is over
    assert cal.desk_window(utc("2026-10-31T15:00"))[0] == "closed"             # Saturday
    assert cal.desk_window(utc("2026-11-01T22:30"))[0] == "closed"             # Sun 17:30 New York (EST from 11-01): not yet
    assert cal.desk_window(utc("2026-11-01T23:05"))[0] == "thin"               # Sun 18:05 New York: the reopen
    assert cal.desk_window(utc("2026-11-02T22:30"))[0] == "break"              # Mon 17:30 New York (EST)
    assert cal.desk_window(utc("2026-10-27T21:30"))[0] == "break"              # Tue 17:30 New York (EDT)
    assert cal.desk_window(utc("2026-11-03T08:00"))[0] == "open"               # Tue 03:00 New York: London
    assert cal.desk_window(utc("2026-11-03T06:30"))[0] == "thin"               # Tue 01:30 New York: Asia


def test_next_friday_close_after_clock_change():
    assert cal.next_friday_close(utc("2026-11-02T10:00")) == utc("2026-11-06T22:00")
    assert cal.next_friday_close(utc("2026-10-30T20:59")) == utc("2026-10-30T21:00")     # same Friday, before the close (EDT)
    assert cal.next_friday_close(utc("2026-10-30T21:00")) == utc("2026-11-06T22:00")     # at the close: the next week's


def test_liquidity_uses_given_window():
    from gold_agents.agents import liquidity
    from gold_agents.context import build_context
    bars = make_m1(start="2026-10-01", days=30, seed=7)
    ctx = build_context(bars, pd.Timestamp("2026-10-30T20:30:00Z"), Config())
    assert liquidity.run(ctx).veto                                             # v1-v3's padded window: shut from Fri 20:00 UTC
    rep = liquidity.run(ctx, window=cal.desk_window)
    assert not rep.veto and rep.facts["market"] == "open"
    assert liquidity.run(ctx, window=lambda t: ("break", "daily break")).veto


# ---------------- Task 4: desk v3.1 core ----------------
from gold_agents import desk_v31 as D31  # noqa: E402
from gold_agents.context import build_context  # noqa: E402
from gold_agents.llm import FakeLLM  # noqa: E402


@pytest.fixture(scope="module")
def history():
    return make_m1(start="2026-06-01", days=136, seed=5, vol=0.25)


def asof(hist):
    return hist.index[hist.index.dayofweek == 2][-1000]          # a Wednesday, 2026-10-14 15:20 UTC


def sell_trigger(price=1.0):
    return {"kind": "level_break", "direction": "SELL", "level": price, "name": "asia_low"}


LIVE = {"cross": {"USD_JPY": {"chg_1h_pct": 0.4, "chg_4h_pct": 0.9}}, "book": {"above": [], "below": []},
        "positions": {"long_pct": 70.0}, "volume_ratio": 2.4,
        "news": [{"title": "Gold slides as yields jump", "source": "Reuters", "age_min": 12, "published": "x"}]}


def price_at(hist, t):
    return float(hist.loc[:t - pd.Timedelta(minutes=1), "close"].iloc[-1])


def fake31(hist, t, conf=0.55, stop_gap=8.0, decision="PLACE", direction="SELL", hold=3.0, **chart):
    px = price_at(hist, t)
    sign = 1 if direction == "BUY" else -1
    return FakeLLM({
        "Chart trader": {"bias": 0.6 * sign, "confidence": 0.6, "read": "breakdown", **chart, "setup": {
            "direction": direction, "entry_type": "market", "entry": None, "stop": px - sign * stop_gap,
            "tp1": px + sign * (1.5 * stop_gap + 1), "tp2": px + sign * 3 * stop_gap, "valid_hours": 1, "max_hold_hours": hold,
            "why": "broke the Asia low"}},
        "Cross-asset analyst": {"score": -0.3, "confidence": 0.5, "summary": "dollar firm"},
        "News analyst": {"score": -0.4, "confidence": 0.6, "summary": "yields driving gold down", "driver": "yields", "risk_flag": False},
        "Master trader": {"decision": decision, "confidence": conf, "reason": "clean break"}})


def decide31(hist, t, llm=None, **kw):
    return D31.decide_at(hist, t, D31.config(), llm=llm, events=kw.pop("events", []), macro_df=None, live=kw.pop("live", LIVE),
                         trigger=kw.pop("trigger", sell_trigger()), v31=kw.pop("v31", D31.V31(counter_run=99)), **kw)


def open_entry(t, mode, direction, px, minutes_before=30):
    """A logged call still open at `t`: a market plan with levels far from price."""
    sign = 1 if direction == "BUY" else -1
    at = t - pd.Timedelta(minutes=minutes_before)
    return {"id": f"{at.isoformat()}|{mode}|x", "as_of": at.isoformat(), "mode": mode, "decision": direction, "price": px,
            "plan": {"direction": direction, "entry_type": "market", "entry": px, "stop": px - sign * 70, "tp1": px + sign * 150,
                     "tp2": px + sign * 200, "max_hold_hours": 24.0}}


def test_v31_config_and_hash():
    cfg = D31.config()
    assert (cfg.equity, cfg.risk_pct, cfg.daily_loss_limit_r, cfg.max_open_calls, cfg.master_min_confidence) == (5000.0, 1.5, 3.0, 2, 0.5)
    assert cfg.min_stop == 0.0 and cfg.max_stop == float("inf") and cfg.same_side_cooldown_h == 0.0 and cfg.expiry_hours == 24.0
    assert D31.V31().min_rr == 1.5
    h = D31.v31_hash(cfg)
    assert h not in (KNOWN_HASHES["v3"], KNOWN_HASHES["v2"]["XAU_USD"]) and h != D31.v31_hash(cfg, D31.V31(min_rr=2.0))
    assert D31.JOURNAL.name == "calls_v31.jsonl" and D31.OUTCOMES.name == "outcomes_v31.jsonl" and D31.PROMPTS.name == "prompts_v31.jsonl"
    assert D31.DASHBOARD.name == "dashboard_v31.html" and D31.WATCH_LOG.name == "watch_v31.jsonl"
    assert D31.WATCH_STATE.name == "watch_state_v31.json" and D31.BRIEF_LOG.name == "brief_v31.jsonl"


def test_rules_calls_do_not_fill_the_model_limit(history):
    """10-30 19:46: the model passed on "3 calls open, limit 2" because the rules baseline's call counted."""
    t = asof(history)
    px = price_at(history, t)
    prior = [open_entry(t, "llm", "BUY", px), open_entry(t, "rules", "SELL", px, 20), open_entry(t, "rules", "SELL", px, 10)]
    assert [e["mode"] for e in D31.prior_for(prior, "llm")] == ["llm"]
    call = decide31(history, t, fake31(history, t), prior_entries=prior)
    assert call["decision"] == "SELL", call["reason"]
    # and the bug as it was: v3 counts all three
    v3_state = J.state_at(J.score_entries(prior, history.loc[:t - pd.Timedelta(minutes=1)], D31.config(), t), t)
    assert v3_state["open_calls"] == 3


def test_same_side_waits_for_close_but_not_a_clock(history):
    t = asof(history)
    px = price_at(history, t)
    blocked = decide31(history, t, fake31(history, t), prior_entries=[open_entry(t, "llm", "SELL", px)])
    assert blocked["decision"] == "PASS" and "still open" in blocked["reason"]
    closed = open_entry(t, "llm", "SELL", px, 10)
    closed["plan"].update(max_hold_hours=0.05)                       # closed three minutes after it opened, seven before `t`
    scored = J.score_entries([closed], history.loc[:t - pd.Timedelta(minutes=1)], D31.config(), t)
    assert scored[0]["scores"]["master"]["outcome"] == "expired" and not D31.side_open(scored, "SELL")
    call = decide31(history, t, fake31(history, t), prior_entries=[closed])
    assert call["decision"] == "SELL", call["reason"]


def ctx_at(hist, t, events=()):
    return build_context(hist, t, D31.config(), None, list(events), {})


def market_sell(px, gap, hold=None):
    return {"direction": "SELL", "entry_type": "market", "entry": None, "stop": px + gap, "tp1": px - 1.6 * gap, "tp2": px - 3 * gap,
            "valid_hours": 1, "max_hold_hours": hold, "why": "x"}


def test_wide_stop_allowed_when_sizable(history):
    ctx = ctx_at(history, asof(history))
    plan, why = D31.check(ctx, market_sell(ctx.price, 40.0), D31.V31(counter_run=99), {}, atr_m5=2.0)
    assert why is None and plan["lots"] == 0.01 and plan["risk_usd"] == pytest.approx(40.0)


def test_stop_too_wide_to_size_is_refused(history):
    ctx = ctx_at(history, asof(history))
    plan, why = D31.check(ctx, market_sell(ctx.price, 90.0), D31.V31(counter_run=99), {}, atr_m5=2.0)
    assert plan is None and "even 0.01 lot risks $90" in why and "$75" in why


def test_stop_inside_noise_refused(history):
    ctx = ctx_at(history, asof(history))
    plan, why = D31.check(ctx, market_sell(ctx.price, 4.0), D31.V31(counter_run=99), {}, atr_m5=6.0)
    assert plan is None and "M5 noise" in why


def test_bad_hold_defaults(history):
    v = D31.V31()
    for bad in (None, 0, -1, "soon", float("nan"), float("inf"), True):
        assert D31.normal_hold(bad, v) == v.default_hold_hours, bad
    assert D31.normal_hold("2.5", v) == 2.5
    ctx = ctx_at(history, asof(history))
    plan, _ = D31.check(ctx, market_sell(ctx.price, 10.0, hold=10000), D31.V31(counter_run=99), {}, atr_m5=2.0)
    assert plan["max_hold_hours"] == 10000
    assert J._expiry(plan, ctx.as_of, D31.config()) == pd.Timestamp(plan["flat_by"])     # cut by the Friday close


def test_bad_hold_from_the_model_never_crashes(history):
    t = asof(history)
    for bad in (None, 0, "soon", 1e9):
        call = decide31(history, t, fake31(history, t, hold=bad))
        assert call["decision"] == "SELL" and call["plan"]["max_hold_hours"] > 0


def test_plan_carries_flat_by(history):
    ctx = ctx_at(history, asof(history))
    plan, _ = D31.check(ctx, market_sell(ctx.price, 10.0), D31.V31(counter_run=99), {}, atr_m5=2.0)
    assert pd.Timestamp(plan["flat_by"]) == pd.Timestamp(cal.next_friday_close(ctx.as_of.to_pydatetime()))
    assert plan["flat_by"].startswith("2026-10-16 21:00")


def test_pending_order_never_valid_past_flat_by(history):
    t = pd.Timestamp("2026-10-16T16:00:00Z")                         # Friday, five hours before the close
    ctx = ctx_at(history, t)
    px = ctx.price
    setup = {"direction": "SELL", "entry_type": "limit", "entry": px + 2, "stop": px + 12, "tp1": px - 14, "tp2": px - 30,
             "valid_hours": 12, "why": "x"}
    plan, why = D31.check(ctx, setup, D31.V31(counter_run=99), {}, atr_m5=2.0)
    assert why is None and pd.Timestamp(plan["valid_until"]) == pd.Timestamp(plan["flat_by"])


def test_card_shows_risk_at_minimum_lot(history):
    t = asof(history)
    call = decide31(history, t, fake31(history, t, stop_gap=12.5))
    text = D31.card(call)
    dist = abs(call["plan"]["entry"] - call["plan"]["stop"])
    assert f"Stop distance {dist:.2f}" in text and f"At 0.01 lot: risk ${dist:.2f}" in text
    assert "v3.1 SELL" in text.splitlines()[0] and "Woken by: level_break" in text


def test_post_event_block_and_no_fade_still_apply(history):
    t = asof(history)
    cpi = {"time": (t - pd.Timedelta(hours=1)).to_pydatetime(), "name": "US CPI", "impact": "high"}
    call = decide31(history, t, fake31(history, t), events=[cpi])
    assert call["decision"] == "PASS" and "after US CPI" in call["reason"]
    ctx = ctx_at(history, t)
    st = {"short_sequence": {"timeframe": "M5", "rising_lows": 2, "falling_highs": 0, "lows": [1, 2, 3], "highs": []}}
    plan, why = D31.check(ctx, market_sell(ctx.price, 10.0), D31.V31(), st, atr_m5=2.0)
    assert plan is None and "lows have risen" in why


def test_liquidity_reads_new_york_hours(history):
    t = pd.Timestamp("2026-10-16T20:30:00Z")                         # Fri 16:30 New York: v3's window was already shut
    call = decide31(history, t)
    assert call["reports"]["liquidity"]["facts"]["market"] == "open"


# ---------------- Task 5: move memory and trend read in the chart agent ----------------
def chart_call(llm):
    return next(c for c in llm.calls if c["agent"] == "chart")


def test_chart_prompt_has_move_and_no_news(history):
    t = asof(history)
    llm = fake31(history, t)
    call = decide31(history, t, llm)
    c = chart_call(llm)
    assert "MOVE:" in c["user"] and '"legs"' in c["user"] and '"started_at"' in c["user"]
    assert call["reports"]["chart"]["facts"]["move"]["direction"] in ("up", "down", "none")
    assert "Gold slides" not in c["user"]                                  # the chart agent never sees a headline
    text = c["system"] + c["user"]
    assert "$5" not in text and "$" not in c["system"] and "quick trades" not in text
    assert "rising M5 lows" in c["system"] and "high-impact release" in c["system"] and "squeeze" in c["system"]
    assert "max_hold_hours" in c["system"] and "day_type" in c["system"]


def test_chart_reply_keeps_day_type(history):
    t = asof(history)
    call = decide31(history, t, fake31(history, t, day_type="Trending", day_direction="down", hold="soon"))
    f = call["reports"]["chart"]["facts"]
    assert (f["day_type"], f["day_direction"]) == ("trending", "down")
    assert call["plan"]["max_hold_hours"] == D31.V31().default_hold_hours     # "soon" went through normal_hold
    f = decide31(history, t, fake31(history, t, hold=2.0))["reports"]["chart"]["facts"]
    assert (f["day_type"], f["day_direction"]) == ("unclear", "unclear")
    assert decide31(history, t, fake31(history, t, hold=2.0))["plan"]["max_hold_hours"] == 2.0


def test_chart_sees_its_own_calls_on_the_move_and_never_the_rules_ones(history):
    t = asof(history)
    px = price_at(history, t)
    llm = fake31(history, t)
    decide31(history, t, llm, prior_entries=[open_entry(t, "llm", "BUY", px, 40), open_entry(t, "rules", "SELL", px, 20)])
    import json as _json
    move = _json.loads(chart_call(llm)["user"].split("MOVE:\n", 1)[1].split("\n\nSTRUCTURE:", 1)[0])
    assert [o["direction"] for o in move["open"]] == ["BUY"]
