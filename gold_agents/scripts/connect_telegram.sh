#!/bin/bash
# Connect the gold desk's OWN Telegram bot (never the product's or a client's) so BUY/SELL entries reach your phone.
# 1. In @BotFather create a bot and COPY its token (it stays on your clipboard; it is never printed or typed here).
# 2. Send that bot any message (e.g. "hi") from your own Telegram account.
# 3. Run:  ! scripts/connect_telegram.sh
# It checks the token, finds your chat, deploys the latest code, writes GOLD_TG_TOKEN / GOLD_TG_CHAT into the server's .env
# (replacing older values) and sends one test message.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOST="${GOLD_VPS:-root@138.68.188.28}"; KEY="${GOLD_VPS_KEY:-$HOME/.ssh/telegram_bot_vps}"
ENVF=/home/golddesk/gold_desk/gold_agents/.env
looks_like_token() { case "$1" in [0-9]*:*[A-Za-z0-9_-]) [ "${#1}" -ge 40 ] && [ "${#1}" -le 70 ] ;; *) return 1 ;; esac; }
# token source: GOLD_TG_TOKEN in the local gold_agents/.env (easiest), else the clipboard
TOKEN="$(grep -E '^GOLD_TG_TOKEN=' "$HERE/../.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '[:space:]"'"'"'' || true)"
looks_like_token "$TOKEN" || TOKEN="$(pbpaste | tr -d '[:space:]')"
if ! looks_like_token "$TOKEN"; then
  echo "Waiting up to 2 minutes: copy the bot token from BotFather now (the clipboard does not hold one yet)."
  for _ in $(seq 1 120); do
    sleep 1; TOKEN="$(pbpaste | tr -d '[:space:]')"
    looks_like_token "$TOKEN" && break
  done
fi
looks_like_token "$TOKEN" || { echo "No bot token appeared on the clipboard. Run this again, then copy the token."; exit 1; }
curl -fsS "https://api.telegram.org/bot$TOKEN/getMe" >/dev/null || { echo "Telegram rejected that token."; exit 1; }
CHAT="$(curl -fsS "https://api.telegram.org/bot$TOKEN/getUpdates" | python3 -c "
import json,sys
msgs=[u['message'] for u in json.load(sys.stdin)['result'] if 'message' in u and u['message']['chat']['type']=='private']
print(msgs[-1]['chat']['id'] if msgs else '')")"
[ -n "$CHAT" ] || { echo "The bot has no messages yet. Send it 'hi' from your Telegram, then run this again."; exit 1; }
"$HERE/deploy_vps.sh" >/dev/null
printf 'GOLD_TG_TOKEN=%s\nGOLD_TG_CHAT=%s\n' "$TOKEN" "$CHAT" | ssh -i "$KEY" -o BatchMode=yes "$HOST" \
  "f=$ENVF; sed -i '/^GOLD_TG_TOKEN=/d;/^GOLD_TG_CHAT=/d' \$f; cat >> \$f; chown golddesk:golddesk \$f; chmod 600 \$f"
curl -fsS "https://api.telegram.org/bot$TOKEN/sendMessage" -d "chat_id=$CHAT" \
  --data-urlencode "text=Gold desk connected. You will get a message for every BUY or SELL entry (PASS stays silent). Research only, no orders are placed." >/dev/null
echo "Connected. Test message sent to your Telegram; the next scheduled slot will use it."
