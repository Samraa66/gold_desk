"""Bar loading and the as-of rule.

Everything an agent sees goes through `closed_bars(m1, as_of)`: only 1-minute bars that had finished by
`as_of` exist for it. Higher timeframes are built from those, and a higher-timeframe bar that is still
forming is dropped. This is what keeps a replay honest (no look-ahead), and tests/test_no_lookahead.py
proves a decision does not change when future bars are appended.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
GOLD_BOT = HERE.parent / "gold_bot"
HIST_PARQUET = GOLD_BOT / "data" / "xauusd_m1_histdata.parquet"
MT5_CSV = GOLD_BOT / "data" / "mt5" / "xauusd_m1.csv"
OANDA_CSV = GOLD_BOT / "data" / "oanda" / "xauusd_m1.csv"
OHLC = ["open", "high", "low", "close"]

TF = {"M15": "15min", "H1": "1h", "H4": "4h", "D1": "1D"}


def load_m1(hist: Path | None = HIST_PARQUET, mt5: Path | None = MT5_CSV, oanda: Path | None = OANDA_CSV,
            instrument: str | None = None) -> pd.DataFrame:
    """UTC-indexed 1-minute bid bars. Where sources share a minute the later one wins: history < MT5 < OANDA
    (the live sources carry spread)."""
    if instrument and instrument != "XAU_USD":
        return _load_oanda_only(instrument)
    frames = []
    if hist and Path(hist).exists():
        h = pd.read_parquet(hist)[OHLC]
        h["spread"] = float("nan")
        frames.append(h)
    if mt5 and Path(mt5).exists():
        m = pd.read_csv(mt5)
        m["time"] = pd.to_datetime(m["time"], utc=True)
        m = m.set_index("time")[OHLC + ["spread"]]
        m["spread"] = m["spread"] / 100.0          # MT5 reports points; 100 points = 1.00 price unit
        frames.append(m)
    if oanda and Path(oanda).exists():
        o = pd.read_csv(oanda)
        o["time"] = pd.to_datetime(o["time"], utc=True)
        o = o.set_index("time")[OHLC + ["spread"]]
        o["spread"] = o["spread"] / 100.0          # same convention as MT5: points in the file, price units here
        frames.append(o)
    if not frames:
        raise FileNotFoundError("no bar files found; see README 'Data'")
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index.name = "time"
    return df


def _load_oanda_only(instrument: str) -> pd.DataFrame:
    """Bars for a non-gold instrument: OANDA only. Its csv stores spread in PRICE units (gold's stores points)."""
    from . import instruments as I
    spec = I.get(instrument)
    if not spec.bars_path.exists():
        raise FileNotFoundError(f"no bars for {instrument}: run python -m gold_agents.oanda_data <since> {instrument}")
    o = pd.read_csv(spec.bars_path)
    o["time"] = pd.to_datetime(o["time"], utc=True)
    o = o.set_index("time")[OHLC + ["spread"]]
    o["spread"] = o["spread"] * spec.spread_scale
    o = o[~o.index.duplicated(keep="last")].sort_index()
    o.index.name = "time"
    return o


def closed_bars(m1: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Minute bars whose whole minute is over at `as_of` (a bar stamped 10:00 closes at 10:01)."""
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    return m1.loc[: as_of - pd.Timedelta(minutes=1)]   # sorted index: a slice, not a full-array compare


def resample(m1_closed: pd.DataFrame, tf: str, as_of: pd.Timestamp) -> pd.DataFrame:
    """OHLC at timeframe `tf`, forming bar excluded. D1 is a UTC-midnight day (an approximation of the
    17:00 New York rollover, stated in the README)."""
    rule = TF[tf]
    agg = m1_closed[OHLC].resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    return agg[agg.index + pd.Timedelta(rule) <= as_of]
