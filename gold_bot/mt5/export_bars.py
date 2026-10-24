"""Append MT5 M1 bars (bid-based, converted to UTC) to data/mt5/xauusd_m1.csv. Read-only. Usage: export_bars.py [SYMBOL] [SINCE_UTC]"""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]  # the embeddable Python ignores the script dir
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import MetaTrader5 as mt5

from common import connect_demo
from src.mt5_data import MT5_CSV, merge_bars, read_mt5, to_utc_frame

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
SINCE = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-10-05", tz="UTC")

offset = connect_demo(SYMBOL)
now = datetime.now(timezone.utc)
# MT5 reads and writes "server time as if it were UTC": ask a day wider on both sides, then filter after conversion
lo = (SINCE - pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=None)
hi = (now + timedelta(days=1)).replace(tzinfo=None)
rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, lo, hi)
if rates is None or len(rates) == 0:
    mt5.shutdown(); raise SystemExit(f"FAIL: no bars returned: {mt5.last_error()}")
new = to_utc_frame(pd.DataFrame(rates), offset)
new = new[(new.index >= SINCE) & (new.index <= pd.Timestamp(now) - pd.Timedelta("1min"))]   # never store the forming bar
old = read_mt5()
merged = merge_bars(old, new)
MT5_CSV.parent.mkdir(parents=True, exist_ok=True)
merged.to_csv(MT5_CSV)
print(f"server offset +{offset}h; stored {len(old)} -> {len(merged)} bars, {merged.index.min()} .. {merged.index.max()}")
mt5.shutdown()
