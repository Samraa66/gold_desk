"""Headlines and the economic calendar for desk v3. Read-only; a dead feed means no headlines, never a guess.

Headlines: Google News RSS (free, no key; its terms are personal, non-commercial use, which this research is). A headline is
kept only if it was published by the as-of time. They are outside text: the agent reading them is told they are data.
Calendar: the Forex Factory weekly feed, high-impact US releases only, written to `events.csv` (see calendar.py), so CPI, PPI
and the rest block the desk the same way FOMC and payrolls do.
"""
from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

from .calendar import EVENTS_FILE

FEEDS = ("https://news.google.com/rss/search?q=gold+price+when:1d&hl=en-US&gl=US&ceid=US:en",
         "https://news.google.com/rss/search?q=federal+reserve+OR+treasury+yields+OR+dollar+index+when:1d&hl=en-US&gl=US&ceid=US:en")
CALENDAR = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse_rss(xml: str, as_of: pd.Timestamp, hours: float = 12.0, limit: int = 25) -> list[dict]:
    """Newest first, published inside the window before `as_of`, one per title."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out, seen = [], set()
    for item in root.iter("item"):
        title, pub = (item.findtext("title") or "").strip(), item.findtext("pubDate")
        if not title or not pub:
            continue
        try:
            t = pd.Timestamp(parsedate_to_datetime(pub)).tz_convert("UTC")
        except (TypeError, ValueError):
            continue
        if not as_of - pd.Timedelta(hours=hours) <= t <= as_of or title in seen:
            continue
        seen.add(title)
        out.append({"title": title[:200], "source": (item.findtext("source") or "").strip(), "published": t.isoformat(),
                    "age_min": int((as_of - t).total_seconds() // 60)})
    return sorted(out, key=lambda x: x["age_min"])[:limit]


def headlines(as_of: pd.Timestamp, session=requests, limit: int = 25) -> list[dict]:
    rows = []
    for url in FEEDS:
        try:
            r = session.get(url, headers=HEADERS, timeout=15)
            if r.ok:
                rows.extend(parse_rss(r.text, as_of))
        except requests.RequestException:
            continue
    seen, out = set(), []
    for h in sorted(rows, key=lambda x: x["age_min"]):
        if h["title"] not in seen:
            seen.add(h["title"])
            out.append(h)
    return out[:limit]


def parse_calendar(rows: list[dict]) -> list[dict]:
    out = []
    for e in rows:
        if e.get("country") == "USD" and str(e.get("impact", "")).lower() == "high":
            t = pd.Timestamp(e["date"]).tz_convert("UTC")
            out.append({"time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "name": str(e["title"]), "impact": "high"})
    return out


def write_events(rows: list[dict], path: Path = EVENTS_FILE) -> int:
    """Merge into the csv: earlier rows stay, the same time and name is not added twice. -> how many are new."""
    path = Path(path)
    old = list(csv.DictReader(path.open())) if path.exists() else []
    have = {(r["time_utc"], r["name"]) for r in old}
    new = [r for r in rows if (r["time_utc"], r["name"]) not in have]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["time_utc", "name", "impact"])
        w.writeheader()
        w.writerows(sorted(old + new, key=lambda r: r["time_utc"]))
    return len(new)


def refresh_calendar(path: Path = EVENTS_FILE, session=requests) -> int:
    r = session.get(CALENDAR, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return write_events(parse_calendar(r.json()), path)
