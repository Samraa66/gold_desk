# Gold bot research (XAUUSD)

Standalone research. Nothing here imports from `backend/`, nothing here is deployed,
and no real money is involved until a written pass criterion is met.

## Question
Can a rule-based or statistical strategy for XAUUSD make money after spread and
slippage, on data it never trained on? And do the real traders whose signals we
already receive have an edge worth learning from?

## Stages (each one can end the project)
1. Score the traders' own signals against real candles, with costs.
2. Baseline strategy, walk-forward, same costs, compared with the traders.
3. Demo account forward test, 2-3 months. No real money before this passes.
4. Tiny real size. Only then, anything near clients.

## Pass criteria (written before looking at results)
- Positive after spread and slippage on data it never saw.
- Holds across more than one market regime (trend, range, high volatility).
- Max drawdown we could live with: set before the first run, recorded in `results/`.

## Layout
- `data/`     market data and exported signals. NEVER committed (see .gitignore).
- `src/`      code.
- `results/`  written findings and charts that are safe to commit (no trader or client names).

## Setup
Own environment, separate from the product:
    cd gold_bot && python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

## Status (updated 2026-10-13)
- Stage 1 done: the channel's signals lose money for a follower (results/stage1_signals.md).
- Stage 2 done: a plain breakout rule looks profitable in 2025-26 but loses in 7 of 7 earlier years
  (results/stage2_baseline.md, results/stage2b_regimes.md). FAILED. No demo account, no real money.
- Data: Dukascopy's raw feed refuses scripted downloads (they point to their official export page), so the
  history comes from HistData.com files placed by hand in data/histdata*/.
- Stage 2c (ML on price features): weak skill (AUC 0.52-0.57), never clears costs at 15-minute scale. FAILED validation
  (results/stage2c_ml.md). 2025-26 holdout was opened by mistake once (19 trades, noise), so it is no longer clean.
- Stage 3 (2026-10-15): session opening-range breakout, London and New York, rules fixed in results/stage3_orb_spec.md.
  FAILED both sessions (results/stage3_orb.md). Faint raw edge (PF 1.06-1.09 at zero spread) is smaller than the spread.
  Variant set B (60-minute range) also FAILED (0/7 years). Rule retired; next step is a different idea.

## Tests (added 2026-10-14)
    source .venv/bin/activate && python -m pytest -q
`src/engine.py` holds the shared fill logic (used by `src/orb.py`). `tests/` covers fills, bid/ask sides, the
stop-wins-ties rule, entry-bar exclusion, DST handling, and look-ahead. `baseline.py` and `score.py` still carry
their own copies of the fill logic and are not yet migrated or tested.

## Stage 4 (2026-10-14): H1 EMA50/200 trend + M15 pullback
Spec and pass criteria written before any run: results/stage4_pullback_spec.md. Code: src/pullback.py, src/run_pullback.py.
FAILED at the dev stage (research 2018-21 and validation 2022-23 both negative, 6 of 6 years negative, all 6 sensitivity
neighbours negative; zero-cost PF 1.02, i.e. no edge before costs). Test years 2024+ never opened (results/stage4_dev.md).
`baseline.py` now uses src/engine.py too, output unchanged (its "picked on 2025 only" label was wrong, it is 2018-2025).
`score.py` (stage 1) is the only script still carrying its own fill logic.

## Stage 5 (2026-10-14): H4 Donchian breakout (spec: results/stage5_h4_spec.md)
FAILED at dev: research PF 0.92, validation PF 1.20 (needs >= 1.15 in both). Zero-cost PF 1.11, base 1.01: cost is not the
main problem on 4-hour bars, there is just little signal. Test years never opened. Ideas tried: 16.
**Forward call log** (`python -m src.paper_calls log`, then `score`): the frozen rule logs BUY/SELL calls on data after 2026-10-09
into an append-only file (results/paper_calls_<rulehash>.csv); each call is scored only from later data; nothing is judged
under 30 resolved calls; a call logged more than 6 h after its bar closed is flagged late. To feed it: re-download the current
month's HistData XAUUSD zip into data/histdata/, then `python -m src.paper_calls log --rebuild`. Once MT5 is up, the same
log can be fed from the terminal automatically.
