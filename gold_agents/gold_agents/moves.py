"""Move memory for desk v3.1: where the current move started, how far it has gone, its legs and pullbacks, and the desk's own
calls on it. Plain rules from closed bars, shown to the chart agent on every wake.

Why: on 2026-10-30 gold fell $135 in legs. v3 had no memory of its own calls and no idea what kind of day it was, so it could
not re-enter a move on purpose. The move is read on two scales: H1 swings (k=3) mark the move, M15 swings (k=2) mark its legs.
No judgement here, only what a trader would count off the chart.
"""
from __future__ import annotations

import pandas as pd

from . import structure as S

OPEN = ("open", "pending", "waiting")


def _move_start(h1: pd.DataFrame, bias: int) -> dict | None:
    """The most recent H1 swing extreme against the bias: the last swing high of a down move, the last swing low of an up move."""
    kind = "H" if bias < 0 else "L"
    sw = [s for s in S.swings(h1.iloc[-96:], k=3) if s["kind"] == kind]
    return sw[-1] if sw else None


def _legs(m15: pd.DataFrame, start: dict, down: bool) -> tuple[int, int]:
    """(legs, pullbacks) after the start. A leg is a push to a new extreme the move's way; a pullback is an M15 swing against it
    after a leg. A new extreme after a pullback starts the next leg, confirmed or still running."""
    after = m15[m15.index > start["time"]]
    if after.empty:
        return 0, 0
    lead, back = ("L", "H") if down else ("H", "L")
    beyond = (lambda a, b: a < b) if down else (lambda a, b: a > b)
    legs, pullbacks, extreme, pulled = 0, 0, start["price"], False
    confirmed = S.swings(after, k=2)
    for s in confirmed:
        if s["kind"] == lead and beyond(s["price"], extreme):
            if legs == 0 or pulled:
                legs += 1
                pulled = False
            extreme = s["price"]
        elif s["kind"] == back and legs:
            pullbacks += 1
            pulled = True
    tail = after[after.index > confirmed[-1]["time"]] if confirmed else after
    run = float(tail["low"].min()) if down else float(tail["high"].max())
    if len(tail) and beyond(run, extreme) and (legs == 0 or pulled):
        legs += 1                                   # a leg under way that has not printed a confirmed swing yet
    return legs, pullbacks


def current(tf: dict, as_of, atr_d1: float | None, scored: list[dict]) -> dict:
    """The move in force at `as_of`. `tf` holds closed H1 and M15 bars; `scored` is the desk's own scored calls (one mode only).
    -> direction ("down", "up", "none"), started_at, start_price, size, size_atr_d1, legs, pullbacks, calls (this move's),
    open (every call still open or waiting), last_close."""
    h1, m15 = tf["H1"], tf["M15"]
    last_close = round(float(m15["close"].iloc[-1]), 2) if len(m15) else None
    open_now = [{"as_of": e["as_of"], "direction": e["decision"], "entry": (e.get("plan") or {}).get("entry"),
                 "stop": (e.get("plan") or {}).get("stop"), "tp1": (e.get("plan") or {}).get("tp1"),
                 "outcome": e["scores"]["master"]["outcome"]}
                for e in scored if e["decision"] in ("BUY", "SELL") and (e["scores"].get("master") or {}).get("outcome") in OPEN]
    none = {"direction": "none", "started_at": None, "start_price": None, "size": None, "size_atr_d1": None, "legs": 0,
            "pullbacks": 0, "calls": [], "open": open_now, "last_close": last_close}
    bias = S.pattern(S.swings(h1.iloc[-96:], k=3))["bias"] if len(h1) else 0
    if bias == 0:
        return none
    start = _move_start(h1, bias)
    if start is None:
        return none
    down = bias < 0
    after = m15[m15.index > start["time"]]
    far = 0.0
    if len(after):
        far = max((start["price"] - float(after["low"].min())) if down else (float(after["high"].max()) - start["price"]), 0.0)
    legs, pullbacks = _legs(m15, start, down)
    t0 = pd.Timestamp(start["time"])
    calls = [{"as_of": e["as_of"], "direction": e["decision"], "entry": (e.get("plan") or {}).get("entry"),
              "outcome": (e["scores"].get("master") or {}).get("outcome"), "r": (e["scores"].get("master") or {}).get("r")}
             for e in scored if e["decision"] in ("BUY", "SELL") and pd.Timestamp(e["as_of"]) >= t0]
    return {**none, "direction": "down" if down else "up", "started_at": str(t0), "start_price": round(start["price"], 2),
            "size": round(far, 2), "size_atr_d1": round(far / atr_d1, 2) if atr_d1 else None, "legs": legs, "pullbacks": pullbacks,
            "calls": calls}
