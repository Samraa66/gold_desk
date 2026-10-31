"""Desk v3.1 (2026-10-31). Offline: no network, no key, no bars beyond the synthetic ones."""
import pandas as pd
import pytest

from gold_agents import desk_v2 as V2
from gold_agents import desk_v3 as V3
from gold_agents import instruments as I
from gold_agents.config import rules_hash

# Read once on 2026-10-31 from the code at the v3 baseline commit and pasted here. v3.1 must leave every one of them alone.
KNOWN_HASHES = {
    "v1": {"XAU_USD": "0eed0fd6", "XAG_USD": "d9bb2b05", "EUR_USD": "b87656d9", "GBP_USD": "1740076f"},
    "v2": {"XAU_USD": "80b98c11", "XAG_USD": "df6c1617", "EUR_USD": "969c1a3d", "GBP_USD": "f827a7ce"},
    "v3": "2bbfa4f5",
}


# ---------------- identity ----------------
def test_older_hashes_do_not_move():
    assert {k: rules_hash(s.config()) for k, s in I.INSTRUMENTS.items()} == KNOWN_HASHES["v1"]
    assert {k: V2.v2_hash(s.config()) for k, s in I.INSTRUMENTS.items()} == KNOWN_HASHES["v2"]
    assert V3.v3_hash(V3.config()) == KNOWN_HASHES["v3"]


# ---------------- Task 2: the scorer honours a plan's holding time and the Friday close ----------------
from gold_agents import journal as J  # noqa: E402
from gold_agents.config import Config  # noqa: E402


def minute_bars(spans):
    """spans = [(start, minutes, price)]: flat minute bars at `price`, 0.2 wide, with gaps wherever the spans leave them."""
    frames = []
    for start, n, px in spans:
        idx = pd.date_range(start, periods=n, freq="min", tz="UTC")
        frames.append(pd.DataFrame({"open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "spread": 0.2}, index=idx))
    return pd.concat(frames)


def sell(entry_type="market", **keys):
    p = {"direction": "SELL", "entry_type": entry_type, "entry": 4000.0, "stop": 4100.0, "tp1": 3800.0, "tp2": 3700.0, **keys}
    if entry_type == "limit":
        p["entry"], p["valid_until"] = 3999.95, "2026-10-14T18:00:00+00:00"
    return p


def test_plan_hold_overrides_expiry():
    bars = minute_bars([("2026-10-14T15:00:00Z", 240, 4000.0)])
    cfg = Config(expiry_hours=6.0)
    now = pd.Timestamp("2026-10-14T19:00:00Z")
    for et in ("market", "limit"):
        s = J.score_plan("SELL", sell(et, max_hold_hours=1.0), pd.Timestamp("2026-10-14T15:00:00Z"), bars, cfg, now)
        assert s["outcome"] == "expired", et
        assert pd.Timestamp(s["closed_at"]) == pd.Timestamp("2026-10-14T16:00:00Z"), et
    # without the key the 6 h config expiry still applies: nothing is closed after 4 h
    assert J.score_plan("SELL", sell(), pd.Timestamp("2026-10-14T15:00:00Z"), bars, cfg, now)["outcome"] == "open"


FRIDAY_WEEKEND = [("2026-10-30T19:00:00Z", 120, 3990.0), ("2026-11-01T23:00:00Z", 60, 3950.0)]   # Fri last bar 20:59, Sun reopen 23:00 UTC


def test_flat_by_ends_trade_before_weekend():
    bars = minute_bars(FRIDAY_WEEKEND)
    flat_by = "2026-10-30T21:00:00+00:00"
    for et, start in (("market", "2026-10-30T19:00:00Z"), ("limit", "2026-10-30T19:00:00Z")):
        plan = sell(et, max_hold_hours=24.0, flat_by=flat_by)
        if et == "limit":
            plan.update(entry=3989.95, valid_until="2026-10-31T01:00:00+00:00")
        s = J.score_plan("SELL", plan, pd.Timestamp(start), bars, Config(expiry_hours=24.0), pd.Timestamp("2026-11-02T00:00:00Z"))
        assert s["outcome"] == "expired", et
        assert pd.Timestamp(s["closed_at"]) <= pd.Timestamp(flat_by), et
        exit_px = 3990.0 + 0.6                                        # Friday's last bid close plus the spread, never Sunday's 3950
        fill = s["fill"]
        assert s["r"] == pytest.approx(round((fill - exit_px) / abs(plan["entry"] - plan["stop"]), 3)), et


def test_flat_by_with_no_bar_after_it_yet_still_closes():
    bars = minute_bars(FRIDAY_WEEKEND[:1])
    s = J.score_plan("SELL", sell(flat_by="2026-10-30T21:00:00+00:00"), pd.Timestamp("2026-10-30T19:00:00Z"), bars,
                     Config(expiry_hours=24.0), pd.Timestamp("2026-10-30T21:00:00Z"))
    assert s["outcome"] == "expired" and pd.Timestamp(s["closed_at"]) <= pd.Timestamp("2026-10-30T21:00:00Z")


def test_plan_without_new_keys_scores_as_before():
    """v1-v3 plans keep the old rule, Sunday open included: changing it would move their scores."""
    bars = minute_bars(FRIDAY_WEEKEND)
    s = J.score_plan("SELL", sell(), pd.Timestamp("2026-10-30T19:00:00Z"), bars, Config(expiry_hours=6.0),
                     pd.Timestamp("2026-11-02T00:00:00Z"))
    assert s["outcome"] == "expired" and s["closed_at"] == "2026-11-01 23:00:00+00:00"
    assert s["r"] == pytest.approx(round((3989.7 - 3950.6) / 100.0, 3))
