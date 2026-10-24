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
