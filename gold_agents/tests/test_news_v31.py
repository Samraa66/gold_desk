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
