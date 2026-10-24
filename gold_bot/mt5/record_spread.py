"""Sample the live XAUUSD spread to data/mt5/spread_XAUUSD.csv (append). Read-only.
Usage: record_spread.py [SYMBOL] [HOURS] [SECONDS_BETWEEN_SAMPLES]. Rows are written only when the tick changed, so a closed market adds nothing."""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]  # the embeddable Python ignores the script dir
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

from common import connect_demo, tick_offset

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
HOURS = float(sys.argv[2]) if len(sys.argv) > 2 else 24
EVERY = float(sys.argv[3]) if len(sys.argv) > 3 else 5
OUT = Path(__file__).resolve().parent.parent / "data" / "mt5" / f"spread_{SYMBOL}.csv"

offset = connect_demo(SYMBOL)
OUT.parent.mkdir(parents=True, exist_ok=True)
new_file = not OUT.exists()
end, last, n = time.time() + HOURS * 3600, None, 0
with open(OUT, "a", newline="") as fh:
    w = csv.writer(fh)
    if new_file:
        w.writerow(["utc", "bid", "ask", "spread", "server_offset_h"])
    while time.time() < end:
        t = mt5.symbol_info_tick(SYMBOL)
        if t is not None and t.time_msc != last:
            last = t.time_msc
            utc = datetime.fromtimestamp(t.time_msc / 1000 - offset * 3600, timezone.utc)
            w.writerow([utc.isoformat(timespec="milliseconds"), t.bid, t.ask, round(t.ask - t.bid, 5), offset]); n += 1
            if n % 20 == 0:
                fh.flush()
        if n % 500 == 499:
            offset = tick_offset(SYMBOL)          # follow a server-clock change instead of freezing the old offset
        time.sleep(EVERY)
mt5.shutdown()
print(f"done: {n} samples")
