"""One spec per instrument the desk watches (added 2026-10-24).

Gold keeps its original config, files and log byte for byte; its spec is the baseline. Every other instrument gets
its own bar file, its own call log and its own `Config` (stop limits, contract size, assumed costs, rounding), so the
`rules_hash` differs and results are never pooled across instruments. `extra["instrument"]` carries the OANDA name.

Costs are conservative guesses at OANDA practice spreads plus slippage, fixed before any result is seen.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config

HERE = Path(__file__).resolve().parent.parent
GOLD_BOT = HERE.parent / "gold_bot"


@dataclass(frozen=True)
class Instrument:
    oanda: str                 # OANDA name, also the id used in logs
    label: str                 # what the prompts and cards call it
    file: str                  # bar csv name under gold_bot/data/oanda/
    journal: str               # call log name under journal/
    dashboard: str
    dp: int                    # decimals when printing prices
    spread_scale: float        # csv spread value x this = price units (gold's csv stores points, others store price)
    overrides: dict            # Config fields that differ from gold
    macro_weights: dict        # sign/size of each macro driver for THIS instrument (see agents/macro.py)

    def config(self) -> Config:
        return Config(**self.overrides, extra={"instrument": self.oanda, "label": self.label, "dp": self.dp})

    @property
    def bars_path(self) -> Path:
        return GOLD_BOT / "data" / "oanda" / self.file

    @property
    def journal_path(self) -> Path:
        return HERE / "journal" / self.journal

    @property
    def dashboard_path(self) -> Path:
        return HERE / "journal" / self.dashboard


# macro drivers: dxy %, us10y pp, silver %, vix pts, spx % (weights are fed to tanh scales in agents/macro.py)
GOLD_WEIGHTS = {"dxy": -0.4, "us10y": -0.4, "silver": 0.1, "vix": 0.1, "spx": 0.0}
USD_QUOTE_WEIGHTS = {"dxy": -0.5, "us10y": -0.3, "silver": 0.0, "vix": -0.1, "spx": 0.1}   # EUR/USD, GBP/USD: strong dollar = down

INSTRUMENTS: dict[str, Instrument] = {i.oanda: i for i in (
    Instrument("XAU_USD", "gold (XAUUSD)", "xauusd_m1.csv", "calls.jsonl", "dashboard.html", 2, 0.01, {}, GOLD_WEIGHTS),
    Instrument("XAG_USD", "silver (XAGUSD)", "xagusd_m1.csv", "calls_xagusd.jsonl", "dashboard_xagusd.html", 3, 1.0,
               dict(min_stop=0.15, max_stop=3.0, spread_assumed=0.06, slippage_assumed=0.03),
               {**GOLD_WEIGHTS, "silver": 0.0}),
    Instrument("EUR_USD", "EUR/USD", "eurusd_m1.csv", "calls_eurusd.jsonl", "dashboard_eurusd.html", 5, 1.0,
               dict(min_stop=0.0008, max_stop=0.0150, spread_assumed=0.00015, slippage_assumed=0.00005), USD_QUOTE_WEIGHTS),
    Instrument("GBP_USD", "GBP/USD", "gbpusd_m1.csv", "calls_gbpusd.jsonl", "dashboard_gbpusd.html", 5, 1.0,
               dict(min_stop=0.0010, max_stop=0.0200, spread_assumed=0.00020, slippage_assumed=0.00007), USD_QUOTE_WEIGHTS),
)}

# Units per 1.00 lot (USD value of a 1.0 price move per lot, as every spec here is quoted in USD).
ROUND_STEP = {"XAU_USD": 50.0, "XAG_USD": 1.0, "EUR_USD": 0.01, "GBP_USD": 0.01}   # "big figure" for key levels
CONTRACT = {"XAU_USD": 100.0, "XAG_USD": 5000.0, "EUR_USD": 100_000.0, "GBP_USD": 100_000.0}


def get(name: str | None) -> Instrument:
    name = (name or "XAU_USD").upper()
    if name not in INSTRUMENTS:
        raise SystemExit(f"unknown instrument {name!r}; known: {', '.join(INSTRUMENTS)}")
    return INSTRUMENTS[name]


def of(cfg: Config) -> Instrument:
    return get(cfg.extra.get("instrument"))
