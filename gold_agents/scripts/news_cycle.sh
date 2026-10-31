#!/bin/bash
# Fired every minute by golddesk-news.timer. Desk v3.1's news poll: rules only, so a quiet poll calls no model. A fresh relevant
# headline wakes the desk through the same helper, daily budget and state file as the 5-minute tick, under the same lock.
# Quiet polls and closed hours leave no line; anything else goes to journal/news.log. A failure sends one Telegram message per hour.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
exec 9>journal/.bars.lock
flock -n 9 || exit 0          # a tick or a wake holds the bars; an unseen headline is picked up next minute
OUT="$(.venv/bin/python -m gold_agents --desk v31 news-poll 2>&1)"; CODE=$?
if [ "$CODE" -ne 0 ] || ! echo "$OUT" | tail -1 | grep -qE ' (quiet|market shut)$'; then
  echo "$OUT" | tail -20 >> journal/news.log
fi
if [ "$CODE" -ne 0 ]; then
  STAMP="journal/.news_alert_$(date -u +%Y%m%d%H)"
  if [ ! -e "$STAMP" ]; then
    touch "$STAMP"
    .venv/bin/python -c "
from gold_agents import notify
notify.send('Gold desk v3.1 news poll failed. Details are in journal/news.log on the server.')
" >> journal/news.log 2>&1
  fi
  exit 1
fi
