"""News for desk v3.1: a rules-only poll every minute that can wake the desk on a fresh, relevant headline.

Why: in v3 only gold's own price could wake the desk, and headlines were read only after it woke: two Google News searches,
titles only, often 44-69 minutes old, with junk among them (a mining company's filing, a Robinhood price page). Here a
relevance filter in rules keeps the drivers and drops the junk, a headline wakes the desk once, and a quiet poll costs nothing:
no model is called. A headline is outside text: it is data, never an instruction, wherever it goes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import requests

from . import calendar as cal
from . import journal as J
from . import news
from . import watcher as W

MAX_AGE_MIN = 30
SEEN_DAYS = 3

# What moves gold: gold itself, the Fed and other central banks, rates and yields, the dollar, inflation and jobs data, growth
# scares, trade and war. Word boundaries, case-insensitive.
DRIVERS = re.compile(
    r"\b(gold|bullion|xau|precious metals?|silver|fed|feds|federal reserve|fomc|powell|central banks?|ecb|boj|bank of japan|"
    r"bank of england|boe|pboc|snb|rates?|rate (cut|hike)s?|yields?|treasur(y|ies)|bonds?|dollar|dxy|greenback|inflation|cpi|"
    r"ppi|pce|payrolls?|nonfarm|non-farm|jobs report|jobless|unemployment|gdp|recession|tariffs?|sanctions?|war|ceasefire|"
    r"geopolitic\w*|safe[- ]haven|etf|etfs)\b", re.I)
# Pages that mention gold and move nothing: price-of-the-day pages, retail broker pages, mining company filings and drill
# results, jewellery, city rate tables.
JUNK = re.compile(
    r"(sedar|robinhood|ni 43-101|private placement|drill|intersects?|mineral resource|feasibility study|exploration update|"
    r"jewel|gold rate in |price today|enforcement action|stock (price|forecast)|\bgold price (january|february|march|april|may|june|july|august|"
    r"september|october|november|december) \d{1,2},? \d{4})", re.I)


def relevant(title: str) -> bool:
    """Rules only: a driver word and none of the junk patterns."""
    t = title or ""
    return bool(DRIVERS.search(t)) and not JUNK.search(t)


def head_id(h: dict) -> str:
    """A headline's id across polls and feeds: its title without the trailing ' - Source', lower case."""
    title = h.get("title", "")
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip().lower()


def fresh(heads: list[dict], seen: set, max_age_min: int = MAX_AGE_MIN) -> list[dict]:
    """Relevant headlines not seen before and at most `max_age_min` old, newest first, one per id."""
    out, ids = [], set()
    for h in sorted(heads, key=lambda x: x.get("age_min", 1e9)):
        i = head_id(h)
        if i in seen or i in ids or h.get("age_min") is None or h["age_min"] > max_age_min or not relevant(h.get("title", "")):
            continue
        ids.add(i)
        out.append(h)
    return out


def load_seen(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text()) if Path(path).exists() else {}
    except (OSError, ValueError):
        return {}


def poll(now: pd.Timestamp, session=requests, seen_path: Path | None = None, max_age_min: int = MAX_AGE_MIN) -> list[dict]:
    """One poll of the sources: fresh relevant headlines, marked seen so each wakes the desk at most once. Rules only."""
    heads = sources(now, session, hours=max(1.0, max_age_min / 60 + 0.5))
    seen = load_seen(seen_path) if seen_path else {}
    new = fresh(heads, set(seen), max_age_min)
    if seen_path is not None:
        keep = {k: v for k, v in seen.items() if now - pd.Timestamp(v) < pd.Timedelta(days=SEEN_DAYS)}
        keep.update({head_id(h): now.isoformat() for h in new})
        Path(seen_path).parent.mkdir(parents=True, exist_ok=True)
        Path(seen_path).write_text(json.dumps(keep))
    return new


# Google News (as v3) plus primary sources: the Federal Reserve's and the Treasury's own press feeds, which carry a decision or
# a statement before any article about it. Titles only: article text is not fetched (no free source whose terms clearly allow it
# was confirmed). Checked live on 2026-10-31. Treasury publishes no press-release feed (its rss.xml is old site pages), so that
# entry is Google's index of the press-release pages: the Treasury's own words, but later than the Fed's own feed by the index delay.
PRIMARY = {"Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
           "US Treasury": "https://news.google.com/rss/search?q=site:home.treasury.gov/news/press-releases&hl=en-US&gl=US&ceid=US:en"}


def sources(now: pd.Timestamp, session=requests, hours: float = 12.0) -> list[dict]:
    """Every headline the desk can read, newest first, one per id: Google News and the primary feeds, published by `now`.
    A dead feed gives nothing, never a guess."""
    rows = []
    feeds = [(None, url) for url in news.FEEDS] + [(name, url) for name, url in PRIMARY.items()]
    for name, url in feeds:
        try:
            r = session.get(url, headers=news.HEADERS, timeout=15)
            if r.ok:
                got = news.parse_rss(r.content.decode("utf-8-sig", "replace"), now, hours=hours, limit=50)   # the Fed sends a BOM and no charset
                rows.extend({**h, "source": h["source"] or name, "primary": name is not None} for h in got)
        except requests.RequestException:
            continue
    out, ids = [], set()
    for h in sorted(rows, key=lambda x: x["age_min"]):
        if head_id(h) not in ids:
            ids.add(head_id(h))
            out.append(h)
    return out


def for_desk(heads: list[dict], limit: int = 25) -> list[dict]:
    """What the news agent reads: the relevant headlines only, newest first."""
    return [h for h in heads if relevant(h.get("title", ""))][:limit]


def headline_lag(heads: list[dict]) -> dict | str:
    """How old the news is when the desk wakes, measured on every wake: the newest and the median relevant headline's age."""
    ages = sorted(h["age_min"] for h in heads if h.get("age_min") is not None)
    if not ages:
        return "unavailable"
    return {"newest_min": ages[0], "median_min": ages[len(ages) // 2], "count": len(ages)}


# ---------------------------------------------------------------- calendar (wider than v1-v3's)
EVENTS_V31 = cal.EVENTS_V31_FILE
CENTRAL_BANK = re.compile(r"(policy rate|cash rate|overnight rate|refinancing rate|deposit rate|bank rate|rate statement|monetary policy|"
                          r"policy statement|press conference|minutes|\bgov\b|governor|lagarde|ueda|bailey|outlook report|mpc|fomc)", re.I)


def calendar_rows(rows: list[dict]) -> list[dict]:
    """From the weekly calendar feed: US releases of high or medium impact, and other central banks' decisions, statements and
    speeches of high or medium impact, each marked with its impact. Only `high` blocks the desk (`calendar.blocking_event`)."""
    out = []
    for e in rows:
        impact, country, title = str(e.get("impact", "")).lower(), str(e.get("country", "")), str(e.get("title", ""))
        if impact not in ("high", "medium"):
            continue
        if country != "USD" and not CENTRAL_BANK.search(title):
            continue
        try:
            t = pd.Timestamp(e["date"]).tz_convert("UTC")
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "name": title if country == "USD" else f"{country} {title}",
                    "impact": impact})
    return out


def refresh_calendars(session=requests, path_v3: Path | None = None, path_v31: Path | None = None) -> tuple[int, int]:
    """One read of the calendar feed, written twice: events.csv (high-impact US, what v1-v3 block on, unchanged) and
    events_v31.csv (the wider list). -> new rows in each."""
    r = session.get(news.CALENDAR, headers=news.HEADERS, timeout=15)
    r.raise_for_status()
    rows = r.json()
    return (news.write_events(news.parse_calendar(rows), path_v3 or cal.EVENTS_FILE),
            news.write_events(calendar_rows(rows), path_v31 or EVENTS_V31))


def trigger(h: dict) -> dict:
    return {"kind": "news", "direction": None, "level": None, "name": h["title"][:80]}


def tick(now: pd.Timestamp, poll_fn, wake, state_path: Path, log_path: Path, w: W.WatchV31 = W.WATCH_V31,
         window=cal.desk_window) -> str:
    """One news poll. `poll_fn()` -> fresh relevant headlines; `wake(trigger, now)` runs the desk. Shares the watcher's state
    file, so one daily budget covers every trigger and a headline right after a wake does not wake the desk again."""
    if window(now.to_pydatetime())[0] in ("closed", "break"):
        return "market shut"
    heads = poll_fn()
    if not heads:
        return "quiet"
    trigs = [trigger(h) for h in heads]
    state = W.load_state(state_path)
    ok, why = W.should_wake(trigs[:1], state, now, w)
    J._append_lines(Path(log_path), [{"at": now.isoformat(), "source": "news", "triggers": trigs, "slot": False, "woke": ok,
                                      "why": why, "state_wakes": state.get("wakes", 0),
                                      "headlines": [{k: h.get(k) for k in ("title", "source", "published", "age_min")} for h in heads]}])
    if ok:
        W.record_wake(trigs[:1], state, now)
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(state))
    if ok:
        wake(trigs[0], now)
        return "woke"
    return why
