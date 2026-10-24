"""The MT5 folder must stay read-only until the order milestone: no order or position-changing calls anywhere in it."""
import re
from pathlib import Path

FORBIDDEN = re.compile(r"order_send|order_check|order_calc|positions_close|TRADE_ACTION|ORDER_TYPE_(BUY|SELL)|Sltp|position_close", re.I)

def test_mt5_folder_has_no_order_calls():
    files = list(Path("mt5").glob("*.py"))
    assert files
    hits = [(f.name, m.group(0)) for f in files for m in FORBIDDEN.finditer(f.read_text())
            if not (f.name == "probe.py" and m.start() < f.read_text().index('import json'))]  # the docstring may name them
    assert hits == [], hits
