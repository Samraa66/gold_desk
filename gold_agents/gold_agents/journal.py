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
        as_of = pd.Timestamp(e["as_of"])
        strategies = {}
        if e["decision"] in ("BUY", "SELL") and e.get("plan"):
            strategies["master"] = score_plan(e["decision"], e["plan"], as_of, m1, cfg, now)
        for name, b in (e.get("baselines") or {}).items():
            if b:
                strategies[name] = score_plan(b["direction"], b["plan"], as_of, m1, cfg, now)
        out.append({**e, "scores": strategies})
    return out


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
