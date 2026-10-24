#!/bin/bash
# macOS blocks launchd jobs from reading ~/Documents, so the scheduled runner lives in ~/gold_desk.
# This syncs CODE (never the journal, .env, bars or venv) from the repo to the runner, and builds the runner on first use.
# Re-run it after any code change you want the scheduler to use. Changing config.py starts a new rules_hash (see README).
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/gold_desk"
mkdir -p "$DEST/gold_agents" "$DEST/gold_bot/data"
rsync -a --delete --exclude '.venv' --exclude 'journal' --exclude '.env' --exclude 'data' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$SRC/" "$DEST/gold_agents/"
mkdir -p "$DEST/gold_agents/journal" "$DEST/gold_agents/data"
rsync -a "$SRC/data/" "$DEST/gold_agents/data/"
[ -f "$DEST/gold_agents/.env" ] || { cp "$SRC/.env" "$DEST/gold_agents/.env"; chmod 600 "$DEST/gold_agents/.env"; }
# bars: history + MT5 once; the OANDA file is the runner's own from here on
rsync -a --ignore-existing "$SRC/../gold_bot/data/xauusd_m1_histdata.parquet" "$DEST/gold_bot/data/"
mkdir -p "$DEST/gold_bot/data/mt5" && rsync -a --ignore-existing "$SRC/../gold_bot/data/mt5/xauusd_m1.csv" "$DEST/gold_bot/data/mt5/"
if [ ! -x "$DEST/gold_agents/.venv/bin/python" ]; then
  /opt/miniconda3/bin/python3 -m venv "$DEST/gold_agents/.venv"
  "$DEST/gold_agents/.venv/bin/pip" install -q -r "$DEST/gold_agents/requirements.txt"
fi
echo "runner ready at $DEST/gold_agents"
