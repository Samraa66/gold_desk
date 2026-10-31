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
ORDER = ("level_break", "range_break", "sweep", "spike")      # which trigger leads when several fire on one bar


def triggers(m5: pd.DataFrame, levels: list[dict] | None = None, w: Watch = WATCH) -> list[dict]:
    """What the last closed M5 bar did. `direction` is the side a trade would take, None when it says nothing."""
    if len(m5) < w.atr_bars + 2:
        return []
    bar, prev = m5.iloc[-1], m5.iloc[-2]
    rng = float(bar["high"] - bar["low"])
    normal = float((m5["high"] - m5["low"]).iloc[-w.atr_bars - 1:-1].mean())
    recent = m5.iloc[-w.range_bars - 1:-1]
    top, bottom = float(recent["high"].max()), float(recent["low"].min())
    out = []
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
    if all(cool(t) for t in trigs):
        return False, "cooling down"
    return True, "trigger"


def record_wake(trigs: list[dict], state: dict, now: pd.Timestamp) -> None:
    _fresh(state, now)
    state["wakes"] += 1
    for t in trigs:
        state["last"][_key(t)] = now.isoformat()


def slot_due(now: pd.Timestamp, w: Watch = WATCH) -> bool:
    return now.hour in w.slots and now.minute < 5


def load_state(path: Path) -> dict:
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def tick(now: pd.Timestamp, fetch, wake, state_path: Path, log_path: Path, w: Watch = WATCH) -> str:
    """One 5-minute look. `fetch()` -> closed M5 bars; `wake(trigger or None, now)` runs the desk. -> what happened."""
    window = cal.market_window(now.to_pydatetime())[0]
    if window in ("closed", "rollover"):
        return "market shut"
    if window == "thin" and not slot_due(now, w):          # Asia-only hours: wide spreads, and the budget is for London and New York
        return "thin hours"
    bars = fetch()
    if bars.empty or now - (bars.index[-1] + pd.Timedelta(minutes=5)) > pd.Timedelta(minutes=w.stale_min):
        return "no fresh bars"
    trigs = triggers(bars, S.key_levels(bars), w)
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


def params(w: Watch = WATCH) -> dict:
    return asdict(w)
