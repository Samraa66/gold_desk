"""Move memory (desk v3.1): synthetic paths with known moves, legs and pullbacks."""
import numpy as np
import pandas as pd

from gold_agents import moves
from gold_agents.data import resample

T0 = pd.Timestamp("2026-10-12T00:00:00Z")       # a Monday


def path(anchors, wiggle=0.1):
    """Minute bars along straight lines between (hours after T0, price) anchors."""
    hrs = np.array([a[0] for a in anchors], dtype=float)
    px = np.array([a[1] for a in anchors], dtype=float)
    n = int(hrs[-1] * 60)
    idx = pd.date_range(T0, periods=n, freq="min", tz="UTC")
    close = np.interp(np.arange(1, n + 1) / 60, hrs, px)
    open_ = np.concatenate([[px[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wiggle, "low": np.minimum(open_, close) - wiggle,
                         "close": close, "spread": 0.2}, index=idx)


def tfs(m1):
    as_of = m1.index[-1] + pd.Timedelta(minutes=1)
    return {name: resample(m1, name, as_of) for name in ("M15", "H1")}, as_of


# lower highs and lower lows on H1, a top at +30 h, then three legs down with one-hour pullbacks too small to be H1 swings
FALLING = [(0, 4100), (6, 4140), (12, 4080), (18, 4120), (24, 4060), (30, 4100),
           (33, 4060), (34, 4070), (37, 4030), (38, 4040), (41, 4000), (42, 4005)]


def test_move_on_a_falling_day():
    tf, as_of = tfs(path(FALLING))
    m = moves.current(tf, as_of, atr_d1=50.0, scored=[])
    assert m["direction"] == "down" and m["legs"] == 3 and m["pullbacks"] >= 2
    assert pd.Timestamp(m["started_at"]) == T0 + pd.Timedelta(hours=29) and abs(m["start_price"] - 4100) < 1   # the +30 h top's H1 bar
    assert 99 <= m["size"] <= 101 and m["size_atr_d1"] == round(m["size"] / 50.0, 2)
    assert abs(m["last_close"] - 4005) < 1


def test_no_move_in_a_range():
    rng = [(0, 4100), (6, 4130), (12, 4080), (18, 4140), (24, 4070), (30, 4110), (31, 4105)]   # higher highs with lower lows
    tf, as_of = tfs(path(rng))
    m = moves.current(tf, as_of, atr_d1=50.0, scored=[])
    assert m["direction"] == "none" and m["legs"] == 0 and m["started_at"] is None


def call(at, direction, outcome, r=None):
    return {"as_of": str(at), "decision": direction, "plan": {"entry": 4050.0, "stop": 4060.0, "tp1": 4035.0},
            "scores": {"master": {"outcome": outcome, "r": r}}}


def test_calls_on_this_move_only():
    tf, as_of = tfs(path(FALLING))
    before = call(T0 + pd.Timedelta(hours=20), "SELL", "loss", -1.1)
    leg1 = call(T0 + pd.Timedelta(hours=32), "SELL", "win", 1.4)
    now = call(T0 + pd.Timedelta(hours=39), "SELL", "open")
    passed = {**call(T0 + pd.Timedelta(hours=35), "SELL", "open"), "decision": "PASS"}
    m = moves.current(tf, as_of, atr_d1=50.0, scored=[before, leg1, now, passed])
    assert [c["as_of"] for c in m["calls"]] == [leg1["as_of"], now["as_of"]]
    assert m["calls"][0] == {"as_of": leg1["as_of"], "direction": "SELL", "entry": 4050.0, "outcome": "win", "r": 1.4}
    assert [o["as_of"] for o in m["open"]] == [now["as_of"]]
