"""The live demo's market-data snapshot may only contain symbols of the synthetic demo – never real holdings."""

import csv
import json
import pickle
import re
from pathlib import Path

import pytest

from portfolio_tracker.market import BENCHMARKS, DEFAULT_TICKER_OVERRIDES

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "demo_cache"
pytestmark = pytest.mark.skipif(not SNAPSHOT.exists(), reason="no demo snapshot built")


def allowed() -> set[str]:
    with (ROOT / "data/sample/demo_portfolio.csv").open() as f:
        isins = {r["symbol"] for r in csv.DictReader(f) if r["symbol"]}
    watch = json.loads((ROOT / "data/sample/demo_watchlist.json").read_text())["entries"]
    us = json.loads((SNAPSHOT / "guidance" / "us_symbols.json").read_text()) if (SNAPSHOT / "guidance").exists() else {}
    return ({DEFAULT_TICKER_OVERRIDES[i] for i in isins} | {e["ticker"] for e in watch} | set(BENCHMARKS.values())
            | set(us.values()))


def symbols_in_snapshot() -> set[str]:
    found = set()
    prices = pickle.loads((SNAPSHOT / "prices.pkl").read_bytes())
    found |= {c for c in prices["data"].columns if not re.fullmatch(r"EUR[A-Z]{3}=X", c)}
    for name in ("dividends.pkl", "splits.pkl"):
        found |= set(pickle.loads((SNAPSHOT / name).read_bytes()))
    found |= set(json.loads((SNAPSHOT / "metadata.json").read_text()))
    found |= {p.stem.removeprefix("fund_") for p in (SNAPSHOT / "research").glob("*.pkl")}
    found |= {p.stem.removeprefix("filings_").replace("_", ".") for p in (SNAPSHOT / "guidance").glob("filings_*.pkl")}
    return found


def test_snapshot_holds_only_demo_symbols():
    extra = symbols_in_snapshot() - allowed()
    assert not extra, f"non-demo symbols in data/demo_cache: {sorted(extra)} – rebuild with scripts/make_demo_snapshot.py"


def test_snapshot_has_no_personal_files():
    names = {p.name for p in SNAPSHOT.rglob("*")}
    assert not names & {"watchlist.json", "demo_watchlist.json"} and not any(n.endswith(".csv") for n in names)
