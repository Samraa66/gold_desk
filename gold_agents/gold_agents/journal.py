"""The forward call log and its scorer.

Append-only JSON lines. A call is written BEFORE its outcome exists and is never edited; scoring is a pure
function of the stored call and later bars. Conservative on purpose (a flattering record is worse than none):

- A call fills at the open of the first minute bar at/after its as-of time.
- Bars are bid prices. A BUY pays the spread on entry; a SELL's stop and target are checked against the ask
  (bid + spread). Spread is the assumed 0.60, not the demo's thinner 0.21. Entry and stop fills also slip 0.30.
- Stop and target in the same bar count as the stop.
- A win exits at TP1 and is worth tp1_r; a loss is about -1R plus costs. Open after `expiry_hours` marks to market.
- R is measured against the INTENDED risk (planned entry to stop), so costs show up as lost R.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import Config

JOURNAL = Path(__file__).resolve().parent.parent / "journal" / "calls.jsonl"


def append(entry: dict, path: Path = JOURNAL) -> bool:
    """Append unless this id is already logged. Returns whether it wrote."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(e["id"] == entry["id"] for e in load(path)):
        return False
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    return True


def load(path: Path = JOURNAL) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sidecar(journal: Path, kind: str) -> Path:
    """calls_v2_eurusd.jsonl -> <kind>_v2_eurusd.jsonl beside it. Never named calls*: the Telelytics page reads those."""
    journal = Path(journal)
    return journal.with_name(kind + journal.name.removeprefix("calls"))


def _append_lines(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")


def save_prompts(call: dict, records: list[dict], journal: Path) -> None:
    """Every model call behind a logged call, word for word: prompt, raw reply, tokens, cost (2026-10-29)."""
    _append_lines(sidecar(journal, "prompts"), [{"call_id": call["id"], "as_of": call["as_of"], **r} for r in records])


FINAL = ("win", "loss", "expired", "unfilled")


def freeze_outcomes(scored: list[dict], journal: Path) -> int:
    """Write each scored entry's outcome once it can no longer change: every strategy closed, and for a PASS the 24 h
    after it over. Scores are otherwise recomputed from bars, which the server trims to ~200 days; this keeps them."""
    path = sidecar(journal, "outcomes")
    have = {r["id"] for r in load(path)}
    rows = []
    for e in scored:
        if e["id"] in have or any(s.get("outcome") not in FINAL for s in e["scores"].values()):
            continue
        if e["decision"] == "PASS" and not (e.get("after") and e["after"].get("net_atr") is not None):
            continue
        rows.append({"id": e["id"], "as_of": e["as_of"], "mode": e["mode"], "instrument": e.get("instrument"),
                     "decision": e["decision"], "scores": e["scores"], "after": e.get("after"),
                     "frozen_at": pd.Timestamp.now(tz="UTC").isoformat()})
    _append_lines(path, rows)
    return len(rows)


def score_plan(direction: str, plan: dict, as_of: pd.Timestamp, bars: pd.DataFrame, cfg: Config, now: pd.Timestamp) -> dict:
    """Score one plan on minute bars. `bars` may include anything; only bars from `as_of` up to `now` are used."""
    long = direction == "BUY"
    spread, slip = cfg.spread_assumed, cfg.slippage_assumed
    stop, tp1, tp2 = plan["stop"], plan["tp1"], plan["tp2"]
    planned_risk = abs(plan["entry"] - stop)
    window = bars.loc[as_of: now - pd.Timedelta(minutes=1)]        # only bars that have closed by `now`
    if window.empty:
        return {"outcome": "pending", "r": None}
    if plan.get("entry_type", "market") != "market":
        return _score_pending(long, plan, as_of, window, cfg, now)
    expiry = as_of + pd.Timedelta(hours=cfg.expiry_hours)
    idx = window.index
    op, hi, lo = window["open"].to_numpy(), window["high"].to_numpy(), window["low"].to_numpy()
    fill = op[0] + spread + slip if long else op[0] - slip
    n_live = int(idx.searchsorted(expiry, side="left"))            # bars strictly before expiry can hit a level
    stop_hit = (lo[:n_live] <= stop) if long else (hi[:n_live] + spread >= stop)
    tp_hit = (hi[:n_live] >= tp1) if long else (lo[:n_live] + spread <= tp1)
    hit = (stop_hit | tp_hit).nonzero()[0]
    if len(hit):
        i = int(hit[0])
        if stop_hit[i]:                                            # a tie inside one bar counts as the stop
            exit_px = stop - slip if long else stop + slip
            r = ((exit_px - fill) if long else (fill - exit_px)) / planned_risk
            return {"outcome": "loss", "r": round(float(r), 3), "fill": round(float(fill), 2), "closed_at": str(idx[i]),
                    "note": "stop and target in one bar; counted as the stop" if tp_hit[i] else ""}
        r = ((tp1 - fill) if long else (fill - tp1)) / planned_risk
        tp2_hit = bool((hi[i:] >= tp2).any() if long else (lo[i:] + spread <= tp2).any())
        return {"outcome": "win", "r": round(float(r), 3), "fill": round(float(fill), 2), "closed_at": str(idx[i]), "tp2_reached": tp2_hit}
    if n_live < len(idx):                                          # reached expiry without either level
        exit_px = op[n_live] if long else op[n_live] + spread
        r = ((exit_px - fill) if long else (fill - exit_px)) / planned_risk
        return {"outcome": "expired", "r": round(float(r), 3), "fill": round(float(fill), 2), "closed_at": str(idx[n_live])}
    return {"outcome": "open", "r": None, "fill": round(float(fill), 2)}


def _score_pending(long: bool, plan: dict, as_of: pd.Timestamp, window: pd.DataFrame, cfg: Config, now: pd.Timestamp) -> dict:
    """A limit or stop order (desk v2). It fills only when price reaches `entry` before `valid_until`, else it is
    `unfilled` (worth nothing, not a resolved call). Same conservative costs as a market fill:
    - SELL limit fills when the bid high reaches entry; BUY limit when the ask low (bid low + spread) does.
    - SELL stop fills when the bid low reaches entry; BUY stop when the ask high does. A gap through the level fills
      at the bar's open (worse), never at the level.
    - Every fill slips `slippage_assumed` against us. In the fill bar only the STOP is checked (a target in the same
      bar is not counted), so an entry and a stop-out in one bar is a loss. Expiry runs `expiry_hours` from the fill."""
    spread, slip = cfg.spread_assumed, cfg.slippage_assumed
    entry, stop, tp1, tp2 = plan["entry"], plan["stop"], plan["tp1"], plan["tp2"]
    et = plan["entry_type"]
    planned_risk = abs(entry - stop)
    idx = window.index
    op, hi, lo = window["open"].to_numpy(), window["high"].to_numpy(), window["low"].to_numpy()
    valid_until = pd.Timestamp(plan["valid_until"]) if plan.get("valid_until") else as_of + pd.Timedelta(hours=24)
    n_valid = int(idx.searchsorted(valid_until, side="left"))
    if et == "limit":
        touch = (lo[:n_valid] + spread <= entry) if long else (hi[:n_valid] >= entry)
    else:
        touch = (hi[:n_valid] + spread >= entry) if long else (lo[:n_valid] <= entry)
    t = touch.nonzero()[0]
    if not len(t):
        if now >= valid_until:
            return {"outcome": "unfilled", "r": None, "closed_at": str(valid_until)}
        return {"outcome": "waiting", "r": None}
    i0 = int(t[0])
    if et == "limit":
        fill = entry + slip if long else entry - slip    # a limit fills at its price; slippage kept to stay conservative
    else:
        gap = (op[i0] + spread > entry) if long else (op[i0] < entry)
        base = (op[i0] + spread if long else op[i0]) if gap else entry
        fill = base + slip if long else base - slip
    expiry = idx[i0] + pd.Timedelta(hours=cfg.expiry_hours)
    n_live = int(idx.searchsorted(expiry, side="left"))
    stop_hit = (lo[i0:n_live] <= stop) if long else (hi[i0:n_live] + spread >= stop)
    tp_hit = (hi[i0:n_live] >= tp1) if long else (lo[i0:n_live] + spread <= tp1)
    if len(tp_hit):
        tp_hit[0] = False                              # the fill bar can stop us out but never pays the target
    hit = (stop_hit | tp_hit).nonzero()[0]
    base_out = {"fill": round(float(fill), 6), "filled_at": str(idx[i0])}
    if len(hit):
        i = i0 + int(hit[0])
        if stop_hit[int(hit[0])]:
            exit_px = stop - slip if long else stop + slip
            r = ((exit_px - fill) if long else (fill - exit_px)) / planned_risk
            return {"outcome": "loss", "r": round(float(r), 3), **base_out, "closed_at": str(idx[i]),
                    "note": "filled and stopped in the same bar" if i == i0 else ""}
        r = ((tp1 - fill) if long else (fill - tp1)) / planned_risk
        tp2_hit = bool((hi[i:] >= tp2).any() if long else (lo[i:] + spread <= tp2).any())
        return {"outcome": "win", "r": round(float(r), 3), **base_out, "closed_at": str(idx[i]), "tp2_reached": tp2_hit}
    if n_live < len(idx):
        exit_px = op[n_live] if long else op[n_live] + spread
        r = ((exit_px - fill) if long else (fill - exit_px)) / planned_risk
        return {"outcome": "expired", "r": round(float(r), 3), **base_out, "closed_at": str(idx[n_live])}
    return {"outcome": "open", "r": None, **base_out}


def score_entries(entries: list[dict], m1: pd.DataFrame, cfg: Config, now: pd.Timestamp) -> list[dict]:
    """Attach `scores` = {strategy: result} to each entry. Strategies: master (its call) and the baselines."""
    out = []
    for e in entries:
        # A v3 call is scored from when the model finished (`fill_from`): the bars before that could not have been traded.
        as_of = pd.Timestamp(e.get("fill_from") or e["as_of"])
        strategies = {}
        if e["decision"] in ("BUY", "SELL") and e.get("plan"):
            strategies["master"] = score_plan(e["decision"], e["plan"], as_of, m1, cfg, now)
        for name, b in (e.get("baselines") or {}).items():
            if b:
                strategies[name] = score_plan(b["direction"], b["plan"], as_of, m1, cfg, now)
        out.append({**e, "scores": strategies, "after": move_after(e, m1, now) if e["decision"] == "PASS" else None})
    return out


def move_after(entry: dict, m1: pd.DataFrame, now: pd.Timestamp, hours: float = 24.0) -> dict | None:
    """What price did in the `hours` after a PASS: the biggest move up and down from the call's price and where it
    ended, in price units and in H1 ATRs (the desk's own volatility unit at the time). Lets a PASS be judged:
    'stood aside and price went nowhere' reads differently from 'stood aside and it ran 4 ATR'. Only once the whole
    window has closed; never used by any decision."""
    t0 = pd.Timestamp(entry["as_of"])
    end = t0 + pd.Timedelta(hours=hours)
    if now < end:
        return None
    w = m1.loc[t0: end - pd.Timedelta(minutes=1)]
    if w.empty:
        return None
    px = float(entry["price"])
    up, down, net = float(w["high"].max()) - px, px - float(w["low"].min()), float(w["close"].iloc[-1]) - px
    facts = ((entry.get("reports") or {}).get("chart") or {}).get("facts") or {}
    atr = (facts.get("structure") or {}).get("atr", {}).get("h1") or facts.get("h1_atr")
    in_atr = (lambda x: round(x / atr, 2)) if atr else (lambda x: None)
    return {"hours": hours, "up": round(up, 6), "down": round(down, 6), "net": round(net, 6),
            "up_atr": in_atr(up), "down_atr": in_atr(down), "net_atr": in_atr(net), "h1_atr": atr}


def summarize_passes(scored: list[dict], big_atr: float = 3.0) -> dict:
    """PASSes whose 24 h window has closed, split by whether price then made a big one-way move (>= `big_atr` H1 ATRs
    net). A desk that passes before most big moves is missing trades; one that passes in chop is doing its job.
    Reporting only: the threshold shapes this summary and nothing else."""
    done = [e["after"] for e in scored if e.get("after") and e["after"]["net_atr"] is not None]
    if not done:
        return {"passes_judged": 0}
    big_up = sum(a["net_atr"] >= big_atr for a in done)
    big_down = sum(a["net_atr"] <= -big_atr for a in done)
    return {"passes_judged": len(done), "big_move_after": big_up + big_down, "big_up": big_up, "big_down": big_down,
            "quiet_after": len(done) - big_up - big_down,
            "avg_abs_net_atr": round(sum(abs(a["net_atr"]) for a in done) / len(done), 2), "big_atr": big_atr}


def state_at(scored: list[dict], as_of: pd.Timestamp) -> dict:
    """Facts the risk agent needs: open master calls, R realised today (UTC), last call time per side."""
    open_calls, realised, last = 0, 0.0, {}
    day = as_of.normalize()
    for e in scored:
        t = pd.Timestamp(e["as_of"])
        if e["decision"] in ("BUY", "SELL"):
            last[e["decision"]] = max(last.get(e["decision"], t), t)
        s = e["scores"].get("master")
        if not s:
            continue
        if s["outcome"] in ("open", "pending", "waiting"):     # a v2 order still waiting to fill holds a slot
            open_calls += 1
        elif s["outcome"] in ("win", "loss", "expired") and s["r"] is not None:
            closed = pd.Timestamp(s.get("closed_at", e["as_of"]))
            if closed.normalize() == day:
                realised += s["r"]
    return {"open_calls": open_calls, "realised_r_today": round(realised, 3), "last_call_by_side": last}


def summarize(scored: list[dict]) -> dict:
    """Per strategy: calls, resolved, wins, losses, expired, avg R and total R over RESOLVED calls only."""
    names = sorted({n for e in scored for n in e["scores"]})
    out = {"runs": len(scored), "passes": sum(e["decision"] == "PASS" for e in scored)}
    for n in names:
        rs = [e["scores"][n] for e in scored if n in e["scores"]]
        res = [s for s in rs if s["outcome"] in ("win", "loss", "expired") and s["r"] is not None]
        tot = round(sum(s["r"] for s in res), 2)
        out[n] = {"calls": len(rs), "resolved": len(res), "wins": sum(s["outcome"] == "win" for s in res),
                  "losses": sum(s["outcome"] == "loss" for s in res), "expired": sum(s["outcome"] == "expired" for s in res),
                  "unfilled": sum(s["outcome"] == "unfilled" for s in rs),
                  "still_open": len(rs) - len(res) - sum(s["outcome"] == "unfilled" for s in rs), "total_r": tot, "avg_r": round(tot / len(res), 3) if res else None}
    return out
