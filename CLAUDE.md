# CLAUDE.md

Research project, not a product. Read `gold_agents/README.md` before changing anything: it holds the pass criteria, the version history (v1, v2) and what has been tested.

## Layout
- `gold_agents/` — the desk (Python package `gold_agents`, own `.venv`, Python 3.13 from `/opt/miniconda3`). Code reads `../gold_bot/data/` for bars, so the two folders must stay siblings (same layout as the VPS).
- `gold_bot/` — earlier failed research; kept for its data and MT5 tools.
- Secrets in `gold_agents/.env` (gitignored): `ANTHROPIC_API_KEY` (a research key, never the Telelytics product key), `OANDA_API_TOKEN` (practice), `GOLD_TG_TOKEN` / `GOLD_TG_CHAT`.

## Commands (from `gold_agents/`)
```bash
.venv/bin/python -m pytest -q                                   # offline tests
.venv/bin/python -m gold_agents --desk v2 run --dry --llm       # one call, written nowhere
.venv/bin/python -m gold_agents --desk v2 --instrument XAU_USD score
scripts/deploy_vps.sh                                           # code only; never touches the server's journal, .env or bars
scripts/pull_dashboard.sh                                       # copy the LIVE logs and dashboards to ~/gold_desk_live
```
Score on the VPS, not locally: local bars for silver/EUR/GBP go stale and every call reads "pending".

## Where it runs
VPS 138.68.188.28 (shared with the Telelytics product, `ssh -i ~/.ssh/telegram_bot_vps root@138.68.188.28`). The desk lives at `/home/golddesk/gold_desk/{gold_agents,gold_bot}` as the unprivileged user `golddesk`, systemd `golddesk.timer` (weekdays 06/10/14/18 UTC). Never touch `/root/telegram-lead-bot` or the `telegrambot` service from this project.

The one link to Telelytics: its developer-only page `telelytics.org/admin/gold-desk` (`backend/app/gold_desk_routes.py` in that repo) reads `/home/golddesk/gold_desk/gold_agents/journal/` (dashboards and `calls*.jsonl`). Renaming those files or that folder breaks the page.

## Rules
- No order code. None is added until the README's Stage B pass criteria are met (30+ resolved calls over 6+ weeks, avg R > +0.15 after costs, beat the H4-trend baseline, llm beats rules).
- Criteria and config are never retuned on the same data. A config change once a live log has started is a new version with its own hash and log.
- Replays are plumbing checks, never evidence; the model layer can only be tested forward (past dates leak).
- A PASS is a normal answer. When the desk says PASS, a live read given to the user says PASS too; no fades into a momentum leg (rising lows / falling highs), and extra caution right after high-impact events.
