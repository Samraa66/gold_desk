import pandas as pd

from gold_agents.config import Config
from gold_agents.runner import decide_at
from tests.conftest import make_m1

AS_OF = pd.Timestamp("2026-09-02T14:00:00Z")


def _strip(call):
    return {k: v for k, v in call.items() if k != "id"}


def test_decision_ignores_the_future():
    full = make_m1(days=150, seed=5)
    cut = full.loc[: AS_OF - pd.Timedelta(minutes=1)]
    a = decide_at(cut, AS_OF, Config())
    b = decide_at(full, AS_OF, Config())
    assert _strip(a) == _strip(b)


def test_the_still_forming_bar_is_not_used():
    full = make_m1(days=150, seed=5)
    forming = full.loc[: AS_OF]                 # includes the minute stamped exactly AS_OF (opens at AS_OF)
    same = full.loc[: AS_OF - pd.Timedelta(minutes=1)]
    assert _strip(decide_at(forming, AS_OF, Config())) == _strip(decide_at(same, AS_OF, Config()))
