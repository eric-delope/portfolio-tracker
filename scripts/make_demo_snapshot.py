"""Build the market-data snapshot the public live demo runs on (``data/demo_cache``).

    python scripts/make_demo_snapshot.py

Starts from an empty folder and renders every page, tab and research step of the demo once – online – so the
cache ends up holding exactly the public market data the demo needs, and nothing else. Never copy
``data/cache`` instead: it was filled by your own portfolio and would reveal its tickers.
``tests/test_demo_snapshot.py`` checks that the snapshot only contains demo symbols.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "demo_cache"
APP = ROOT / "app" / "dashboard.py"

ANALYSIS_TABS = ["Overview", "Positions", "Performance", "Risk", "Dividends", "Entries & trades", "Taxes & costs"]
RESEARCH_STEPS = ["1 · Overview", "2 · Financials", "3 · Quality", "4 · Growth", "5 · Reverse DCF", "6 · Valuation",
                  "7 · My price", "8 · Plan"]


def main() -> None:
    shutil.rmtree(SNAPSHOT, ignore_errors=True)
    SNAPSHOT.mkdir(parents=True)
    os.environ.update(PORTFOLIO_HOSTED="1", PORTFOLIO_CACHE_DIR=str(SNAPSHOT))
    os.environ.pop("PORTFOLIO_OFFLINE", None)
    from streamlit.testing.v1 import AppTest

    watchlist = [e["ticker"] for e in json.loads((ROOT / "data/sample/demo_watchlist.json").read_text())["entries"]]
    problems = []

    def run(page: str, **state) -> None:
        at = AppTest.from_file(str(APP), default_timeout=900)
        for key, value in state.items():
            at.session_state[key] = value
        at.switch_page(page)
        at.run()
        errors = [e.value for e in at.exception] + [e.value for e in at.error]
        print(f"{page:24s} {state}  {'FAIL ' + str(errors[:1]) if errors else 'ok'}", flush=True)
        problems.extend(errors)

    for ccy in ("EUR", "USD"):
        for page in ("views/monthly.py", "views/planning.py", "views/watchlist.py", "views/privacy.py"):
            run(page, base_ccy=ccy)
        for tab in ANALYSIS_TABS:
            run("views/analysis.py", base_ccy=ccy, depot_tab=tab)
    run("views/watchlist.py", bt_all=True)
    for ticker in watchlist:
        for step in RESEARCH_STEPS:
            run("views/research.py", research_ticker=ticker, rstep=step)

    shutil.rmtree(SNAPSHOT / "yf", ignore_errors=True)       # yfinance's own time-zone cache, not needed
    (SNAPSHOT / "SNAPSHOT").write_text(date.today().isoformat())
    size = sum(f.stat().st_size for f in SNAPSHOT.rglob("*") if f.is_file()) / 1e6
    print(f"\nSnapshot: {len(list(SNAPSHOT.iterdir()))} files, {size:.1f} MB, problems: {len(problems)}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
