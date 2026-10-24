# Data fix: HistData timestamps were one hour late in summer (found 2026-10-15)

**Bug.** `src/histdata.py` treated the file clock as fixed US Eastern without daylight saving (UTC-5), as the vendor's note
says. The file's clock is actually New York wall-clock time WITH daylight saving. So every bar between the March and November
clock changes (about 8 months a year, 2018-2026) was stamped one hour later than real UTC. Winter bars were right.

**Evidence.** (1) Daily reopen sat at 23:00 "UTC" in every season; real gold reopens at 18:00 New York = 22:00 UTC in summer.
(2) MetaTrader 5's server clock vs the old HistData stamps differs by exactly +2 h in all 22 months checked (Jan 2025 to Oct 2026),
winter and summer; MT5's own offset was measured at +3 h against the Mac clock in October, i.e. HistData was +1 h late then.
(3) After the fix, MT5 vs HistData over 6,480 overlapping minutes (5-9 Oct 2026): median |close difference| 0.095,
95th percentile 0.225, and best alignment is a shift of 0 (before: median 5.4 at shift 0, best at +60 min). Reopen times identical.

**Fix.** `to_utc_bars` localises the stamps as America/New_York and converts to UTC (the hours repeated or skipped at the clock
changes fall in the weekend closure and are dropped). Parquet rebuilt; old file kept as `data/xauusd_m1_histdata.OLD_fixed_utc5.parquet`.
Tests: tests/test_histdata_time.py (DST cases, daily reopen in both seasons).

**Effect on every earlier result (rules and pass criteria unchanged; old outputs kept in results/pre_timefix/):**
- Stage 1 (channel signals): the export clock is also New York wall time (offset -4 in summer, -5 in winter on the true candles).
  Re-run with proper conversion: numbers identical to the stored table. Unchanged: still loses for a follower.
- Stage 2 (15-min breakout): no time-of-day logic, tables identical.
- Stage 3 (opening-range breakout): session opens were an hour early in summer before the fix. Re-run: still FAIL, 0-1 of 7 positive years
  (results/stage3_orb_timefixed_A.md and _B.md).
- Stage 4 (pullback): still FAIL (research PF 0.64, validation 0.77).
- Stage 5 (H4 breakout): validation PF moved from 1.20 to 0.92, so the earlier "decent validation year" was partly the clock error. Both
  periods are now below 1.0. Still FAIL.
- Stage 2c (ML, uses hour-of-day features): NOT re-run. Its verdict (AUC 0.52-0.57) is unverified on the corrected data.
Test years for stages 4 and 5 remain unopened.
