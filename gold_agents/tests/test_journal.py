import pandas as pd

from gold_agents import journal as J
from gold_agents.config import Config

CFG = Config()           # spread 0.60, slippage 0.30
T0 = pd.Timestamp("2026-10-12T10:00:00Z")


def bars(rows, spread=0.2):
    idx = pd.date_range(T0, periods=len(rows), freq="min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(spread=spread)


def plan(entry=100.0, stop=90.0, tp1=120.0, tp2=130.0):
    return {"entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2}


def test_buy_win_pays_costs():
    b = bars([[100, 101, 99.5, 100.5], [100.5, 121, 100, 120]])
    s = J.score_plan("BUY", plan(), T0, b, CFG, T0 + pd.Timedelta(hours=1))
    # filled at open + spread + slip = 100.9; exit at 120 -> 19.1 on 10 risk
    assert s["outcome"] == "win" and s["r"] == 1.91


def test_stop_wins_a_tie_within_one_bar():
    b = bars([[100, 125, 85, 100]])
    s = J.score_plan("BUY", plan(), T0, b, CFG, T0 + pd.Timedelta(hours=1))
    assert s["outcome"] == "loss" and "counted as the stop" in s["note"]


def test_sell_stop_is_checked_against_the_ask():
    # high 109.5 + spread 0.6 = 110.1 >= stop 110 : a short is stopped although the bid never reached 110
    b = bars([[100, 109.5, 99, 105]])
    s = J.score_plan("SELL", plan(entry=100, stop=110, tp1=80, tp2=70), T0, b, CFG, T0 + pd.Timedelta(hours=1))
    assert s["outcome"] == "loss" and s["r"] < -1.0


def test_sell_win():
    b = bars([[100, 100.5, 79, 80]])
    s = J.score_plan("SELL", plan(entry=100, stop=110, tp1=80, tp2=70), T0, b, CFG, T0 + pd.Timedelta(hours=1))
    assert s["outcome"] == "win"


def test_only_bars_closed_by_now_count():
    b = bars([[100, 101, 99.5, 100.5], [100.5, 121, 100, 120]])
    s = J.score_plan("BUY", plan(), T0, b, CFG, T0 + pd.Timedelta(minutes=1))     # second bar not closed yet
    assert s["outcome"] == "open"
    assert J.score_plan("BUY", plan(), T0, b, CFG, T0)["outcome"] == "pending"


def test_expiry_marks_to_market():
    cfg = Config(expiry_hours=1.0)
    idx = pd.date_range(T0, periods=90, freq="min", tz="UTC")
    b = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "spread": 0.2}, index=idx)
    s = J.score_plan("BUY", plan(), T0, b, cfg, T0 + pd.Timedelta(minutes=90))
    assert s["outcome"] == "expired" and s["r"] < 0       # the cost of getting in and out, nothing else moved


def test_append_is_idempotent_and_never_rewrites(tmp_path):
    p = tmp_path / "calls.jsonl"
    e = {"id": "a", "as_of": str(T0), "decision": "PASS"}
    assert J.append(e, p) is True and J.append({**e, "decision": "BUY"}, p) is False
    assert J.load(p) == [e]


def test_state_counts_open_and_today_realised():
    e1 = {"as_of": str(T0), "decision": "BUY", "scores": {"master": {"outcome": "loss", "r": -1.1, "closed_at": str(T0 + pd.Timedelta(hours=1))}}}
    e2 = {"as_of": str(T0 + pd.Timedelta(hours=2)), "decision": "SELL", "scores": {"master": {"outcome": "open", "r": None}}}
    st = J.state_at([e1, e2], T0 + pd.Timedelta(hours=3))
    assert st["open_calls"] == 1 and st["realised_r_today"] == -1.1
    assert set(st["last_call_by_side"]) == {"BUY", "SELL"}


def test_summary_uses_resolved_calls_only():
    sc = [{"decision": "BUY", "scores": {"master": {"outcome": "win", "r": 1.9}}},
          {"decision": "BUY", "scores": {"master": {"outcome": "loss", "r": -1.1}}},
          {"decision": "SELL", "scores": {"master": {"outcome": "open", "r": None}}},
          {"decision": "PASS", "scores": {}}]
    s = J.summarize(sc)
    assert s["passes"] == 1 and s["master"]["resolved"] == 2 and s["master"]["still_open"] == 1 and s["master"]["total_r"] == 0.8


def test_scorer_is_not_biased_on_a_driftless_walk():
    """Zero-cost, always-BUY calls on a random walk should win about a third of the time (stop 1.5 ATR, target 3 ATR,
    some expire). A scorer that tilts the odds would show up here."""
    from gold_agents.agents import risk
    from gold_agents.context import build_context
    from tests.conftest import make_m1
    m = make_m1(days=150, seed=21)
    cfg = Config(spread_assumed=0.0, slippage_assumed=0.0)
    wins = n = 0
    for t in pd.date_range("2026-09-01", "2026-10-10", freq="3h", tz="UTC"):
        if t.weekday() >= 5:
            continue
        p, _ = risk.size_plan(build_context(m, t, cfg, None, [], None), "BUY")
        s = J.score_plan("BUY", p.to_dict(), t, m, cfg, pd.Timestamp("2026-10-25", tz="UTC"))
        if s["outcome"] in ("win", "loss", "expired"):
            n += 1
            wins += s["outcome"] == "win"
    assert n > 80 and 0.2 < wins / n < 0.42
