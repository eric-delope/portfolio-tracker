"""Check watchlist price alerts from the command line, optionally with a macOS notification.

    python -m portfolio_tracker.alerts            # print status
    python -m portfolio_tracker.alerts --notify   # also notify for newly reached alerts

Meant to run on a schedule (e.g. launchd, once per trading day).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .research import Research
from .watchlist import Watchlist, alert_status, mark_triggered

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WATCHLIST = ROOT / "data" / "user" / "watchlist.json"


def notify(title: str, message: str) -> None:
    """macOS notification via AppleScript; silently skipped on other systems."""
    if sys.platform != "darwin":
        return
    script = f'display notification {json_quote(message)} with title {json_quote(title)} sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def json_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    parser = argparse.ArgumentParser(description="Check watchlist price alerts.")
    parser.add_argument("--watchlist", type=Path, default=DEFAULT_WATCHLIST)
    parser.add_argument("--notify", action="store_true", help="macOS notification for newly reached alerts")
    args = parser.parse_args()

    wl = Watchlist(args.watchlist)
    if not len(wl):
        print("Watchlist is empty.")
        return
    research = Research(ROOT / "data" / "cache")
    quotes = research.quotes([e.ticker for e in wl])
    prices = {tk: p for tk, p in quotes["price"].items() if p is not None}

    newly = mark_triggered(wl, prices)
    wl.save()

    status = alert_status(wl, prices)
    for _, r in status.sort_values("distance").iterrows():
        dist = "–" if r["distance"] is None else f"{r['distance'] * 100:+.1f}%"
        print(f"{r['state']:8s} {r['name'][:28]:28s} {r['label'][:12]:12s} "
              f"alert {r['alert_price']:.2f} {r['currency']} | now {r['price'] or float('nan'):.2f} | {dist}")

    for entry, alert in newly:
        msg = f"{entry.name}: {alert.label or 'Alert'} reached at {alert.price:.2f} {entry.currency}"
        print("NEW:", msg)
        if args.notify:
            notify("Price alert", msg)


if __name__ == "__main__":
    main()
