#!/bin/bash
# Copy the live dashboards, call logs, model prompts and frozen outcomes from the VPS to ~/gold_desk_live/ and open it. Read-only on the server.
set -euo pipefail
HOST="${GOLD_VPS:-root@138.68.188.28}"; KEY="${GOLD_VPS_KEY:-$HOME/.ssh/telegram_bot_vps}"
R=/home/golddesk/gold_desk/gold_agents/journal
mkdir -p "$HOME/gold_desk_live"
rsync -a -e "ssh -i $KEY -o BatchMode=yes" --include="dashboard*.html" --include="calls*.jsonl" --include="prompts*.jsonl" --include="outcomes*.jsonl" --include="watch_v3.jsonl" --include="cycle.log" --exclude="*" "$HOST:$R/" "$HOME/gold_desk_live/" 2>&1 | grep -v "^$" || true
if [ -f "$HOME/gold_desk_live/dashboard.html" ]; then open "$HOME/gold_desk_live"/dashboard*.html; else echo "no dashboard yet: the first cycle (06:02 UTC) creates it"; fi
echo "tail of cycle.log:"; tail -n 12 "$HOME/gold_desk_live/cycle.log" 2>/dev/null || true
