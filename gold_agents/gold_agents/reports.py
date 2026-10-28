"""Telegram reports for desk v2 (2026-10-28): one message per slot with every instrument's decision, calls AND passes,
and one scorecard at the end of the day. The owner asked to see what the desk goes for and what it skips, then
have it scored. Read-only over the v2 logs; nothing here makes or changes a decision.
"""
from __future__ import annotations

import pandas as pd

from . import desk_v2
from . import instruments as I
from . import journal as J

TG_LIMIT = 3900            # Telegram caps a message at 4096 characters


def _f(spec, x):
    return "—" if x is None else f"{x:,.{spec.dp}f}"


def _order(spec, p: dict) -> str:
    kind = {"market": "at market", "limit": "LIMIT", "stop": "STOP"}.get(p.get("entry_type", "market"), "")
    until = f" · until {p['valid_until'][11:16]} UTC" if p.get("valid_until") else ""
    rr = f" ({p['rr_tp1']}R)" if p.get("rr_tp1") else ""
    return f"{p['direction']} {kind} {_f(spec, p['entry'])} · SL {_f(spec, p['stop'])} · TP1 {_f(spec, p['tp1'])}{rr}{until}"


def _cut(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _pick(entries: list[dict], as_of: str) -> dict | None:
    """The slot's decision: the model's call when there is one, else the rules call."""
    at = [e for e in entries if e["as_of"] == as_of]
    return next((e for e in at if e["mode"] == "llm"), None) or next((e for e in at if e["mode"] == "rules"), None)


def slot_line(spec, e: dict) -> str:
    name = spec.label.split(" (")[0].upper() if "(" in spec.label else spec.label
    if e["decision"] in ("BUY", "SELL"):
        return f"▶ {name}: {_order(spec, e['plan'])}\n   {_cut(e['reason'], 220)}"
    chart = ((e.get("reports") or {}).get("chart") or {}).get("facts") or {}
    setup = (e.get("baselines") or {}).get("chart_setup") or (e.get("baselines") or {}).get("rejected_setup")
    extra = ""
    if setup:
        extra = f"\n   chart wanted {_order(spec, setup['plan'])} (scored anyway)"
    elif chart.get("setup", {}).get("why") and e["mode"] == "llm":
        extra = f"\n   chart: {_cut(chart['setup']['why'], 140)}"
    return f"· {name}: PASS · {_cut(e['reason'], 180)}{extra}"


def slot_digest(as_of: str, instruments: list[str]) -> str | None:
    """One message for the whole slot. None when no instrument logged anything for it."""
    as_of = pd.Timestamp(as_of).isoformat()
    lines = []
    for name in instruments:
        spec = I.get(name)
        e = _pick(J.load(desk_v2.journal_path(spec)), as_of)
        if e:
            lines.append(slot_line(spec, e))
    if not lines:
        return None
    calls = sum(l.startswith("▶") for l in lines)
    head = f"Desk v2 · {as_of[:16].replace('T', ' ')} UTC · {calls} call{'s' if calls != 1 else ''}, {len(lines) - calls} pass"
    return _fit(head + "\n\n" + "\n\n".join(lines) + "\n\nResearch only, no orders placed. Scored tonight.")


OUTCOME = {"win": "WIN", "loss": "LOSS", "expired": "EXPIRED", "open": "running", "waiting": "order waiting",
           "unfilled": "never filled", "pending": "pending"}


def _stats(s: dict) -> str:
    if not s or not s.get("calls"):
        return "no calls yet"
    avg = "—" if s["avg_r"] is None else f"{s['avg_r']:+.2f}R"
    return f"{s['wins']}W {s['losses']}L {s['expired']}exp · {s['still_open']} open · {s.get('unfilled', 0)} unfilled · total {s['total_r']:+.2f}R, avg {avg} over {s['resolved']}"


def scorecard(day: str, instruments: list[str], loader=None) -> str:
    """End of day: today's calls and their status, yesterday's passes judged 24 h on, running v2 totals per instrument."""
    from .data import load_m1
    loader = loader or (lambda name: load_m1(instrument=name))
    d0 = pd.Timestamp(day, tz="UTC").normalize()
    out = [f"Desk v2 scorecard · {d0:%a %d %b} (UTC)"]
    for name in instruments:
        spec = I.get(name)
        entries = [e for e in J.load(desk_v2.journal_path(spec)) if e["mode"] == "llm"]
        if not entries:
            continue
        m1 = loader(name)
        now = m1.index[-1] + pd.Timedelta(minutes=1)
        scored = J.score_entries(entries, m1, spec.config(), now)
        today = [e for e in scored if d0 <= pd.Timestamp(e["as_of"]) < d0 + pd.Timedelta(days=1)]
        label = spec.label.split(" (")[0].upper() if "(" in spec.label else spec.label
        block = [f"\n{label}"]
        for e in today:
            t = e["as_of"][11:16]
            if e["decision"] in ("BUY", "SELL"):
                sc = e["scores"].get("master") or {}
                r = f" {sc['r']:+.2f}R" if sc.get("r") is not None else ""
                block.append(f"  {t} {e['decision']} {e['plan'].get('entry_type', 'market')} {_f(spec, e['plan']['entry'])} → {OUTCOME.get(sc.get('outcome'), sc.get('outcome'))}{r}")
            else:
                shadow = next(((k, v) for k, v in e["scores"].items() if k in ("chart_setup", "rejected_setup")), None)
                tail = ""
                if shadow:
                    k, v = shadow
                    r = f" {v['r']:+.2f}R" if v.get("r") is not None else ""
                    tail = f" · its {'refused ' if k == 'rejected_setup' else ''}setup → {OUTCOME.get(v.get('outcome'), v.get('outcome'))}{r}"
                block.append(f"  {t} PASS{tail}")
        judged = [e for e in scored if e.get("after") and e["after"].get("net_atr") is not None
                  and d0 - pd.Timedelta(days=1) <= pd.Timestamp(e["as_of"]) < d0]
        if judged:
            big = [e for e in judged if abs(e["after"]["net_atr"]) >= 3]
            moves = ", ".join(f"{e['as_of'][11:16]} {e['after']['net_atr']:+.1f}ATR" for e in big)
            block.append(f"  yesterday's {len(judged)} passes, 24h on: {len(judged) - len(big)} quiet" + (f", big move after {len(big)} ({moves})" if big else ""))
        s = J.summarize(scored)
        block.append(f"  all v2 calls: {_stats(s.get('master'))}")
        if s.get("chart_setup"):
            block.append(f"  chart setups (incl. passed): {_stats(s['chart_setup'])}")
        if s.get("rules_setup"):
            block.append(f"  rules setups: {_stats(s['rules_setup'])}")
        out.extend(block)
    out.append("\nNothing is judged under 30 resolved calls. R is after assumed costs.")
    return _fit("\n".join(out))


def _fit(text: str) -> str:
    return text if len(text) <= TG_LIMIT else text[: TG_LIMIT - 20].rstrip() + "\n… (cut, see dashboard)"
