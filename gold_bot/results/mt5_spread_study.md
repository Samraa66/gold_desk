# Real XAUUSD spread on MetaQuotes-Demo (measured 2026-10-15/16)

Source: the `spread` field of MT5's own M1 bars, 12,036 bars, 2026-10-05 to 2026-10-16 02:35 UTC (8+ trading days, every hour covered).
In price units (points / 100).

| Window (UTC) | Median | 90th pct | Notes |
|---|---|---|---|
| All hours | 0.21 | 0.33 | mean 0.22, 99th pct 0.50, max 0.93 |
| 07-19 (London + New York) | 0.19 | 0.26 | |
| 00-07 (Asia) | 0.24 | 0.34 | |
| 22-24 (rollover) | 0.38 | 0.51 | max 0.93; 22:00 hour is the widest |

Minutes above 0.60: 0.2%. Above 1.00: none.

## What this does and does not say
- The backtests assumed 0.60 (plus 0.30 commission/slippage). On this feed the typical cost is about a third of that.
- This is MetaQuotes' own demo server, not a retail broker: no commission is shown here and retail brokers usually quote wider
  or add a commission. The sample is 8 days with no stress event in it. So 0.60 stays the base assumption until the user's REAL
  broker demo is measured; this only shows the assumption is not unreasonably low.
- The tick sampler (data/mt5/spread_XAUUSD.csv, 341 rows over 24 h) is NOT used: it caught the feed only when the Mac was active
  (likely macOS throttling the background app), so it is biased. Median 0.38 there, from a sample skewed to certain hours.
- The pass criteria were fixed at 0.60 before the runs and are not re-judged here.
