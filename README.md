# research/

Standalone research. Nothing here is imported by `backend/` or deployed.

| Folder | What | Status |
|---|---|---|
| `gold_bot/` | Rule-based and ML tests on XAUUSD (the traders' signals, breakouts, ORB, pullback, H4), MT5 read-only link, HistData/MT5 data, forward call log of the frozen H4 rule | 5 stages, all failed their written criteria. Data and MT5 tools are reused by `gold_agents/`. |
| `gold_agents/` | Multi-agent desk (chart, macro, liquidity, risk, master) with a forward log and baselines | Built 2026-10-21, 45 tests pass, rules mode runs, model mode untested against a real model (no API key). Forward log empty. |

Rule for both: no real money until a written pass criterion is met on data the rules never saw.
