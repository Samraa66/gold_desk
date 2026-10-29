# gold_desk

Trading research: can an agent desk read gold (and silver, EUR/USD, GBP/USD) well enough to trade it?
Moved out of the Telelytics repo (`research/`) on 2026-10-29, history kept.

| Folder | What | Status |
|---|---|---|
| `gold_agents/` | The desk: chart, macro, liquidity, risk and master agents; v1 and v2 (reads candles, calls setups at levels); forward logs, shadow baselines, Telegram digest and scorecard. Runs on the VPS. | Live forward test since 2026-10-22 (v2 since 2026-10-28). Start with `gold_agents/README.md`. |
| `gold_bot/` | Earlier rule-based and ML tests on XAUUSD (traders' signals, breakouts, ORB, pullback, H4), MT5 read-only link | 5 stages, all failed their written criteria. Its `data/` (bars) is read by `gold_agents/`, so keep it beside it. |

Rule for both: no real money until a written pass criterion is met on data the rules never saw.
