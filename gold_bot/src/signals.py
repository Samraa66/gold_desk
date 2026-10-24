"""Turn channel posts into structured signals, and recognise the updates that follow them.

A signal: direction, entry zone (lo, hi), stop loss, take-profit levels (numbers; a bare
"TP" with no number is an open runner and is counted separately). Anything that does not
parse cleanly is returned as None and counted: we never guess a level.
"""
import re

import pandas as pd

NUM = r"(\d{3,5}(?:\.\d+)?)"
_DIR = re.compile(r"\b(buy|sell)\b", re.I)
_ENTRY = re.compile(rf"\b(?:buy|sell)(?:\s+(?:limit|stop))?\s*(?:@|at|now)?\s*{NUM}(?:\s*[-–/,]\s*{NUM})?", re.I)
_SL = re.compile(rf"\bSL\s*[:@]?\s*{NUM}", re.I)
# "TP 4822", "TP1 3887", "TP: 3810", or a bare "TP" (an open runner). The optional index is a
# single digit NOT followed by more digits, so it can never eat the first digit of a price.
_TP = re.compile(rf"\bTP\s*(?:\d(?![\d.]))?\s*[:@]?\s*{NUM}?", re.I)
_RECAP = re.compile(r"\b(recap|pips|closed early|so far)\b", re.I)
_PLAUSIBLE = (1500.0, 9000.0)       # a gold price; guards against "TP 25" style noise


def parse_signal(text: str):
    if not text or _RECAP.search(text):
        return None
    d = _DIR.search(text)
    sl = _SL.search(text)
    if not (d and sl):
        return None
    e = _ENTRY.search(text)
    if e:
        lo = float(e.group(1))
        hi = float(e.group(2)) if e.group(2) else lo
        lo, hi = min(lo, hi), max(lo, hi)
    else:
        lo = hi = None                      # market entry: priced from the candle at post time
    stop = float(sl.group(1))
    tps, runners = [], 0
    for m in _TP.finditer(text):
        if m.group(1):
            tps.append(float(m.group(1)))
        else:
            runners += 1
    direction = d.group(1).lower()
    levels = [stop] + tps + ([lo, hi] if lo is not None else [])
    if not all(_PLAUSIBLE[0] <= v <= _PLAUSIBLE[1] for v in levels):
        return None
    ref_lo = lo if lo is not None else (min(tps) if direction == "buy" and tps else stop)
    if direction == "buy":
        if not (stop < (lo if lo is not None else min(tps + [stop + 1]))):
            return None
        if lo is not None and not all(t > hi for t in tps):
            return None
    else:
        if not (stop > (hi if hi is not None else max(tps + [stop - 1]))):
            return None
        if hi is not None and not all(t < lo for t in tps):
            return None
    return {"direction": direction, "entry_lo": lo, "entry_hi": hi, "sl": stop,
            "tps": tps, "runners": runners}


_BE = re.compile(r"\b(sl\s*(?:to|at)?\s*(?:be|break\s*even|entry)|break\s*even|breakeven|\bbe\b)", re.I)
_SL_MOVE = re.compile(rf"\b(?:change\s+|move\s+)?sl\s*(?:to|at|@)\s*{NUM}", re.I)
_CLOSE = re.compile(r"\b(close[sd]?\s+(?:all|now|here|manually)|exit|cut\s+(?:it|the trade|loss)|stopped\s+out)\b", re.I)


def classify_update(text: str):
    """BE | SL_MOVE | CLOSE | None for a post that is not a signal."""
    if not text:
        return None
    if _SL_MOVE.search(text):
        return "SL_MOVE"
    if _BE.search(text):
        return "BE"
    if _CLOSE.search(text):
        return "CLOSE"
    return None


def extract(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in df.itertuples():
        s = parse_signal(r.text)
        if s:
            rows.append({"msg_id": r.msg_id, "ts_local": r.ts_local, "text": r.text, **s})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    df = pd.read_parquet(sys.argv[1])
    sig = extract(df)
    cand = df[df.text.str.contains(r"\b(buy|sell)\b", case=False) & df.text.str.contains(r"\bSL\b", case=False)]
    print(f"{len(sig)} signals parsed of {len(cand)} posts that mention buy/sell and SL")
    print(sig.direction.value_counts().to_dict(), "| with >=1 numbered TP:", int((sig.tps.str.len() > 0).sum()))
    rejected = cand[~cand.msg_id.isin(sig.msg_id)]
    print("\nsample of buy/sell+SL posts NOT parsed:")
    for t in rejected.text.sample(min(12, len(rejected)), random_state=2):
        print("•", t[:170].replace("\n", " | "))
    sig.to_parquet(sys.argv[1].replace("messages_", "signals_"))
