"""python -m gold_agents run|score|replay|report  (run from gold_agents)"""
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
from . import desk_v2, desk_v3
from .runner import card, decide_at, watch_text


def _llm(args):
    if args.rules_only:
        return None
    client = L.from_env()
    if client is None and args.llm:
        sys.exit("--llm needs ANTHROPIC_API_KEY (env or gold_agents/.env)")
    return client if args.llm else None


def should_notify(call: dict, wrote: bool, flag: bool) -> bool:
    """Telegram only for a newly logged BUY or SELL. PASS is the common answer and would bury the entries."""
    return bool(flag and wrote and call["decision"] in ("BUY", "SELL"))


def should_watch(call: dict, wrote: bool, flag: bool) -> bool:
    """A WATCH message for a newly logged PASS that still has a chart lean. Sent from the model's call only: it
    has the richer reason, and sending from both modes would double every message."""
    return bool(flag and wrote and call["mode"] == "llm" and watch_text(call))


def keep_model_io(call: dict, llm, journal, wrote: bool) -> None:
    """A model run's cost goes on the call; its prompts and raw replies go beside the log, once, when the call is logged."""
    records = getattr(llm, "records", None)
    if not records:
        return
    call["usage"] = L.usage(records)
    if wrote:
        J.save_prompts(call, records, journal)


def _setup(args):
    """-> (spec, cfg, journal path, m1). Gold uses its original log unless --journal says otherwise."""
    spec = I.get(args.instrument)
    if args.desk == "v3":
        return spec, desk_v3.config(), args.journal or desk_v3.JOURNAL, load_m1(instrument=spec.oanda)
    journal = args.journal or (desk_v2.journal_path(spec) if args.desk == "v2" else spec.journal_path)
    return spec, spec.config(), journal, load_m1(instrument=spec.oanda)


def v3_live(now: pd.Timestamp, oanda=None, bars=None) -> dict:
    """What v3 reads besides its own candles, fetched once and stored on the call. A dead source comes back empty."""
    from . import live_data, news
    return {**(oanda or live_data.Oanda()).snapshot(bars), "news": news.headlines(now)}


def v3_wake(trigger, as_of: pd.Timestamp, llm, m1, macro_df, live: dict, journal: Path, send=notify.send, clock=None,
            v3: desk_v3.V3 = desk_v3.V3_DEFAULT) -> list[dict]:
    """One wake: the model's call and the rules call on the same time. Both fill from the first full minute after the model
    finished, so neither is credited with a price it could not have traded."""
    clock = clock or (lambda: pd.Timestamp(datetime.now(timezone.utc)))
    cfg, prior = desk_v3.config(), J.load(journal)
    calls = []
    for model in ((llm, None) if llm is not None else (None,)):
        call = desk_v3.decide_at(m1, as_of, cfg, llm=model, macro_df=macro_df, prior_entries=prior, v3=v3, trigger=trigger, live=live)
        if not calls:
            fill_from = str(clock().ceil("min"))
        call["fill_from"] = fill_from
        keep_model_io(call, model, journal, wrote=False)
        wrote = J.append(call, journal)
        keep_model_io(call, model, journal, wrote)
        if should_notify(call, wrote and model is not None, True):
            send(desk_v3.card(call))
        calls.append(call)
    return calls


def cmd_watch(args):
    """One 5-minute look at gold. The desk only runs, and only spends, when `watcher.tick` wakes it."""
    from . import dashboard, live_data, news, oanda_data, watcher
    spec = I.get("XAU_USD")
    journal = args.journal or desk_v3.JOURNAL
    now = pd.Timestamp(datetime.now(timezone.utc)).floor("min")
    oanda = live_data.Oanda()
    seen = {}

    def fetch():
        seen["bars"] = oanda.m5()
        return seen["bars"]

    def wake(trigger, at):
        print(oanda_data.refresh(at - pd.Timedelta(days=3), spec.bars_path, instrument=spec.oanda))
        if trigger is None:           # a slot: the calendar changes slowly and 4 reads a day is plenty
            try:
                print("calendar: new events", news.refresh_calendar())
            except Exception as e:
                print(f"calendar refresh failed: {e}")
        m1 = load_m1(instrument=spec.oanda)
        live = v3_live(at, oanda, seen["bars"])
        macro_df = macro_data.macro_frame(at.to_pydatetime())
        client = L.from_env()
        if client is None:
            print("no ANTHROPIC_API_KEY: rules only")
        calls = v3_wake(trigger, at, client, m1, macro_df, live, journal)
        print(*[f"{c['mode']}: {c['decision']} ({c['reason'][:120]})" for c in calls], sep="\n")
        scored = J.score_entries(J.load(journal), m1, desk_v3.config(), m1.index[-1] + pd.Timedelta(minutes=1))
        J.freeze_outcomes(scored, journal)
        dashboard.build(journal, desk_v3.DASHBOARD, instrument=spec.oanda)
        if at.hour == 18 and trigger is None:
            notify.send(desk_v3.day_text(scored, str(at.date()), watcher.load_state(desk_v3.WATCH_STATE).get("wakes", 0)))

    print(now, watcher.tick(now, fetch, wake, desk_v3.WATCH_STATE, desk_v3.WATCH_LOG))


def cmd_events(args):
    """Fill events.csv from the calendar feed: high-impact US releases. Every desk's event blocks read this file."""
    from . import news
    print("new events:", news.refresh_calendar())


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
    decide, show = {"v2": (desk_v2.decide_at, desk_v2.card), "v3": (desk_v3.decide_at, desk_v3.card)}.get(args.desk, (decide_at, card))
    extra = {"live": v3_live(as_of)} if args.desk == "v3" else {}
    call = decide(m1, as_of, cfg, llm=llm, macro_df=macro_data.macro_frame(as_of.to_pydatetime()),
                  prior_entries=J.load(args.journal), **extra)
    keep_model_io(call, llm, args.journal, wrote=False)
    print(show(call))
    if args.dry:
        return
    wrote = J.append(call, args.journal)
    keep_model_io(call, llm, args.journal, wrote)
    print("logged" if wrote else "already logged for this time, rules and mode; nothing written")
    if should_notify(call, wrote, args.notify):
        notify.send(show(call))
    elif args.desk != "v2" and should_watch(call, wrote, args.notify):
        notify.send(watch_text(call))


def cmd_score(args):
    spec, cfg, journal, m1 = _setup(args)
    args.journal = journal
    now = pd.Timestamp(args.now) if args.now else m1.index[-1] + pd.Timedelta(minutes=1)
    scored = J.score_entries(J.load(args.journal), m1, cfg, now)
    frozen = J.freeze_outcomes(scored, args.journal)
    s = J.summarize(scored)
    print(f"scored through {now}  (bars end {m1.index[-1] + pd.Timedelta(minutes=1)})")
    print(f"runs {s['runs']}, passes {s['passes']}, outcomes frozen now {frozen}")
    for name in [k for k in s if isinstance(s[k], dict)]:
        v = s[name]
        print(f"  {name:10s} calls {v['calls']:3d} resolved {v['resolved']:3d} W{v['wins']} L{v['losses']} exp{v['expired']} "
              f"open {v['still_open']}  total {v['total_r']:+.2f}R  avg {v['avg_r']}")
    for mode in ("llm", "rules"):
        ps = J.summarize_passes([e for e in scored if e["mode"] == mode])
        if ps["passes_judged"]:
            print(f"  {mode} passes judged {ps['passes_judged']}: quiet after {ps['quiet_after']}, big move after {ps['big_move_after']} "
                  f"(up {ps['big_up']}, down {ps['big_down']}, >= {ps['big_atr']:g} H1 ATR in 24h)  avg |net| {ps['avg_abs_net_atr']} ATR")
    if all(isinstance(s.get(n), dict) and s[n]["resolved"] < 30 for n in s if isinstance(s[n], dict)):
        print("Nothing is judged under 30 resolved calls per strategy.")


def cmd_digest(args):
    """One Telegram message for a slot: every instrument's v2 decision, calls and passes."""
    from . import reports
    text = reports.slot_digest(args.as_of, args.instruments.split(","))
    if text is None:
        print("nothing logged for this slot")
        return
    print(text)
    if args.send:
        notify.send(text)


def cmd_scorecard(args):
    """End-of-day v2 scorecard to Telegram."""
    from . import reports
    day = args.day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    text = reports.scorecard(day, args.instruments.split(","))
    print(text)
    if args.send:
        notify.send(text)


def cmd_feed(args):
    """The Telegram feed as a page, with scores (journal/dashboard_v2_digest.html)."""
    from . import reports
    out = I.get("XAU_USD").journal_path.with_name(reports.FEED_NAME)
    print("wrote", reports.feed_html(args.instruments.split(","), out, days=args.days))


def cmd_dashboard(args):
    from . import dashboard
    spec = I.get(args.instrument)
    v2 = args.desk == "v2"
    if args.desk == "v3":
        print(f"wrote {dashboard.build(args.journal or desk_v3.JOURNAL, desk_v3.DASHBOARD, instrument=spec.oanda)}")
        return
    out = dashboard.build(args.journal or (desk_v2.journal_path(spec) if v2 else spec.journal_path),
                          desk_v2.dashboard_path(spec) if v2 else spec.dashboard_path, instrument=spec.oanda)
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
    ap.add_argument("--desk", default="v1", choices=("v1", "v2", "v3"),
                    help="v1 (original record), v2 (reads the chart, setups at levels) or v3 (gold only, woken by the market, reads the news)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--as-of"); r.add_argument("--llm", action="store_true")
    r.add_argument("--rules-only", action="store_true"); r.add_argument("--dry", action="store_true")
    r.add_argument("--notify", action="store_true"); r.add_argument("--allow-leaky", action="store_true"); r.set_defaults(fn=cmd_run)
    s = sub.add_parser("score"); s.add_argument("--now"); s.set_defaults(fn=cmd_score)
    d = sub.add_parser("dashboard"); d.set_defaults(fn=cmd_dashboard)
    w = sub.add_parser("watch"); w.set_defaults(fn=cmd_watch)
    v = sub.add_parser("events"); v.set_defaults(fn=cmd_events)
    ALL = ",".join(I.INSTRUMENTS)
    g = sub.add_parser("digest"); g.add_argument("--as-of", required=True); g.add_argument("--instruments", default=ALL)
    g.add_argument("--send", action="store_true"); g.set_defaults(fn=cmd_digest)
    c = sub.add_parser("scorecard"); c.add_argument("--day"); c.add_argument("--instruments", default=ALL)
    c.add_argument("--send", action="store_true"); c.set_defaults(fn=cmd_scorecard)
    f = sub.add_parser("feed"); f.add_argument("--instruments", default=ALL); f.add_argument("--days", type=int, default=7)
    f.set_defaults(fn=cmd_feed)
    p = sub.add_parser("replay"); p.add_argument("--start", required=True); p.add_argument("--end", required=True)
    p.add_argument("--step-hours", type=int, default=4); p.add_argument("--llm", action="store_true"); p.set_defaults(fn=cmd_replay)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
