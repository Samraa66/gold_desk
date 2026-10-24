import numpy as np
from src.engine import resolve_position

def bars(rows):
    a = np.array(rows, float)           # (high, low, close)
    return a[:, 0], a[:, 1], a[:, 2]

def test_long_target_hit():
    hi, lo, cl = bars([(0, 0, 0), (101, 99.5, 100.5), (103, 100, 102)])
    pnl, i, why = resolve_position(1, 100.6, 99.0, 102.6, hi, lo, cl, 0.6, 1, 3)
    assert (why, i) == ("target", 2) and abs(pnl - 2.0) < 1e-9

def test_long_stop_hit():
    hi, lo, cl = bars([(0, 0, 0), (100, 98, 99)])
    pnl, i, why = resolve_position(1, 100.6, 99.0, 102.6, hi, lo, cl, 0.6, 1, 2)
    assert why == "stop" and abs(pnl - (-1.6)) < 1e-9

def test_same_bar_touching_both_counts_as_stop():
    hi, lo, cl = bars([(0, 0, 0), (110, 90, 100)])
    _, _, why = resolve_position(1, 100.0, 95.0, 105.0, hi, lo, cl, 0.0, 1, 2)
    assert why == "stop"
    _, _, why = resolve_position(-1, 100.0, 105.0, 95.0, hi, lo, cl, 0.0, 1, 2)
    assert why == "stop"

def test_short_exits_on_the_ask():
    # bid high 104.5 + spread 0.6 = ask 105.1 >= stop 105.0 -> stopped, though bid never reached 105
    hi, lo, cl = bars([(0, 0, 0), (104.5, 100, 101)])
    pnl, _, why = resolve_position(-1, 100.0, 105.0, 90.0, hi, lo, cl, 0.6, 1, 2)
    assert why == "stop" and abs(pnl - (-5.0)) < 1e-9

def test_short_target_needs_ask_to_reach_it():
    # bid low 90.2 + 0.6 = ask 90.8: does not reach target 90.5
    hi, lo, cl = bars([(0, 0, 0), (95, 90.2, 91)])
    _, _, why = resolve_position(-1, 100.0, 105.0, 90.5, hi, lo, cl, 0.6, 1, 2)
    assert why == "time"

def test_time_exit_pays_spread_on_short_only():
    hi, lo, cl = bars([(0, 0, 0), (101, 99, 100.0)])
    pnl_s, _, _ = resolve_position(-1, 100.0, 110.0, 80.0, hi, lo, cl, 0.6, 1, 2)
    pnl_l, _, _ = resolve_position(1, 100.6, 90.0, 120.0, hi, lo, cl, 0.6, 1, 2)
    assert abs(pnl_s - (-0.6)) < 1e-9 and abs(pnl_l - (-0.6)) < 1e-9

def test_entry_bar_cannot_decide_its_own_exit():
    # bar 0 (the entry bar) has a huge range; search starts at bar 1 so it must be ignored
    hi, lo, cl = bars([(500, -500, 100), (100.1, 99.9, 100)])
    _, i, why = resolve_position(1, 100.0, 95.0, 105.0, hi, lo, cl, 0.0, 1, 2)
    assert why == "time" and i == 1
