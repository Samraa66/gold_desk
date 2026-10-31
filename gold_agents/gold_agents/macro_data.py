"""Macro series from Yahoo's chart endpoint (no key). Daily closes, cached per day under data/macro/.

Read only the days BEFORE the decision day: today's daily bar is still forming, so using it would leak.
If Yahoo is unreachable the macro agent gets an empty frame and reports "no data" (score 0), never a guess.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(__file__).resolve().parent.parent / "data" / "macro"
SYMBOLS = {"dxy": "DX-Y.NYB", "us10y": "^TNX", "vix": "^VIX", "spx": "^GSPC", "silver": "SI=F"}
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
UA = {"User-Agent": "Mozilla/5.0 (research script)"}


def _parse(payload: dict) -> pd.Series:
    res = payload["chart"]["result"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).normalize()
    closes = res["indicators"]["quote"][0]["close"]
    s = pd.Series(closes, index=idx, dtype="float64").dropna()
    return s[~s.index.duplicated(keep="last")]


def fetch(sym: str, range_: str = "1y", cache_dir: Path = CACHE, max_age_h: float = 6.0,
          session=requests) -> pd.Series:
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / (sym.replace("^", "_").replace("=", "_") + ".json")
    if f.exists() and (time.time() - f.stat().st_mtime) / 3600 < max_age_h:
        return _parse(json.loads(f.read_text()))
    try:
        r = session.get(URL.format(sym=sym), params={"range": range_, "interval": "1d"}, headers=UA, timeout=15)
        r.raise_for_status()
        payload = r.json()
        series = _parse(payload)
        f.write_text(json.dumps(payload))
        return series
    except Exception:
        if f.exists():                      # stale cache beats nothing, but is flagged by age in the report
            return _parse(json.loads(f.read_text()))
        return pd.Series(dtype="float64")


def fred_real_yield(session=requests) -> pd.Series:
    """10-year TIPS yield (FRED DFII10), the single biggest driver of gold. Only when FRED_API_KEY is set
    (env or .env); otherwise an empty series and the macro agent simply has no real-yield line."""
    key = os.environ.get("FRED_API_KEY")
    env = Path(__file__).resolve().parent.parent / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("FRED_API_KEY=") and line.split("=", 1)[1].strip():
                key = line.split("=", 1)[1].strip()
    if not key:
        return pd.Series(dtype="float64")
    try:
        r = session.get("https://api.stlouisfed.org/fred/series/observations",
                        params={"series_id": "DFII10", "api_key": key, "file_type": "json", "sort_order": "asc",
                                "observation_start": "2025-01-01"}, timeout=15)
        r.raise_for_status()
        rows = [(o["date"], float(o["value"])) for o in r.json()["observations"] if o["value"] not in (".", "")]
        return pd.Series([v for _, v in rows], index=pd.to_datetime([d for d, _ in rows], utc=True), dtype="float64")
    except Exception:
        return pd.Series(dtype="float64")


def macro_frame(as_of: datetime, **kw) -> pd.DataFrame:
    """Daily closes of each macro series, rows strictly before the as-of day."""
    cols = {name: fetch(sym, **kw) for name, sym in SYMBOLS.items()}
    ry = fred_real_yield()
    if len(ry):
        cols["real10y"] = ry
    df = pd.DataFrame(cols).sort_index().ffill()
    day = pd.Timestamp(as_of).tz_convert("UTC").normalize() if pd.Timestamp(as_of).tzinfo else pd.Timestamp(as_of, tz="UTC").normalize()
    return df[df.index < day]


# ---------------------------------------------------------------- desk v3.1: free inputs with their age (2026-10-31)
# Each returns a dict that carries the data's age, or the string "unavailable": a dead source is never filled in. Cached under
# data/macro/ so 30+ wakes a day make a few requests, not dozens. URLs and field names checked live on 2026-10-31.
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"          # public, no key: the series' graph download
CFTC_LEGACY = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"   # CFTC public reporting, legacy futures-only COT
COT_MARKET = "GOLD - COMMODITY EXCHANGE INC."


def _cached_text(name: str, fetch, cache_dir: Path | None, max_age_h: float) -> str | None:
    cache_dir = Path(cache_dir or CACHE)
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / name
    if f.exists() and (time.time() - f.stat().st_mtime) / 3600 < max_age_h:
        return f.read_text()
    try:
        text = fetch()
        f.write_text(text)
        return text
    except Exception:
        return f.read_text() if f.exists() else None      # a stale copy beats nothing; its age is reported with it


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    """FRED's graph csv: a header row, then date,value; missing days are '.' or empty. -> [(date, value)] oldest first."""
    out = []
    for line in (text or "").strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            out.append((parts[0].strip(), float(parts[1])))
        except ValueError:
            continue
    return out


def real_yield(now: pd.Timestamp, session=requests, cache_dir: Path | None = None, max_age_h: float = 6.0) -> dict | str:
    """The 10-year TIPS yield (FRED DFII10), gold's main driver, with its 5-day change and age. No key needed."""
    text = _cached_text("dfii10.csv", lambda: _get_text(session, FRED_CSV, {"id": "DFII10"}), cache_dir, max_age_h)
    rows = parse_fred_csv(text) if text else []
    if not rows:
        return "unavailable"
    day, value = rows[-1]
    prev = rows[-6][1] if len(rows) > 5 else None
    return {"value_pct": value, "change_5d_pp": round(value - prev, 3) if prev is not None else None, "date": day,
            "age_days": _age_days(now, day), "source": "FRED DFII10 (daily, published with a lag of a day or more)"}


def parse_cot(rows: list[dict]) -> dict | None:
    """The two latest legacy COT rows for COMEX gold -> large speculators' (non-commercial) net position and its weekly change."""
    try:
        rows = sorted(rows, key=lambda r: r["report_date_as_yyyy_mm_dd"], reverse=True)
        net = lambda r: int(float(r["noncomm_positions_long_all"])) - int(float(r["noncomm_positions_short_all"]))
        last = rows[0]
        return {"report_date": last["report_date_as_yyyy_mm_dd"][:10], "noncommercial_net": net(last),
                "net_change_week": net(last) - net(rows[1]) if len(rows) > 1 else None,
                "open_interest": int(float(last["open_interest_all"]))}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def cot_gold(now: pd.Timestamp, session=requests, cache_dir: Path | None = None, max_age_h: float = 12.0) -> dict | str:
    """Weekly positioning in COMEX gold futures (CFTC, positions as of Tuesday, published Friday), with its age."""
    params = {"$where": f"market_and_exchange_names='{COT_MARKET}'", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 2}
    text = _cached_text("cot_gold.json", lambda: _get_text(session, CFTC_LEGACY, params), cache_dir, max_age_h)
    try:
        cot = parse_cot(json.loads(text)) if text else None
    except ValueError:
        cot = None
    if not cot:
        return "unavailable"
    return {**cot, "age_days": _age_days(now, cot["report_date"]), "source": "CFTC legacy futures-only report (weekly)"}


def etf_flows(now: pd.Timestamp) -> str:
    """Gold ETF holdings: no free source whose terms allow automated reading was confirmed, so this stays unavailable."""
    return "unavailable"


def _get_text(session, url: str, params: dict) -> str:
    r = session.get(url, params=params, headers=UA, timeout=15)
    r.raise_for_status()
    return r.text


def _age_days(now: pd.Timestamp, day: str) -> float:
    return round((pd.Timestamp(now).tz_convert("UTC") - pd.Timestamp(day, tz="UTC")).total_seconds() / 86400, 1)
