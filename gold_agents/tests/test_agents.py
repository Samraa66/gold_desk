import pandas as pd
import pytest

from gold_agents import calendar as cal
from gold_agents.agents import chart, liquidity, macro, master, risk
from gold_agents.config import Config
from gold_agents.context import build_context
from gold_agents.llm import FakeLLM, parse_json
from gold_agents.runner import decide_at
from tests.conftest import make_m1

CFG = Config()
WED = pd.Timestamp("2026-09-02T14:00:00Z")           # Wednesday, London + New York overlap


def ctx_at(m1, t=WED, journal=None, events=None, **kw):
    return build_context(m1, t, kw.pop("cfg", CFG), None, events if events is not None else [], journal)


# ---------------- risk ----------------
def test_lots_come_from_contract_size(m1):
    rep, plans, blocked = risk.run(ctx_at(m1))
    p = plans["BUY"]
    assert p.risk_per_lot == pytest.approx(abs(p.entry - p.stop) * 100, rel=1e-3)
    assert p.risk_usd <= CFG.equity * CFG.risk_pct / 100 + 1e-9
    assert plans["SELL"].stop > plans["SELL"].entry > plans["SELL"].tp1


def test_tp1_is_r_multiple(m1):
    _, plans, _ = risk.run(ctx_at(m1))
    p = plans["BUY"]
    assert (p.tp1 - p.entry) == pytest.approx((p.entry - p.stop) * CFG.tp1_r, abs=0.02)


def test_daily_loss_limit_blocks(m1):
    rep, _, blocked = risk.run(ctx_at(m1, journal={"realised_r_today": -2.5}))
    assert rep.veto and "daily loss limit" in blocked["BUY"]


def test_open_call_limit_blocks(m1):
    rep, _, blocked = risk.run(ctx_at(m1, journal={"open_calls": 2}))
    assert rep.veto


def test_cooldown_blocks_only_the_same_side(m1):
    rep, _, blocked = risk.run(ctx_at(m1, journal={"last_call_by_side": {"BUY": WED - pd.Timedelta(hours=1)}}))
    assert blocked["BUY"] and blocked["SELL"] is None and not rep.veto


def test_tiny_equity_cannot_size(m1):
    rep, plans, blocked = risk.run(ctx_at(m1, cfg=Config(equity=100.0)))
    assert plans["BUY"] is None and rep.veto


# ---------------- liquidity ----------------
def test_weekend_is_vetoed(m1):
    r = liquidity.run(ctx_at(m1, t=pd.Timestamp("2026-09-05T12:00:00Z")))        # Saturday
    assert r.veto and "weekend" in r.summary


def test_rollover_is_vetoed(m1):
    assert liquidity.run(ctx_at(m1, t=pd.Timestamp("2026-09-02T21:30:00Z"))).veto


def test_event_window_is_vetoed_and_clears_after(m1):
    ev = [{"time": WED.to_pydatetime(), "name": "US CPI", "impact": "high"}]
    assert liquidity.run(ctx_at(m1, events=ev)).veto
    later = [{"time": (WED - pd.Timedelta(hours=2)).to_pydatetime(), "name": "US CPI", "impact": "high"}]
    assert not liquidity.run(ctx_at(m1, events=later)).veto


def test_low_impact_event_does_not_block(m1):
    ev = [{"time": WED.to_pydatetime(), "name": "minor", "impact": "low"}]
    assert not liquidity.run(ctx_at(m1, events=ev)).veto


def test_stale_bars_are_vetoed(m1):
    stale = m1.loc[: WED - pd.Timedelta(hours=3)]
    assert "stale" in liquidity.run(ctx_at(stale)).summary


def test_wide_spread_is_vetoed():
    m = make_m1(days=100)
    m.loc[m.index >= WED - pd.Timedelta(minutes=20), "spread"] = 1.5
    assert "spread" in liquidity.run(ctx_at(m)).summary


# ---------------- calendar ----------------
def test_nfp_is_830_new_york_in_both_dst_regimes():
    summer = [e for e in cal.builtin_events(pd.Timestamp("2026-07-01", tz="UTC").to_pydatetime(), pd.Timestamp("2026-07-31", tz="UTC").to_pydatetime())
              if "payrolls" in e["name"]][0]
    winter = [e for e in cal.builtin_events(pd.Timestamp("2026-12-01", tz="UTC").to_pydatetime(), pd.Timestamp("2026-12-31", tz="UTC").to_pydatetime())
              if "payrolls" in e["name"]][0]
    assert (summer["time"].hour, summer["time"].day) == (12, 3) and (winter["time"].hour, winter["time"].day) == (13, 4)


# ---------------- chart / macro ----------------
def test_chart_follows_a_clear_trend():
    up = make_m1(drift=0.04, seed=3, days=150)
    r = chart.run(ctx_at(up, t=pd.Timestamp("2026-10-01T14:00:00Z")))
    assert r.score > 0 and r.side == "long"


def test_chart_abstains_when_weak():
    r = chart.run(ctx_at(make_m1(seed=11, days=150), t=pd.Timestamp("2026-10-01T14:00:00Z")))
    assert r.score == 0.0 or abs(r.score) >= CFG.chart_min_score


def test_macro_without_data_abstains(m1):
    r = macro.run(ctx_at(m1))
    assert r.score == 0.0 and "no macro data" in r.summary


def test_macro_rules_lean_against_a_strong_dollar_and_rising_yields(m1):
    idx = pd.date_range("2026-08-01", periods=40, freq="D", tz="UTC")
    df = pd.DataFrame({"dxy": [100 + i * 0.2 for i in range(40)], "us10y": [4.0 + i * 0.02 for i in range(40)],
                       "vix": 15.0, "spx": 5000.0, "silver": 30.0}, index=idx)
    c = build_context(m1, WED, CFG, df, [], None)
    assert macro.run(c).score < -0.4


# ---------------- master ----------------
def _reports(chart_s=0.6, macro_s=0.2, liq_veto=False):
    from gold_agents.types import Report
    return {"chart": Report("chart", chart_s, 0.6, "c"), "macro": Report("macro", macro_s, 0.3, "m"),
            "liquidity": Report("liquidity", 0.0, 1.0, "VETO: x" if liq_veto else "ok", veto=liq_veto), "risk": Report("risk", 0.0, 1.0, "r")}


def _plans(m1):
    return risk.run(ctx_at(m1))[1:]


def test_rules_master_trades_when_aligned(m1):
    plans, blocked = _plans(m1)
    d, why, plan, src = master.decide(ctx_at(m1), _reports(), plans, blocked)
    assert d == "BUY" and plan is plans["BUY"] and src == "rules"


def test_rules_master_passes_when_macro_opposes(m1):
    plans, blocked = _plans(m1)
    assert master.decide(ctx_at(m1), _reports(0.6, -0.5), plans, blocked)[0] == "PASS"


def test_a_liquidity_veto_is_final_and_skips_the_model(m1):
    plans, blocked = _plans(m1)
    llm = FakeLLM(default={"decision": "BUY", "confidence": 1.0, "reason": "go"})
    d = master.decide(ctx_at(m1), _reports(liq_veto=True), plans, blocked, llm)
    assert d[0] == "PASS" and llm.calls == []


def test_the_model_cannot_override_a_risk_block(m1):
    plans, _ = _plans(m1)
    blocked = {"BUY": "daily loss limit reached", "SELL": None}
    llm = FakeLLM(default={"decision": "BUY", "confidence": 0.95, "reason": "strong"})
    d = master.decide(ctx_at(m1), _reports(), plans, blocked, llm)
    assert d[0] == "PASS" and "risk blocks" in d[1]


def test_low_confidence_model_call_is_downgraded(m1):
    plans, blocked = _plans(m1)
    llm = FakeLLM(default={"decision": "SELL", "confidence": 0.4, "reason": "meh"})
    assert master.decide(ctx_at(m1), _reports(), plans, blocked, llm)[0] == "PASS"


def test_confident_model_call_goes_through_with_the_right_plan(m1):
    plans, blocked = _plans(m1)
    llm = FakeLLM(default={"decision": "SELL", "confidence": 0.8, "reason": "dollar strength"})
    d, why, plan, src = master.decide(ctx_at(m1), _reports(), plans, blocked, llm)
    assert d == "SELL" and plan is plans["SELL"] and src == CFG.deep_model


def test_garbage_model_decision_is_a_pass(m1):
    plans, blocked = _plans(m1)
    llm = FakeLLM(default={"decision": "MOON", "confidence": 1})
    assert master.decide(ctx_at(m1), _reports(), plans, blocked, llm)[0] == "PASS"


# ---------------- model seam ----------------
def test_parse_json_tolerates_fences_and_chatter():
    assert parse_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('here {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_model_scores_are_clamped_and_labelled(m1):
    llm = FakeLLM(default={"score": 7, "confidence": 3, "summary": "x"})
    r = chart.run(ctx_at(m1), llm)
    assert r.score == 1.0 and r.confidence == 1.0 and r.source == CFG.quick_model and "rules_score" in r.facts


def test_full_run_with_a_fake_model_logs_a_complete_call(trending):
    llm = FakeLLM(replies={"Master trader": {"decision": "BUY", "confidence": 0.9, "reason": "trend"}},
                  default={"score": 0.7, "confidence": 0.7, "summary": "up"})
    call = decide_at(trending, pd.Timestamp("2026-09-02T14:00:00Z"), CFG, llm=llm, events=[])
    assert call["mode"] == "llm" and call["decision"] in ("BUY", "PASS") and set(call["reports"]) == {"chart", "macro", "liquidity", "risk"}
    assert len(llm.calls) == 2          # chart + master; macro had no data, so it abstains without spending a call


def test_real_yield_reaches_the_macro_facts_when_present(m1):
    idx = pd.date_range("2026-08-01", periods=40, freq="D", tz="UTC")
    df = pd.DataFrame({"dxy": 100.0, "us10y": 4.0, "vix": 15.0, "spx": 5000.0, "silver": 30.0,
                       "real10y": [1.5 + i * 0.01 for i in range(40)]}, index=idx)
    f = macro.facts(build_context(m1, WED, CFG, df, [], None))
    assert f["real_yield_10y_pct"] == pytest.approx(1.89, abs=0.01) and f["real_yield_change_10d_pp"] == pytest.approx(0.10, abs=0.01)


def test_fred_is_skipped_without_a_key_and_parsed_with_one(monkeypatch, tmp_path):
    from gold_agents import macro_data
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(macro_data, "Path", lambda *a, **k: tmp_path / "none")   # no .env to find
    assert macro_data.fred_real_yield().empty

    class Resp:
        ok = True
        def raise_for_status(self): pass
        def json(self): return {"observations": [{"date": "2026-10-01", "value": "1.80"}, {"date": "2026-10-02", "value": "."}]}
    class Sess:
        def get(self, *a, **k): return Resp()
    monkeypatch.setenv("FRED_API_KEY", "k")
    s = macro_data.fred_real_yield(Sess())
    assert list(s.values) == [1.80]


def test_notify_is_a_noop_without_credentials(monkeypatch):
    from gold_agents import notify
    monkeypatch.delenv("GOLD_TG_TOKEN", raising=False)
    monkeypatch.setattr(notify, "_env", lambda name: None)
    assert notify.send("hi") is False


def test_stale_bars_are_caught_in_thin_hours_too(m1):
    thin_time = pd.Timestamp("2026-09-02T04:00:00Z")           # Asia-only hours
    stale = m1.loc[: thin_time - pd.Timedelta(hours=5)]
    r = liquidity.run(ctx_at(stale, t=thin_time))
    assert r.veto and "stale" in r.summary


def test_a_pass_still_records_the_chart_lean_as_a_shadow_baseline(trending):
    """Macro leaning hard against an uptrend makes the desk PASS; the chart's lean is still scored, the macro-filtered one is not."""
    t = pd.Timestamp("2026-09-02T14:00:00Z")
    idx = pd.date_range("2026-07-25", periods=40, freq="D", tz="UTC")
    macro_df = pd.DataFrame({"dxy": [100 + i * 0.2 for i in range(40)], "us10y": [4.0 + i * 0.02 for i in range(40)],
                             "vix": 15.0, "spx": 5000.0, "silver": 30.0}, index=idx)
    call = decide_at(trending, t, CFG, events=[], macro_df=macro_df)
    b = call["baselines"]
    assert call["decision"] == "PASS" and "chart_lean" in b and b["chart_lean"]["plan"]["lots"] > 0
    assert b["chart_lean"]["direction"] == "BUY" and "chart_macro" not in b
    # the shadow rows never change the rules in force
    assert call["rules_hash"] == decide_at(trending, t, CFG, events=[])["rules_hash"]


def test_shadow_baselines_are_scored_like_any_other_strategy(trending):
    from gold_agents import journal as J
    t = pd.Timestamp("2026-09-02T14:00:00Z")
    call = decide_at(trending, t, CFG, events=[])
    scored = J.score_entries([call], trending, CFG, t + pd.Timedelta(hours=60))
    for name in call["baselines"]:
        if call["baselines"][name]:
            assert name in scored[0]["scores"]
