# Stage 2b: the same rule on every year, 2018-2026

Rule and settings fixed beforehand (picked on 2025): 15-min breakout of the last 96 bars, stop 1x ATR,
target 4x ATR, one position at a time, 24h limit, bid/ask costs, same-minute tie = stop.

| Year | Trades | Win % | Total pts | Total % of price |
|---|---|---|---|---|
| 2018 | 570 | 10.0 | -329 | -25.9 |
| 2019 | 568 | 11.4 | -292 | -21.4 |
| 2020 | 486 | 17.3 | -205 | -12.9 |
| 2021 | 487 | 15.0 | -270 | -15.0 |
| 2022 | 486 | 16.5 | -222 | -12.4 |
| 2023 | 441 | 14.3 | -323 | -16.6 |
| 2024 | 497 | 18.1 | -205 | -9.4 |
| 2025 | 529 | 21.7 | +368 | +8.7 |
| 2026 | 376 | 22.6 | +404 | +8.2 |

(spread 0.60; at 1.00 the pattern is the same and every earlier year is worse)

## Verdict: FAILS the pass criteria
- Profitable in 2 years of 9, and only in the two years gold went nearly vertical.
- All 8 settings tried lose in every year from 2018 to 2024. This is not one unlucky setting.
- The 2025-2026 result was the market, not the rule. Stage 2's "pass" was a false positive of a single regime,
  which is exactly what testing across regimes exists to catch.

## Caveats
- 2023 has about 13% fewer bars than other years (gaps in the free data).
- A fixed $0.60 spread is likely optimistic for 2018-2020, which would make the earlier years look worse still,
  not better. It does not rescue the rule.
- Years 2018-2024 have now been looked at. Any new idea tried on them needs a fresh untouched test period.
