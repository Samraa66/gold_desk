#!/bin/bash
# One scheduled cycle: refresh bars, make a call, log it, score the log.
# Bars come from OANDA (OANDA_API_TOKEN in research/gold_agents/.env) unless BAR_SOURCE=mt5, which needs the MT5
# terminal open on the DEMO account. UNVERIFIED end to end: run it once by hand and read the output before scheduling it.
#   scripts/run_cycle.sh            rules-only call (no API key needed)
#   scripts/run_cycle.sh --llm      agents + master use the model (needs ANTHROPIC_API_KEY)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BOT="$HERE/../gold_bot"
SINCE="$(date -u -v-10d +%Y-%m-%d)"

cd "$HERE"
if [ "${BAR_SOURCE:-oanda}" = "mt5" ]; then
  ( cd "$BOT" && mt5/run_win_python.sh mt5/export_bars.py XAUUSD "$SINCE" )
else
  .venv/bin/python -m gold_agents.oanda_data "$SINCE"
fi
.venv/bin/python -m gold_agents run --notify "$@"
.venv/bin/python -m gold_agents score
