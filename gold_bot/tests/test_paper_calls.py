import numpy as np
import pandas as pd
from src.h4 import H4Params
from src.paper_calls import log_calls, score, summary, new_calls, rule_hash, LATE_HOURS

def synth(minutes=4 * 60 * 60, spike_at=None):
    idx = pd.date_range("2024-01-01", periods=minutes, freq="1min", tz="UTC")
    c = np.full(minutes, 100.0) + np.sin(np.arange(minutes) / 500.0)
    if spike_at: c[spike_at:] += 60
    return pd.DataFrame({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c}, index=idx)

START = pd.Timestamp("2024-01-02", tz="UTC")

def test_calls_only_after_forward_start_and_append_only(tmp_path):
    m1 = synth(spike_at=60 * 200)
    path = tmp_path / "calls.csv"
    p = H4Params()
    assert new_calls(m1, p, pd.Timestamp("2030-01-01", tz="UTC")).empty
    n1 = log_calls(m1, p, START, now=pd.Timestamp("2024-01-10", tz="UTC"), path=path)
    before = path.read_text()
    n2 = log_calls(m1, p, START, now=pd.Timestamp("2024-02-10", tz="UTC"), path=path)   # run again: nothing new, nothing edited
    assert n1 >= 1 and n2 == 0 and path.read_text() == before

def test_late_logged_calls_are_flagged(tmp_path):
    m1 = synth(spike_at=60 * 200); path = tmp_path / "c.csv"
    log_calls(m1, H4Params(), START, now=pd.Timestamp("2024-03-01", tz="UTC"), path=path)
    d = pd.read_csv(path)
    assert d.late.all() and (d.lag_hours > LATE_HOURS).all()

def test_new_data_appends_only_new_calls(tmp_path):
    m1 = synth(spike_at=60 * 200); path = tmp_path / "c.csv"
    half = m1.iloc[:60 * 220]
    a = log_calls(half, H4Params(), START, now=pd.Timestamp("2024-01-05", tz="UTC"), path=path)
    first = path.read_text().splitlines()
    b = log_calls(m1.iloc[:60 * 260 + 5], H4Params(), START, now=pd.Timestamp("2024-01-06", tz="UTC"), path=path)
    assert a >= 1 and path.read_text().splitlines()[:len(first)] == first      # earlier rows untouched

def test_score_resolves_and_open_calls_are_not_scored(tmp_path):
    m1 = synth(spike_at=60 * 200); path = tmp_path / "c.csv"
    log_calls(m1, H4Params(), START, now=pd.Timestamp("2024-01-05", tz="UTC"), path=path)
    res = score(m1, H4Params(), path)
    assert len(res) >= 1 and set(res.status) <= {"stop", "target", "time", "open", "skipped", "no data yet"}
    cut = score(m1.iloc[:60 * 202], H4Params(), path)       # the future is not there yet: the outcome must be unknown
    assert cut.r.isna().all()

def test_summary_refuses_to_judge_a_short_streak():
    res = pd.DataFrame({"r": [2.0] * 5, "late": [False] * 5})
    assert "Too few to judge" in summary(res)

def test_rule_hash_changes_when_params_change():
    assert rule_hash(H4Params()) != rule_hash(H4Params(lookback=21))

def test_empty_log_scores_and_summarises_cleanly(tmp_path):
    m1 = synth()
    res = score(m1, H4Params(), tmp_path / "does_not_exist.csv")
    assert res.empty and "0 on-time calls resolved" in summary(res)

def test_late_calls_never_count_toward_the_verdict():
    res = pd.DataFrame({"r": [3.0] * 40, "late": [True] * 40})
    msg = summary(res)
    assert "0 on-time calls resolved" in msg and "Meets" not in msg


def test_current_state_never_reports_a_bar_that_is_still_forming():
    from src.paper_calls import current_state
    m1 = synth(minutes=60 * 24 * 3)
    m1 = m1.iloc[: 60 * 50 + 20]                    # stops 20 min into an H4 bar (bar 48h-52h is open)
    msg = current_state(m1, H4Params())
    assert "2024-01-03 00:00" in msg and "04:00" not in msg.split("ends")[1][:20]
