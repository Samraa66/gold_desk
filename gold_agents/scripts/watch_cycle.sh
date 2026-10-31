#!/bin/bash
# Fired every 5 minutes by golddesk-watch.timer. Desk v3.1's look at gold and the other markets (desk v3 before v3.1 was
# deployed): a quiet tick asks OANDA for bars and stops; only a trigger or a fixed slot runs the desk. One line per tick in
# journal/watch.log; a failure sends one Telegram message per hour.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
exec 9>journal/.bars.lock
# The same lock as news_cycle.sh: a tick and a news poll never wake the desk at once.
flock -n 9 || { echo "$(date -u +%FT%TZ) another cycle holds the bars; skipped" >> journal/watch.log; exit 0; }
OUT="$(.venv/bin/python -m gold_agents --desk v31 watch 2>&1)"; CODE=$?
echo "$OUT" | tail -20 >> journal/watch.log
if [ "$CODE" -ne 0 ]; then
  STAMP="journal/.watch_alert_$(date -u +%Y%m%d%H)"
  if [ ! -e "$STAMP" ]; then
    touch "$STAMP"
    .venv/bin/python -c "
from gold_agents import notify
notify.send('Gold desk v3.1 watcher failed. Details are in journal/watch.log on the server.')
" >> journal/watch.log 2>&1
  fi
  exit 1
fi
