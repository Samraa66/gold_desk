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
  desk_v2.py desk_v3.py structure.py watcher.py news.py live_data.py   later desks and what they read
  journal.py            append-only call log + conservative scorer + baselines
  runner.py llm.py notify.py __main__.py
journal/calls.jsonl     THE forward log (committed, append-only). replay_calls.jsonl is a plumbing artefact, not evidence
scripts/run_cycle.sh    refresh MT5 bars -> make a call -> log -> score (unverified end to end, see below)
tests/                  offline tests (no network, no key, no MT5)
```

## Setup and use
```bash
cd gold_agents
/opt/miniconda3/bin/python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt   # already done on this Mac
.venv/bin/python -m pytest -q                       # 45 pass
.venv/bin/python -m gold_agents run --dry           # make a call, print it, write nothing
.venv/bin/python -m gold_agents run                 # make a call and log it (rules only unless --llm)
.venv/bin/python -m gold_agents run --llm           # agents + master use the model (needs ANTHROPIC_API_KEY)
.venv/bin/python -m gold_agents score               # score the log against later bars, vs the baselines
.venv/bin/python -m gold_agents replay --start 2026-08-17 --end 2026-10-07   # plumbing check only
```
Keys go in `gold_agents/.env` (gitignored): `ANTHROPIC_API_KEY=`, optional `FRED_API_KEY=` (free; real
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

## Desk v2: it reads the chart (2026-10-28)
v1's chart agent never saw a candle: ten summary numbers (EMA-cross trend signs on H4/H1, a 20-day breakout position,
momentum, ATR, five levels), plus the rule score handed to the model as an anchor. From 2026-10-26 to 10-28 its lean went
0 wins / 16 losses (-16.5R): one correlated bet, SELL into a 3,975-3,989 floor that held five times while gold bounced to
4,070. In its own summaries it saw the support, then leaned short anyway. The desk itself passed every time; the WATCH
messages carried the lean to Telegram.

v2 (`gold_agents/desk_v2.py`, `gold_agents/structure.py`, run with `--desk v2`) changes three things:
1. **The chart agent reads the chart**: the last 30 D1, 60 H4, 48 H1 and 32 M15 candles, plus computed structure (fractal
   swings in order, HH/HL vs LH/LL per timeframe, support/resistance zones clustered from swings with touch counts, where
   price sits between support and resistance). No rule score in its prompt. Model: `deep_model`.
2. **A call is a setup**: market, LIMIT at a zone or STOP beyond a level, stop beyond structure, TP1 at least `min_rr` (1.5) R,
   valid up to 24 h. "none" is the normal answer. Rules mode trades the H4 swing pattern from a zone and refuses to trade into
   a zone touched twice or more right next to price.
3. **The scorer fills a pending order only if price reaches it** (`journal._score_pending`): unfilled orders are counted
   apart and are never a win or a loss; fill and stop in one bar is a loss; the fill bar never pays the target.

Own hash (`desk_v2.v2_hash`, includes v1's), own logs `journal/calls_v2*.jsonl` and dashboards `dashboard_v2*.html`; shadows
`chart_setup` (the chart's setup with no master) and `rules_setup`. Macro and liquidity agents are v1's. v1 keeps running,
logged silently, as the comparison. Telegram gets ONE message per slot listing every instrument's v2 model decision, calls and passes
(`python -m gold_agents digest`), and after the 18:00 UTC slot a scorecard (`scorecard`): the day's calls and their status, the
day's passes with their scored setups, yesterday's passes judged 24 h on, and running v2 totals per instrument.
Same pass bar as below. Spot check on real bars (rules only, not evidence): on 2026-10-27 10:00/14:00 and 10-28 06:00 v2 gave
no setup where v1's lean sold into the floor.

**v2 rules added 2026-10-28 evening (new v2 hash; the 18:00 slot that day stays under the old one).** From a short the owner
took at resistance an hour after FOMC, stopped out when a double bottom (4,024 / 4,027) rallied $35 through it. In code
(`desk_v2.setup_filters`), whatever the model says, and stated in its prompt: no setup within `post_event_hours` (3) after a
high-impact release; the stop at least `min_stop_atr_h1` (1.0) x H1 ATR; no SELL after `counter_run` (2) rising M5 swing lows in
a row, no BUY after 2 falling M5 highs, neither in a squeeze (`structure.short_term`, read on M5 because an M15 swing needs 30 min
to confirm). A setup they refuse is still scored (`rejected_setup`, with the reason), so the record shows whether they help.
Replayed on that evening's bars: the post-event rule refuses the trade; the rising-lows rule would only have seen it ~10 min later.

## Desk v3: gold only, woken by the market, reads the news (2026-10-30)
On 2026-10-30 gold fell $135. v2 leaned bearish at 06:00 and 10:00 UTC and proposed nothing ("no mapped zone beneath it for a
target"), the break came between its slots, and its one setup arrived at 14:00, $52 above price. Its shadow record the same week:
6 chart setups the desk passed on, 5 wins, 1 unfilled, +8.97R over two correlated days, across four pairs. That is a reason to
build a new version, not evidence. The owner chose gold alone, fast trades instead of $50 swings, and a $1,000 demo as the sizing.

v3 (`gold_agents/desk_v3.py`, `--desk v3`, hash `desk_v3.v3_hash`, log `journal/calls_v3.jsonl`, dashboard `dashboard_v3.html`):
1. **Move watcher** (`watcher.py`, `scripts/watch_cycle.sh`, `golddesk-watch.timer`, every 5 min). Rules only, no model cost on a quiet
   tick: a close beyond the 3 h range, a close through a named level (prior day, today, Asia, round $50), a wick through a level
   that closes back (sweep), a bar 2.5x normal. A level counts only when crossed by a quarter of a normal M5 bar. Asia-only hours
   do not spend wakes. 30 min cooldown per trigger and side, 30 model wakes a day at most, plus the 4 slots. Simulated on 10-20 to 10-30
   bars before go-live (plumbing, not evidence): a cap of 16 ran out as early as 12:11 UTC, before New York, so the cap is 30.
   Every trigger is logged to `journal/watch_v3.jsonl`, woken or not. A trigger is a reason to look, never a reason to trade.
2. **Fast trades.** Stop $5-15, at least 1x M5 ATR; TP1 at least 1.5R, at a level or plain R-based when nothing is mapped; orders
   valid up to 2 h, near price; a trade closes by 6 h. 1.5% of $1,000 = $15 risk, 0.01 lot on the widest stop. Same-side
   cooldown 1 h, daily loss limit 3R, two open calls.
3. **Agents reading different things.** News (`news.py`: Google News RSS, published before the as-of only, Sonnet). Cross-asset (`live_data.py`:
   dollar, 10-year bond price, S&P, oil, silver over 1 h and 4 h, plus v1's daily macro). Liquidity for the chart agent: OANDA's order
   and position books (its own clients, not the market), session levels, equal highs/lows, tick volume against normal. The chart agent
   sees no news, so agreement between agents still means something.
4. **Master bar 0.50**, set before any v3 result. It is informed by two days of v2, which is exactly why only v3's own forward log
   can judge it. Vetoes, the post-event rule and the no-fade rules are v2's, in code.
5. **Honest fills.** `fill_from` on the call: scored from the first full minute after the model finished, not from the trigger.

`rules_setup` is the baseline the model must beat: trade a directional trigger at market unless H1 structure opposes it, stop
1.5x M5 ATR, TP1 1.5R. `chart_setup` and `rejected_setup` are shadows as in v2. Same pass bar as below, with `rules_setup` in
place of `trend_h4` for criterion 3. v2 gold is the control and keeps running untouched.

**Known risks, stated before the first result.** Cost: 0.90 of assumed spread and slippage is 0.18R on a $5 stop and 0.06R on $15, so
tight trades carry a real handicap, and spreads widen on exactly the bars that trigger. Noise: a $15 stop is under one H1 ATR on
a day like 10-30 (ATR $18); v2 forbade that (`min_stop_atr_h1`), v3 allows it because fast trades were the owner's call. Trades 5 minutes apart
are not independent, so more calls do not automatically mean more evidence (see the power note).

**Calendar.** `python -m gold_agents events`, and every v3 slot, fills `events.csv` with high-impact US releases from the Forex
Factory weekly feed. It did not exist on the server before, so CPI and PPI were invisible. v1 and v2 read the same file: no number
changed, so no hash moved, but both now also block those releases once it exists.

**v1 and v2 stopped 2026-10-30 (owner's decision: gold only, one desk).** `golddesk.timer` is disabled, so silver, EUR and GBP and the v2 gold
control have stopped, and with them the slot digest and the v2 scorecard. Their logs and code stay; the Telelytics page keeps showing their last
state. v2's last gold call (SELL limit 3972, 14:00 slot) was never rescored by a cycle: `--desk v2 score` still works while bars exist. To restart:
`systemctl enable --now golddesk.timer`. v3's comparison is `rules_setup` in its own log. Only `golddesk-watch.timer` runs now.

## Keeping everything (2026-10-29)
The owner asked that every slot, PASS included, leave enough behind to judge it later and improve the model. Recording
only: no decision changed, so no hash moved.
- **Every model call, word for word**, in `journal/prompts_v2*.jsonl` (and `prompts*.jsonl` for v1): call id, agent
  (chart, macro, master), model, full system prompt, full user prompt (candles + structure), raw reply, tokens and dollar cost
  (`llm.PRICES`, list prices 2026-10). Named so they never match `calls*`, which the Telelytics page reads.
- **Each call's cost** as `usage` on the call itself; the 18:00 scorecard shows the day's model spend per instrument and in total.
- **Frozen outcomes** in `journal/outcomes_v2*.jsonl`: written once by `score` when every strategy on the call is final
  (win, loss, expired, unfilled) and, for a PASS, its 24 h window has closed. Scores are otherwise recomputed from bars,
  which the server trims to ~200 days.
- **v1's model run stopped**; its free rules run continues as the comparison. v1's model log ends at the 2026-10-29 14:00 slot.
- **Backup**: `scripts/pull_dashboard.sh` also copies prompts and outcomes; `scripts/launchd/com.golddesk.backup.plist` copies the
  whole server journal nightly to `~/gold_desk_live/journal/` once installed in `~/Library/LaunchAgents/`.

Why the prompts matter: the model's training ends before these dates, so a changed prompt could be re-run on the saved inputs
without the model knowing how the day ended. Whether such a replay counts as evidence is the owner's call; until then the rule
above stands (replays are plumbing checks).

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

## Scheduler (moved to the VPS 2026-10-22; since 2026-10-30 only v3's `golddesk-watch.timer` runs, see Desk v3)
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
