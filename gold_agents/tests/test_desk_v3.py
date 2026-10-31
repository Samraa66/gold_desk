import json

import pandas as pd
import pytest

from gold_agents import desk_v2 as V2
from gold_agents import desk_v3 as V3
from gold_agents import journal as J
from gold_agents import live_data as D
from gold_agents import news as N
from gold_agents import structure as S
from gold_agents import watcher as W
from gold_agents.config import Config
from gold_agents.llm import FakeLLM
from tests.conftest import make_m1

T = pd.Timestamp("2026-10-14T15:01:00Z")      # a Wednesday, London + New York


def m5(rows, end="2026-10-14T15:00:00Z"):
    """Closed M5 bars ending with the bar stamped `end`. rows = (open, high, low, close)."""
    idx = pd.date_range(end=end, periods=len(rows), freq="5min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=1000)


def flat(n=60, px=4000.0, w=2.0):
    return [(px, px + w, px - w, px)] * n


# ---------------- levels ----------------
def test_key_levels_take_the_prior_day_and_leave_out_the_last_bar():
    b = m5(flat(300), end="2026-10-14T15:00:00Z")
    b.loc["2026-10-13T16:00:00Z", "high"] = 4050.0
    b.loc["2026-10-13T16:00:00Z", "low"] = 3950.0
    b.iloc[-1, b.columns.get_loc("high")] = 4100.0
    lv = {x["name"]: x["price"] for x in S.key_levels(b)}
    assert lv["prior_day_high"] == 4050.0 and lv["prior_day_low"] == 3950.0
    assert lv["today_high"] == 4002.0                     # the bar being judged is not its own level


def test_key_levels_include_the_round_numbers_around_price():
    lv = {x["name"]: x["price"] for x in S.key_levels(m5(flat(300, px=3912.0)))}
    assert lv["round_above"] == 3950.0 and lv["round_below"] == 3900.0


def test_equal_lows_are_a_stop_pool():
    sw = [{"kind": "L", "price": 3990.0, "time": 1}, {"kind": "L", "price": 3990.4, "time": 2},
          {"kind": "L", "price": 3970.0, "time": 3}, {"kind": "H", "price": 4010.0, "time": 4}]
    assert S.equal_levels(sw, tol=1.0) == [{"kind": "equal_lows", "price": 3990.2, "touches": 2}]


# ---------------- watcher ----------------
def test_a_quiet_market_triggers_nothing():
    assert W.triggers(m5(flat())) == []


def test_a_close_under_the_recent_range_is_a_sell_trigger():
    t = W.triggers(m5(flat() + [(4000, 4000.5, 3985, 3987)]))
    assert any(x["kind"] == "range_break" and x["direction"] == "SELL" for x in t)


def test_a_close_over_the_recent_range_is_a_buy_trigger():
    t = W.triggers(m5(flat() + [(4000, 4014, 3999.5, 4012)]))
    assert any(x["kind"] == "range_break" and x["direction"] == "BUY" for x in t)


def test_an_oversized_bar_is_a_spike_even_when_it_closes_inside_the_range():
    rows = flat()
    rows[20] = (4000, 4030, 3970, 4000)
    t = W.triggers(m5(rows + [(4000, 4018, 3998, 4001)]))
    assert [x["kind"] for x in t] == ["spike"]


def test_a_wick_through_a_level_that_closes_back_is_a_sweep_against_it():
    t = W.triggers(m5(flat() + [(4000, 4012, 3999, 4000.5)]), levels=[{"name": "prior_day_high", "price": 4010.0}])
    s = [x for x in t if x["kind"] == "sweep"]
    assert s and s[0]["direction"] == "SELL" and s[0]["level"] == 4010.0


def test_a_close_through_a_named_level_is_a_level_break():
    rows = flat() + [(4000, 4001, 3992, 3994)]
    t = W.triggers(m5(rows), levels=[{"name": "asia_low", "price": 3996.0}])
    assert any(x["kind"] == "level_break" and x["direction"] == "SELL" and x["level"] == 3996.0 for x in t)


def test_a_tiny_poke_through_a_level_is_not_a_break():
    t = W.triggers(m5(flat() + [(3996.5, 3997, 3995.5, 3995.8)]), levels=[{"name": "asia_low", "price": 3996.0}])
    assert not [x for x in t if x["kind"] == "level_break"]


def test_a_tiny_wick_through_a_level_is_not_a_sweep():
    t = W.triggers(m5(flat() + [(4000, 4010.2, 3999, 4000.5)]), levels=[{"name": "prior_day_high", "price": 4010.0}])
    assert not [x for x in t if x["kind"] == "sweep"]


def test_the_same_trigger_cools_down():
    trig = [{"kind": "range_break", "direction": "SELL"}]
    state = {}
    assert W.should_wake(trig, state, T)[0]
    W.record_wake(trig, state, T)
    assert not W.should_wake(trig, state, T + pd.Timedelta(minutes=5))[0]
    assert W.should_wake(trig, state, T + pd.Timedelta(minutes=31))[0]


def test_the_other_direction_is_not_cooled_down():
    state = {}
    W.record_wake([{"kind": "range_break", "direction": "SELL"}], state, T)
    assert W.should_wake([{"kind": "range_break", "direction": "BUY"}], state, T)[0]


def test_the_daily_budget_stops_model_wakes():
    state = {"day": "2026-10-14", "wakes": W.WATCH.max_wakes_day, "last": {}}
    ok, why = W.should_wake([{"kind": "spike", "direction": None}], state, T)
    assert not ok and "budget" in why


def test_the_budget_resets_on_a_new_day():
    state = {"day": "2026-10-13", "wakes": W.WATCH.max_wakes_day, "last": {}}
    assert W.should_wake([{"kind": "spike", "direction": None}], state, T)[0]


def test_a_slot_wakes_the_desk_with_no_trigger_once():
    assert W.slot_due(pd.Timestamp("2026-10-14T14:01:00Z"))
    assert not W.slot_due(pd.Timestamp("2026-10-14T14:06:00Z"))
    assert not W.slot_due(pd.Timestamp("2026-10-14T15:01:00Z"))


# ---------------- news and calendar ----------------
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Gold slides as yields jump - Reuters</title><pubDate>Wed, 14 Oct 2026 14:30:00 GMT</pubDate><source>Reuters</source></item>
<item><title>Gold slides as yields jump - Reuters</title><pubDate>Wed, 14 Oct 2026 14:20:00 GMT</pubDate><source>Reuters</source></item>
<item><title>Old story - CNBC</title><pubDate>Mon, 12 Oct 2026 14:30:00 GMT</pubDate><source>CNBC</source></item>
<item><title>Tomorrow's story - CNBC</title><pubDate>Thu, 15 Oct 2026 14:30:00 GMT</pubDate><source>CNBC</source></item>
<item><title>No date</title></item>
</channel></rss>"""


def test_headlines_after_the_as_of_time_never_reach_the_desk():
    h = N.parse_rss(RSS, T, hours=12)
    assert [x["title"] for x in h] == ["Gold slides as yields jump - Reuters"]
    assert h[0]["source"] == "Reuters" and h[0]["age_min"] == 31


def test_a_broken_feed_gives_no_headlines_not_a_crash():
    assert N.parse_rss("<rss><unclosed>", T) == []


FF = [{"title": "CPI m/m", "country": "USD", "date": "2026-10-15T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
      {"title": "Crude Oil Inventories", "country": "USD", "date": "2026-10-15T10:30:00-04:00", "impact": "Low"},
      {"title": "ECB Press Conference", "country": "EUR", "date": "2026-10-15T08:45:00-04:00", "impact": "High"}]


def test_the_calendar_keeps_high_impact_us_events_in_utc():
    assert N.parse_calendar(FF) == [{"time_utc": "2026-10-15T12:30:00Z", "name": "CPI m/m", "impact": "high"}]


def test_writing_events_keeps_earlier_rows_and_adds_new_ones(tmp_path):
    p = tmp_path / "events.csv"
    p.write_text("time_utc,name,impact\n2026-10-01T12:30:00Z,PPI m/m,high\n")
    N.write_events(N.parse_calendar(FF), p)
    N.write_events(N.parse_calendar(FF), p)
    rows = p.read_text().strip().splitlines()
    assert len(rows) == 3 and "PPI" in rows[1] and "CPI" in rows[2]


def test_a_written_events_file_blocks_the_release():
    from gold_agents import calendar as cal
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "events.csv"
        N.write_events(N.parse_calendar(FF), p)
        ev = cal.blocking_event(pd.Timestamp("2026-10-15T12:40:00Z").to_pydatetime(), 30, 30, cal.file_events(p))
    assert ev["name"] == "CPI m/m"


# ---------------- live data ----------------
def candles(closes, end="2026-10-14T15:00:00Z"):
    idx = pd.date_range(end=end, periods=len(closes), freq="5min", tz="UTC")
    return [{"complete": True, "time": t.isoformat(), "volume": 100 + i,
             "mid": {"o": str(c), "h": str(c + 1), "l": str(c - 1), "c": str(c)}} for i, (t, c) in enumerate(zip(idx, closes))]


def test_parse_m5_drops_the_forming_candle():
    rows = candles([1.0, 2.0, 3.0])
    rows[-1]["complete"] = False
    b = D.parse_m5({"candles": rows})
    assert len(b) == 2 and b["close"].iloc[-1] == 2.0 and b["volume"].iloc[-1] == 101


def test_changes_over_one_and_four_hours():
    b = D.parse_m5({"candles": candles([100.0] * 40 + [110.0] * 12 + [121.0])})
    c = D.changes(b)
    assert c["chg_1h_pct"] == pytest.approx(10.0)
    assert c["chg_4h_pct"] == pytest.approx(21.0)


def test_book_shows_the_biggest_clusters_each_side_of_price():
    book = {"orderBook": {"price": "4000", "time": "t", "buckets": [
        {"price": "3980", "longCountPercent": "0.5", "shortCountPercent": "0.1"},
        {"price": "3990", "longCountPercent": "2.0", "shortCountPercent": "0.1"},
        {"price": "4010", "longCountPercent": "0.1", "shortCountPercent": "3.0"},
        {"price": "4900", "longCountPercent": "9.0", "shortCountPercent": "9.0"}]}}
    s = D.parse_book(book, 4000.0, width=50.0)
    assert s["above"][0]["price"] == 4010.0 and s["below"][0]["price"] == 3990.0
    assert all(x["price"] < 4100 for x in s["above"])


def test_position_book_totals_who_is_long_and_short():
    book = {"positionBook": {"time": "t", "buckets": [
        {"price": "3990", "longCountPercent": "30", "shortCountPercent": "10"},
        {"price": "4010", "longCountPercent": "40", "shortCountPercent": "20"}]}}
    assert D.parse_positions(book)["long_pct"] == 70.0


def test_volume_ratio_compares_the_last_bars_with_their_normal():
    b = D.parse_m5({"candles": candles([1.0] * 60)})
    b["volume"] = [100] * 57 + [300] * 3
    assert D.volume_ratio(b) == pytest.approx(3.0)


# ---------------- the desk: identity ----------------
def test_v3_has_its_own_hash_and_leaves_v2_alone():
    cfg = V3.config()
    assert V3.v3_hash(cfg) != V2.v2_hash(Config())
    assert V3.v3_hash(cfg) != V3.v3_hash(cfg, V3.V3(min_rr=2.0))
    assert V2.v2_hash(Config()) == "80b98c11"


def test_v3_logs_apart_from_v2():
    assert V3.JOURNAL.name == "calls_v3.jsonl" and V3.DASHBOARD.name == "dashboard_v3.html"


def test_v3_sizes_for_the_1000_dollar_demo():
    cfg = V3.config()
    assert cfg.equity == 1000.0 and cfg.max_stop == 15.0 and cfg.expiry_hours == 6.0


# ---------------- the desk: today's miss ----------------
@pytest.fixture(scope="module")
def history():
    return make_m1(start="2026-06-01", days=136, seed=5, vol=0.25)


def asof(hist):
    return hist.index[hist.index.dayofweek == 2][-1000]


def sell_trigger(price):
    return {"kind": "level_break", "direction": "SELL", "level": price, "name": "asia_low"}


def test_rules_trade_a_breakdown_with_no_zone_under_it_using_an_atr_target(history):
    from gold_agents.context import build_context
    t = asof(history)
    ctx = build_context(history, t, V3.config())
    s = V3.rules_setup(ctx, {"h1_pattern": {"bias": -1}}, sell_trigger(ctx.price + 1), V3.V3(), atr_m5=6.0)
    assert s["direction"] == "SELL" and s["entry_type"] == "market"
    assert s["stop"] > ctx.price and s["tp1"] < ctx.price
    assert (ctx.price - s["tp1"]) / (s["stop"] - ctx.price) == pytest.approx(1.5)


def test_rules_do_not_trade_a_break_against_the_h1_structure(history):
    from gold_agents.context import build_context
    ctx = build_context(history, asof(history), V3.config())
    s = V3.rules_setup(ctx, {"h1_pattern": {"bias": 1}}, sell_trigger(ctx.price), V3.V3(), atr_m5=6.0)
    assert s["entry_type"] == "none"


def test_rules_take_no_trade_without_a_directional_trigger(history):
    from gold_agents.context import build_context
    ctx = build_context(history, asof(history), V3.config())
    assert V3.rules_setup(ctx, {"h1_pattern": {"bias": 1}}, None, V3.V3(), atr_m5=6.0)["entry_type"] == "none"


# ---------------- the desk: a model decision ----------------
LIVE = {"cross": {"USD_JPY": {"chg_1h_pct": 0.4, "chg_4h_pct": 0.9}}, "book": {"above": [], "below": []},
        "positions": {"long_pct": 70.0}, "volume_ratio": 2.4,
        "news": [{"title": "Gold slides as yields jump", "source": "Reuters", "age_min": 12, "published": "x"}]}


def fake(history, t, conf=0.55, stop_gap=8.0, decision="PLACE"):
    px = float(history.loc[:t - pd.Timedelta(minutes=1), "close"].iloc[-1])
    return FakeLLM({
        "Chart trader": {"bias": -0.6, "confidence": 0.6, "read": "breakdown", "setup": {
            "direction": "SELL", "entry_type": "market", "entry": None, "stop": px + stop_gap, "tp1": px - 1.5 * stop_gap - 1,
            "tp2": px - 3 * stop_gap, "valid_hours": 1, "why": "broke the Asia low"}},
        "Cross-asset analyst": {"score": -0.3, "confidence": 0.5, "summary": "dollar firm"},
        "News analyst": {"score": -0.4, "confidence": 0.6, "summary": "yields driving gold down", "driver": "yields", "risk_flag": False},
        "Master trader": {"decision": decision, "confidence": conf, "reason": "clean break"}})


def decide(history, t, llm=None, **kw):
    return V3.decide_at(history, t, V3.config(), llm=llm, events=[], macro_df=None, live=LIVE,
                        trigger=sell_trigger(1.0), v3=kw.pop("v3", V3.V3(counter_run=99)), **kw)


def test_the_desk_calls_the_breakdown_at_v3s_own_confidence_bar(history):
    t = asof(history)
    call = decide(history, t, fake(history, t))
    assert call["decision"] == "SELL" and call["desk"] == "v3" and call["plan"]["entry_type"] == "market"
    assert call["trigger"]["kind"] == "level_break"


def test_a_low_confidence_master_still_passes_and_the_setup_is_scored(history):
    t = asof(history)
    call = decide(history, t, fake(history, t, conf=0.45))
    assert call["decision"] == "PASS" and call["baselines"]["chart_setup"]["plan"]["direction"] == "SELL"


def test_the_model_sees_the_m5_candles_and_the_trigger(history):
    t = asof(history)
    llm = fake(history, t)
    decide(history, t, llm)
    user = next(c for c in llm.calls if c["agent"] == "chart")["user"]
    assert "M5 last" in user and "level_break" in user and "key_levels" in user


def test_the_chart_agent_never_sees_the_news(history):
    t = asof(history)
    llm = fake(history, t)
    decide(history, t, llm)
    assert "Gold slides" not in next(c for c in llm.calls if c["agent"] == "chart")["user"]


def test_the_news_agent_reads_the_headlines(history):
    t = asof(history)
    llm = fake(history, t)
    call = decide(history, t, llm)
    assert "Gold slides" in next(c for c in llm.calls if c["agent"] == "news")["user"]
    assert call["reports"]["news"]["summary"] == "yields driving gold down"


def test_the_master_sees_news_and_cross_assets(history):
    t = asof(history)
    llm = fake(history, t)
    decide(history, t, llm)
    user = next(c for c in llm.calls if c["agent"] == "master")["user"]
    assert "yields driving gold down" in user and "dollar firm" in user and "long_pct" in user


def test_no_headlines_means_the_news_agent_abstains_without_a_model_call(history):
    t = asof(history)
    llm = fake(history, t)
    V3.decide_at(history, t, V3.config(), llm=llm, events=[], live={**LIVE, "news": []}, trigger=sell_trigger(1.0), v3=V3.V3(counter_run=99))
    assert not [c for c in llm.calls if c["agent"] == "news"]


def test_a_stop_inside_m5_noise_is_refused_and_still_scored(history):
    t = asof(history)
    call = decide(history, t, fake(history, t, stop_gap=5.0), v3=V3.V3(counter_run=99, min_stop_atr_m5=99.0))
    assert call["decision"] == "PASS" and "M5" in call["reason"]
    assert call["baselines"]["rejected_setup"]["rejected_because"]


def test_a_decision_does_not_change_when_future_bars_are_added(history):
    t = asof(history)
    a = decide(history.loc[:t], t)
    b = decide(history, t)
    assert (a["decision"], a["reason"], a["baselines"]) == (b["decision"], b["reason"], b["baselines"])


def test_card_says_v3(history):
    t = asof(history)
    assert "v3" in V3.card(decide(history, t, fake(history, t))).splitlines()[0]


# ---------------- honest fills ----------------
def test_a_call_is_scored_from_when_the_model_finished_not_when_the_trigger_fired():
    idx = pd.date_range("2026-10-14T15:00:00Z", periods=4, freq="min", tz="UTC")
    b = pd.DataFrame({"open": [4000.0, 4000, 3990, 3990], "high": [4000.5, 4000.5, 3990.5, 3990.5], "low": [3999.5, 3989, 3989, 3989],
                      "close": [4000.0, 3990, 3990, 3990], "spread": 0.2}, index=idx)
    plan = {"direction": "SELL", "entry_type": "market", "entry": 4000.0, "stop": 4010.0, "tp1": 3990.0, "tp2": 3980.0}
    e = {"id": "x", "as_of": str(idx[0]), "decision": "SELL", "plan": plan, "fill_from": str(idx[2]), "price": 4000.0}
    s = J.score_entries([e], b, Config(), idx[-1] + pd.Timedelta(minutes=1))[0]["scores"]["master"]
    assert s["fill"] == pytest.approx(3989.7)        # the 3,990 bar, not the 4,000 one


def test_an_old_call_without_fill_from_scores_as_before():
    idx = pd.date_range("2026-10-14T15:00:00Z", periods=2, freq="min", tz="UTC")
    b = pd.DataFrame({"open": [4000.0, 4000], "high": [4000.5, 4000.5], "low": [3999.5, 3999.5], "close": [4000.0, 4000], "spread": 0.2}, index=idx)
    plan = {"direction": "SELL", "entry_type": "market", "entry": 4000.0, "stop": 4010.0, "tp1": 3990.0, "tp2": 3980.0}
    e = {"id": "x", "as_of": str(idx[0]), "decision": "SELL", "plan": plan, "price": 4000.0}
    assert J.score_entries([e], b, Config(), idx[-1] + pd.Timedelta(minutes=1))[0]["scores"]["master"]["fill"] == pytest.approx(3999.7)


# ---------------- the day's summary ----------------
def test_the_day_summary_counts_calls_and_shadow_setups():
    scored = [{"as_of": "2026-10-14T10:01:00+00:00", "mode": "llm", "decision": "SELL",
               "scores": {"master": {"outcome": "win", "r": 1.4}, "chart_setup": {"outcome": "win", "r": 1.4}}},
              {"as_of": "2026-10-14T12:01:00+00:00", "mode": "llm", "decision": "PASS",
               "scores": {"chart_setup": {"outcome": "loss", "r": -1.1}}},
              {"as_of": "2026-10-14T12:01:00+00:00", "mode": "rules", "decision": "PASS", "scores": {}},
              {"as_of": "2026-10-13T12:01:00+00:00", "mode": "llm", "decision": "PASS", "scores": {}}]
    text = V3.day_text(scored, "2026-10-14", wakes=5)
    assert "5 wakes" in text and "1 calls" in text and "+1.40R" in text and "+0.30R" in text


# ---------------- the tick ----------------
class Book:
    """Records what the tick did instead of calling OANDA, Anthropic or Telegram."""
    def __init__(self, bars):
        self.bars, self.woke, self.sent = bars, [], []

    def fetch(self):
        return self.bars

    def wake(self, trigger, now):
        self.woke.append(trigger)
        return []


def test_a_tick_with_nothing_happening_wakes_nothing(tmp_path):
    b = Book(m5(flat()))
    out = W.tick(T, b.fetch, b.wake, tmp_path / "state.json", tmp_path / "watch.jsonl")
    assert out == "quiet" and not b.woke


def test_a_tick_on_a_break_wakes_the_desk_and_logs_the_trigger(tmp_path):
    b = Book(m5(flat() + [(4000, 4000.5, 3985, 3987)]))
    log = tmp_path / "watch.jsonl"
    W.tick(T, b.fetch, b.wake, tmp_path / "state.json", log)
    assert b.woke[0]["direction"] == "SELL"
    assert json.loads(log.read_text().splitlines()[0])["woke"] is True


def test_a_second_tick_on_the_same_move_is_cooled_down_but_still_logged(tmp_path):
    b = Book(m5(flat() + [(4000, 4000.5, 3985, 3987)]))
    log = tmp_path / "watch.jsonl"
    W.tick(T, b.fetch, b.wake, tmp_path / "state.json", log)
    W.tick(T + pd.Timedelta(minutes=5), b.fetch, b.wake, tmp_path / "state.json", log)
    assert len(b.woke) == 1 and len(log.read_text().splitlines()) == 2


def test_a_tick_does_nothing_while_the_market_is_shut(tmp_path):
    b = Book(m5(flat() + [(4000, 4000.5, 3985, 3987)]))
    assert W.tick(pd.Timestamp("2026-10-17T15:01:00Z"), b.fetch, b.wake, tmp_path / "s.json", tmp_path / "w.jsonl") == "market shut"
    assert not b.woke


def test_a_tick_in_thin_asia_hours_does_not_spend_a_wake(tmp_path):
    b = Book(m5(flat() + [(4000, 4000.5, 3985, 3987)], end="2026-10-14T03:00:00Z"))
    out = W.tick(pd.Timestamp("2026-10-14T03:01:00Z"), b.fetch, b.wake, tmp_path / "s.json", tmp_path / "w.jsonl")
    assert out == "thin hours" and not b.woke


def test_a_slot_tick_wakes_the_desk_with_no_trigger(tmp_path):
    b = Book(m5(flat()))
    W.tick(pd.Timestamp("2026-10-14T14:01:00Z"), b.fetch, b.wake, tmp_path / "s.json", tmp_path / "w.jsonl")
    assert b.woke == [None]


# ---------------- one wake ----------------
def test_a_wake_logs_model_and_rules_on_one_time_with_one_fill_time(history, tmp_path):
    from gold_agents.__main__ import v3_wake
    t = asof(history)
    log, sent = tmp_path / "calls_v3.jsonl", []
    done = t + pd.Timedelta(seconds=75)
    v3_wake(sell_trigger(1.0), t, fake(history, t), history, None, LIVE, log, sent.append, clock=lambda: done)
    a, b = J.load(log)
    assert {a["mode"], b["mode"]} == {"llm", "rules"} and a["as_of"] == b["as_of"]
    assert a["fill_from"] == b["fill_from"] == str(t + pd.Timedelta(minutes=2))


def test_a_wake_sends_the_model_call_and_not_the_rules_one(history, tmp_path):
    from gold_agents.__main__ import v3_wake
    t = asof(history)
    sent = []
    v3_wake(sell_trigger(1.0), t, fake(history, t), history, None, LIVE, tmp_path / "c.jsonl", sent.append, clock=lambda: t, v3=V3.V3(counter_run=99))
    assert len(sent) == 1 and "v3 SELL" in sent[0]


def test_a_pass_sends_nothing(history, tmp_path):
    from gold_agents.__main__ import v3_wake
    t = asof(history)
    sent = []
    v3_wake(None, t, fake(history, t, decision="PASS"), history, None, LIVE, tmp_path / "c.jsonl", sent.append, clock=lambda: t, v3=V3.V3(counter_run=99))
    assert sent == []


def test_a_repeated_wake_logs_nothing_new(history, tmp_path):
    from gold_agents.__main__ import v3_wake
    t = asof(history)
    log = tmp_path / "c.jsonl"
    for _ in range(2):
        v3_wake(None, t, fake(history, t), history, None, LIVE, log, lambda x: None, clock=lambda: t)
    assert len(J.load(log)) == 2


def test_v3_commands_parse():
    from gold_agents.__main__ import main
    with pytest.raises(SystemExit) as e:
        main(["--desk", "v3", "watch", "--help"])
    assert e.value.code == 0
