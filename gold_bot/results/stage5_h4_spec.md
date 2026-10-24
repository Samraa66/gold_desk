# Stage 5 spec: H4 Donchian breakout on XAUUSD (written 2026-10-14, BEFORE any code or run)

Why this idea: stages 3 and 4 showed a flat signal (PF 1.0-1.1 before costs) eaten by a 0.9-point cost on 4-5 point
stops. On H4 bars the stop is ~40 points, so the same cost is ~2% of risk. This tests whether COST was the only problem.
A research hypothesis, not a belief.

## Rules (fixed now; no fitting)
- Bars: 4-hour bars from the 1-minute BID file, UTC-aligned (00,04,08,...), usable only after they close. ATR14 = mean true range of the last 14 H4 bars.
- Signal at an H4 bar close: Long if close > highest HIGH of the previous 20 H4 bars. Short if close < lowest LOW of the previous 20.
- Entry: market at the OPEN of the first minute after the bar closes (no gap over 2 min, else no trade). Buy pays ask (bid + spread).
- Stop: 2.0 x ATR14 from the entry bid (a short's stop is compared with the ask, like every earlier stage). Target: RR 2.0 (= about 4 x ATR).
- Time exit: 5 days (7,200 minutes) after entry, at the market. One position at a time. No session or trend filter.
- Costs: base spread 0.60 + 0.30 per trade; stress spread 1.00 + 0.60. A minute touching both stop and target = the stop.
- Account curve: 0.25% of equity risked per trade, in R multiples (net points / risk).
- Not modelled: news calendar, swaps (positions can last days, so swaps matter here; they can help or hurt by a few points/day on
  a $4,000+ metal), real spreads, real commission.

## Data split (same as stage 4)
Research 2018-01..2021-12, validation 2022-01..2023-12, test 2024-01..2026-10-09. The test is run ONCE (lock file), only if
dev passes. Other stages looked at these years with other rules; the clean test is the forward call log below.

## Ideas tried (multiple-testing count)
Stage 2: 8. Stage 2c: 1. Stage 3: 4. Stage 4: 2. This stage: 1 (single fixed setting). Total >= 16.

## Pass criteria (decided before the run)
1. Research AND validation each: net R > 0, PF >= 1.15.
2. Trades: research >= 60, validation >= 30, test >= 40 (H4 trades are rare; fewer trades = wider error, so the bar is PF not count).
3. Test (once): net R > 0 and PF >= 1.15.
4. Stress costs: total net R over the whole sample > 0.
5. At least 6 of 9 calendar years positive (base costs).
6. Whole sample minus the best 5% of trades: net R still > 0.
7. Max equity drawdown at 0.25% risk <= 10% in every period.
Fail any one = FAIL, not allowed to go to demo.

## Informational (cannot change the rules)
Sensitivity on research + validation: lookback 10 / 40, stop 1.5 / 3.0 ATR, RR 1.5 / 3.0.

## Forward call log (the real test)
After the backtest, whatever its verdict, the frozen rule logs buy/sell calls on data that arrives AFTER 2026-10-09.
`results/paper_calls.csv` is append-only: time of call, side, entry reference, stop, target, and a hash of the rule+params.
Each call is scored later only from market data after the call. Judged on at least 30 resolved calls, not on days elapsed.
A change to the rule means a new rule hash and a NEW log (old rows are never edited or deleted).
