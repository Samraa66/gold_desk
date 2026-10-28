#!/bin/bash
# Fired every hour by launchd (com.telelytics.golddesk). Acts only at 06/10/14/18 UTC on weekdays:
# refresh bars once, make the rules call and the model call on the SAME timestamp, score the log, rebuild the dashboard.
# Output goes to journal/cycle.log. A repeated time/mode/rules is never logged twice (idempotent).
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
# launchd fires hourly and needs this gate; systemd's timer already fires only at the slots (GOLD_NO_GATE=1).
if [ -z "${GOLD_NO_GATE:-}" ]; then
  DOW="$(date -u +%u)"; HOUR="$(date -u +%H)"
  case "$HOUR" in 06|10|14|18) ;; *) exit 0 ;; esac
  [ "$DOW" -le 5 ] || exit 0
fi
AS_OF="$(date -u +%Y-%m-%dT%H:00:00Z)"
FAILED=""
step() { name="$1"; shift; "$@" || { echo "STEP FAILED: $name"; FAILED="$FAILED $name"; return 1; }; }
# Gold first (the original record), then the added instruments. One instrument failing never stops the rest.
INSTRUMENTS="${GOLD_INSTRUMENTS:-XAU_USD XAG_USD EUR_USD GBP_USD}"
{
  echo "=== $(date -u +%FT%TZ) cycle as_of=$AS_OF"
  for INST in $INSTRUMENTS; do
    echo "--- $INST"
    if step "bars-$INST" .venv/bin/python -m gold_agents.oanda_data auto "$INST"; then
      # v1: the original record, logged silently since 2026-10-28 (its WATCH leans went 0 for 16; v2 sends the messages)
      step "rules-$INST" .venv/bin/python -m gold_agents --instrument "$INST" run --as-of "$AS_OF" --rules-only
      step "model-$INST" .venv/bin/python -m gold_agents --instrument "$INST" run --as-of "$AS_OF" --llm
      step "score-$INST" .venv/bin/python -m gold_agents --instrument "$INST" score
      step "dashboard-$INST" .venv/bin/python -m gold_agents --instrument "$INST" dashboard
      # v2 (2026-10-28): reads the candles + structure, calls setups at levels. Only the model's call is sent to Telegram.
      step "v2-rules-$INST" .venv/bin/python -m gold_agents --desk v2 --instrument "$INST" run --as-of "$AS_OF" --rules-only
      step "v2-model-$INST" .venv/bin/python -m gold_agents --desk v2 --instrument "$INST" run --as-of "$AS_OF" --llm
      step "v2-score-$INST" .venv/bin/python -m gold_agents --desk v2 --instrument "$INST" score
      step "v2-dashboard-$INST" .venv/bin/python -m gold_agents --desk v2 --instrument "$INST" dashboard
    else
      echo "bar refresh failed for $INST; its calls were skipped"
    fi
  done
} >> journal/cycle.log 2>&1
# Telegram (2026-10-28): one message per slot with every instrument's v2 decision, calls and passes; after the last
# slot of the day (18:00 UTC) the day's scorecard.
{
  step "v2-digest" .venv/bin/python -m gold_agents digest --as-of "$AS_OF" --instruments "${INSTRUMENTS// /,}" --send
  if [ "${AS_OF:11:2}" = "18" ]; then
    step "v2-scorecard" .venv/bin/python -m gold_agents scorecard --instruments "${INSTRUMENTS// /,}" --send
  fi
} >> journal/cycle.log 2>&1
# One message per failed cycle (never per step). PASS stays silent, so this is how a broken job gets noticed.
if [ -n "$FAILED" ]; then
  .venv/bin/python -c "
import sys
from gold_agents import notify
notify.send('Gold desk cycle ' + sys.argv[1] + ' had a problem at:' + sys.argv[2] + '. Details are in journal/cycle.log on the server.')
" "$AS_OF" "$FAILED" >> journal/cycle.log 2>&1
  exit 1
fi
