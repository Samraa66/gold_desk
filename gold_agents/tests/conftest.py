import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_m1(start="2026-06-01", days=120, seed=1, drift=0.0, vol=0.35, base=4000.0, spread=0.25):
    """Synthetic UTC minute bars (weekdays only), a random walk with optional drift, bid-based, with a spread column."""
    idx = pd.date_range(start, periods=days * 24 * 60, freq="min", tz="UTC")
    idx = idx[idx.weekday < 5]
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(drift, vol, len(idx)))
    open_ = np.concatenate([[base], close[:-1]])
    wiggle = np.abs(rng.normal(0, vol * 0.6, len(idx)))
    df = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wiggle,
                       "low": np.minimum(open_, close) - wiggle, "close": close, "spread": spread}, index=idx)
    df.index.name = "time"
    return df


@pytest.fixture(scope="session")
def m1():
    return make_m1()


@pytest.fixture(scope="session")
def trending():
    return make_m1(drift=0.02, seed=3)
