"""Shared fill logic for the research backtests (one place, so every script costs trades the same way).

Prices are the BID series; the ask is bid + a fixed spread. A buy pays the ask on entry and leaves on the
bid. A sell hits the bid on entry and leaves on the ask. A bar that touches both stop and target counts as
the STOP (worst case). Exits are only looked for on bars AFTER the entry bar, so the bar that produced the
signal can never also decide the exit.
"""
import numpy as np


def resolve_position(side: int, entry: float, stop: float, target: float, hi: np.ndarray, lo: np.ndarray,
                     cl: np.ndarray, spread: float, first: int, end: int):
    """Walk bars first..end-1 (bid hi/lo/close arrays) and return (pnl, exit_index, reason).

    side: +1 buy, -1 sell. entry/stop/target are in ask terms for a sell's entry already built by the caller
    (a sell's stop and target are compared with the ASK = bid + spread). reason: 'stop' | 'target' | 'time'.
    A window with no bars closes at the last close before `end` (entry bar's close if the window is empty).
    """
    if side == 1:
        s, t = lo[first:end] <= stop, hi[first:end] >= target
    else:
        s, t = hi[first:end] + spread >= stop, lo[first:end] + spread <= target
    si = int(s.argmax()) if s.any() else None
    ti = int(t.argmax()) if t.any() else None
    if si is not None and (ti is None or si <= ti):
        return side * (stop - entry), first + si, "stop"
    if ti is not None:
        return side * (target - entry), first + ti, "target"
    last = cl[end - 1] if side == 1 else cl[end - 1] + spread
    return side * (last - entry), end - 1, "time"
