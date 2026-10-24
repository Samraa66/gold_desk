from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import Config
from .data import closed_bars, resample


@dataclass
class Context:
    as_of: pd.Timestamp
    cfg: Config
    m1: pd.DataFrame                      # closed minute bars only
    tf: dict                              # "M15","H1","H4","D1" -> closed bars
    price: float                          # last closed minute's close (bid)
    last_bar_end: pd.Timestamp
    spread_now: float | None
    spread_normal: float | None
    macro: pd.DataFrame
    events: list | None = None            # None = built-ins + events.csv
    journal: dict = field(default_factory=dict)   # open_calls, realised_r_today, last_call_by_side


def build_context(m1_all: pd.DataFrame, as_of, cfg: Config, macro: pd.DataFrame | None = None,
                  events: list | None = None, journal: dict | None = None) -> Context:
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    m1 = closed_bars(m1_all, as_of)
    if m1.empty:
        raise ValueError(f"no bars before {as_of}")
    tf = {name: resample(m1.loc[as_of - pd.Timedelta(days=130):], name, as_of) for name in ("M15", "H1", "H4", "D1")}
    sp = m1["spread"].dropna() if "spread" in m1 else pd.Series(dtype=float)
    recent = sp[sp.index >= as_of - pd.Timedelta(minutes=30)]
    base = sp[sp.index >= as_of - pd.Timedelta(days=7)]
    return Context(
        as_of=as_of, cfg=cfg, m1=m1, tf=tf, price=float(m1["close"].iloc[-1]),
        last_bar_end=m1.index[-1] + pd.Timedelta(minutes=1),
        spread_now=float(recent.median()) if len(recent) else None,
        spread_normal=float(base.median()) if len(base) >= 200 else None,
        macro=macro if macro is not None else pd.DataFrame(), events=events, journal=journal or {},
    )
