"""Load and clean a broker's CSV transaction export.

The exports mix the securities account (trades, dividends) with the cash
account (transfers, card payments, interest). ``brokers`` turns each supported
format into one typed transaction table with a normalized ``event`` column;
columns that only carry personal data (counterparty names, IBANs, free-text
descriptions) are dropped on import. This module adds checks and summaries.

Sign conventions in the export, verified against the raw data:
- ``shares`` is signed: positive for buys, negative for sells.
- ``amount`` is the gross cash amount *excluding* fees and taxes.
- ``fee`` and ``tax`` are separate signed cash amounts (negative = paid,
  positive = refunded).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from . import brokers

log = logging.getLogger(__name__)

NUMERIC_COLUMNS = ["shares", "price", "amount", "fee", "tax"]

# Absolute tolerance (EUR) for |amount + shares * price| on trades; covers
# rounding of fractional shares.
TRADE_AMOUNT_TOLERANCE = 0.05

# Position sizes below this are treated as zero (float noise after selling).
SHARE_EPSILON = 1e-6


def load_transactions(path) -> pd.DataFrame:
    """Read a broker export into a clean, chronologically sorted table.

    Trade Republic, Scalable Capital and the generic CSV layout are recognised by their header line
    (``brokers.detect``); the detected format is kept in ``tx.attrs["format"]``.
    """
    data = path.getvalue() if hasattr(path, "getvalue") else Path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    fmt_name, tx = brokers.parse(text)
    tx.attrs["format"] = fmt_name
    return tx


def trades(tx: pd.DataFrame) -> pd.DataFrame:
    """Only buy and sell rows."""
    return tx[tx["event"].isin(["buy", "sell"])]


def validate(tx: pd.DataFrame) -> list[str]:
    """Plausibility checks; returns a list of human-readable issues (empty = all good)."""
    issues: list[str] = []

    dupes = tx["transaction_id"].duplicated()
    if dupes.any():
        issues.append(f"{dupes.sum()} duplicate transaction_id(s)")

    t = trades(tx)
    wrong_sign = t[((t["event"] == "buy") & (t["shares"] <= 0))
                   | ((t["event"] == "sell") & (t["shares"] >= 0))]
    for _, row in wrong_sign.iterrows():
        issues.append(f"{row['date']:%Y-%m-%d} {row['name']}: {row['event']} with shares={row['shares']}")

    mismatch = (t["amount"] + t["shares"] * t["price"]).abs() > TRADE_AMOUNT_TOLERANCE
    for _, row in t[mismatch].iterrows():
        issues.append(
            f"{row['date']:%Y-%m-%d} {row['name']}: amount {row['amount']:.2f} "
            f"!= shares x price {row['shares'] * row['price']:.2f}"
        )

    running = t.groupby("isin")["shares"].cumsum()
    oversold = t[running < -SHARE_EPSILON]
    for _, row in oversold.iterrows():
        issues.append(f"{row['date']:%Y-%m-%d} {row['name']}: position negative after sell")

    balance = tx["net_cash"].cumsum()
    if (balance < -0.01).any():
        first = tx.loc[(balance < -0.01).idxmax(), "date"]
        issues.append(f"Cash balance negative from {first:%Y-%m-%d} (export incomplete?)")

    return issues


def holdings(tx: pd.DataFrame, as_of: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Open positions (shares per ISIN) as of a booking date, default: end of export."""
    t = trades(tx)
    if as_of is not None:
        t = t[t["date"] <= pd.Timestamp(as_of)]
    pos = (
        t.groupby("isin")
        .agg(name=("name", "last"), asset_class=("asset_class", "last"), shares=("shares", "sum"))
    )
    return pos[pos["shares"].abs() > SHARE_EPSILON].sort_values("name")


def summary(tx: pd.DataFrame) -> pd.Series:
    """Cash-flow totals per category in EUR."""
    by_event = tx.groupby("event")
    gross = by_event["amount"].sum()
    net = by_event["net_cash"].sum()
    return pd.Series({
        "deposits": gross.get("deposit", 0.0),
        "withdrawals": gross.get("withdrawal", 0.0),
        "card_spending": net.get("card", 0.0),
        "bought (gross)": gross.get("buy", 0.0),
        "sold (gross)": gross.get("sell", 0.0),
        "dividends (net)": net.get("dividend", 0.0),
        "interest (net)": net.get("interest", 0.0),
        "saveback": net.get("saveback", 0.0),
        "trading fees": trades(tx)["fee"].sum(),
        "taxes incl. refunds": tx["tax"].sum(),
        "cash balance": tx["net_cash"].sum(),
    }).round(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a broker CSV export (Trade Republic, Scalable Capital, generic).")
    parser.add_argument("csv", type=Path, help="Path to the export")
    parser.add_argument("--out", type=Path, help="Write the cleaned table to this CSV file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    tx = load_transactions(args.csv)
    print(f"Format: {tx.attrs.get('format')}")
    print(f"{len(tx)} transactions, {tx['date'].min():%Y-%m-%d} to {tx['date'].max():%Y-%m-%d}\n")

    issues = validate(tx)
    print("Validation:", "OK" if not issues else f"{len(issues)} issue(s)")
    for issue in issues:
        print("  -", issue)

    print("\nOpen positions:")
    print(holdings(tx).to_string())
    print("\nCash-flow summary (EUR):")
    print(summary(tx).to_string())

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        tx.to_csv(args.out, index=False)
        print(f"\nCleaned table written to {args.out}")


if __name__ == "__main__":
    main()
