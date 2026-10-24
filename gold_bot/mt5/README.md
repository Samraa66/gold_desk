# MT5 link (read-only until the order milestone)

Setup done 2026-10-14: MetaTrader 5 (MetaQuotes' Mac app, Wine 11.1) + Windows Python 3.12.10 embeddable at
`~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/py312` with `MetaTrader5`, numpy, pandas.
Run: `mt5/run_win_python.sh mt5/probe.py XAUUSD results/mt5_probe.json` (terminal must be open and logged in).
`probe.py` stops unless the API reports a DEMO account and never calls any order function (tests/test_mt5_readonly.py).

## Findings 2026-10-15 (results/mt5_probe.json), MetaQuotes-Demo, XAUUSD
- Demo, USD, leverage 1:100, hedging, balance 100,000. Market execution, volume 0.01 to 100 step 0.01, contract 100 oz.
- Spread is floating: one sample 0.47 (47 points); the last five M1 bars showed 0.23 to 0.30. A real spread study needs
  hours of samples across sessions before it replaces the 0.60 assumption.
- Swap: long -12.6 points, short -4.6 points per night (swap_mode 1 = points).
- WARNING tick value: the server reports trade_tick_value 0.1 for tick size 0.01, but contract 100 oz implies 1.0 USD per tick
  per lot (a $1 move = $100 on 1.00 lot, not $10). Position sizing must NOT trust tick_value alone: cross-check against
  contract_size x tick_size and reject the trade if they disagree.
- Server time is UTC+3 (tick time 04:54 when real UTC was 01:54). The terminal log runs on the Mac's Wine clock (GMT-5).
  Every timestamp from MT5 must be converted before it is compared with the UTC research data.
- terminal.trade_allowed is False: the AutoTrading button is OFF, so API orders would be refused. Leave it off until the
  order milestone.

## Added 2026-10-15
- `mt5/export_bars.py` appends MT5 M1 bars (bid-based, converted to UTC, forming bar never stored, older bars never rewritten) to
  data/mt5/xauusd_m1.csv. `src/mt5_data.py` holds the tested conversion and merge logic. The terminal caps M1 requests at ~50,000 bars.
- `mt5/record_spread.py [SYMBOL] [HOURS] [SECONDS]` samples the live spread to data/mt5/spread_XAUUSD.csv (a row per changed tick).
- Feed the call log from MT5: `mt5/run_win_python.sh mt5/export_bars.py XAUUSD 2026-10-05`, then `python -m src.paper_calls log --mt5`.
- MT5's server clock = New York wall time + 7 h (UTC+2 winter, UTC+3 summer). See results/DATA_FIX_time_labels.md for how this
  exposed the HistData time bug.
