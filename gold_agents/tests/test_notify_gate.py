from gold_agents.__main__ import should_notify


def test_only_new_buy_or_sell_notifies():
    assert should_notify({"decision": "BUY"}, wrote=True, flag=True)
    assert should_notify({"decision": "SELL"}, wrote=True, flag=True)
    assert not should_notify({"decision": "PASS"}, wrote=True, flag=True)      # PASS would bury the entries
    assert not should_notify({"decision": "BUY"}, wrote=False, flag=True)      # a repeated slot is not re-sent
    assert not should_notify({"decision": "BUY"}, wrote=True, flag=False)


def test_watch_goes_out_only_from_the_model_call_for_a_logged_pass_with_a_lean():
    from gold_agents.__main__ import should_watch
    lean = {"decision": "PASS", "mode": "llm", "as_of": "2026-10-26T10:00:00+00:00", "reason": "macro against",
            "reports": {"liquidity": {"veto": False}},
            "baselines": {"chart_lean": {"direction": "SELL", "plan": {"entry": 4000.0, "stop": 4010.0, "tp1": 3980.0}}}}
    assert should_watch(lean, wrote=True, flag=True)
    assert not should_watch({**lean, "mode": "rules"}, wrote=True, flag=True)      # one message per slot, not two
    assert not should_watch(lean, wrote=False, flag=True)
    assert not should_watch(lean, wrote=True, flag=False)
    assert not should_watch({**lean, "reports": {"liquidity": {"veto": True}}}, wrote=True, flag=True)
    assert not should_watch({**lean, "baselines": {"chart_lean": None}}, wrote=True, flag=True)
