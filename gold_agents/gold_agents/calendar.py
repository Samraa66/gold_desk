"""Scheduled-event blocks and market-hours windows.

Built in: FOMC decision days, US non-farm payrolls (first Friday), the weekend close, the daily rollover.
Everything else (CPI, PPI, retail sales, Fed speakers) comes from events.csv, which YOU keep current:
    time_utc,name,impact
    2026-11-12T13:30:00Z,US CPI,high
Only `high` rows block. An event list that is out of date makes the liquidity agent weaker, and it says so
in its report (`events_file_age_days`).

FOMC dates are the 2026 schedule as I know it; verify against federalreserve.gov before relying on them.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

FOMC_DECISION_DAYS_2026 = [date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
                           date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]

EVENTS_FILE = Path(__file__).resolve().parent.parent / "events.csv"


def _ny_to_utc(d: date, hh: int, mm: int) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=NY).astimezone(UTC)


def first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def builtin_events(start: datetime, end: datetime) -> list[dict]:
    out = []
    for d in FOMC_DECISION_DAYS_2026:
        out.append({"time": _ny_to_utc(d, 14, 0), "name": "FOMC decision", "impact": "high"})
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append({"time": _ny_to_utc(first_friday(y, m), 8, 30), "name": "US non-farm payrolls", "impact": "high"})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return [e for e in out if start - timedelta(days=1) <= e["time"] <= end + timedelta(days=1)]


def file_events(path: Path = EVENTS_FILE) -> list[dict]:
    if not Path(path).exists():
        return []
    df = pd.read_csv(path)
    out = []
    for _, r in df.iterrows():
        out.append({"time": pd.Timestamp(r["time_utc"]).to_pydatetime().astimezone(UTC), "name": str(r["name"]),
                    "impact": str(r.get("impact", "high")).lower()})
    return out


def events_file_age_days(path: Path = EVENTS_FILE, now: datetime | None = None) -> float | None:
    p = Path(path)
    if not p.exists():
        return None
    now = now or datetime.now(UTC)
    return round((now - datetime.fromtimestamp(p.stat().st_mtime, UTC)).total_seconds() / 86400, 1)


def blocking_event(as_of: datetime, before_min: int, after_min: int, events: list[dict] | None = None) -> dict | None:
    """The high-impact event whose window contains `as_of`, if any."""
    as_of = as_of.astimezone(UTC)
    pool = events if events is not None else builtin_events(as_of - timedelta(days=2), as_of + timedelta(days=2)) + file_events()
    for e in pool:
        if e["impact"] != "high":
            continue
        if e["time"] - timedelta(minutes=before_min) <= as_of <= e["time"] + timedelta(minutes=after_min):
            return e
    return None


def next_events(as_of: datetime, hours: int = 48, events: list[dict] | None = None) -> list[dict]:
    as_of = as_of.astimezone(UTC)
    pool = events if events is not None else builtin_events(as_of, as_of + timedelta(hours=hours)) + file_events()
    return sorted((e for e in pool if as_of <= e["time"] <= as_of + timedelta(hours=hours)), key=lambda e: e["time"])


def market_window(as_of: datetime) -> tuple[str, str | None]:
    """('open'|'closed'|'rollover'|'thin', reason). Gold trades Sun ~22:00 UTC to Fri ~21:00 UTC with a
    daily break; times shift an hour with US daylight saving, so the edges are padded rather than exact."""
    t = as_of.astimezone(UTC)
    wd, hr = t.weekday(), t.hour + t.minute / 60
    if wd == 5 or (wd == 4 and hr >= 20.0) or (wd == 6 and hr < 23.0):
        return "closed", "weekend: the market is shut or about to be"
    if 20.5 <= hr < 23.0:
        return "rollover", "daily rollover: spreads widen and liquidity thins"
    if hr < 6.0 or hr >= 20.0:
        return "thin", "Asia-only hours: thin, wider spread"
    return "open", None


# Desk v3.1: hours in New York time, because the break moves an hour in UTC with US clock changes. OANDA gold bars measured
# 2025-10 to 2026-10: last bar 16:59 New York, first bar about 18:04, daily and at the weekend. `market_window` above stays as
# it is, so v1-v3 decide exactly as before.
DESK_CLOSE = time(17, 0)      # New York: Friday's close and the start of the daily break
DESK_OPEN = time(18, 0)       # New York: Sunday's reopen and the end of the daily break
THIN_UNTIL = time(2, 0)       # New York: before this the market is Asia only (close enough to London's 06:00 UTC lead-in for a label)


def desk_window(as_of: datetime) -> tuple[str, str | None]:
    """('open'|'thin'|'break'|'closed', reason) in New York time: open Sunday 18:00 to Friday 17:00, shut 17:00-18:00 daily."""
    t = as_of.astimezone(NY)
    wd, hm = t.weekday(), t.time()
    if wd == 5 or (wd == 4 and hm >= DESK_CLOSE) or (wd == 6 and hm < DESK_OPEN):
        return "closed", "weekend: the market is shut (Friday 17:00 to Sunday 18:00 New York)"
    if DESK_CLOSE <= hm < DESK_OPEN:
        return "break", "daily break: no trading 17:00-18:00 New York"
    if hm >= DESK_OPEN or hm < THIN_UNTIL:
        return "thin", "Asia-only hours: thin, wider spread"
    return "open", None


def next_friday_close(as_of: datetime) -> datetime:
    """The first Friday 17:00 New York strictly after `as_of`, in UTC: the time a v3.1 trade must be flat by."""
    t = as_of.astimezone(NY)
    d = t.date() + timedelta(days=(4 - t.weekday()) % 7)
    close = datetime.combine(d, DESK_CLOSE, tzinfo=NY)
    if close <= t:
        close = datetime.combine(d + timedelta(days=7), DESK_CLOSE, tzinfo=NY)
    return close.astimezone(UTC)


def session(as_of: datetime) -> str:
    h = as_of.astimezone(UTC).hour
    if 7 <= h < 12:
        return "london"
    if 12 <= h < 16:
        return "london+new_york"
    if 16 <= h < 21:
        return "new_york"
    return "asia"
