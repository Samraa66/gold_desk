"""Live numbers for desk v3 from OANDA, read-only: M5 bars with volume, other markets over the last hours, and OANDA's order
and position books. Fetched once when the desk wakes and stored on the call, so a decision can be read back as it was made.

The books are OANDA's own clients, a slice of retail flow, not the whole market. Still the only real look at where orders
and positions cluster that spot gold offers. Anything unavailable is reported as such, never filled in.
"""
from __future__ import annotations

import pandas as pd
import requests

from .oanda_data import HOSTS, _env, _get

GOLD = "XAU_USD"
CROSS = {"USD_JPY": "dollar vs yen, up = stronger dollar", "EUR_USD": "euro vs dollar, up = weaker dollar",
         "USB10Y_USD": "US 10-year bond PRICE, down = yields rising", "SPX500_USD": "S&P 500", "BCO_USD": "Brent oil", "XAG_USD": "silver"}


def parse_m5(payload: dict) -> pd.DataFrame:
    rows = [{"time": pd.to_datetime(c["time"], utc=True), "open": float(c["mid"]["o"]), "high": float(c["mid"]["h"]),
             "low": float(c["mid"]["l"]), "close": float(c["mid"]["c"]), "volume": int(c.get("volume", 0))}
            for c in payload.get("candles", []) if c.get("complete")]
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], tz="UTC", name="time"))
    return pd.DataFrame(rows).set_index("time").sort_index()


def changes(b: pd.DataFrame) -> dict:
    c = b["close"]
    pct = lambda n: round((float(c.iloc[-1]) / float(c.iloc[-1 - n]) - 1) * 100, 3) if len(c) > n else None
    return {"last": float(c.iloc[-1]) if len(c) else None, "chg_1h_pct": pct(12), "chg_4h_pct": pct(48)}


def volume_ratio(b: pd.DataFrame, n: int = 3, base: int = 48) -> float | None:
    """The last `n` bars' tick volume against the `base` bars before them. 2.0 = twice the normal activity."""
    if len(b) < n + base:
        return None
    normal = float(b["volume"].iloc[-n - base:-n].mean())
    return round(float(b["volume"].iloc[-n:].mean()) / normal, 2) if normal else None


def parse_book(payload: dict, price: float, width: float, top: int = 3) -> dict:
    """The biggest clusters of open orders within `width` of price, each side."""
    rows = [{"price": float(x["price"]), "long_pct": float(x["longCountPercent"]), "short_pct": float(x["shortCountPercent"])}
            for x in payload.get("orderBook", {}).get("buckets", [])]
    size = lambda x: x["long_pct"] + x["short_pct"]
    near = [x for x in rows if abs(x["price"] - price) <= width]
    return {"time": payload.get("orderBook", {}).get("time"),
            "above": sorted((x for x in near if x["price"] > price), key=size, reverse=True)[:top],
            "below": sorted((x for x in near if x["price"] < price), key=size, reverse=True)[:top]}


def parse_positions(payload: dict) -> dict:
    rows = payload.get("positionBook", {}).get("buckets", [])
    lng, sht = sum(float(x["longCountPercent"]) for x in rows), sum(float(x["shortCountPercent"]) for x in rows)
    total = lng + sht
    return {"time": payload.get("positionBook", {}).get("time"), "long_pct": round(lng / total * 100, 1) if total else None,
            "short_pct": round(sht / total * 100, 1) if total else None}


def parse_positions_near(payload: dict, price: float, width: float) -> dict:
    """Long/short among positions within `width` of price, and that slice's share of the whole book. `parse_positions` reads the
    whole book, thousands of buckets of mostly old positions, which hardly moves (README, desk v3.1)."""
    book = payload.get("positionBook", {})
    rows = book.get("buckets", [])
    near = [x for x in rows if abs(float(x["price"]) - price) <= width]
    lng, sht = sum(float(x["longCountPercent"]) for x in near), sum(float(x["shortCountPercent"]) for x in near)
    total = lng + sht
    whole = sum(float(x["longCountPercent"]) + float(x["shortCountPercent"]) for x in rows)
    return {"time": book.get("time"), "long_pct": round(lng / total * 100, 1) if total else None,
            "short_pct": round(sht / total * 100, 1) if total else None,
            "share_of_book_pct": round(total / whole * 100, 1) if whole else None, "width": width}


class Oanda:
    def __init__(self, session=requests):
        self.session = session
        self.token = _env("OANDA_API_TOKEN")
        self.base = HOSTS[(_env("OANDA_ENV") or "practice").lower()]

    def _json(self, path: str, params: dict | None = None) -> dict:
        r = _get(self.session, f"{self.base}/v3/instruments/{path}", params or {}, {"Authorization": f"Bearer {self.token}"})
        r.raise_for_status()
        return r.json()

    def m5(self, instrument: str = GOLD, count: int = 400) -> pd.DataFrame:
        return parse_m5(self._json(f"{instrument}/candles", {"granularity": "M5", "price": "M", "count": count}))

    def snapshot(self, gold_m5: pd.DataFrame | None = None, width: float = 60.0) -> dict:
        out = {"cross": {}, "book": "unavailable", "positions": "unavailable", "volume_ratio": None}
        try:
            b = gold_m5 if gold_m5 is not None else self.m5()
            out["volume_ratio"] = volume_ratio(b)
            price = float(b["close"].iloc[-1])
            out["book"] = parse_book(self._json(f"{GOLD}/orderBook"), price, width)
            out["positions"] = parse_positions(self._json(f"{GOLD}/positionBook"))
        except (requests.RequestException, KeyError, ValueError, IndexError) as e:
            print(f"gold book unavailable: {e}")
        for inst, meaning in CROSS.items():
            try:
                out["cross"][inst] = {"meaning": meaning, **changes(self.m5(inst, 60))}
            except (requests.RequestException, KeyError, ValueError, IndexError) as e:
                print(f"{inst} unavailable: {e}")
        return out
