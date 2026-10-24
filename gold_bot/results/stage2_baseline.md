# Stage 2: plain breakout baseline, chosen on 2025, judged on 2026

Rule: 15-min close breaks the last N bars' high/low -> enter next minute. Stop K x ATR, target M x ATR,
one position at a time, closed at 24h. Buys pay the ask, exits on the real side, same-minute tie = stop.
8 settings tried (N 48/96, K 1/2, M 2/4). Picked on 2025 only, then run on 2026 (never seen).

Picked: N=96, stop 1x ATR, target 4x ATR.
| Spread | 2025 (chosen on) | 2026 (unseen) | 2026 max drawdown |
|---|---|---|---|
| 0.60 | +380 pts (525 trades, 22% win) | +404 pts (376 trades, 23% win) | 571 pts |
| 1.00 | +135 pts | +217 pts | 572 pts |

## What this does and does not show
- Positive in both halves after costs, including the worse spread. A much better result than the channel's signals.
- NOT a pass. Both halves are one regime: gold rose from about 2,600 to 5,500 with rising volatility, which suits
  breakout rules. 2026 beat 2025 for almost every setting tried, which points at the market, not the rule.
- The drawdown (571) is larger than the profit (404). A 22% win rate means long losing runs.
- Only 8 settings were tried, but only one asset, one 21-month window and one regime. The pass criteria ask for
  more than one regime. 2022-2024 (ranging, then trending) has not been tested.
- Next: test the same rule, untouched, on earlier years (HistData has XAUUSD back to 2009), and add a
  cost stress with a wider spread around news.
