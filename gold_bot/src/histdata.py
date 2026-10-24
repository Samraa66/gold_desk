"""HistData.com XAUUSD 1-minute bars (zip files in data/histdata/) -> bid/ask candles in UTC.

HistData gives one price series (treated as the BID side) stamped in New York wall-clock time (DST included), and no spread. The ask is built as bid + a fixed spread, passed in
so the same history can be scored at a normal and a worse cost.
"""
import io
import zipfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent


def load_bars() -> pd.DataFrame:
    frames = []
    zips = sorted((HERE / "data" / "histdata").glob("*.zip")) + sorted((HERE / "data" / "histdata_history").glob("*.zip"))
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            raw = pd.read_csv(io.BytesIO(zf.read(name)), sep=";", header=None,
                              names=["t", "open", "high", "low", "close", "vol"])
        frames.append(raw)
    return to_utc_bars(pd.concat(frames, ignore_index=True))


def to_utc_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Raw HistData rows (column t = 'YYYYMMDD HHMMSS') -> OHLC indexed in true UTC.

    The file's clock is New York WALL-CLOCK time, daylight saving included (the daily break sits at 17:00 to 18:00 all year).
    It is NOT a fixed UTC-5 clock as the vendor's note suggests: treating it that way made every summer bar one hour late
    (found 2026-10-15 by overlaying MetaTrader 5 bars: a constant +2 h gap to MT5's server clock in all 22 months checked).
    The repeated hour at the autumn change and the skipped hour at the spring change fall in the weekend closure and are dropped.
    """
    ts = pd.to_datetime(df["t"], format="%Y%m%d %H%M%S").dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    keep = ts.notna().values
    df = df.loc[keep].copy()
    df.index = ts[keep].dt.tz_convert("UTC")
    df.index.name = "time"
    df = df.drop(columns=["t", "vol"]).sort_index()
    return df[~df.index.duplicated()]


def with_spread(bars: pd.DataFrame, spread: float) -> pd.DataFrame:
    out = pd.DataFrame(index=bars.index)
    for c in ("open", "high", "low", "close"):
        out[f"{c}_bid"] = bars[c]
        out[f"{c}_ask"] = bars[c] + spread
    return out


if __name__ == "__main__":
    bars = load_bars()
    bars.to_parquet(HERE / "data" / "xauusd_m1_histdata.parquet")
    print(len(bars), "bars", bars.index.min(), "->", bars.index.max())
    print("close range", round(bars.close.min(), 1), "-", round(bars.close.max(), 1))
