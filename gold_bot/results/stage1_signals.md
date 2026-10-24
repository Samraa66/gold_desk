# Stage 1: do the channel's own signals make money on real candles?

Data: 1,212 fully specified signals (entry zone, stop, numbered targets), 2025-07-10 to 2026-04-20.
49 posts dropped for impossible levels (typos). Candles: 1-minute XAUUSD, spread assumed fixed.
Worst case rule: a minute touching both stop and target counts as the stop.
Points: 1.00 = $1 move on one ounce (= 10 "pips" as the channel counts them; 1 lot = 100 oz).

| Entry | Spread | Run as | n | Win rate | Avg pts/trade | Total pts | Max drawdown pts |
|---|---|---|---|---|---|---|---|
| as claimed (zone midpoint) | 0.60 | all-in TP1 | 1134 | 71.8% | +0.40 | +450 | 236 |
| as claimed | 0.60 | split + BE after TP1 | 1134 | 71.8% | +0.54 | +616 | 212 |
| as claimed | 1.00 | all-in TP1 | 1134 | 70.5% | +0.06 | +66 | 330 |
| after the post (market) | 0.60 | all-in TP1 | 1212 | 62.5% | -0.78 | -949 | 977 |
| after the post (market) | 0.60 | split + BE after TP1 | 1212 | 64.7% | -0.55 | -668 | 726 |
| after the post (market) | 1.00 | all-in TP1 | 1212 | 59.6% | -1.14 | -1382 | 1408 |

## Findings
1. Reward to risk is about 0.5 (median stop $7, median first target $3.50). A 62-72% win rate barely carries that.
2. At the claimed entry price the edge is small and positive; with a $1.00 spread it is almost gone.
3. Entering after the post, as any follower does, the same signals lose money in every variant.
   31% of signals are entered more than $2 worse than the quoted zone.
4. Therefore: copying these signals with a delay is not a profitable strategy. Any edge lives in the entry timing.

## Caveats (not yet resolved)
- "After the post" uses the close of the posting minute: up to 59 s late, and ignores follower reaction time.
  The truth for a fast follower lies between the two entry models.
- Spread is a fixed assumption; real spreads widen around news. Slippage on stops is not modelled.
- Posts after 2026-04 use a different, chat-style format with no stop/targets and are not scored here.
- Not yet done: comparison with the trader's own recap claims.
