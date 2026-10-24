#!/bin/bash
# Run a script with the Windows Python that lives inside MetaTrader 5's Wine prefix (MT5 must be open and logged in).
#   mt5/run_win_python.sh mt5/probe.py XAUUSD results/mt5_probe.json
W="/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine"
export WINEPREFIX="$HOME/Library/Application Support/net.metaquotes.wine.metatrader5" WINEDEBUG=-all
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
script="$1"; shift
args=()
for a in "$@"; do case "$a" in results/*|data/*) args+=("Z:$ROOT/$a");; *) args+=("$a");; esac; done
cd "$WINEPREFIX/drive_c/py312" && "$W" python.exe "Z:$ROOT/$script" "${args[@]}"
