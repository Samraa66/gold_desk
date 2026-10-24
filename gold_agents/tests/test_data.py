import pandas as pd

from gold_agents.data import closed_bars, resample
from tests.conftest import make_m1


def test_closed_bars_excludes_the_minute_that_starts_at_as_of():
    m = make_m1(days=5)
    t = pd.Timestamp("2026-06-03T10:00:00Z")
    c = closed_bars(m, t)
    assert c.index[-1] == pd.Timestamp("2026-06-03T09:59:00Z")


def test_resample_drops_the_forming_bar_and_aggregates_ohlc():
    m = make_m1(days=5)
    t = pd.Timestamp("2026-06-03T10:30:00Z")
    h1 = resample(closed_bars(m, t), "H1", t)
    assert h1.index[-1] == pd.Timestamp("2026-06-03T09:00:00Z")          # the 10:00 hour is still forming
    hour = m.loc["2026-06-03T09:00:00Z":"2026-06-03T09:59:00Z"]
    row = h1.loc["2026-06-03T09:00:00Z"]
    assert row["open"] == hour["open"].iloc[0] and row["close"] == hour["close"].iloc[-1]
    assert row["high"] == hour["high"].max() and row["low"] == hour["low"].min()
