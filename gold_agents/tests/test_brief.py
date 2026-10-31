"""Desk v3.1's daily brief. Offline: a fake model, synthetic bars, no Telegram."""
import json

import pandas as pd
import pytest

from gold_agents import brief as B
from gold_agents import desk_v31 as D31
from gold_agents.llm import FakeLLM
from tests.conftest import make_m1

TUE_0201_NY = pd.Timestamp("2026-11-03T07:01:00Z")        # 02:01 New York (EST)
REPLY = {"drivers": ["Real yields up 6bp", "Dollar firm into CPI"], "trend": "Down day: lower highs on H1.",
         "levels": [{"price": 3980.0, "why": "prior day low"}], "risks": ["US CPI 13:30 UTC"], "summary": "Sellers in control."}


def test_due_before_london_once():
    assert B.due(TUE_0201_NY, None, [])
    assert B.reason(TUE_0201_NY, None, []) == "london"
    assert not B.due(TUE_0201_NY - pd.Timedelta(minutes=10), None, [])            # 01:51 New York: not yet
    done = {"at": TUE_0201_NY.isoformat()}
    assert not B.due(TUE_0201_NY + pd.Timedelta(minutes=5), done, [])               # once a day
    yesterday = {"at": (TUE_0201_NY - pd.Timedelta(days=1)).isoformat()}
    assert B.due(TUE_0201_NY, yesterday, [])
    assert not B.due(pd.Timestamp("2026-11-07T07:01:00Z"), None, [])                # Saturday
    assert B.due(pd.Timestamp("2026-10-27T06:01:00Z"), None, [])                    # 02:01 New York in EDT is 06:01 UTC


def test_due_after_a_listed_release():
    cpi = {"time": pd.Timestamp("2026-11-03T13:30:00Z").to_pydatetime(), "name": "CPI m/m", "impact": "high"}
    morning = {"at": TUE_0201_NY.isoformat()}
    assert B.reason(pd.Timestamp("2026-11-03T13:31:00Z"), morning, [cpi]) == "release: CPI m/m"
    assert not B.due(pd.Timestamp("2026-11-03T13:26:00Z"), morning, [cpi])          # before it
    assert not B.due(pd.Timestamp("2026-11-03T13:36:00Z"), {"at": "2026-11-03T13:31:00+00:00"}, [cpi])   # already written
    assert not B.due(pd.Timestamp("2026-11-03T16:00:00Z"), morning, [cpi])          # too long after: no stale brief
    medium = {**cpi, "impact": "medium", "name": "Retail Sales m/m"}
    assert B.due(pd.Timestamp("2026-11-03T13:31:00Z"), morning, [medium])
    assert not B.due(pd.Timestamp("2026-11-03T13:31:00Z"), morning, [{**cpi, "impact": "low"}])


def test_brief_ends_with_call_or_pass():
    b = B.write(TUE_0201_NY, {"why": "london", "open_call": None}, FakeLLM(default=REPLY))
    assert b["text"].splitlines()[-1] == "Desk: PASS" and B.telegram(b, None).splitlines()[-1] == "Desk: PASS"
    assert set(("at", "drivers", "trend", "levels", "risks", "text")) <= set(b)
    call = {"decision": "SELL", "as_of": "2026-11-03T06:40:00+00:00",
            "plan": {"entry_type": "limit", "entry": 4015.0, "stop": 4030.0, "tp1": 3990.0}}
    assert B.telegram(b, call).splitlines()[-1] == "Desk: SELL LIMIT 4015.00, SL 4030.00, TP1 3990.00 (called 06:40 UTC)"


def test_brief_has_no_prices_to_trade():
    bad = {**REPLY, "entry": 4015, "stop": 4030, "tp1": 3990, "levels": [{"price": 3980.0, "why": "low", "target": 3950}],
           "setup": {"tp": 3900, "note": "x"}}
    b = B.write(TUE_0201_NY, {"why": "london"}, FakeLLM(default=bad))
    blob = json.dumps({k: v for k, v in b.items() if k != "dropped_fields"})
    for key in ('"entry"', '"stop"', '"tp1"', '"tp"', '"target"'):
        assert key not in blob, key
    assert b["dropped_fields"] == ["entry", "stop", "target", "tp", "tp1"]
    assert b["levels"] == [{"price": 3980.0, "why": "low"}]
    llm = FakeLLM(default=REPLY)
    B.write(TUE_0201_NY, {"why": "london"}, llm)
    assert "Never give an entry, a stop or a target" in llm.calls[0]["system"] and llm.calls[0]["model"] == "claude-sonnet-5-5"


@pytest.fixture(scope="module")
def history():
    return make_m1(start="2026-06-01", days=136, seed=5, vol=0.25)


def asof(hist):
    return hist.index[hist.index.dayofweek == 2][-1000]


def fake(hist, t):
    px = float(hist.loc[:t - pd.Timedelta(minutes=1), "close"].iloc[-1])
    return FakeLLM({
        "Chart trader": {"bias": -0.6, "confidence": 0.6, "read": "down", "setup": {
            "direction": "SELL", "entry_type": "market", "stop": px + 8, "tp1": px - 13, "tp2": px - 24, "valid_hours": 1,
            "max_hold_hours": 3, "why": "x"}},
        "Cross-asset analyst": {"score": -0.3, "confidence": 0.5, "summary": "dollar firm"},
        "News analyst": {"score": -0.4, "confidence": 0.6, "summary": "yields", "driver": "yields", "risk_flag": False},
        "Master trader": {"decision": "PLACE", "confidence": 0.6, "reason": "clean"}})


LIVE = {"cross": {}, "book": "unavailable", "positions": "unavailable", "volume_ratio": None,
        "news": [{"title": "Gold slides as yields jump", "source": "Reuters", "age_min": 12, "published": "x"}]}
BRIEF = {"at": "2026-10-14T06:01:00+00:00", "drivers": ["BRIEFMARKER real yields"], "trend": "down", "levels": [], "risks": [],
         "text": "BRIEFMARKER"}


def decide(hist, t, llm):
    return D31.decide_at(hist, t, D31.config(), llm=llm, events=[], live=LIVE, trigger=None, brief=BRIEF, v31=D31.V31(counter_run=99))


def test_chart_never_gets_the_brief(history):
    t = asof(history)
    llm = fake(history, t)
    decide(history, t, llm)
    chart = next(c for c in llm.calls if c["agent"] == "chart")
    assert "BRIEFMARKER" not in chart["user"] + chart["system"]


def test_master_news_macro_get_the_brief(history):
    t = asof(history)
    llm = fake(history, t)
    decide(history, t, llm)
    for agent in ("master", "news", "macro"):
        assert "BRIEFMARKER real yields" in next(c for c in llm.calls if c["agent"] == agent)["user"], agent


def test_no_model_means_no_brief(tmp_path):
    sent = []
    assert B.write(TUE_0201_NY, {"why": "london"}, None) is None
    out = B.step(TUE_0201_NY, None, lambda: pytest.fail("no facts are fetched without a model"), [], tmp_path / "brief.jsonl", sent.append)
    assert out is None and sent == [] and not (tmp_path / "brief.jsonl").exists()


def test_step_writes_stores_and_sends_once(tmp_path):
    sent, path = [], tmp_path / "brief_v31.jsonl"
    b = B.step(TUE_0201_NY, FakeLLM(default=REPLY), lambda: {"open_call": None}, [], path, sent.append)
    assert b["why"] == "london" and B.latest(path)["at"] == TUE_0201_NY.isoformat() and len(sent) == 1
    assert B.step(TUE_0201_NY + pd.Timedelta(minutes=5), FakeLLM(default=REPLY), dict, [], path, sent.append) is None
    assert len(sent) == 1


def test_brief_facts_come_from_closed_bars_and_name_the_open_call(history):
    t = asof(history)
    f = D31.brief_facts_at(history, t, D31.config(), LIVE, [], events=[])
    assert f["open_call"] is None and f["move"]["direction"] in ("up", "down", "none") and f["key_levels"]
    assert f["real_yield"] == "unavailable" and f["headlines"][0]["title"] == "Gold slides as yields jump"
    later = D31.brief_facts_at(pd.concat([history.loc[:t], history.loc[t + pd.Timedelta(minutes=1):].iloc[:600]]), t, D31.config(), LIVE, [], events=[])
    assert later["structure"] == f["structure"] and later["move"] == f["move"]


def test_only_a_recent_brief_reaches_the_desk(tmp_path):
    path = tmp_path / "brief_v31.jsonl"
    path.write_text(json.dumps(BRIEF) + "\n")
    assert D31.current_brief(pd.Timestamp("2026-10-14T15:00:00Z"), path)["at"] == BRIEF["at"]
    assert D31.current_brief(pd.Timestamp("2026-10-15T07:00:00Z"), path) is None
    assert D31.current_brief(pd.Timestamp("2026-10-14T05:00:00Z"), path) is None     # never one from after the decision time
