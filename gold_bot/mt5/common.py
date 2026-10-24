"""Shared read-only MT5 connection for the scripts in this folder (Windows Python inside the MT5 Wine prefix)."""
import os
import sys
import time
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))      # so `src.mt5_data` imports under Wine
from src.mt5_data import detect_offset_hours  # noqa: E402

TERMINAL = os.environ.get("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")


def connect_demo(symbol: str):
    """Initialise, refuse anything that is not a demo account, select the symbol. Returns the server offset in hours."""
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"FAIL initialize: {mt5.last_error()}")
    acc = mt5.account_info()
    if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
        mt5.shutdown()
        raise SystemExit("FAIL: not a demo account (or not logged in). Stopping.")
    if not mt5.symbol_select(symbol, True):
        mt5.shutdown()
        raise SystemExit(f"FAIL: symbol {symbol} unavailable: {mt5.last_error()}")
    return tick_offset(symbol)


def tick_offset(symbol: str) -> int:
    for _ in range(10):
        t = mt5.symbol_info_tick(symbol)
        if t is not None and t.time:
            return detect_offset_hours(int(t.time), time.time())
        time.sleep(0.5)
    raise SystemExit("FAIL: no tick received (market closed or no connection)")
