# Desk v3.1 design (2026-10-31)

Status: approved by the owner 2026-10-31. Nothing here is built yet.

## Intent
Gold trends are made of legs. On 2026-10-30 gold fell $135. The owner does not want one $80 trade; they want a run of shorter trades along the move: for example sell around 4015, take profit and close, wait for confirmation, sell again around 3980, and repeat while the move lasts. They want 3-4 trades on a good day, more if they are there, and none when nothing is there.

The owner also wants nothing important missing from what the desk reads, and a daily view of what can move gold today, with entries, stops and targets from the desk.

The desk's speed advantage is breadth: reading many markets and sources at once and connecting them within minutes. It cannot beat bank algorithms to the first tick.

## What was found in v3
1. v3 is built for isolated scalps. It has no memory of earlier calls and no idea of what kind of day it is, so it cannot re-enter a move on purpose.
2. Bug: `journal.state_at` counts rules-baseline entries as if they were desk calls. `v3_wake` loads both modes from one log. The 19:46 model PASS on 10-30 ("3 calls open, limit 2") counted the 19:31 rules call. The daily loss limit is double-counted the same way.
3. Stops are capped at a fixed $15 and the prompt says "quick trades", while the H1 ATR on 10-30 was $18.
4. The watcher is blind from 20:00 to 06:00 UTC. It missed the last hour of Friday and will miss Sunday's reopen until Monday 06:01 UTC.
5. Only gold's own price can wake the desk. Other markets and news are read after it wakes.
6. Headlines come from two Google News searches: titles only, best age 4-5 minutes, often 44-69 minutes, and junk among them (a mining company report, a Robinhood price page).
7. Client positions read 70.9% long on all six runs on 10-30 while the timestamp moved. The cause is unknown and the desk used the number as "fuel below".
8. The 6-hour expiry can cross a weekend: a call filled Friday is marked at the Sunday open.

All feeds did reach the models on 10-30 (checked in `journal/prompts_v3.jsonl`), so there is no repeat of the v1 no-candles bug.

## Goals
- Catch several legs of one move, each as a separate trade that takes profit and closes.
- Stops, targets and holding time set by the model from current structure and volatility, with no dollar figures in code or prompts.
- A trend read and a memory of the current move on every wake.
- Watching from the Sunday reopen to the Friday close, woken by gold, other markets or news.
- A daily brief from the desk, with one source of truth.
- Every input logged so it can be judged later.

## Non-goals
- No order code. Stage B is unchanged.
- No separate project for the brief.
- No riding one position through a whole trend, and no scaling in.
- No paid data feeds until free-feed lag has been measured.
- No markets other than gold.

## Anti-goals
- A quota. 3-4 trades a day is a hope, not a target; zero on a choppy day is correct.
- Entries, stops or targets from anywhere but a passed desk call.
- Inputs added because they sound useful and never judged.
- Retuning any v3.1 number on v3.1's own results.

## Constraints
From `CLAUDE.md` and the README: new hash and log for a config change; replays are plumbing checks; the model layer is only tested forward; pass criteria unchanged; PASS is a normal answer; no fades into a momentum leg; extra caution after high-impact events. The journal folder and `calls*.jsonl` names must keep working for the Telelytics page. Never touch `/root/telegram-lead-bot`.

## Design

### Fixed rules (protect the account; these stay in code)
- Risk as a percent of equity per trade, and the daily loss limit.
- Lots follow from risk and stop distance. A stop that cannot be sized at the 0.01 minimum lot is refused. See "Open decision".
- No fades against rising lows or falling highs; squeeze waits.
- The post-event block stays. See Shadow records.
- Liquidity vetoes stay rules, as they are now.
- Stop at least 1x M5 ATR, a noise floor that moves with the market.
- Flat by the Friday close.
- Two open desk calls at most, counting only model calls (bug 2 fixed). The fixed same-side 1 h cooldown goes; a new call on a side needs the previous call on that side to have closed, so legs follow one another and never stack.

### The model's calls
Stop distance, targets, order validity and maximum holding time all come from the model, each justified in its `why`. The "$5-15" and "quick trades" wording goes from the prompt. The scorer reads `max_hold_hours` from the plan. A win still exits in full at TP1, as the owner asked ("get TPs and close"). `tp2` stays informational.

### Move memory (new, computed by rules, shown to the chart agent)
On every wake: where the current move started, its size against the D1 ATR, how many legs and pullbacks so far, the desk's calls on this move with their outcome so far, what is open now, and the last close. The chart agent is told re-entries after a failed pullback or a fresh break are the main setup.

### Trend read (new, in the chart agent's reply)
The chart agent states the day type (trending, ranging, unclear) and direction, and logs it. Its setup must be consistent with that read or say why not. No separate agent: the chart agent already sees the candles, and a separate one would add cost and another opinion to reconcile.

### Daily brief (new, inside the desk)
Written once before London opens and once at the first slot after any release listed on the calendar. It covers what can move gold today, the trend read, key levels and scheduled risks, and ends with the current call or PASS. Sent to Telegram and stored at `journal/brief_v31.jsonl`, shown on the v3.1 dashboard. Master, news and macro read it. The chart agent does not, so that agreement between chart and news still means something.

### Waking
- Hours are set in New York time, because the break moves in UTC with US clock changes. OANDA gold bars measured 2025-10 to 2026-10: last bar 16:59 NY, first bar about 18:04 NY, daily and at the weekend. So the desk watches Sunday 18:00 NY to Friday 17:00 NY, except 17:00-18:00 NY daily. From 2026-11-01 that is 22:00-23:00 UTC. The watcher uses its own window so `calendar.market_window` and v1/v2 stay as they are. `liquidity` takes the same window, or its veto would refuse Sunday's first bars and Friday's last hour.
- Triggers: gold's existing four, plus `cross_move` (a 5-minute move in the dollar, bonds, S&P, oil or silver that is large against that market's own normal bar) and `news` (a fresh relevant headline). `cross_move` and `news` carry no direction. A trigger is a reason to look, never a reason to trade.
- News polling: a new `golddesk-news.timer` every minute. The poll is rules only, so a quiet poll costs nothing.
- One daily wake budget across all triggers, so cost stays bounded.
- First tick after a weekend: the desk must read a gap as a gap, not as a break.

### Inputs (each logged, each with an "unavailable" state)
- Fix: the client positions reading (find the cause first), and drop it from the prompt if it cannot be trusted.
- News: relevance filter in rules, then primary sources (Fed, Treasury) alongside Google News. Article text only where free and permitted. Headlines stay data, never instructions.
- Calendar: add other central banks and medium-impact releases, marked by impact. The post-event block keeps to high impact.
- Macro: real yield and any intraday figure available free. Show the data's age on every value.
- Positioning and flows: weekly COT and gold ETF holdings if reliably available free, otherwise logged as missing.
- Measure and log headline lag on every wake.

### Shadow records
`rejected_setup` already logs refused setups. Add `post_event_setup`: what the desk would have called inside the post-event block, scored but never sent. This shows from forward results whether a later version should shorten the block. `rules_setup` stays the baseline, with its stops scaled the same way as today. Rules-mode calls never count toward the desk's limits.

### Version handling
`desk_v31.py` builds on v3, as v3 did on v2. Own hash, `calls_v31.jsonl`, `outcomes_v31.jsonl`, `prompts_v31.jsonl`, `dashboard_v31.html`, `watch_v31.jsonl`. CLI `--desk v31`. The watcher moves to v3.1 and v3 stops, keeping its log and code; v3 has three calls, so nothing of value is lost. The Stage B clock starts fresh with v3.1. The bug fix to `state_at` must be scoped so that v1, v2 and v3's hashes and scoring do not change. The Telelytics page must be checked for whether it lists the new file names; that repo is read only from here.

### Testing
Offline tests for every new rule. Before go-live, a plain-rules check of the re-entry idea on older bars, held apart from any tuning. It is a plumbing and sanity check, never evidence for the model. Live dry run, then deploy with `scripts/deploy_vps.sh` after the timer change is reviewed.

## Left to the builder
Exact trigger thresholds, poll source list, prompt wording, dashboard layout, and how moves are detected, provided each number is frozen in the hash before go-live.

## Sizing (the owner's decision, 2026-10-31)
The research demo is $5,000 at 1.5% risk, a $75 budget, because 0.01 lot is 1 oz and a $1,000 demo would make $15 the widest possible stop. Results are scored in R, so the demo size does not distort the record.

The owner sizes real trades relative to their own account. Every call card shows the risk as dollars at 0.01 lot and the stop distance, so they can size it themselves or skip it. The desk does not store the owner's balance.

Decisions are the owner's and approved as written. The calls listed to the owner: exit in full at TP1, trend read inside the chart agent, post-event block kept with a shadow record, same-side cooldown removed, two open model calls, v3 stops when v3.1 starts, brief before London and after listed releases, free data first.
