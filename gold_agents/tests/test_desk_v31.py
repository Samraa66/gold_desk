"""Desk v3.1 (2026-10-31). Offline: no network, no key, no bars beyond the synthetic ones."""
import pandas as pd
import pytest

from gold_agents import desk_v2 as V2
from gold_agents import desk_v3 as V3
from gold_agents import instruments as I
from gold_agents.config import rules_hash

# Read once on 2026-10-31 from the code at the v3 baseline commit and pasted here. v3.1 must leave every one of them alone.
KNOWN_HASHES = {
    "v1": {"XAU_USD": "0eed0fd6", "XAG_USD": "d9bb2b05", "EUR_USD": "b87656d9", "GBP_USD": "1740076f"},
    "v2": {"XAU_USD": "80b98c11", "XAG_USD": "df6c1617", "EUR_USD": "969c1a3d", "GBP_USD": "f827a7ce"},
    "v3": "2bbfa4f5",
}


# ---------------- identity ----------------
def test_older_hashes_do_not_move():
    assert {k: rules_hash(s.config()) for k, s in I.INSTRUMENTS.items()} == KNOWN_HASHES["v1"]
    assert {k: V2.v2_hash(s.config()) for k, s in I.INSTRUMENTS.items()} == KNOWN_HASHES["v2"]
    assert V3.v3_hash(V3.config()) == KNOWN_HASHES["v3"]
