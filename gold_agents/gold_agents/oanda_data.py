"""Fresh XAU/USD 1-minute bars from OANDA (practice by default). Read-only: it only asks for candles.

Writes the same shape the MT5 export wrote (bid OHLC, `spread` in points where 100 points = 1.00 price unit) into
its own file, so OANDA and MT5 prices are never mixed inside one file. `data.load_m1` lets OANDA win on a
shared minute. Only COMPLETE candles are stored, so the forming bar never reaches an agent.

Token: OANDA_API_TOKEN (env or gold_agents/.env). OANDA_ENV=practice|live (default practice).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent.parent
OANDA_CSV = HERE.parent / "gold_bot" / "data" / "oanda" / "xauusd_m1.csv"
HOSTS = {"practice": "https://api-fxpractice.oanda.com", "live": "https://api-fxtrade.oanda.com"}
PAGE = 5000   # OANDA's cap per request
COLS = ["open", "high", "low", "close", "spread"]


def _env(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(name + "=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def parse_candles(payload: dict, spread_mult: float = 100.0) -> pd.DataFrame:
    """Complete candles -> UTC-indexed bid OHLC plus spread in points (ask close - bid close, x100)."""
    rows = []
    for c in payload.get("candles", []):
        if not c.get("complete"):
            continue
        bid, ask = c["bid"], c["ask"]
        rows.append({
            "time": pd.to_datetime(c["time"], utc=True),
            "open": float(bid["o"]), "high": float(bid["h"]), "low": float(bid["l"]), "close": float(bid["c"]),
            "spread": round((float(ask["c"]) - float(bid["c"])) * spread_mult, 1 if spread_mult >= 100 else 6),
        })
    if not rows:
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="time"))
    return pd.DataFrame(rows).set_index("time").sort_index()[COLS]


RETRY_WAITS = (2, 6, 15)   # seconds before attempts 2, 3, 4; OANDA's gateway answers 502/504 now and then


def _get(session, url, params, headers, sleep=time.sleep):
    """GET with a few retries on a gateway error, rate limit, timeout or dropped connection. Auth errors are not retried."""
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            r = session.get(url, params=params, headers=headers, timeout=30)
            if r.status_code not in (429, 500, 502, 503, 504):
                return r
            failure = f"HTTP {r.status_code}"
        except (requests.Timeout, requests.ConnectionError) as e:
            r, failure = None, type(e).__name__
        if attempt == len(RETRY_WAITS):
            if r is not None:
                return r
            raise
        print(f"OANDA {failure}, retrying in {RETRY_WAITS[attempt]}s", file=sys.stderr)
        sleep(RETRY_WAITS[attempt])


def fetch_since(since: pd.Timestamp, token: str, env: str = "practice", instrument: str = "XAU_USD",
                session=requests, now: datetime | None = None, spread_mult: float = 100.0) -> pd.DataFrame:
    """Every complete M1 candle from `since` up to now, paging 5000 at a time."""
    url = f"{HOSTS[env]}/v3/instruments/{instrument}/candles"
    headers = {"Authorization": f"Bearer {token}"}
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    cursor, frames = pd.Timestamp(since), []
    while cursor < now:
        params = {"granularity": "M1", "price": "BA", "count": PAGE, "from": cursor.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")}
        r = _get(session, url, params, headers)
        if r.status_code in (401, 403):
            raise SystemExit(f"OANDA refused the token ({r.status_code}): check OANDA_API_TOKEN and OANDA_ENV={env}")
        r.raise_for_status()
        page = parse_candles(r.json(), spread_mult)
        raw = r.json().get("candles", [])
        if not raw:
            break
        frames.append(page)
        last = pd.to_datetime(raw[-1]["time"], utc=True)
        if last < cursor or len(raw) < PAGE:
            break
        cursor = last + pd.Timedelta(minutes=1)
    if not frames:
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="time"))
    df = pd.concat(frames)
    return df[~df.index.duplicated(keep="last")].sort_index()


def merge(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    df = pd.concat([old, new])
    return df[~df.index.duplicated(keep="last")].sort_index()


def read_csv(path: Path = OANDA_CSV) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="time"))
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time")[COLS]


def refresh(since: pd.Timestamp, path: Path = OANDA_CSV, session=requests, now: datetime | None = None,
            instrument: str = "XAU_USD") -> str:
    token = _env("OANDA_API_TOKEN")
    if not token:
        raise SystemExit("OANDA_API_TOKEN is not set (env or gold_agents/.env)")
    env = (_env("OANDA_ENV") or "practice").lower()
    if env not in HOSTS:
        raise SystemExit(f"OANDA_ENV must be practice or live, not {env!r}")
    old = read_csv(path)
    new = fetch_since(since, token, env, instrument, session=session, now=now,
                      spread_mult=100.0 if instrument == "XAU_USD" else 1.0)
    merged = merge(old, new)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path)
    if merged.empty:
        return "OANDA returned no bars (market closed for the whole window?)"
    return f"OANDA {env}: stored {len(old)} -> {len(merged)} bars, {merged.index.min()} .. {merged.index.max()}"


if __name__ == "__main__":
    # usage: python -m gold_agents.oanda_data [since-date] [INSTRUMENT]   (default gold, last 10 days)
    from . import instruments as I
    inst = I.get(sys.argv[2] if len(sys.argv) > 2 else "XAU_USD")
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "auto":      # first run for an instrument backfills ~135 days (the agents read 130); later runs top up 10
        arg = (datetime.now(timezone.utc) - timedelta(days=10 if inst.bars_path.exists() else 135)).date().isoformat()
    since = pd.Timestamp(arg or (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat(), tz="UTC")
    print(refresh(since, inst.bars_path, instrument=inst.oanda))
