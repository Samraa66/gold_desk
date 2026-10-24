import numpy as np
import pandas as pd
import pytest
from src.mt5_data import detect_offset_hours, to_utc_frame, merge_bars, combined, compare_overlap

def test_offset_detection():
    assert detect_offset_hours(1792040055, 1792040055 - 3 * 3600 + 2) == 3
    assert detect_offset_hours(1000 + 2 * 3600, 1000) == 2
    with pytest.raises(ValueError):
        detect_offset_hours(1000 + 5400, 1000)            # 1.5 h: stale tick or wrong clock

def test_server_time_converted_to_utc():
    rates = [{"time": 1792039800, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "spread": 29}]
    f = to_utc_frame(rates, 3)
    assert f.index[0] == pd.Timestamp(1792039800 - 3 * 3600, unit="s", tz="UTC")
    assert f.index.tz is not None and list(f.columns) == ["open", "high", "low", "close", "spread"]

def _bars(start, n, base=100.0):
    idx = pd.date_range(start, periods=n, freq="1min", tz="UTC", name="time")
    return pd.DataFrame({"open": base, "high": base + 1, "low": base - 1, "close": base, "spread": 25.0}, index=idx)

def test_merge_is_append_only_and_never_rewrites_old_bars():
    old = _bars("2026-10-10 00:00", 10, 100.0)
    new = _bars("2026-10-10 00:05", 10, 999.0)            # overlaps 5 stored minutes with different prices
    m = merge_bars(old, new)
    assert len(m) == 15 and (m.loc[:old.index.max(), "close"] == 100.0).all() and (m.iloc[10:].close == 999.0).all()
    assert merge_bars(old, new.iloc[:0]).equals(old)

def test_combined_uses_mt5_only_after_history_ends():
    hist = _bars("2026-10-09 21:50", 9, 100.0)             # ends 21:58
    mt5 = _bars("2026-10-09 21:55", 10, 555.0)             # overlaps the last 4 hist minutes
    c = combined(hist, mt5)
    assert (c.loc[:hist.index.max()].close == 100.0).all()
    assert c.index.is_unique and c.index.max() == mt5.index.max() and (c.loc[hist.index.max() + pd.Timedelta("1min"):].close == 555.0).all()

def test_overlap_check_finds_the_right_alignment():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-10-05", periods=600, freq="1min", tz="UTC", name="time")
    px = 4000 + np.cumsum(rng.normal(0, 0.5, 600))
    hist = pd.DataFrame({"close": px}, index=idx)
    mt5 = pd.DataFrame({"close": px + 0.05}, index=idx + pd.Timedelta(minutes=60))      # feed stamped one hour late
    r = compare_overlap(hist, mt5).set_index("shift_min")
    assert r.median_abs_diff.idxmin() == -60 and r.loc[-60, "median_abs_diff"] < 0.1 < r.loc[0, "median_abs_diff"]
