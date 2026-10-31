"""The move watcher (desk v3): looks at gold every 5 minutes and wakes the model only when something happened.

Plain rules, no model, so a quiet tick costs nothing. Why: on 2026-10-30 the fixed 06/10/14/18 UTC slots looked at 3,991
at 10:00 and at 3,920 at 14:00; the break of the 3,975-3,989 floor happened between them. A trigger is a reason to look,
never a reason to trade: the desk still decides.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from . import calendar as cal
from . import journal as J
from . import structure as S


@dataclass(frozen=True)
class Watch:
    """Part of the v3 hash; changing one starts a new record."""
    range_bars: int = 36              # a close beyond the range of the last 3 hours
    atr_bars: int = 14
    spike_mult: float = 2.5           # a bar this many times the normal M5 range
    min_poke: float = 0.25            # a level counts as crossed only this many normal M5 bars beyond it; less is chop
    cooldown_min: int = 30            # the same trigger on the same side does not wake the model again for this long
    max_wakes_day: int = 30           # triggers only; the 4 fixed slots do not count. 16 ran out before New York on 10-27
    stale_min: int = 15               # bars older than this mean the feed is down
    slots: tuple = (6, 10, 14, 18)


WATCH = Watch()


@dataclass(frozen=True)
class WatchV31:
    """Desk v3.1's watcher. A copy of `Watch` (left untouched, so v3's hash holds) plus other markets, gaps and news. Part of
    the v3.1 hash; changing one starts a new record."""
    range_bars: int = 36
    atr_bars: int = 14
    spike_mult: float = 2.5
    min_poke: float = 0.25
    cooldown_min: int = 30
    max_wakes_day: int = 30           # one budget across every trigger: gold, other markets and news
    stale_min: int = 15
    slots: tuple = (6, 10, 14, 18)
    cross_mult: float = 3.0           # a 5-minute bar in the dollar, bonds, S&P, oil or silver this many times its own normal
    gap_min: int = 30                 # bars further apart than this (beyond the 5 minutes) are a gap: weekend or daily break
    news_cooldown_min: int = 15       # a news trigger never wakes the desk this soon after any wake


WATCH_V31 = WatchV31()
# which trigger leads when several fire on one bar; v3.1's kinds come last, so v3's order is unchanged
ORDER = ("level_break", "range_break", "sweep", "spike", "gap", "cross_move", "news")


def triggers(m5: pd.DataFrame, levels: list[dict] | None = None, w: Watch = WATCH, gap_min: int | None = None) -> list[dict]:
    """What the last closed M5 bar did. `direction` is the side a trade would take, None when it says nothing.
    `gap_min` (desk v3.1): the first bar after a gap (weekend, daily break) is read as a gap and nothing else, because its
    break of a range or level is the market reopening, not a move; after it, the 3 h range counts only bars since the gap."""
    if len(m5) < w.atr_bars + 2:
        return []
    bar, prev = m5.iloc[-1], m5.iloc[-2]
    rng = float(bar["high"] - bar["low"])
    normal = float((m5["high"] - m5["low"]).iloc[-w.atr_bars - 1:-1].mean())
    recent = m5.iloc[-w.range_bars - 1:-1]
    if gap_min is not None:
        step = recent.index.to_series().diff() > pd.Timedelta(minutes=5 + gap_min)
        if m5.index[-1] - m5.index[-2] > pd.Timedelta(minutes=5 + gap_min):
            return gap_trigger(bar, prev, recent, normal, m5.index[-1] - m5.index[-2])
        if step.any():
            recent = recent.loc[step[step].index[-1]:]          # the range since the market reopened
    top, bottom = float(recent["high"].max()), float(recent["low"].min())
    out = []
    if len(recent) < 3:                                         # too soon after a gap for a range to mean anything
        top, bottom = float("inf"), float("-inf")
    if bar["close"] > top:
        out.append({"kind": "range_break", "direction": "BUY", "level": top, "name": "3h high"})
    elif bar["close"] < bottom:
        out.append({"kind": "range_break", "direction": "SELL", "level": bottom, "name": "3h low"})
    poke = w.min_poke * normal
    for lv in levels or []:
        p = lv["price"]
        if prev["close"] <= p and bar["close"] >= p + poke:
            out.append({"kind": "level_break", "direction": "BUY", "level": p, "name": lv["name"]})
        elif prev["close"] >= p and bar["close"] <= p - poke:
            out.append({"kind": "level_break", "direction": "SELL", "level": p, "name": lv["name"]})
        elif prev["close"] < p and bar["close"] < p and bar["high"] >= p + poke:
            out.append({"kind": "sweep", "direction": "SELL", "level": p, "name": lv["name"]})
        elif prev["close"] > p and bar["close"] > p and bar["low"] <= p - poke:
            out.append({"kind": "sweep", "direction": "BUY", "level": p, "name": lv["name"]})
    if normal and rng >= w.spike_mult * normal:
        body = float(bar["close"] - bar["open"])
        d = None if abs(body) < rng / 2 else ("BUY" if body > 0 else "SELL")
        out.append({"kind": "spike", "direction": d, "level": None, "name": f"{rng / normal:.1f}x the normal bar"})
    return sorted(out, key=lambda x: ORDER.index(x["kind"]))


def gap_trigger(bar, prev, recent: pd.DataFrame, normal: float, gap: pd.Timedelta) -> list[dict]:
    """The first bar after a gap: a `gap` trigger when it opened or closed beyond the range before the gap, or jumped at least
    one normal bar. No direction: a gap is a reason to look, never a side."""
    top, bottom = float(recent["high"].max()), float(recent["low"].min())
    jump = float(bar["open"] - prev["close"])
    outside = any(x > top or x < bottom for x in (float(bar["open"]), float(bar["close"])))
    if not outside and not (normal and abs(jump) >= normal):
        return []
    return [{"kind": "gap", "direction": None, "level": float(prev["close"]),
             "name": f"{gap.total_seconds() / 3600:.0f}h gap, opened {jump:+.2f} from the last close"}]


def cross_triggers(bars_by_market: dict, w: WatchV31 = WATCH_V31, now: pd.Timestamp | None = None) -> list[dict]:
    """Desk v3.1: a 5-minute bar in another market (the `CROSS` list in live_data) at least `cross_mult` times that market's own
    normal bar. No direction: it is a reason to look at gold, never a side. A dead or stale market is skipped, never guessed."""
    out = []
    for inst, b in (bars_by_market or {}).items():
        if b is None or len(b) < w.atr_bars + 2:
            continue
        if now is not None and now - (b.index[-1] + pd.Timedelta(minutes=5)) > pd.Timedelta(minutes=w.stale_min):
            continue
        ranges = b["high"] - b["low"]
        normal, rng = float(ranges.iloc[-w.atr_bars - 1:-1].mean()), float(ranges.iloc[-1])
        if normal > 0 and rng >= w.cross_mult * normal:
            out.append({"kind": "cross_move", "direction": None, "level": None, "name": f"{inst} {rng / normal:.1f}x its normal 5-min bar"})
    return out


def _key(t: dict) -> str:
    return f"{t['kind']}|{t['direction']}"


def _fresh(state: dict, now: pd.Timestamp) -> dict:
    day = str(now.date())
    if state.get("day") != day:
        state.update(day=day, wakes=0)
    state.setdefault("wakes", 0)
    state.setdefault("last", {})
    return state


def should_wake(trigs: list[dict], state: dict, now: pd.Timestamp, w: Watch = WATCH) -> tuple[bool, str]:
    _fresh(state, now)
    if not trigs:
        return False, "no trigger"
    if state["wakes"] >= w.max_wakes_day:
        return False, f"daily budget of {w.max_wakes_day} wakes used"
    cool = lambda t: _key(t) in state["last"] and now - pd.Timestamp(state["last"][_key(t)]) < pd.Timedelta(minutes=w.cooldown_min)
    news_cool = getattr(w, "news_cooldown_min", None)               # v3.1 only: a headline never wakes the desk twice in a row
    if news_cool is not None and state.get("last_wake"):
        just_woke = now - pd.Timestamp(state["last_wake"]) < pd.Timedelta(minutes=news_cool)
        cool = (lambda base: lambda t: base(t) or (t["kind"] == "news" and just_woke))(cool)
    if all(cool(t) for t in trigs):
        return False, "cooling down"
    return True, "trigger"


def record_wake(trigs: list[dict], state: dict, now: pd.Timestamp) -> None:
    _fresh(state, now)
    state["wakes"] += 1
    state["last_wake"] = now.isoformat()
    for t in trigs:
        state["last"][_key(t)] = now.isoformat()


def slot_due(now: pd.Timestamp, w: Watch = WATCH) -> bool:
    return now.hour in w.slots and now.minute < 5


def load_state(path: Path) -> dict:
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def tick(now: pd.Timestamp, fetch, wake, state_path: Path, log_path: Path, w: Watch = WATCH, window=cal.market_window,
         thin_sleeps: bool = True, extra=None) -> str:
    """One 5-minute look. `fetch()` -> closed M5 bars; `wake(trigger or None, now)` runs the desk. -> what happened.
    v3.1 passes `window=calendar.desk_window` (New York hours, the daily `break` shut), `thin_sleeps=False` (it watches Asia
    hours and Sunday's reopen too) and `extra()` -> more triggers (other markets). The defaults are v3's behaviour."""
    state_now = window(now.to_pydatetime())[0]
    if state_now in ("closed", "rollover", "break"):
        return "market shut"
    if state_now == "thin" and thin_sleeps and not slot_due(now, w):   # v3: Asia-only hours, the budget is for London and New York
        return "thin hours"
    bars = fetch()
    if bars.empty or now - (bars.index[-1] + pd.Timedelta(minutes=5)) > pd.Timedelta(minutes=w.stale_min):
        return "no fresh bars"
    trigs = triggers(bars, S.key_levels(bars), w, gap_min=getattr(w, "gap_min", None))
    if extra is not None:
        trigs = sorted(trigs + list(extra() or []), key=lambda x: ORDER.index(x["kind"]))
    slot = slot_due(now, w)
    if not trigs and not slot:
        return "quiet"
    state = load_state(state_path)
    ok, why = should_wake(trigs, state, now, w)
    J._append_lines(Path(log_path), [{"at": now.isoformat(), "price": float(bars["close"].iloc[-1]), "triggers": trigs, "slot": slot,
                                      "woke": bool(ok or slot), "why": why, "state_wakes": state.get("wakes", 0)}])
    if ok:
        record_wake(trigs, state, now)
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(state))
    if ok or slot:
        wake(trigs[0] if ok else None, now)
        return "woke"
    return why


def params(w: Watch | WatchV31 = WATCH) -> dict:
    return asdict(w)
