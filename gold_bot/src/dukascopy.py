"""Free XAUUSD 1-minute candles from Dukascopy's public datafeed (bid and ask).

One file per day per side: .../XAUUSD/<year>/<month 0-11>/<day>/{BID,ASK}_candles_min_1.bi5
(LZMA-compressed, 24-byte records: seconds since midnight UTC, open, close, low, high as
big-endian ints, then a float volume). Prices are ints at 1/1000 for XAUUSD.

Downloaded days are cached under data/raw/ so a rerun only fetches what is missing.
A weekend or holiday answers 404 or an empty file: stored as an empty marker, not retried.
"""
import lzma
import struct
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
PRICE_DIV = 1000.0
PAUSE = 2.0                  # seconds between requests
_REC = struct.Struct(">IIIIIf")


def _url(day: date, side: str) -> str:
    return f"{BASE}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{side}_candles_min_1.bi5"


def fetch_day(day: date, side: str, session: requests.Session) -> bytes:
    path = RAW / side / f"{day.isoformat()}.bi5"
    if path.exists():
        return path.read_bytes()
    r = None
    for wait in (0, 30, 60, 120, 300, 600, 900):      # be polite: back off on 429 and on timeouts
        time.sleep(wait + PAUSE)
        try:
            r = session.get(_url(day, side), timeout=30)
        except requests.RequestException:
            r = None
            continue
        if r.status_code not in (429, 500, 502, 503, 504):
            break
    if r is None or r.status_code in (429, 500, 502, 503, 504):
        raise RuntimeError(f"Dukascopy would not serve {side} {day} after retries; rerun to resume")
    if r.status_code == 404:
        data = b""
    else:
        r.raise_for_status()
        data = r.content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def parse_day(day: date, blob: bytes) -> pd.DataFrame:
    cols = ["time", "open", "high", "low", "close", "volume"]
    if not blob:
        return pd.DataFrame(columns=cols)
    raw = lzma.decompress(blob)
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rows = []
    for off in range(0, len(raw) - _REC.size + 1, _REC.size):
        sec, o, c, lo, hi, vol = _REC.unpack_from(raw, off)
        rows.append((base + timedelta(seconds=sec), o / PRICE_DIV, hi / PRICE_DIV,
                     lo / PRICE_DIV, c / PRICE_DIV, vol))
    return pd.DataFrame(rows, columns=cols)


def _days(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() != 5:                 # Saturday: no market
            yield day
        day += timedelta(days=1)


def download(start: date, end: date, workers: int = 1) -> pd.DataFrame:
    """Bid and ask candles for [start, end], joined on minute. Columns: *_bid, *_ask.

    Missing days are fetched by a few workers in parallel (cached days are free)."""
    from concurrent.futures import ThreadPoolExecutor

    def grab(args):
        day, side = args
        return fetch_day(day, side, requests.Session())

    jobs = [(d, side) for d in _days(start, end) for side in ("BID", "ASK")]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, _ in enumerate(pool.map(grab, jobs), 1):
            if i % 100 == 0:
                print(f"  fetched {i}/{len(jobs)}", flush=True)

    frames = []
    for day in _days(start, end):
        sides = {side: parse_day(day, fetch_day(day, side, requests.Session())).set_index("time")
                 for side in ("BID", "ASK")}
        if not sides["BID"].empty and not sides["ASK"].empty:
            frames.append(sides["BID"].join(sides["ASK"], lsuffix="_bid", rsuffix="_ask", how="inner"))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated()]


if __name__ == "__main__":
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    df = download(start, end)
    dest = RAW.parent / f"xauusd_1m_{start}_{end}.parquet"
    df.to_parquet(dest)
    print(f"{len(df)} minutes, {df.index.min()} -> {df.index.max()}  saved {dest.name}")
    spread = (df["open_ask"] - df["open_bid"])
    print("median spread", round(float(spread.median()), 3), " mean", round(float(spread.mean()), 3))
    print("last close bid", float(df["close_bid"].iloc[-1]))
