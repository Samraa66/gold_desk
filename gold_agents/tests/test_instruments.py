import pandas as pd

from gold_agents import instruments as I
from gold_agents.agents import risk
from gold_agents.agents.base import localise
from gold_agents.config import Config, rules_hash
from gold_agents.context import build_context
from tests.conftest import make_m1


def test_gold_rules_hash_is_the_one_the_live_log_was_written_under():
    assert rules_hash(Config()) == "0eed0fd6" == rules_hash(I.get("XAU_USD").config())


def test_every_instrument_has_its_own_hash_so_results_are_never_pooled():
    hashes = {k: rules_hash(v.config()) for k, v in I.INSTRUMENTS.items()}
    assert len(set(hashes.values())) == len(hashes)


def test_each_instrument_has_its_own_files_and_gold_keeps_the_original_log():
    assert I.get("XAU_USD").journal == "calls.jsonl"
    assert len({v.journal for v in I.INSTRUMENTS.values()}) == len(I.INSTRUMENTS)
    assert len({v.file for v in I.INSTRUMENTS.values()}) == len(I.INSTRUMENTS)


def test_fx_plan_is_sized_in_pips_and_rounded_to_five_places():
    spec = I.get("EUR_USD")
    m1 = make_m1(base=1.12, vol=0.00012, spread=0.00012, days=140)
    ctx = build_context(m1, pd.Timestamp("2026-09-02T14:00:00Z"), spec.config(), None, [], None)
    plan, why = risk.size_plan(ctx, "BUY")
    assert plan is not None, why
    assert 0.0008 <= plan.entry - plan.stop <= 0.0150
    assert round(plan.entry, 5) == plan.entry and abs(plan.risk_per_lot - (plan.entry - plan.stop) * 100_000) < 1.0
    assert plan.risk_usd <= 50.0 + 1e-6           # 0.5% of the 10,000 demo equity


def test_prompts_name_the_instrument_and_gold_text_is_untouched():
    t = "one analyst on a small gold (XAUUSD) trading desk; implies for gold"
    assert localise(t, Config()) == t
    assert localise(t, I.get("EUR_USD").config()) == "one analyst on a small EUR/USD trading desk; implies for EUR/USD"


def test_unknown_instrument_is_refused():
    import pytest
    with pytest.raises(SystemExit):
        I.get("DOGE_USD")
