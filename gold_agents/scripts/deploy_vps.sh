#!/bin/bash
# Deploy the gold desk to the VPS as its own unprivileged user (golddesk), apart from the product.
# Syncs CODE only on every run; the journal, .env and bar files on the server are never overwritten.
# First run also creates the user, the venv, the systemd timer and seeds the .env and trimmed history.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${GOLD_VPS:-root@138.68.188.28}"; KEY="${GOLD_VPS_KEY:-$HOME/.ssh/telegram_bot_vps}"
SSH="ssh -i $KEY -o BatchMode=yes"
H=/home/golddesk/gold_desk
$SSH "$HOST" "id golddesk >/dev/null 2>&1 || useradd -m -s /bin/bash golddesk; mkdir -p $H/gold_agents/journal $H/gold_agents/data $H/gold_bot/data/oanda"
rsync -a --delete -e "$SSH" --exclude .venv --exclude journal --exclude .env --exclude events.csv --exclude data --exclude __pycache__ --exclude .pytest_cache "$SRC/" "$HOST:$H/gold_agents/"
rsync -a -e "$SSH" "$SRC/data/" "$HOST:$H/gold_agents/data/"
# one-time seeds (never overwritten once present)
$SSH "$HOST" "[ -f $H/gold_agents/.env ]" || rsync -a -e "$SSH" "$SRC/.env" "$HOST:$H/gold_agents/.env"
$SSH "$HOST" "[ -f $H/gold_bot/data/xauusd_m1_histdata.parquet ]" || rsync -a -e "$SSH" "$SRC/../gold_bot/data/xauusd_m1_histdata.parquet" "$HOST:$H/gold_bot/data/"
$SSH "$HOST" "chown -R golddesk:golddesk /home/golddesk && chmod 600 $H/gold_agents/.env"
$SSH "$HOST" "[ -x $H/gold_agents/.venv/bin/python ] || runuser -u golddesk -- bash -c 'python3 -m venv $H/gold_agents/.venv && $H/gold_agents/.venv/bin/pip install -q -r $H/gold_agents/requirements.txt'"
rsync -a -e "$SSH" "$SRC/scripts/systemd/" "$HOST:/etc/systemd/system/"
$SSH "$HOST" "systemctl daemon-reload && systemctl enable --now golddesk-watch.timer && systemctl list-timers "golddesk*" --no-pager | head -4"
echo "deployed to $HOST:$H"
