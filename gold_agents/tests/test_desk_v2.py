import pandas as pd
import pytest

from gold_agents import desk_v2 as V
from gold_agents import journal as J
from gold_agents import structure as S
from gold_agents.config import Config, rules_hash
from gold_agents.context import build_context
from gold_agents.llm import FakeLLM
from tests.conftest import make_m1

CFG = Config()
WED = pd.Timestamp("2026-09-02T14:00:00Z")
T0 = pd.Timestamp("2026-10-12T10:00:00Z")


def bars(rows, spread=0.2):
    idx = pd.date_range(T0, periods=len(rows), freq="min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(spread=spread)


def ohlc(highs, lows):
    idx = pd.date_range("2026-09-01", periods=len(highs), freq="4h", tz="UTC")
    return pd.DataFrame({"open": lows, "high": highs, "low": lows, "close": highs}, index=idx)


# ---------------- v1 is untouched ----------------
def test_v1_gold_hash_is_unchanged():
    assert rules_hash(Config()) == "0eed0fd6"


def test_v2_has_its_own_hash():
    assert V.v2_hash(CFG) != rules_hash(CFG)
    assert V.v2_hash(CFG) != V.v2_hash(CFG, V.V2(min_rr=2.0))


# ---------------- structure ----------------
def test_swings_find_a_peak_and_a_trough():
    b = ohlc([10, 11, 15, 11, 10, 9, 10, 11], [5, 6, 7, 6, 2, 4, 5, 6])
    sw = S.swings(b, k=2)
    assert {"kind": "H", "price": 15.0} in [{k: s[k] for k in ("kind", "price")} for s in sw]
    assert {"kind": "L", "price": 2.0} in [{k: s[k] for k in ("kind", "price")} for s in sw]


def test_pattern_reads_lower_highs_and_lower_lows():
    sw = [{"kind": "H", "price": 20}, {"kind": "L", "price": 10}, {"kind": "H", "price": 18}, {"kind": "L", "price": 8}]
    p = S.pattern(sw)
    assert p["highs"] == "lower_high" and p["lows"] == "lower_low" and p["bias"] == -1


def test_zones_count_touches_of_a_tested_floor():
    t = pd.Timestamp("2026-10-23", tz="UTC")
    pts = [{"time": t, "kind": "L", "price": p} for p in (3975.4, 3978.0, 3981.0)] + [{"time": t, "kind": "H", "price": 4070.0}]
    zs = S.zones(pts, tol=10.0, price=4040.0)
    floor = next(z for z in zs if z["side"] == "support")
    assert floor["touches"] == 3 and floor["lo"] == 3975.4 and floor["hi"] == 3981.0
    assert next(z for z in zs if z["side"] == "resistance")["touches"] == 1


def test_bars_text_has_one_line_per_bar():
    txt = S.bars_text(ohlc([1.0, 2.0, 3.0], [0.5, 1.0, 2.0]), 2)
    assert len(txt.splitlines()) == 3 and txt.splitlines()[-1].endswith("3.00")


# ---------------- the pending-order scorer ----------------
def lim(direction="SELL", entry=110.0, stop=115.0, tp1=100.0, tp2=95.0, et="limit", hours=1):
    return {"entry_type": et, "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2,
            "valid_until": str(T0 + pd.Timedelta(hours=hours))}


def test_sell_limit_never_reached_is_unfilled():
    b = bars([[100, 105, 99, 104]] * 70)
    s = J.score_plan("SELL", lim(), T0, b, CFG, T0 + pd.Timedelta(minutes=70))
    assert s["outcome"] == "unfilled" and s["r"] is None


def test_sell_limit_waits_while_valid():
    b = bars([[100, 105, 99, 104]] * 10)
    assert J.score_plan("SELL", lim(), T0, b, CFG, T0 + pd.Timedelta(minutes=10))["outcome"] == "waiting"


def test_sell_limit_fills_at_its_price_then_wins():
    b = bars([[100, 105, 99, 104], [104, 110.5, 104, 109], [109, 109, 99, 99.5]])
    s = J.score_plan("SELL", lim(), T0, b, CFG, T0 + pd.Timedelta(minutes=3))
    # fill 110 - 0.30 slip = 109.7; TP1 100 -> 9.7 on 5 risk
    assert s["outcome"] == "win" and s["fill"] == pytest.approx(109.7) and s["r"] == pytest.approx(1.94)


def test_fill_and_stop_in_one_bar_is_a_loss():
    b = bars([[104, 116, 104, 112]])
    s = J.score_plan("SELL", lim(), T0, b, CFG, T0 + pd.Timedelta(minutes=1))
    assert s["outcome"] == "loss" and "same bar" in s["note"]


def test_target_in_the_fill_bar_does_not_pay():
    b = bars([[104, 110.5, 99, 100]])          # touches entry and TP1 in the same minute
    s = J.score_plan("SELL", lim(), T0, b, CFG, T0 + pd.Timedelta(minutes=1))
    assert s["outcome"] == "open"


def test_sell_stop_gap_fills_at_the_worse_open():
    p = lim(entry=95.0, stop=100.0, tp1=85.0, tp2=80.0, et="stop")
    b = bars([[97, 97.5, 96, 96.5], [93, 93.5, 92, 92.5]])        # gaps below 95
    s = J.score_plan("SELL", p, T0, b, CFG, T0 + pd.Timedelta(minutes=2))
    assert s["fill"] == pytest.approx(92.7)                        # open 93 - 0.30 slip, not 95


def test_market_plans_score_exactly_as_before():
    b = bars([[100, 101, 99.5, 100.5], [100.5, 121, 100, 120]])
    p = {"entry": 100.0, "stop": 90.0, "tp1": 120.0, "tp2": 130.0}
    assert J.score_plan("BUY", p, T0, b, CFG, T0 + pd.Timedelta(hours=1)) == \
        J.score_plan("BUY", {**p, "entry_type": "market"}, T0, b, CFG, T0 + pd.Timedelta(hours=1))


def test_waiting_order_holds_a_slot_and_unfilled_does_not():
    e = {"as_of": str(T0), "decision": "SELL", "scores": {"master": {"outcome": "waiting", "r": None}}}
    u = {"as_of": str(T0), "decision": "SELL", "scores": {"master": {"outcome": "unfilled", "r": None}}}
    assert J.state_at([e], T0)["open_calls"] == 1 and J.state_at([u], T0)["open_calls"] == 0


# ---------------- setup checks ----------------
def ctx(m1):
    return build_context(m1, WED, CFG, None, [], {})


def test_sell_limit_below_price_is_rejected(m1):
    c = ctx(m1)
    s = {"direction": "SELL", "entry_type": "limit", "entry": c.price - 5, "stop": c.price + 10, "tp1": c.price - 40}
    plan, why = V.check_setup(c, s, V.V2_DEFAULT)
    assert plan is None and "above price" in why


def test_low_reward_setup_is_rejected(m1):
    c = ctx(m1)
    s = {"direction": "SELL", "entry_type": "limit", "entry": c.price + 2, "stop": c.price + 12, "tp1": c.price - 5}
    plan, why = V.check_setup(c, s, V.V2_DEFAULT)
    assert plan is None and "need 1.5R" in why


def test_good_limit_setup_is_sized_with_an_expiry(m1):
    c = ctx(m1)
    s = {"direction": "SELL", "entry_type": "limit", "entry": c.price + 3, "stop": c.price + 13, "tp1": c.price - 17, "valid_hours": 8}
    plan, why = V.check_setup(c, s, V.V2_DEFAULT)
    assert why is None and plan["entry_type"] == "limit" and plan["rr_tp1"] == pytest.approx(2.0, abs=0.01)
    assert pd.Timestamp(plan["valid_until"]) == WED + pd.Timedelta(hours=8) and plan["lots"] > 0


# ---------------- the desk ----------------
def test_model_sees_candles_and_no_rule_score(m1):
    fake = FakeLLM(default={"bias": 0, "confidence": 0.2, "read": "mid-range", "setup": {"entry_type": "none"},
                            "score": 0, "decision": "PASS", "reason": "no setup", "summary": "x"})
    call = V.decide_at(m1, WED, CFG, llm=fake, events=[])
    chart_prompt = next(c for c in fake.calls if "price structure" in c["system"])
    assert "CANDLES" in chart_prompt["user"] and "H4 last 60" in chart_prompt["user"]
    assert "rule_score" not in chart_prompt["user"] and "zones_nearest" in chart_prompt["user"]
    assert call["decision"] == "PASS" and call["desk"] == "v2"


def test_model_setup_becomes_the_call(m1):
    c = ctx(m1)
    setup = {"direction": "BUY", "entry_type": "limit", "entry": round(c.price - 4, 2), "stop": round(c.price - 14, 2),
             "tp1": round(c.price + 16, 2), "tp2": round(c.price + 30, 2), "valid_hours": 6, "why": "buy the retest"}
    fake = FakeLLM(replies={"price structure": {"bias": 0.6, "confidence": 0.7, "read": "higher lows", "setup": setup},
                            "Master trader": {"decision": "PLACE", "confidence": 0.8, "reason": "structure up"}},
                   default={"score": 0, "confidence": 0.1, "summary": "flat"})
    call = V.decide_at(m1, WED, CFG, llm=fake, events=[])
    assert call["decision"] == "BUY" and call["plan"]["entry_type"] == "limit"
    assert call["baselines"]["chart_setup"]["plan"] == call["plan"]
    assert "v2 BUY" in V.card(call) and "LIMIT" in V.card(call)


def test_v2_ignores_the_future():
    full = make_m1(days=150, seed=5)
    cut = full.loc[: WED - pd.Timedelta(minutes=1)]
    strip = lambda c: {k: v for k, v in c.items() if k != "id"}
    assert strip(V.decide_at(cut, WED, CFG, events=[])) == strip(V.decide_at(full, WED, CFG, events=[]))


def test_parse_json_takes_the_first_object_and_ignores_what_follows():
    from gold_agents.llm import parse_json
    assert parse_json('{"a": 1, "s": {"b": 2}}\nNote: {"x": 3}') == {"a": 1, "s": {"b": 2}}
    assert parse_json('Here you go: {"a": 1} {"a": 2}') == {"a": 1}
