# Stage 2c: gradient-boosted model on price features, strict time-order split

Setup: 15-minute bars, 2018-2026. 15 simple features (returns over 5 horizons in ATR units, volatility, distance
to 96-bar high/low, trend gaps, 4h range position, time of day). Label per side: stop 1x ATR, target 2x ATR,
24h limit, bid/ask costs ($0.60), same-minute tie = stop. Train 2018-22, choose cut-off on 2023-24, test 2025-26.
One shallow model per side (depth 3, 150 trees, heavy regularisation).

## Results
- A random entry loses about 0.5-0.6 points per trade (win rate 22% vs 33% break-even). Costs alone do that.
- Skill exists but is weak: AUC (0.5 = none) on 2023-24: long 0.567, short 0.570; on 2025-26: long 0.516, short 0.540.
- It does not clear costs. On validation, the best cut-off (0.30, 331 trades) loses 118 points (win 31.7%, avg -0.36).
  Higher cut-offs leave almost no trades (3 at 0.38, none above): the model never becomes confident enough.
- Verdict: FAILS the validation rule. No cut-off was profitable.

## Process note (be honest about it)
The script was meant to stop before touching 2025-26 when validation failed. A fallback let it run the test anyway:
19 trades, +13 points, which is noise. That result must not be read as evidence. 2025-26 is no longer a clean
holdout for this model family; a future attempt needs a fresh untouched period.

## Reading
- The edge in these features is small and the spread is large relative to a 15-minute ATR ($0.60 against an ATR of a few dollars).
- Most plausible next experiment: a coarser ruler (1-hour or 4-hour bars) so the spread is a smaller share of each
  trade. That is a design change and is run once, with a written pass test, on a fresh holdout.
