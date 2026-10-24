import numpy as np
import pandas as pd
import pytest
from src.h4 import H4Params, h4_features, signals, trade_plan, run

@pytest.fixture(scope="module")
def real_slice():
    return pd.read_parquet("data/xauusd_m1_histdata.parquet").loc["2021-01-01":"2022-06-01"]

def test_breakout_uses_previous_bars_only():
    m1 = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0},
                      index=pd.date_range("2024-01-02", periods=4 * 60 * 40, freq="1min", tz="UTC"))
    f = h4_features(m1, H4Params())
    assert np.isnan(f.hh.iloc[19]) and not np.isnan(f.hh.iloc[20])
    f2 = f.copy(); f2.loc[f2.index[25], ["high", "close"]] = (150.0, 149.0)    # spike on bar 25
    assert f2.hh.iloc[25] == f.hh.iloc[25]                                     # its own high is not in its own channel
    assert signals(f2)[25] == 1 and signals(f2)[26] == 0                       # breakout fires on the spike bar's close only

def test_trade_plan_long_and_short_geometry():
    p = H4Params()
    e, s, t, r = trade_plan(1, 4000.0, 20.0, p)
    assert (e, s) == (4000.6, 3960.0) and abs(r - 40.6) < 1e-9 and abs(t - (e + 2 * r)) < 1e-9
    e, s, t, r = trade_plan(-1, 4000.0, 20.0, p)
    assert (e, s) == (4000.0, 4040.6) and abs(r - 40.6) < 1e-9 and abs(t - (e - 2 * r)) < 1e-9

def test_truncation_and_future_rewrite_do_not_change_earlier_trades(real_slice):
    cut = pd.Timestamp("2021-12-01", tz="UTC")
    full = run(real_slice)
    wild = real_slice.copy(); wild.loc[cut:, ["open", "high", "low", "close"]] *= 1.4
    for other in (run(real_slice.loc[:cut]), run(wild)):
        a = full[full.exit_t < cut - pd.Timedelta("1D")].reset_index(drop=True)
        b = other[other.exit_t < cut - pd.Timedelta("1D")].reset_index(drop=True)
        assert len(a) > 5
        pd.testing.assert_frame_equal(a, b)

def test_entry_after_bar_close_one_position_and_costs(real_slice):
    p = H4Params(); f = h4_features(real_slice, p)
    sig_ends = set(f.end[signals(f) != 0])
    tr = run(real_slice, p, feats=f)
    assert tr.t.isin(sig_ends).mean() > 0.9 and (tr.t.dt.minute == 0).all()
    assert (tr.t.values[1:] > tr.exit_t.values[:-1]).all()
    assert run(real_slice, H4Params(spread=0, extra=0)).pnl.sum() > tr.pnl.sum()
