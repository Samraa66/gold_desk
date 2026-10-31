"""Desk v3.1 news: relevance filter, freshness, the poll as a trigger, and the inputs it feeds. Offline."""
from pathlib import Path

import pandas as pd
import pytest

from gold_agents import calendar as cal
from gold_agents import news_v31 as N
from gold_agents import watcher as W
from gold_agents.llm import FakeLLM

T = pd.Timestamp("2026-11-03T14:31:00Z")          # a Tuesday, New York morning
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def test_relevant_keeps_drivers_drops_junk():
    for keep in ("Gold falls to one-year low", "Fed holds rates", "Dollar jumps as yields rise",
                 "BOJ signals hike as yen slides", "US CPI hotter than forecast"):
        assert N.relevant(keep), keep
    for drop in ("Cartier Files on SEDAR+", "Cartier Resources Files Technical Report for Gold Project on SEDAR+",
                 "Gold Price November 2 2026 - Robinhood", "Gold rate in Chennai today", "Miner intersects 12 g/t gold at depth",
                 "Celebrity wedding photos", ""):
        assert not N.relevant(drop), drop


def head(title, age, source="Reuters"):
    return {"title": f"{title} - {source}", "source": source, "published": str(T - pd.Timedelta(minutes=age)), "age_min": age}


def test_fresh_ignores_seen_and_old():
    heads = [head("Gold falls to one-year low", 3), head("Fed holds rates", 45), head("Dollar jumps as yields rise", 10),
             head("Gold falls to one-year low", 5, "CNBC"), head("Gold Price November 2 2026", 1, "Robinhood")]
    seen = {N.head_id(head("Dollar jumps as yields rise", 0))}
    assert [h["title"] for h in N.fresh(heads, seen, max_age_min=30)] == ["Gold falls to one-year low - Reuters"]


def test_poll_marks_seen_once(tmp_path):
    class Session:
        def get(self, url, **kw):
            return type("R", (), {"ok": True, "text": RSS})()
    seen = tmp_path / "seen.json"
    first = N.poll(T, Session(), seen)
    assert [h["title"] for h in first] == ["Gold falls to one-year low - Reuters"]
    assert N.poll(T, Session(), seen) == []                                   # the same story never wakes the desk twice


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Gold falls to one-year low - Reuters</title><pubDate>Tue, 03 Nov 2026 14:25:00 GMT</pubDate><source>Reuters</source></item>
<item><title>Gold Price November 3 2026 - Robinhood</title><pubDate>Tue, 03 Nov 2026 14:28:00 GMT</pubDate><source>Robinhood</source></item>
<item><title>Fed holds rates - CNBC</title><pubDate>Tue, 03 Nov 2026 12:00:00 GMT</pubDate><source>CNBC</source></item>
</channel></rss>"""


class Desk:
    def __init__(self):
        self.woke = []

    def wake(self, trigger, now):
        self.woke.append(trigger)


def test_news_wake_shares_budget(tmp_path):
    state = tmp_path / "state.json"
    state.write_text('{"day": "2026-11-03", "wakes": %d, "last": {}}' % W.WATCH_V31.max_wakes_day)
    d = Desk()
    out = N.tick(T, lambda: [head("Gold falls to one-year low", 2)], d.wake, state, tmp_path / "w.jsonl")
    assert "budget" in out and d.woke == []


def test_news_wake_wakes_once(tmp_path):
    d = Desk()
    out = N.tick(T, lambda: [head("Gold falls to one-year low", 2)], d.wake, tmp_path / "s.json", tmp_path / "w.jsonl")
    assert out == "woke" and d.woke == [{"kind": "news", "direction": None, "level": None, "name": "Gold falls to one-year low - Reuters"}]


def test_news_and_tick_one_wake(tmp_path):
    """A tick wakes the desk; a headline a minute later does not wake it again. Both scripts take the same lock."""
    state, log = tmp_path / "s.json", tmp_path / "w.jsonl"
    rows = [(4000, 4002, 3998, 4000)] * 60 + [(4000, 4000.5, 3985, 3987)]
    bars = pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=pd.date_range(end="2026-11-03T14:25:00Z", periods=61, freq="5min", tz="UTC")).assign(volume=1)
    d = Desk()
    assert W.tick(T - pd.Timedelta(minutes=1), lambda: bars, d.wake, state, log, W.WATCH_V31, window=cal.desk_window,
                  thin_sleeps=False) == "woke"
    assert N.tick(T, lambda: [head("Gold falls to one-year low", 2)], d.wake, state, log) == "cooling down"
    assert len(d.woke) == 1
    assert N.tick(T + pd.Timedelta(minutes=16), lambda: [head("Fed holds rates", 2)], d.wake, state, log) == "woke"
    for script in ("watch_cycle.sh", "news_cycle.sh"):
        text = (SCRIPTS / script).read_text()
        assert "exec 9>journal/.bars.lock" in text and "flock -n 9" in text and "--desk v31" in text


def test_quiet_poll_spends_nothing(tmp_path):
    llm = FakeLLM(default={"decision": "PASS"})

    def wake(trigger, now):
        llm.complete_json(model="x", system="", user="", max_tokens=1)

    assert N.tick(T, lambda: [], wake, tmp_path / "s.json", tmp_path / "w.jsonl") == "quiet"
    assert llm.calls == [] and not (tmp_path / "w.jsonl").exists()


def test_no_poll_while_shut(tmp_path):
    polled = []
    out = N.tick(pd.Timestamp("2026-10-31T15:00:00Z"), lambda: polled.append(1) or [], Desk().wake, tmp_path / "s.json", tmp_path / "w.jsonl")
    assert out == "market shut" and polled == []


def test_systemd_news_timer_every_minute():
    timer = (SCRIPTS / "systemd" / "golddesk-news.timer").read_text()
    assert "OnCalendar=*-*-* *:*:20 UTC" in timer
    assert "news_cycle.sh" in (SCRIPTS / "systemd" / "golddesk-news.service").read_text()


def test_v31_commands_parse():
    from gold_agents.__main__ import main
    for argv in (["--desk", "v31", "watch", "--help"], ["--desk", "v31", "news-poll", "--help"], ["--desk", "v31", "run", "--help"]):
        with pytest.raises(SystemExit) as e:
            main(argv)
        assert e.value.code == 0


# ---------------- Task 8: wider inputs ----------------
from gold_agents import calendar as cal2  # noqa: E402
from gold_agents import macro_data as M  # noqa: E402

FF = [{"title": "CPI m/m", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High"},
      {"title": "Retail Sales m/m", "country": "USD", "date": "2026-11-13T08:30:00-05:00", "impact": "Medium"},
      {"title": "Crude Oil Inventories", "country": "USD", "date": "2026-11-12T10:30:00-05:00", "impact": "Low"},
      {"title": "BOJ Policy Rate", "country": "JPY", "date": "2026-11-11T22:00:00-05:00", "impact": "High"},
      {"title": "BOJ Gov Ueda Speaks", "country": "JPY", "date": "2026-11-12T01:00:00-05:00", "impact": "Medium"},
      {"title": "German ZEW Economic Sentiment", "country": "EUR", "date": "2026-11-10T05:00:00-05:00", "impact": "Medium"}]


def test_calendar_keeps_boj_and_medium_marked():
    rows = {r["name"]: r for r in N.calendar_rows(FF)}
    assert rows["CPI m/m"]["impact"] == "high" and rows["Retail Sales m/m"]["impact"] == "medium"
    assert rows["JPY BOJ Policy Rate"] == {"time_utc": "2026-11-12T03:00:00Z", "name": "JPY BOJ Policy Rate", "impact": "high"}
    assert rows["JPY BOJ Gov Ueda Speaks"]["impact"] == "medium"
    assert "Crude Oil Inventories" not in rows and not any("ZEW" in n for n in rows)      # low impact, and not a central bank
    from gold_agents import news
    assert news.parse_calendar(FF) == [{"time_utc": "2026-11-12T13:30:00Z", "name": "CPI m/m", "impact": "high"}]   # v1-v3 unchanged


def test_refresh_writes_both_lists_from_one_read(tmp_path):
    calls = []

    class Session:
        def get(self, url, **kw):
            calls.append(url)
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: FF})()

    v3, v31 = tmp_path / "events.csv", tmp_path / "events_v31.csv"
    assert N.refresh_calendars(Session(), v3, v31) == (1, 4) and len(calls) == 1
    assert [e["name"] for e in cal2.file_events(v3)] == ["CPI m/m"]
    assert {e["impact"] for e in cal2.file_events(v31)} == {"high", "medium"}


def test_only_high_impact_blocks(tmp_path):
    v31 = tmp_path / "events_v31.csv"
    from gold_agents import news
    news.write_events(N.calendar_rows(FF), v31)
    ev = cal2.file_events(v31)
    at = lambda s: pd.Timestamp(s).to_pydatetime()
    assert cal2.blocking_event(at("2026-11-13T13:40:00Z"), 30, 30, ev) is None                 # medium retail sales: shown, not blocked
    assert cal2.blocking_event(at("2026-11-12T03:10:00Z"), 30, 30, ev)["name"] == "JPY BOJ Policy Rate"


def test_sources_add_primary_feeds_and_keep_one_per_story():
    fed = """<?xml version="1.0"?><rss><channel>
<item><title>Federal Reserve issues FOMC statement</title><pubDate>Tue, 03 Nov 2026 14:29:00 GMT</pubDate></item>
</channel></rss>"""

    class Session:
        def get(self, url, **kw):
            text = fed if "federalreserve" in url else RSS
            return type("R", (), {"ok": True, "text": text})()

    heads = N.sources(T, Session())
    first = heads[0]
    assert first["title"] == "Federal Reserve issues FOMC statement" and first["source"] == "Federal Reserve" and first["primary"]
    assert sum(h["title"].startswith("Gold falls to one-year low") for h in heads) == 1
    assert [h["title"] for h in N.for_desk(heads)][:2] == ["Federal Reserve issues FOMC statement", "Gold falls to one-year low - Reuters"]
    assert N.headline_lag(N.for_desk(heads))["newest_min"] == 2 and N.headline_lag([]) == "unavailable"


def test_dead_feeds_give_unavailable_not_a_guess(tmp_path):
    class Dead:
        def get(self, *a, **kw):
            import requests
            raise requests.ConnectionError("down")

    assert N.sources(T, Dead()) == []
    assert M.real_yield(T, Dead(), cache_dir=tmp_path) == "unavailable"
    assert M.cot_gold(T, Dead(), cache_dir=tmp_path) == "unavailable"
    assert M.etf_flows(T) == "unavailable"


def test_real_yield_and_cot_carry_their_age(tmp_path):
    fred = "observation_date,DFII10\n" + "\n".join(f"2026-10-{d:02d},{1.80 + d / 100:.2f}" for d in range(20, 31)) + "\n2026-11-02,.\n"
    cot = ('[{"report_date_as_yyyy_mm_dd": "2026-10-27T00:00:00.000", "noncomm_positions_long_all": "250000", '
           '"noncomm_positions_short_all": "60000", "open_interest_all": "500000"}, '
           '{"report_date_as_yyyy_mm_dd": "2026-10-20T00:00:00.000", "noncomm_positions_long_all": "260000", '
           '"noncomm_positions_short_all": "55000", "open_interest_all": "510000"}]')

    class Session:
        def get(self, url, **kw):
            text = fred if "fred" in url else cot
            return type("R", (), {"raise_for_status": lambda self: None, "text": text})()

    ry = M.real_yield(T, Session(), cache_dir=tmp_path)
    assert ry["value_pct"] == 2.10 and ry["date"] == "2026-10-30" and ry["age_days"] == 4.6 and ry["change_5d_pp"] == 0.05
    c = M.cot_gold(T, Session(), cache_dir=tmp_path)
    assert c["noncommercial_net"] == 190000 and c["net_change_week"] == -15000 and c["report_date"] == "2026-10-27" and c["age_days"] > 7
