"""Keeping everything (2026-10-29): every model call's prompt, reply and cost, and each call's final outcome frozen once.
The owner asked that every slot, PASS included, leave enough behind to improve the model later."""
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from gold_agents import desk_v2 as V
from gold_agents import journal as J
from gold_agents import llm as L
from gold_agents.config import Config
from gold_agents.llm import FakeLLM

CFG = Config()
WED = pd.Timestamp("2026-09-02T14:00:00Z")


class _Messages:
    def __init__(self, text, usage):
        self.text, self.usage = text, usage

    def create(self, **kw):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)], usage=self.usage)


def test_anthropic_llm_keeps_prompt_reply_tokens_and_cost():
    client = SimpleNamespace(messages=_Messages('{"bias": 0.2}', SimpleNamespace(input_tokens=1000, output_tokens=500)))
    llm = L.AnthropicLLM(client=client)
    assert llm.complete_json(model="claude-opus-5-5", system="SYS", user="USER", max_tokens=100, agent="chart") == {"bias": 0.2}
    rec = llm.records[0]
    assert (rec["agent"], rec["model"], rec["system"], rec["user"], rec["reply"]) == ("chart", "claude-opus-5-5", "SYS", "USER", '{"bias": 0.2}')
    assert rec["input_tokens"] == 1000 and rec["output_tokens"] == 500
    assert abs(rec["cost_usd"] - (1000 * 4 + 500 * 20) / 1e6) < 1e-12


def test_cost_uses_the_price_table_and_is_none_for_an_unknown_model():
    assert L.cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == 12.0
    assert L.cost_usd("some-other-model", 10, 10) is None


def test_usage_sums_the_calls_of_one_run():
    recs = [{"input_tokens": 100, "output_tokens": 10, "cost_usd": 0.5}, {"input_tokens": 50, "output_tokens": 5, "cost_usd": 0.25}]
    assert L.usage(recs) == {"calls": 2, "input_tokens": 150, "output_tokens": 15, "cost_usd": 0.75}


def test_v2_labels_each_model_call_with_its_agent(m1):
    from gold_agents.context import build_context
    price = build_context(m1, WED, CFG, None, [], {"open_calls": 0, "realised_r_today": 0.0, "last_call_by_side": {}}).price
    setup = {"direction": "BUY", "entry_type": "limit", "entry": round(price - 4, 2), "stop": round(price - 14, 2),
             "tp1": round(price + 16, 2), "tp2": round(price + 30, 2), "valid_hours": 6, "why": "retest"}
    fake = FakeLLM(replies={"price structure": {"bias": 0.6, "confidence": 0.7, "read": "up", "setup": setup},
                            "Master trader": {"decision": "PLACE", "confidence": 0.8, "reason": "ok"}},
                   default={"score": 0, "confidence": 0.1, "summary": "flat"})
    V.decide_at(m1, WED, CFG, llm=fake, events=[], v2=V.V2(counter_run=99, min_stop_atr_h1=0.0))
    agents = [c["agent"] for c in fake.calls]
    assert "chart" in agents and "master" in agents and all(agents)


def test_sidecar_files_sit_next_to_the_call_log_without_the_calls_prefix():
    # The Telelytics admin page reads calls*.jsonl; the sidecars must not match that pattern.
    assert J.sidecar(Path("j/calls_v2_eurusd.jsonl"), "prompts") == Path("j/prompts_v2_eurusd.jsonl")
    assert J.sidecar(Path("j/calls_v2.jsonl"), "outcomes") == Path("j/outcomes_v2.jsonl")


def test_save_prompts_writes_one_line_per_model_call(tmp_path):
    recs = [{"agent": "chart", "model": "m", "system": "s", "user": "u", "reply": "r", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.1}]
    J.save_prompts({"id": "X|llm|h", "as_of": "2026-10-29T14:00:00+00:00"}, recs, tmp_path / "calls_v2.jsonl")
    rows = J.load(tmp_path / "prompts_v2.jsonl")
    assert len(rows) == 1 and rows[0]["call_id"] == "X|llm|h" and rows[0]["agent"] == "chart" and rows[0]["user"] == "u"


def _scored(id_, decision, outcome, after):
    return {"id": id_, "as_of": "2026-10-29T10:00:00+00:00", "mode": "llm", "instrument": "XAU_USD", "decision": decision,
            "scores": {"chart_setup": {"outcome": outcome, "r": -1.0 if outcome == "loss" else None}}, "after": after}


def test_freeze_writes_an_outcome_once_and_only_when_it_is_final(tmp_path):
    log = tmp_path / "calls_v2.jsonl"
    done = _scored("a", "PASS", "loss", {"net_atr": 1.2})
    open_ = _scored("b", "PASS", "open", {"net_atr": 0.3})
    window_open = _scored("c", "PASS", "loss", None)            # 24 h after the PASS not over yet
    assert J.freeze_outcomes([done, open_, window_open], log) == 1
    assert J.freeze_outcomes([done, open_, window_open], log) == 0
    rows = J.load(J.sidecar(log, "outcomes"))
    assert [r["id"] for r in rows] == ["a"] and rows[0]["scores"]["chart_setup"]["outcome"] == "loss" and rows[0]["after"]["net_atr"] == 1.2


def test_scorecard_shows_the_days_model_spend(tmp_path, monkeypatch, m1):
    from gold_agents import reports
    call = V.decide_at(m1, WED, CFG, llm=FakeLLM(default={"bias": 0, "confidence": 0.2, "read": "x", "setup": {"entry_type": "none"},
                                                         "score": 0, "summary": "x"}), events=[])
    call["usage"] = {"calls": 2, "input_tokens": 9000, "output_tokens": 1500, "cost_usd": 0.066}
    path = tmp_path / "calls_v2.jsonl"
    J.append(call, path)
    monkeypatch.setattr(V, "journal_path", lambda spec: path if spec.oanda == "XAU_USD" else tmp_path / "none.jsonl")
    card = reports.scorecard(str(WED.date()), ["XAU_USD"], loader=lambda name: m1)
    assert "model spend today $0.07" in card


def test_a_logged_model_run_keeps_its_usage_and_prompts(tmp_path):
    from gold_agents.__main__ import keep_model_io
    llm = SimpleNamespace(records=[{"agent": "chart", "model": "claude-opus-5-5", "system": "s", "user": "u", "reply": "r",
                                    "input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.014}])
    call = {"id": "T|llm|h", "as_of": "2026-10-29T14:00:00+00:00"}
    log = tmp_path / "calls_v2.jsonl"
    keep_model_io(call, llm, log, wrote=False)
    assert call["usage"]["cost_usd"] == 0.014 and not J.sidecar(log, "prompts").exists()   # a repeat run saves no prompts
    keep_model_io(call, llm, log, wrote=True)
    assert J.load(J.sidecar(log, "prompts"))[0]["call_id"] == "T|llm|h"
    keep_model_io(call, None, log, wrote=True)                                               # rules run: nothing to keep
