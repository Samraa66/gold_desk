"""READ-ONLY MT5 probe (milestones 1-2). Runs under Windows Python inside the MT5 Wine prefix; see mt5/README.md.

Connects to the already-running terminal, refuses to go on unless the account is a DEMO account, and records the
symbol's real trading specification and a few recent bars. It never calls any order function (tests/test_mt5_readonly.py
fails if this file, or any other file in mt5/, mentions one). The account login is NOT written to the output.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"


def fail(msg: str) -> None:
    print("FAIL:", msg)
    mt5.shutdown()
    sys.exit(1)


TERMINAL = os.environ.get("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
if not mt5.initialize(path=TERMINAL):
    fail(f"initialize() -> {mt5.last_error()}")
acc, term = mt5.account_info(), mt5.terminal_info()
if acc is None:
    fail("no account info: is the terminal logged in?")
if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
    fail(f"account trade_mode={acc.trade_mode} is not DEMO. Stopping.")
if not mt5.symbol_select(SYMBOL, True):
    fail(f"symbol {SYMBOL} unavailable -> {mt5.last_error()}")
time.sleep(1.0)
s = mt5.symbol_info(SYMBOL)
ticks = [mt5.symbol_info_tick(SYMBOL) for _ in range(1)]
bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 5)
out = {
    "probed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "python": sys.version.split()[0], "mt5_package": mt5.__version__,
    "terminal": {"build": term.build, "connected": term.connected, "trade_allowed": term.trade_allowed,
                 "company": term.company},
    "account": {"server": acc.server, "demo": True, "currency": acc.currency, "leverage": acc.leverage,
                "margin_mode": acc.margin_mode, "trade_allowed": acc.trade_allowed, "trade_expert": acc.trade_expert,
                "balance": acc.balance},
    "symbol": {k: getattr(s, k) for k in (
        "name", "description", "path", "digits", "point", "spread", "spread_float", "trade_contract_size",
        "trade_tick_size", "trade_tick_value", "trade_tick_value_profit", "trade_tick_value_loss", "volume_min",
        "volume_max", "volume_step", "trade_stops_level", "trade_freeze_level", "trade_mode", "trade_exemode",
        "filling_mode", "swap_mode", "swap_long", "swap_short", "currency_base", "currency_profit", "currency_margin",
        "margin_initial", "session_deals", "visible")},
    "tick": None if ticks[0] is None else {"time_utc_like": int(ticks[0].time), "bid": ticks[0].bid, "ask": ticks[0].ask},
    "last_bars_m1": [{"time": int(b["time"]), "open": float(b["open"]), "close": float(b["close"]),
                      "spread": int(b["spread"])} for b in (bars if bars is not None else [])],
}
if ticks[0] is not None:
    out["tick"]["spread_price"] = round(ticks[0].ask - ticks[0].bid, 6)
text = json.dumps(out, indent=2, default=str)
print(text)
if len(sys.argv) > 2:
    open(sys.argv[2], "w").write(text)
mt5.shutdown()
