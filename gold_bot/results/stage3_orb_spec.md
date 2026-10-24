# Stage 3 spec: session opening-range breakout on XAUUSD (written BEFORE any run, 2026-10-15)

Source idea: opening-range breakout (Zarattini and Aziz, SSRN 4416622 / 4729284), adapted to gold. Those papers
test US equities; nothing here is known to hold on gold. This is a test, not a belief.

## Rules (fixed now, no tuning afterwards)
- Sessions (local clock, DST handled by time zone): London 08:00 Europe/London, New York 09:30 America/New_York.
- Opening range: high and low of the first 30 minutes of the session (1-minute bars).
- Entry: after the range closes, the first 5-minute bar (within the next 3 hours) whose CLOSE is beyond the range.
  Close above the high = buy, close below the low = sell. One trade per session per day. Enter at that bar's close.
- Stop: the opposite side of the range. Target: 2 x the stop distance (2R).
- Time exit: 4 hours after the session open, at the market.
- Costs: buy at ask (bid + spread), sell at bid; exits on the side a real order uses. Spread 0.60 (also run 1.00).
  A minute touching both stop and target counts as the stop.
- No filters, no parameters to fit. Sessions are run separately and not combined.

## Number of ideas tried (for the multiple-testing correction)
2 variants (London, New York) x 1 rule. Any later change to the rules above is a NEW variant and is added to this count.

## Pass criteria (decided before the run)
Judged on 2018-2024 for each session separately, spread 0.60:
1. Total net result positive after costs.
2. Positive in at least 5 of the 7 years.
3. Profit factor >= 1.15 and at least 300 trades.
4. Still positive at spread 1.00.
Fail any one = the session FAILS. 2025-2026 is reported for information only: it was seen with an earlier rule,
and gold trended hard in it, so it cannot count as proof.

## Honest limits
- 2018-2024 was looked at while testing a different rule, so a pass here is weaker than a pass on untouched data.
  The clean test is the demo forward run (from 2026-10-15). A backtest pass only earns the right to go to demo.
- HistData has no spread; 0.60 is assumed. 2023 has gaps in the free data.

## Addendum 2026-10-15 (written BEFORE running): variant set B, 60-minute opening range
Reason: the zero-spread diagnostic showed a faint raw edge eaten by cost (London: spread = 15% of the average stop).
A longer range gives a wider stop, so the same spread is a smaller share of risk.
Change: RANGE_MIN 30 -> 60. EVERYTHING else identical (3-hour entry window counted from range end, 2R, 4h
time exit counted from the open becomes 5h from the open so the trade has the same 3h+ after the range; exit = open + 300 min).
Variants tried so far: 4 (London30, NY30, London60, NY60). Same pass criteria, same 2018-2024 window.
If this fails, no more range-length tweaks on this rule: the next step is a different idea, not a different number.
