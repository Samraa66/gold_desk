"""MT5 bars -> the same UTC, bid-based 1-minute frame the research uses. Pure pandas (no MetaTrader5 import) so it is testable.

MT5 stamps bars and ticks in SERVER time (UTC+3 on MetaQuotes-Demo in October 2026). `server_offset_hours` is measured from a live
tick against the Mac clock; each bar is converted with the offset in force when it was fetched. Bars are only ever appended:
a stored bar is never rewritten, and the still-forming last bar is never stored.
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
MT5_CSV = HERE / "data" / "mt5" / "xauusd_m1.csv"
HIST = HERE / "data" / "xauusd_m1_histdata.parquet"
OHLC = ["open", "high", "low", "close"]


def detect_offset_hours(tick_server_time: int, utc_now: float) -> int:
    off = (tick_server_time - utc_now) / 3600
    r = int(round(off))
    if abs(off - r) > 0.25 or not -12 <= r <= 14:
        raise ValueError(f"server offset {off:.2f} h is not a whole-hour zone: stale tick or wrong clock")
    return r


def to_utc_frame(rates, offset_hours: int) -> pd.DataFrame:
    """rates: iterable of dicts/records with time (server seconds), open, high, low, close, spread -> UTC-indexed frame."""
    df = pd.DataFrame(list(map(dict, rates)) if not isinstance(rates, pd.DataFrame) else rates)
    if df.empty:
        return pd.DataFrame(columns=OHLC + ["spread"], index=pd.DatetimeIndex([], tz="UTC", name="time"))
    idx = pd.to_datetime(df["time"].astype("int64") - offset_hours * 3600, unit="s", utc=True)
    out = df[OHLC + ["spread"]].astype(float).set_axis(idx, axis=0)
    out.index.name = "time"
    return out.sort_index()[~out.index.duplicated()]


def merge_bars(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Append only bars newer than anything stored. Older stored bars are never touched."""
    if existing is None or existing.empty:
        return new
    fresh = new[new.index > existing.index.max()]
    return pd.concat([existing, fresh])


def read_mt5(path: Path = MT5_CSV) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=OHLC + ["spread"], index=pd.DatetimeIndex([], tz="UTC", name="time"))
    d = pd.read_csv(path, index_col="time", parse_dates=["time"])
    d.index = pd.to_datetime(d.index, utc=True)
    return d


def combined(hist: pd.DataFrame = None, mt5: pd.DataFrame = None) -> pd.DataFrame:
    """HistData history, then MT5 bars strictly after the last HistData bar. Never mixes the two feeds in the same minute."""
    hist = pd.read_parquet(HIST) if hist is None else hist
    mt5 = read_mt5() if mt5 is None else mt5
    tail = mt5[mt5.index > hist.index.max()][OHLC]
    return pd.concat([hist[OHLC], tail])


def compare_overlap(hist: pd.DataFrame, mt5: pd.DataFrame, shifts_min=(-60, 0, 60)) -> pd.DataFrame:
    """How well MT5 closes match HistData closes in the overlap, for the stored alignment and for +-1 hour shifts.
    The right alignment has a small median absolute difference; a wrong one is off by the price move of an hour."""
    rows = []
    for s in shifts_min:
        m = mt5.copy(); m.index = m.index + pd.Timedelta(minutes=s)
        j = hist[["close"]].join(m[["close"]], how="inner", lsuffix="_hist", rsuffix="_mt5")
        d = (j.close_mt5 - j.close_hist)
        rows.append({"shift_min": s, "n": len(j), "median_abs_diff": float(d.abs().median()) if len(j) else np.nan,
                     "median_diff": float(d.median()) if len(j) else np.nan})
    return pd.DataFrame(rows)
