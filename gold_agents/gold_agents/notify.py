"""Optional Telegram message. Needs GOLD_TG_TOKEN and GOLD_TG_CHAT in the environment or .env; otherwise a no-op.
Use a SEPARATE bot from the product's (never a client's bot or chat)."""
from __future__ import annotations

import os
from pathlib import Path

import requests


def _env(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    f = Path(__file__).resolve().parent.parent / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip() or None
    return None


def send(text: str, session=requests) -> bool:
    token, chat = _env("GOLD_TG_TOKEN"), _env("GOLD_TG_CHAT")
    if not token or not chat:
        return False
    try:
        r = session.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=15)
        return r.ok
    except Exception:
        return False
