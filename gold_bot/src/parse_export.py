"""Telegram Desktop/macOS HTML export -> one table of messages.

Columns: msg_id, ts_local (naive, as the app showed it), reply_to, text, edited, has_media.
The export carries no time zone: calibrate it against the candles (see calibrate_tz.py).
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

DATE_FMT = "%d %B %Y, %H:%M:%S"


def parse_file(path: Path) -> list[dict]:
    soup = BeautifulSoup(path.read_text(encoding="utf8"), "lxml")
    out = []
    for m in soup.select("div.message.default"):
        mid = (m.get("id") or "").replace("message", "")
        date = m.select_one(".date")
        if not mid or date is None or not date.get("title"):
            continue
        text_el = m.select_one(".text")
        reply = m.select_one(".reply_to a")
        rid = None
        if reply is not None:
            hit = re.search(r"go_to_message(\d+)", reply.get("onclick", "") or reply.get("href", ""))
            rid = int(hit.group(1)) if hit else None
        out.append({
            "msg_id": int(mid),
            "ts_local": datetime.strptime(date["title"].split(" UTC")[0], DATE_FMT),
            "reply_to": rid,
            "text": text_el.get_text("\n", strip=True) if text_el else "",
            "edited": m.select_one(".edited") is not None,
            "has_media": m.select_one(".media_wrap, .photo_wrap, .video_file_wrap") is not None,
        })
    return out


def parse_dir(folder: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(folder.glob("messages*.html"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 1)):
        rows.extend(parse_file(f))
    df = pd.DataFrame(rows).drop_duplicates("msg_id").sort_values("msg_id").reset_index(drop=True)
    return df


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    df = parse_dir(folder)
    dest = folder.parent / f"messages_{folder.name}.parquet"
    df.to_parquet(dest)
    print(len(df), "messages", df.ts_local.min(), "->", df.ts_local.max(), "| with text:", int((df.text != '').sum()),
          "| replies:", int(df.reply_to.notna().sum()))
