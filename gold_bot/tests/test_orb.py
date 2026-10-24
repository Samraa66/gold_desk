import numpy as np
import pandas as pd
from src.orb import session_trades

def day(start_utc, minutes=360, base=2000.0):
    idx = pd.date_range(start_utc, periods=minutes, freq="1min", tz="UTC")
    p = np.full(minutes, base)
    return pd.DataFrame({"open": p, "high": p + 0.5, "low": p - 0.5, "close": p}, index=idx)

def with_breakout(df, minute, level):
    df = df.copy()
    df.iloc[minute:, df.columns.get_indexer(["open", "high", "low", "close"])] = level
    return df

def test_london_winter_and_summer_use_local_open():
    # Tue 2024-01-16: London open 08:00 = 08:00 UTC. Tue 2024-07-16: BST, open 08:00 = 07:00 UTC.
    for date, utc_hour in (("2024-01-16", 7), ("2024-07-16", 6)):
        df = day(f"{date} {utc_hour:02d}:00")        # starts one hour before the local open
        df = with_breakout(df, 60 + 30 + 10, 2010.0)  # breaks up 10 min after the 30-min range ends
        tr = session_trades(df, "london", 0.6)
        assert len(tr) == 1 and tr.side.iloc[0] == 1
        # entry bar is the 5-min close after minute 100 of the file: 5-min bars end at open+30+4 (+5k)
        assert tr.t.iloc[0] >= pd.Timestamp(f"{date} {utc_hour + 1:02d}:34", tz="UTC")

def test_no_trade_when_session_not_in_data():
    df = day("2024-01-16 00:00", minutes=120)         # nothing near 08:00 London
    assert session_trades(df, "london", 0.6).empty

def test_weekend_is_skipped():
    df = day("2024-01-13 07:00")                      # Saturday
    assert session_trades(df, "london", 0.6).empty

def test_entry_decision_ignores_future_bars():
    base = with_breakout(day("2024-01-16 07:00"), 100, 2010.0)
    trunc = base.iloc[:130]                           # cut off everything after entry + a few bars
    a = session_trades(base, "london", 0.6).iloc[0]
    b = session_trades(trunc, "london", 0.6)
    assert not b.empty
    assert (a.t, a.side, a.entry, a.risk) == (b.t.iloc[0], b.side.iloc[0], b.entry.iloc[0], b.risk.iloc[0])

def test_changing_future_prices_cannot_change_entry():
    base = with_breakout(day("2024-01-16 07:00"), 100, 2010.0)
    wild = base.copy(); wild.iloc[140:, :] *= 1.5     # rewrite the future, after the entry
    a = session_trades(base, "london", 0.6).iloc[0]; b = session_trades(wild, "london", 0.6).iloc[0]
    assert (a.t, a.side, a.entry, a.risk) == (b.t, b.side, b.entry, b.risk)

def test_short_breakout_pays_stop_with_spread_in_risk():
    df = with_breakout(day("2024-01-16 07:00"), 100, 1990.0)
    t = session_trades(df, "london", 0.6).iloc[0]
    assert t.side == -1
    # range high = 2000.5; stop = high + spread; entry = bid close 1990 -> risk = 10.5 + 0.6
    assert abs(t.risk - (2000.5 + 0.6 - 1990.0)) < 1e-9
