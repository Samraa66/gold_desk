"""python -m gold_agents run|score|replay|report  (run from research/gold_agents)"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import instruments as I
from . import journal as J
from . import llm as L
from . import macro_data, notify
from .config import Config
from .data import load_m1
from .runner import card, decide_at, watch_text


def _llm(args):
    if args.rules_only:
        return None
    client = L.from_env()
    if client is None and args.llm:
        sys.exit("--llm needs ANTHROPIC_API_KEY (env or research/gold_agents/.env)")
    return client if args.llm else None


def should_notify(call: dict, wrote: bool, flag: bool) -> bool:
    """Telegram only for a newly logged BUY or SELL. PASS is the common answer and would bury the entries."""
    return bool(flag and wrote and call["decision"] in ("BUY", "SELL"))


def should_watch(call: dict, wrote: bool, flag: bool) -> bool:
    """A WATCH message for a newly logged PASS that still has a chart lean. Sent from the model's call only: it
    has the richer reason, and sending from both modes would double every message."""
    return bool(flag and wrote and call["mode"] == "llm" and watch_text(call))


def _setup(args):
    """-> (spec, cfg, journal path, m1). Gold uses its original log unless --journal says otherwise."""
    spec = I.get(args.instrument)
    journal = args.journal or spec.journal_path
    return spec, spec.config(), journal, load_m1(instrument=spec.oanda)


def cmd_run(args):
    spec, cfg, journal, m1 = _setup(args)
    args.journal = journal
    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp(datetime.now(timezone.utc)).floor("min")
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    llm = _llm(args)
    if llm is not None and as_of < pd.Timestamp(datetime.now(timezone.utc)) - pd.Timedelta(hours=6) and not args.allow_leaky:
        sys.exit("refusing a model run on a past date: the model may remember how that day ended. Use --allow-leaky to override "
                 "(the call is then NOT forward evidence).")
    call = decide_at(m1, as_of, cfg, llm=llm, macro_df=macro_data.macro_frame(as_of.to_pydatetime()),
                     prior_entries=J.load(args.journal))
    print(card(call))
    if args.dry:
        return
    wrote = J.append(call, args.journal)
    print("logged" if wrote else "already logged for this time, rules and mode; nothing written")
    if should_notify(call, wrote, args.notify):
        notify.send(card(call))
    elif should_watch(call, wrote, args.notify):
        notify.send(watch_text(call))


def cmd_score(args):
    spec, cfg, journal, m1 = _setup(args)
    args.journal = journal
    now = pd.Timestamp(args.now) if args.now else m1.index[-1] + pd.Timedelta(minutes=1)
    scored = J.score_entries(J.load(args.journal), m1, cfg, now)
    s = J.summarize(scored)
    print(f"scored through {now}  (bars end {m1.index[-1] + pd.Timedelta(minutes=1)})")
    print(f"runs {s['runs']}, passes {s['passes']}")
    for name in [k for k in s if isinstance(s[k], dict)]:
        v = s[name]
        print(f"  {name:10s} calls {v['calls']:3d} resolved {v['resolved']:3d} W{v['wins']} L{v['losses']} exp{v['expired']} "
              f"open {v['still_open']}  total {v['total_r']:+.2f}R  avg {v['avg_r']}")
    if all(isinstance(s.get(n), dict) and s[n]["resolved"] < 30 for n in s if isinstance(s[n], dict)):
        print("Nothing is judged under 30 resolved calls per strategy.")


def cmd_dashboard(args):
    from . import dashboard
    spec = I.get(args.instrument)
    out = dashboard.build(args.journal or spec.journal_path, spec.dashboard_path, instrument=spec.oanda)
    print(f"wrote {out}")


def cmd_replay(args):
    """Smoke-test the plumbing over a past window with RULES only. Writes to a replay journal that is NOT evidence."""
    if args.llm:
        sys.exit("replay never uses the model: it would be leaky")
    cfg, m1 = Config(), load_m1()
    args.journal = args.journal or J.JOURNAL
    path = Path(args.journal).with_name("replay_" + Path(args.journal).name)
    path.unlink(missing_ok=True)
    start, end = pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC")
    entries, n = [], 0
    for t in pd.date_range(start, end, freq=f"{args.step_hours}h"):
        call = decide_at(m1, t, cfg, macro_df=None, prior_entries=entries)
        entries.append(call)
        J.append(call, path)
        n += 1
    scored = J.score_entries(entries, m1, cfg, end)
    print(f"replayed {n} steps -> {path}")
    print(J.summarize(scored))
    print("PLUMBING CHECK ONLY. Not evidence of an edge: the rules were frozen before this run and are not to be tuned on it.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gold_agents")
    ap.add_argument("--journal", type=Path, default=None)
    ap.add_argument("--instrument", default="XAU_USD", help="XAU_USD (default), XAG_USD, EUR_USD, GBP_USD")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--as-of"); r.add_argument("--llm", action="store_true")
    r.add_argument("--rules-only", action="store_true"); r.add_argument("--dry", action="store_true")
    r.add_argument("--notify", action="store_true"); r.add_argument("--allow-leaky", action="store_true"); r.set_defaults(fn=cmd_run)
    s = sub.add_parser("score"); s.add_argument("--now"); s.set_defaults(fn=cmd_score)
    d = sub.add_parser("dashboard"); d.set_defaults(fn=cmd_dashboard)
    p = sub.add_parser("replay"); p.add_argument("--start", required=True); p.add_argument("--end", required=True)
    p.add_argument("--step-hours", type=int, default=4); p.add_argument("--llm", action="store_true"); p.set_defaults(fn=cmd_replay)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
