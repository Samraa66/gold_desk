"""One self-contained HTML page of the forward log: every call, what price did after it, and the scorecard.

Pure read of journal/calls.jsonl + the bar files. It never writes a call and never changes a score; it only
renders what `journal.score_entries` already says. Regenerated at the end of every scheduled cycle.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import instruments as I
from . import journal as J
from .config import Config
from .data import OHLC, load_m1

DP = 2          # decimals for prices; build() sets it for the instrument being drawn
OUT = Path(__file__).resolve().parent.parent / "journal" / "dashboard.html"

CSS = """
:root{--bg:#fafaf8;--card:#fff;--ink:#1c1c1a;--mute:#6b6b66;--line:#e4e4de;--up:#1a7f4b;--dn:#c0392b;--warn:#b7791f;--link:#2b5fa8}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1d1d1b;--ink:#ecece6;--mute:#9a9a92;--line:#33332f;--up:#4cc38a;--dn:#ef7b6e;--warn:#e0b04a;--link:#7fa8e0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 2px}h2{font-size:16px;margin:28px 0 10px}
.sub{color:var(--mute);font-size:13px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--mute);font-weight:500;font-size:12px}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}.pill{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid var(--line)}
.BUY{color:var(--up);border-color:var(--up)}.SELL{color:var(--dn);border-color:var(--dn)}.win{color:var(--up)}.loss{color:var(--dn)}.open,.pending{color:var(--warn)}
.call{display:grid;grid-template-columns:1fr 380px;gap:14px}@media(max-width:760px){.call{grid-template-columns:1fr}}
.lv{font-variant-numeric:tabular-nums;font-size:13px;color:var(--mute)}.reason{margin:8px 0 0;font-size:14px}svg{width:100%;height:auto;display:block}
.note{background:var(--card);border-left:3px solid var(--warn);padding:10px 14px;border-radius:6px;font-size:13px;color:var(--mute);margin:12px 0}
"""


LABELS = {"master": "master (the call)",
          "chart_lean": "chart lean, no vetoes (shadow, every slot)",
          "chart_macro": "chart lean + macro not against (shadow)",
          "chart_setup": "chart's own setup, no master (v2 shadow)",
          "rules_setup": "rules structure setup (v2 shadow)"}


def _fmt_r(x):
    return "—" if x is None else f"{x:+.2f}R"


def _chart(call: dict, m1: pd.DataFrame, now: pd.Timestamp, closed_at: str | None = None, outcome: str = "open") -> str:
    """Price since the call with entry, stop and TP1 drawn on it (closed bars only). The line is solid until the trade
    closed and faint after, with a marker where it closed, so a stop hit before a later reversal is visible."""
    plan = call["plan"]
    t0 = pd.Timestamp(call["as_of"])
    end = min(now, t0 + pd.Timedelta(hours=Config().expiry_hours))
    bars = m1.loc[t0 - pd.Timedelta(hours=3): end - pd.Timedelta(minutes=1), "close"]
    if len(bars) < 2:
        return '<div class="sub">no bars after this call yet</div>'
    bars = bars.resample("15min").last().dropna()
    levels = [plan["entry"], plan["stop"], plan["tp1"]]
    lo, hi = min(list(bars) + levels), max(list(bars) + levels)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    W, H, L, R = 380, 150, 8, 74
    xs = lambda i: L + (W - L - R) * i / max(len(bars) - 1, 1)
    ys = lambda v: H - 10 - (H - 20) * (v - lo) / (hi - lo)
    cut = bars.index.searchsorted(t0)
    stop_i = None
    if closed_at:
        stop_i = min(max(int(bars.index.searchsorted(pd.Timestamp(closed_at))), cut), len(bars) - 1)
    split = (stop_i + 1) if stop_i is not None else len(bars)
    pts = " ".join(f"{xs(i):.1f},{ys(v):.1f}" for i, v in enumerate(bars) if i < split)
    after = " ".join(f"{xs(i):.1f},{ys(v):.1f}" for i, v in enumerate(bars) if i >= split - 1) if stop_i is not None else ""
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Price since the call with entry, stop and target">']
    for name, v, col in (("TP1", plan["tp1"], "var(--up)"), ("entry", plan["entry"], "var(--mute)"), ("SL", plan["stop"], "var(--dn)")):
        parts.append(f'<line x1="{L}" x2="{W-R}" y1="{ys(v):.1f}" y2="{ys(v):.1f}" stroke="{col}" stroke-dasharray="4 3" stroke-width="1"/>'
                     f'<text x="{W-R+4}" y="{ys(v)+4:.1f}" font-size="10" fill="{col}">{name} {v:.{DP}f}</text>')
    parts.append(f'<line x1="{xs(cut):.1f}" x2="{xs(cut):.1f}" y1="6" y2="{H-6}" stroke="var(--line)"/>')
    if after:
        parts.append(f'<polyline points="{after}" fill="none" stroke="var(--mute)" stroke-width="1" stroke-dasharray="2 2" opacity="0.7"/>')
    parts.append(f'<polyline points="{pts}" fill="none" stroke="var(--ink)" stroke-width="1.5"/>')
    if stop_i is not None:
        col = {"win": "var(--up)", "loss": "var(--dn)"}.get(outcome, "var(--warn)")
        lab = {"win": "target hit", "loss": "stopped out", "expired": "48h expiry"}.get(outcome, "closed")
        lvl = {"win": plan["tp1"], "loss": plan["stop"]}.get(outcome, bars.iloc[stop_i])
        parts.append(f'<circle cx="{xs(stop_i):.1f}" cy="{ys(lvl):.1f}" r="4.5" fill="{col}"/>'
                     f'<text x="{min(xs(stop_i) + 7, W - R - 60):.1f}" y="{ys(lvl) - 8:.1f}" font-size="10" font-weight="700" fill="{col}">{lab}</text>')
    parts.append(f'<circle cx="{xs(cut):.1f}" cy="{ys(plan["entry"]):.1f}" r="4" fill="var(--bg)" stroke="var(--ink)" stroke-width="2"/>'
                 f'<text x="{xs(cut) + 3:.1f}" y="12" font-size="9" fill="var(--mute)">ENTRY {plan["entry"]:.{DP}f} · {t0:%H:%M} UTC</text>')
    parts.append(f'<text x="{L}" y="{H-1}" font-size="9" fill="var(--mute)">faint line = after the trade had already closed</text>' if after else "")
    parts.append("</svg>")
    return "".join(parts)


def _scorecard(scored: list[dict]) -> str:
    rows = []
    for mode in ("llm", "rules"):
        es = [e for e in scored if e["mode"] == mode]
        if not es:
            continue
        s = J.summarize(es)
        for name in [k for k in s if isinstance(s[k], dict)]:
            v = s[name]
            label = LABELS.get(name) or (f"{name} (baseline)")
            rows.append(f"<tr><td>{mode}</td><td>{label}</td><td class=n>{v['calls']}</td><td class=n>{v['resolved']}</td>"
                        f"<td class=n>{v['wins']}/{v['losses']}/{v['expired']}</td><td class=n>{v['still_open']}</td>"
                        f"<td class=n>{v['total_r']:+.2f}</td><td class=n>{'—' if v['avg_r'] is None else format(v['avg_r'], '+.3f')}</td></tr>")
    if not rows:
        return '<div class="card sub">No calls logged yet. The first scheduled cycle will add one.</div>'
    return ('<div class="card"><table><tr><th>Mode</th><th>Strategy</th><th class=n>Calls</th><th class=n>Resolved</th>'
            '<th class=n>W / L / expired</th><th class=n>Open</th><th class=n>Total R</th><th class=n>Avg R</th></tr>'
            + "".join(rows) + "</table></div>")


def build(journal_path: Path = J.JOURNAL, out: Path = OUT, now: pd.Timestamp | None = None, m1: pd.DataFrame | None = None,
          instrument: str = "XAU_USD") -> Path:
    global DP
    spec = I.get(instrument)
    DP = spec.dp
    cfg = spec.config()
    m1 = load_m1(instrument=instrument) if m1 is None else m1
    now = now or (m1.index[-1] + pd.Timedelta(minutes=1))
    scored = J.score_entries(J.load(journal_path), m1, cfg, now)
    scored.sort(key=lambda e: (e["as_of"], e["mode"]), reverse=True)
    calls = [e for e in scored if e["decision"] in ("BUY", "SELL")]
    passes = [e for e in scored if e["decision"] == "PASS"]
    resolved = sum(1 for e in calls if (e["scores"].get("master") or {}).get("outcome") in ("win", "loss", "expired"))

    body = [f"<h1>{html.escape(spec.label)} · forward log</h1><div class=sub>Updated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · bars through "
            f"{html.escape(str(m1.index[-1]))[:16]} UTC · research only, no orders are placed</div>"]
    body.append(f'<div class="note">Nothing here is judged until a mode has 30 resolved calls over 6+ weeks (so far: {resolved} resolved calls). '
                f'A few wins or losses in a row prove nothing. Assumed costs ({cfg.spread_assumed:g} spread + {cfg.slippage_assumed:g} slippage, in price units) are already deducted from every R.</div>')
    body.append("<h2>Scorecard</h2>" + _scorecard(scored))
    body.append(f"<h2>Calls ({len(calls)})</h2>")
    if not calls:
        body.append('<div class="card sub">No BUY or SELL yet. PASS is a valid answer; most cycles will be PASS.</div>')
    for e in calls:
        p, sc = e["plan"], e["scores"].get("master") or {}
        outcome = sc.get("outcome", "pending")
        buy = e["decision"] == "BUY"
        t0 = pd.Timestamp(e["as_of"])
        word = {"BUY": "BUY", "SELL": "SELL"}[e["decision"]]
        move = ("goes UP" if buy else "goes DOWN")
        lose = ("falls" if buy else "rises")
        win = ("rises" if buy else "falls")
        fill = (f' · scored as filled at <b>{sc["fill"]:.{DP}f}</b> (open of the next bar, adjusted for assumed spread and slippage)' if sc.get("fill") else "")
        if p.get("entry_type", "market") != "market":      # desk v2: an order at a level, filled only if price gets there
            kind = {"limit": "LIMIT", "stop": "STOP"}[p["entry_type"]]
            got = (f' · filled at {sc["filled_at"][11:16]} UTC, scored at <b>{sc["fill"]:.{DP}f}</b> after assumed costs' if sc.get("filled_at") else "")
            entry_line = (f'<div class="lv">{kind} order at <b>{p["entry"]:.{DP}f}</b>, placed {t0:%Y-%m-%d %H:%M} UTC, valid until '
                          f'{str(p.get("valid_until"))[11:16]} UTC (price was {e["price"]:.{DP}f}){got}</div>')
        else:
            entry_line = f'<div class="lv">Entry <b>{p["entry"]:.{DP}f}</b> at {t0:%Y-%m-%d %H:%M} UTC (price when the call was made){fill}</div>'
        rule = (entry_line + f'<div class="lv">Wins if {spec.label} {win} to <b>{p["tp1"]:.{DP}f}</b> (TP1) · loses if it {lose} to <b>{p["stop"]:.{DP}f}</b> (stop) · '
                f'bigger target {p["tp2"]:.{DP}f}</div>')
        if sc.get("closed_at"):
            ca = pd.Timestamp(sc["closed_at"])
            mins = int((ca - t0).total_seconds() // 60)
            took = f"{mins} min" if mins < 120 else f"{mins / 60:.1f} h"
            verb = {"win": "Target hit", "loss": "Stopped out", "expired": "Expired after 48h, closed at market",
                    "unfilled": "Order never filled; cancelled"}[outcome]
            line = f"{verb} at {str(ca)[11:16]} UTC, {took} after the call: {_fmt_r(sc.get('r'))}."
            later = ""
            if outcome == "loss":
                tail = m1.loc[ca: now - pd.Timedelta(minutes=1)]
                tail = tail.loc[: t0 + pd.Timedelta(hours=Config().expiry_hours)]
                reached = bool((tail["low"] <= p["tp1"]).any()) if not buy else bool((tail["high"] >= p["tp1"]).any())
                if reached:
                    later = (' <span class="sub">Price did reach TP1 later, but the stop was hit first, so it counts as a loss. '
                             'A stop is a stop: this is shown for information and never used to tune the rules.</span>')
            outline = f'<div class="{outcome}" style="margin-top:6px"><b>{outcome.upper()}</b> {line}{later}</div>'
        else:
            outline = (f'<div class="{outcome}" style="margin-top:6px"><b>{outcome.upper()}</b> '
                       f'{"Still running: neither level hit yet." if outcome == "open" else "Order placed, price has not reached it yet." if outcome == "waiting" else "Waiting for the first bar after the call."}</div>')
        body.append(
            f'<div class="card call"><div><span class="pill {e["decision"]}">{word}</span> '
            f'<b style="font-size:17px">entry {p["entry"]:.{DP}f}</b> <span class="sub">· {html.escape(e["as_of"][:16].replace("T", " "))} UTC · {e["mode"]}</span>'
            f'<div class="sub" style="margin-top:2px">The call: {spec.label} {move}.</div>{rule}'
            f'<div class="lv">{p["lots"]} lots, risk ${p["risk_usd"]:.0f} (demo sizing)</div>{outline}'
            f'<p class="reason">{html.escape(e["reason"])}</p></div>'
            f'<div>{_chart(e, m1, now, sc.get("closed_at"), outcome)}</div></div>')
    body.append(f"<h2>PASS decisions ({len(passes)})</h2><div class=card><table><tr><th>Time (UTC)</th><th>Mode</th><th>Chart lean</th><th>Why</th></tr>"
                + "".join(f"<tr><td>{html.escape(e['as_of'][:16].replace('T', ' '))}</td><td>{e['mode']}</td><td>{(((e.get('baselines') or {}).get('chart_lean') or (e.get('baselines') or {}).get('chart_setup')) or {}).get('direction', '—')}</td><td>{html.escape(e['reason'])}</td></tr>"
                          for e in passes[:40]) + "</table></div>")
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(spec.label)} desk log</title><style>{CSS}</style></head><body><main>{"".join(body)}</main></body></html>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
