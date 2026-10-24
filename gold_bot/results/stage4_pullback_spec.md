# Stage 4 spec: H1 trend + M15 pullback on XAUUSD (written 2026-10-14, BEFORE any code or run)

A research hypothesis, not a belief. Nothing here is known to be profitable.

## Rules (fixed now; no fitting)
Bars are built from the 1-minute BID file (UTC). A bar is usable only after it has closed.
- **Trend (H1):** EMA50 vs EMA200 of H1 closes, using the last H1 bar that had CLOSED at the M15 signal bar's close.
  Up if EMA50 > EMA200 (longs only). Down if EMA50 < EMA200 (shorts only). Needs 200 H1 bars of history.
- **Pullback + confirmation (M15 signal bar i, evaluated at its close):**
  - Long: some M15 low in bars i-3..i is <= M15 EMA20 at that bar (a touch), AND close_i > EMA20_i,
    AND close_i > open_i, AND close_i > high_(i-1).
  - Short: mirror (high >= EMA20 within i-3..i, close_i < EMA20_i, close_i < open_i, close_i < low_(i-1)).
- **Session filter:** signal bar closes between 07:00 and 19:00 UTC, Monday to Friday. (Avoids the illiquid rollover and
  Asian hours when real spreads widen; fixed now, not tuned.)
- **Entry:** market, at the OPEN of the first 1-minute bar after the signal bar closes. Buy pays the ask (bid + spread),
  sell hits the bid. If no bar exists within 2 minutes of the close (data gap), no trade.
- **Stop:** long = the further of (lowest low of the last 10 M15 bars incl. the signal bar) and (entry bid - 1.0 x ATR14);
  short mirrored. If the stop is more than 3.0 x ATR14 from the entry bid, SKIP the trade (volatility out of limits).
- **Target:** RR x R, with R = entry (ask-adjusted) to stop distance. Two settings only: **RR 1.5 and RR 2.0**.
- **Time exit:** 12 hours after entry, at the market (a short pays the spread on the way out).
- **One position at a time.** A signal while a position is open is ignored.
- **Costs:** spread 0.60 plus 0.30 points per trade for commission and slippage (base). Stress: spread 1.00 plus 0.60.
  A minute touching both stop and target counts as the stop. Entry minute's own range counts for exits.
- **Position size (for the account curve only):** 0.25% of equity risked per trade, results in R multiples
  (net points / R after costs). Real lot sizing needs broker contract data and is milestone 7.
- **Not modelled, stated plainly:** (1) the US economic-release exclusion window: no calendar data is in the repo, so the
  backtest trades through news and the stress costs stand in for it; the demo must add a real calendar before it means
  anything. (2) Spread is fixed, not the broker's real spread. (3) Swaps (positions are held at most 12 h, some across
  rollover). (4) Real commission.

## Data split (chronological, fixed now)
- **Research:** 2018-01 to 2021-12. **Validation:** 2022-01 to 2023-12. **Test:** 2024-01 to the end of the file (2026-10-09).
- Honesty note: other rules (stages 2 and 3) were looked at on all of these years, so the test years are not virgin
  market history. They ARE untouched by THIS rule. The code enforces one look: the test run needs the RR chosen from
  research + validation, and refuses to run a second time (lock file). The real clean test is the demo forward run.
- Walk-forward: the rule has no fitted parameter, so a rolling fit is meaningless; the per-year table is the walk-forward.

## Ideas tried so far (multiple-testing count)
Stage 2: 8 settings. Stage 2c: 1 model family. Stage 3: 4 variants. This stage: 2 (RR 1.5, 2.0). Total >= 15.
Any later change to the rules above is a NEW variant and is added to the count.

## Pass criteria (decided before the run)
Base costs unless stated. ALL must hold:
1. Research AND validation each: net R > 0 and profit factor >= 1.15.
2. Trade counts: research >= 300, validation >= 150, test >= 200.
3. Test (run once, with the RR picked on research + validation total R): net R > 0 and profit factor >= 1.15.
4. Stress costs: total net R over research + validation + test > 0.
5. At least 6 of the 9 calendar years (2018-2026) positive in net R at base costs.
6. Remove the best 5% of trades by R over the whole sample: total net R still > 0 (profit is not a few lucky trades).
7. Account curve at 0.25% risk per trade: max equity drawdown <= 10% in every period.
8. Cross-check: no result is counted if the test fails for the chosen RR, even if the other RR looks better.
Fail any one = the strategy FAILS and is not allowed to go to demo.

## Informational only (cannot change the rules or the verdict)
- Sensitivity on research + validation only: EMA20 -> 10/30, swing lookback 10 -> 5/20, min stop 1.0 -> 0.75/1.5 ATR.
  The result is robust only if neighbours are also positive; a lone good setting means overfit.
- Performance by regime on research + validation: H1 trend strength (|EMA50-EMA200| / ATR, terciles) and volatility (ATR terciles).
