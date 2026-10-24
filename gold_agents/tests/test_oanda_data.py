import pandas as pd

from gold_agents import oanda_data as O
from gold_agents.data import load_m1


def candle(t, bid, ask, complete=True):
    b = {"o": bid, "h": bid + 1, "l": bid - 1, "c": bid}
    a = {"o": ask, "h": ask + 1, "l": ask - 1, "c": ask}
    return {"time": t, "complete": complete, "bid": {k: str(v) for k, v in b.items()}, "ask": {k: str(v) for k, v in a.items()}}


class Resp:
    status_code = 200
    def __init__(self, body): self.body = body
    def json(self): return self.body
    def raise_for_status(self): pass


class Session:
    def __init__(self, pages): self.pages, self.calls = list(pages), []
    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return Resp({"candles": self.pages.pop(0) if self.pages else []})


def test_parse_keeps_only_complete_candles_and_converts_spread_to_points():
    df = O.parse_candles({"candles": [candle("2026-10-20T10:00:00.000000000Z", 4000.0, 4000.30),
                                      candle("2026-10-20T10:01:00.000000000Z", 4001.0, 4001.30, complete=False)]})
    assert len(df) == 1
    assert df["spread"].iloc[0] == 30.0 and df["close"].iloc[0] == 4000.0


def test_fetch_sends_the_token_and_stops_on_a_short_page():
    s = Session([[candle("2026-10-20T10:00:00.000000000Z", 4000.0, 4000.2)]])
    df = O.fetch_since(pd.Timestamp("2026-10-20", tz="UTC"), "tok", session=s, now=pd.Timestamp("2026-10-20T12:00Z").to_pydatetime())
    assert len(df) == 1 and len(s.calls) == 1
    assert s.calls[0][2]["Authorization"] == "Bearer tok" and "fxpractice" in s.calls[0][0]


def test_refresh_merges_without_duplicates_and_oanda_wins_in_load_m1(tmp_path, monkeypatch):
    path = tmp_path / "o.csv"
    s1 = Session([[candle("2026-10-20T10:00:00.000000000Z", 4000.0, 4000.2)]])
    monkeypatch.setattr(O, "_env", lambda name: {"OANDA_API_TOKEN": "tok"}.get(name))
    now = pd.Timestamp("2026-10-20T12:00Z").to_pydatetime()
    O.refresh(pd.Timestamp("2026-10-20", tz="UTC"), path=path, session=s1, now=now)
    s2 = Session([[candle("2026-10-20T10:00:00.000000000Z", 4000.5, 4000.7), candle("2026-10-20T10:01:00.000000000Z", 4001.0, 4001.2)]])
    O.refresh(pd.Timestamp("2026-10-20", tz="UTC"), path=path, session=s2, now=now)
    got = O.read_csv(path)
    assert len(got) == 2 and got["close"].iloc[0] == 4000.5
    m1 = load_m1(hist=None, mt5=None, oanda=path)
    assert abs(m1["spread"].iloc[0] - 0.2) < 1e-9


class Flaky(Session):
    def __init__(self, codes, pages): super().__init__(pages); self.codes = list(codes)
    def get(self, url, params=None, headers=None, timeout=None):
        if self.codes:
            code = self.codes.pop(0)
            if code == "timeout":
                import requests
                raise requests.Timeout()
            r = Resp({}); r.status_code = code; return r
        return super().get(url, params, headers, timeout)


def test_a_gateway_error_or_timeout_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(O.time, "sleep", lambda s: None)
    s = Flaky([504, "timeout"], [[candle("2026-10-20T10:00:00.000000000Z", 4000.0, 4000.2)]])
    df = O.fetch_since(pd.Timestamp("2026-10-20", tz="UTC"), "tok", session=s, now=pd.Timestamp("2026-10-20T12:00Z").to_pydatetime())
    assert len(df) == 1


def test_a_gateway_error_that_never_clears_still_fails_loudly(monkeypatch):
    import pytest
    monkeypatch.setattr(O.time, "sleep", lambda s: None)
    class Bad(Resp):
        status_code = 504
        def raise_for_status(self): raise O.requests.HTTPError("504")
    class S:
        def get(self, *a, **k): return Bad({})
    with pytest.raises(O.requests.HTTPError):
        O.fetch_since(pd.Timestamp("2026-10-20", tz="UTC"), "tok", session=S(), now=pd.Timestamp("2026-10-20T12:00Z").to_pydatetime())
