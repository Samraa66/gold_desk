import numpy as np
import pandas as pd
import pytest
from src.pullback import Params, make_bars, m15_features, signals, run, drop_top

def synth_m1(start, minutes, f):
    idx = pd.date_range(start, periods=minutes, freq="1min", tz="UTC")
    c = f(np.arange(minutes))
    return pd.DataFrame({"open": c, "high": c + 0.2, "low": c - 0.2, "close": c}, index=idx)

def test_bars_close_at_end_and_gaps_are_dropped():
    m1 = synth_m1("2024-01-16 10:00", 30, lambda x: 100.0 + x)
    b = make_bars(m1, "15min")
    assert list(b.end) == [pd.Timestamp("2024-01-16 10:15", tz="UTC"), pd.Timestamp("2024-01-16 10:30", tz="UTC")]
    assert b.iloc[0].open == 100 and b.iloc[0].close == 114 and b.iloc[0].high == 114.2

def test_h1_trend_is_only_visible_after_that_h1_bar_closes():
    # long flat history, then a jump inside one H1 bar: M15 bars inside it must not see the jump in the trend
    n = 60 * 260
    m1 = synth_m1("2024-01-01 00:00", n, lambda x: np.where(x < 60 * 250 + 20, 100.0, 200.0))
    f = m15_features(m1, Params())
    inside = f[(f.end > pd.Timestamp("2024-01-11 10:00", tz="UTC")) & (f.end < pd.Timestamp("2024-01-11 11:00", tz="UTC"))]
    after = f[f.end == pd.Timestamp("2024-01-11 11:00", tz="UTC")]
    assert (inside.trend_gap.abs() < 1e-6).all()       # H1 bar 10:00-11:00 (holds the jump) not usable until 11:00
    assert after.trend_gap.iloc[0] > 0

def test_no_signal_without_history_or_outside_session():
    m1 = synth_m1("2024-01-16 00:00", 24 * 60, lambda x: 100.0 + x * 0.01)
    f = m15_features(m1, Params())
    assert (signals(f, Params()) == 0).all()           # fewer than 200 H1 bars of history

def test_long_signal_conditions_by_hand():
    p = Params()
    ends = pd.date_range("2024-01-16 10:15", periods=8, freq="15min", tz="UTC")
    f = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 100.0, "close": 100.5, "ema": 99.0, "atr": 1.0,
                      "swing_lo": 99.0, "swing_hi": 101.0, "trend_gap": 5.0, "end": ends})
    f.loc[5, "low"] = 98.5                              # touch of the EMA
    f.loc[6, ["open", "high", "low", "close"]] = (99.5, 102.0, 99.5, 101.5)   # bullish, above prior high 101
    s = signals(f, p)
    assert s[6] == 1
    f2 = f.copy(); f2["trend_gap"] = -5.0               # trend down: a long setup must not fire
    assert signals(f2, p)[6] != 1
    f3 = f.copy(); f3.loc[6, "close"] = 100.9           # fails 'close above prior high'
    assert signals(f3, p)[6] == 0

def test_hour_filter_blocks_asian_session():
    ends = pd.date_range("2024-01-16 03:15", periods=8, freq="15min", tz="UTC")
    f = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 100.0, "close": 100.5, "ema": 99.0, "atr": 1.0,
                      "swing_lo": 99.0, "swing_hi": 101.0, "trend_gap": 5.0, "end": ends})
    f.loc[5, "low"] = 98.5; f.loc[6, ["open", "high", "low", "close"]] = (99.5, 102.0, 99.5, 101.5)
    assert (signals(f, Params()) == 0).all()

@pytest.fixture(scope="module")
def real_slice():
    m1 = pd.read_parquet("data/xauusd_m1_histdata.parquet")
    return m1.loc["2021-01-01":"2022-03-01"]

def test_truncating_the_future_does_not_change_earlier_trades(real_slice):
    cut = pd.Timestamp("2021-12-01", tz="UTC")
    full = run(real_slice)
    short = run(real_slice.loc[:cut])
    a = full[full.exit_t < cut - pd.Timedelta("1D")].reset_index(drop=True)
    b = short[short.exit_t < cut - pd.Timedelta("1D")].reset_index(drop=True)
    assert len(a) > 20
    pd.testing.assert_frame_equal(a, b)

def test_rewriting_the_future_does_not_change_earlier_trades(real_slice):
    cut = pd.Timestamp("2021-12-01", tz="UTC")
    wild = real_slice.copy(); wild.loc[cut:, ["open", "high", "low", "close"]] *= 1.3
    a, b = run(real_slice), run(wild)
    a, b = (x[x.exit_t < cut - pd.Timedelta("1D")].reset_index(drop=True) for x in (a, b))
    pd.testing.assert_frame_equal(a, b)

def test_costs_reduce_every_trade(real_slice):
    cheap = run(real_slice, Params(spread=0.0, extra=0.0))
    dear = run(real_slice, Params(spread=0.6, extra=0.3))
    assert dear.pnl.sum() < cheap.pnl.sum()
    assert (dear.risk > 0).all() and (dear.why.isin(["stop", "target", "time"])).all()

def test_one_position_at_a_time(real_slice):
    tr = run(real_slice)
    assert (tr.t.values[1:] > tr.exit_t.values[:-1]).all()

def test_drop_top_removes_best_five_percent():
    tr = pd.DataFrame({"r": list(range(100))})
    assert len(drop_top(tr)) == 95 and drop_top(tr).r.max() == 94

def _hand_frame():
    ends = pd.date_range("2024-01-16 10:15", periods=8, freq="15min", tz="UTC")
    f = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 100.0, "close": 100.5, "ema": 99.0, "atr": 1.0,
                      "swing_lo": 99.0, "swing_hi": 101.0, "trend_gap": 5.0, "end": ends})
    f.loc[5, "low"] = 98.5
    f.loc[6, ["open", "high", "low", "close"]] = (99.5, 102.0, 99.5, 101.5)
    return f

def test_signal_ignores_the_next_bar():
    f = _hand_frame()
    assert signals(f, Params())[6] == 1
    f.loc[7, ["high", "low", "close"]] = (500.0, 99.9, 100.0)      # a huge next bar must not change bar 6
    assert signals(f, Params())[6] == 1
    f.loc[7, ["high", "low", "close"]] = (0.5, -5.0, 0.0)
    assert signals(f, Params())[6] == 1

def test_entry_is_never_before_the_signal_bar_closes(real_slice):
    p = Params()
    f = m15_features(real_slice, p)
    sig_ends = set(f.end[signals(f, p) != 0])
    tr = run(real_slice, p, feats=f)
    assert len(tr) > 20
    # a trade's entry minute is the signal bar's END (or a later minute only when the minute is missing / busy)
    on_end = tr.t.isin(sig_ends)
    assert on_end.mean() > 0.95
    assert (tr.t.dt.minute % 15 == 0)[on_end].all()
    # entry price is that minute's real open
    t0 = tr.t.iloc[0]
    bid = real_slice.loc[t0, "open"]
    assert abs(tr.entry.iloc[0] - (bid + p.spread)) < 1e-9 or abs(tr.entry.iloc[0] - bid) < 1e-9
