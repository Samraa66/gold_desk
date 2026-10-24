# Gold agents (XAUUSD): a desk of specialist agents, one master, a forward log

Research only. Nothing here imports from `backend/`, nothing is deployed, **no order is ever placed**
(there is no order code in this folder), and no real money is involved. Standalone environment in `.venv`.

Sibling: `../gold_bot/` holds the earlier rule-based research (signals, breakouts, ORB, ML, H4). All of it
failed its written criteria; its fill logic, MT5 link and data are reused here. Start with its README for why
this project is not "find a better chart pattern".

## The idea
Several agents, each reading **different information**, report to a master that decides BUY, SELL or PASS.
Agreement only means something if the agents do not all read the same candles.

| Agent | Reads | Mode | Can veto |
|---|---|---|---|
| Chart analyst | M15/H1/H4/D1 closed bars: trend, 20-day breakout position, momentum, ATR, levels | rules, optionally refined by a model | no |
| Macro analyst | Yahoo daily closes (dollar, US 10y, VIX, S&P, silver) before the decision day, FRED real yield if a key is set, the next 48 h of releases | small rules heuristic, optionally a model | no |
| Liquidity / conditions | market hours, weekend, rollover, high-impact event windows, live spread vs its own normal, bar freshness | **rules only** | yes |
| Risk manager | ATR stop, 2R/3R targets, lots from contract size (100 oz), daily loss limit, open-call cap, same-side cooldown | **rules only** | yes |
| Master | the four reports | rules procedure, or a model | its decision is bounded by the two vetoes in code |

Principles: vetoes are code, never a prompt; PASS is a normal answer and is logged like a trade; a model sees
only numbers computed from bars that had closed by the as-of time; every call is written before its outcome exists.

## Layout
```
gold_agents/            package (python -m gold_agents ...)
  config.py             every number, hashed (rules_hash) and stored on each call
  data.py features.py   closed-bar loading, resampling, ATR/EMA/efficiency
  calendar.py           FOMC + NFP built in, events.csv for the rest, market hours
  macro_data.py         Yahoo (and optional FRED) daily closes, cached in data/macro/
  agents/               chart, macro, liquidity, risk, master
  journal.py            append-only call log + conservative scorer + baselines
  runner.py llm.py notify.py __main__.py
journal/calls.jsonl     THE forward log (committed, append-only). replay_calls.jsonl is a plumbing artefact, not evidence
scripts/run_cycle.sh    refresh MT5 bars -> make a call -> log -> score (unverified end to end, see below)
tests/                  45 offline tests (no network, no key, no MT5)
```

## Setup and use
```bash
cd research/gold_agents
/opt/miniconda3/bin/python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt   # already done on this Mac
.venv/bin/python -m pytest -q                       # 45 pass
.venv/bin/python -m gold_agents run --dry           # make a call, print it, write nothing
.venv/bin/python -m gold_agents run                 # make a call and log it (rules only unless --llm)
.venv/bin/python -m gold_agents run --llm           # agents + master use the model (needs ANTHROPIC_API_KEY)
.venv/bin/python -m gold_agents score               # score the log against later bars, vs the baselines
.venv/bin/python -m gold_agents replay --start 2026-08-17 --end 2026-10-07   # plumbing check only
```
Keys go in `research/gold_agents/.env` (gitignored): `ANTHROPIC_API_KEY=`, optional `FRED_API_KEY=` (free; real
yields are gold's main driver), optional `GOLD_TG_TOKEN=` + `GOLD_TG_CHAT=` for Telegram cards (use a NEW bot, never a
client's). **No Anthropic key was found on this machine in the old gold projects (all empty), so model mode has only
been exercised against a fake model.** Rules mode is what ran.

Keep `events.csv` current (copy `events.example.csv`): CPI, PPI, retail sales, Fed speakers. Without it the
liquidity agent only knows FOMC and payrolls, and its report says how old the file is.

## Data
**Fresh bars now come from OANDA** (`gold_agents/oanda_data.py`, practice account, `OANDA_API_TOKEN` in `.env`; `run_cycle.sh` calls it, `BAR_SOURCE=mt5` keeps the old path). Written 2026-10-21, tested against a fake API only; never run with a real token.

Bars come from `../gold_bot/data/` (HistData M1 history through 2026-10-09, MT5 M1 + spread from 2026-10-05 to
2026-10-16). **Data is stale as of 2026-10-21**, so `run` correctly vetoes ("bar data is N min old") until bars are
refreshed: open MetaTrader 5 on the demo account and run `scripts/run_cycle.sh`. That script has not been run.
D1 is a UTC-midnight day, an approximation of the New York 17:00 rollover.

## Rules fixed before any live result (2026-10-21)
Costs: spread 0.60 + slippage 0.30 in the scorer (the demo's real median is ~0.21; the conservative figure stays until
the user's real broker demo is measured). A win exits at TP1; stop beats target inside one bar; unresolved after 48 h
is marked to market. R is against intended risk, so costs show up as lost R.

A mode (`rules`, `llm`) is judged only on its own calls, under one `rules_hash`. Changing any config value starts a
new record. Nothing is judged under 30 resolved master calls.

**Stage B pass (forward log, rules or llm), all of:**
1. at least 30 resolved master calls spread over at least 6 weeks,
2. average R after costs above +0.15,
3. better than the always-follow-H4-trend baseline (`trend_h4`, same stops, no vetoes) by at least 0.15R average,
4. worst peak-to-trough in cumulative R no worse than -8R,
5. `llm` additionally beats `rules` on the same timestamps (otherwise the model adds cost, not edge).

Failing, we stop or change the idea; we do not retune on the same data. **Stage C** (demo account placing orders by
itself) and anything near real money are not built and not allowed until B passes.

## Instruments and shadow scoring (2026-10-24)
The desk runs on XAU_USD (the original record, config hash `0eed0fd6`, log `journal/calls.jsonl`) and, from the 2026-10-26
06:00 slot, XAG_USD, EUR_USD and GBP_USD. Each has its own bars, config (stops, contract size, assumed costs), rules_hash,
call log (`journal/calls_<pair>.jsonl`) and dashboard; results are never pooled across instruments (`gold_agents/instruments.py`).
Every call also records two **shadow** strategies, scored on every slot whether the desk passed or not: `chart_lean` (the chart's
direction, no vetoes) and `chart_macro` (that lean when macro is not hard against it). A PASS with a chart lean sends a WATCH
message to Telegram (from the model run only); it is never a call. These changed no rule, so no hash moved.

**Power note (scripts/sample_size.py, coin-flip entries through the real sizing and scorer, 2026-10-24):** the per-call spread of R is
about 1.1 to 1.4, so the standard error of an average over 30 calls is about 0.23R. To tell an edge of +0.15R from zero
(80% power, one-sided 5%) takes roughly 350 to 520 INDEPENDENT resolved calls. The 30-call Stage B bar above therefore cannot
show an edge; passing it would be luck. It is left as written (changing it is the owner's call and starts a new version), but read
it as a minimum before looking at anything, not as proof. Coin-flip entries also lose about 0.03 to 0.3R per call after costs
(silver the most), which is the bar a real edge has to beat. Calls 4 hours apart with a 48 h expiry overlap, so they are not independent.

## What is known so far
- Plumbing replay, rules only, 2026-08-17 to 2026-10-07, 4-hourly, no macro data, 307 steps: 245 PASS; the master took
  62 calls, avg -0.53R; the H4-trend baseline avg -0.14R. This is consistent with the earlier research (plain trend
  rules do not clear costs) and was **not** used to tune anything. It is a smoke test with overlapping, correlated calls.
- The scorer was checked for bias: zero-cost always-BUY on a driftless walk wins ~1/3 (test), and on the real window
  at zero cost 25-30%.
- The expected value of this project sits in the macro/model layer, which has not run yet.

## Scheduler (moved to the VPS 2026-10-22)
Runs on the VPS as its own user: systemd timer `golddesk.timer` (weekdays 06:02, 10:02, 14:02, 18:02 UTC) runs
`scripts/scheduled_cycle.sh` in `/home/golddesk/gold_desk/gold_agents` (own venv, own `.env`, 450 MB memory cap, low priority).
It touches nothing of the product. **The LIVE log and dashboard are on the server** (`journal/calls.jsonl`, `dashboard.html`,
`cycle.log`); `scripts/pull_dashboard.sh` copies them to `~/gold_desk_live/` and opens the page. Code changes reach the server only
via `scripts/deploy_vps.sh` (code only; never the journal, `.env` or bars). The server's price history is trimmed to ~200 days
(decisions verified identical to the full history) to fit 1 GB of RAM. The Mac launchd job is disabled (macOS blocks launchd from
~/Documents); `scripts/deploy_runner.sh` and the Mac copy in `~/gold_desk` remain only for local manual runs.
Stop the server job: `systemctl disable --now golddesk.timer` on the VPS.

## Suggested clock (now scheduled, see above)
Weekdays at 06:00, 10:00, 14:00, 18:00 UTC: `scripts/run_cycle.sh` (rules) and, once a key exists, `--llm` at the same
times so the two modes are compared on identical timestamps. Idempotent: a repeated time/mode/rules is not logged twice.
Rough model cost: 3 calls per run (two Sonnet, one Opus), my estimate a few cents each, roughly $5-15 a month at that clock.

## Ported from the old TradingAgents-gold fork
Conservative scoring rules (stop wins ties, count a fill only when traded through, mark expiries to market) and the
"trade only if everything agrees and the levels make sense" check. Its daily-bar swing framework, futures-to-spot gap
logic and company-oriented agents were not kept: we read MT5 spot directly. The fork was moved to the Trash.
