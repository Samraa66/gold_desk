import pandas as pd
from src.histdata import to_utc_bars

def _raw(*stamps):
    return pd.DataFrame({"t": list(stamps), "open": 1, "high": 1, "low": 1, "close": 1, "vol": 0})

def test_histdata_clock_is_new_york_wall_time_with_dst():
    out = to_utc_bars(_raw("20240115 080000", "20240715 080000"))
    # winter: NY = UTC-5 -> 13:00 UTC; summer: NY = UTC-4 -> 12:00 UTC. (A fixed UTC-5 clock would give 13:00 for both.)
    assert [str(x) for x in out.index] == ["2024-01-15 13:00:00+00:00", "2024-07-15 12:00:00+00:00"]
    assert list(out.columns) == ["open", "high", "low", "close"]

def test_daily_break_lands_on_the_real_reopen_in_both_seasons():
    # gold reopens at 18:00 New York time = 23:00 UTC in winter, 22:00 UTC in summer
    out = to_utc_bars(_raw("20240116 180000", "20240716 180000"))
    assert [x.strftime("%m-%d %H:%M") for x in out.index] == ["01-16 23:00", "07-16 22:00"]

def test_dst_change_hours_are_dropped_not_crashed():
    # US spring change 2024-03-10 02:00-03:00 does not exist; autumn change 2024-11-03 01:00-02:00 happens twice
    out = to_utc_bars(_raw("20240310 023000", "20240310 030000", "20241103 013000", "20241103 020000"))
    assert len(out) == 2 and out.index.is_unique
