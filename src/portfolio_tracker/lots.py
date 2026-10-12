"""FIFO lot accounting (first in, first out), as required by German tax law (§ 20 Abs. 4 S. 7 EStG).

Every buy opens a lot. A sell consumes the oldest open lots first; each
consumed (partial) lot becomes one row in the realized-gains table. Order fees
are part of the cost basis (buy) or reduce the proceeds (sell); taxes are kept
separate so all gains here are pre-tax.
"""

from __future__ import annotations

from collections import defaultdict, deque

import pandas as pd

from .importer import SHARE_EPSILON, trades

OPEN_LOT_COLUMNS = ["isin", "name", "asset_class", "buy_date", "buy_id", "shares", "cost", "cost_per_share"]
REALIZED_COLUMNS = [
    "isin", "name", "asset_class", "buy_date", "sell_date", "buy_id", "sell_id",
    "shares", "cost", "proceeds", "gain", "return_pct", "holding_days", "tax",
]


def fifo(tx: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(open_lots, realized)`` for all trades in ``tx``."""
    queues: dict[str, deque[dict]] = defaultdict(deque)
    realized: list[dict] = []

    for row in trades(tx).sort_values("datetime", kind="stable").itertuples(index=False):
        if row.event == "buy":
            cost = -(row.amount + row.fee)
            queues[row.isin].append({
                "isin": row.isin, "name": row.name, "asset_class": row.asset_class,
                "buy_date": row.date, "buy_id": row.transaction_id,
                "shares": row.shares, "cost_per_share": cost / row.shares,
            })
            continue

        to_sell = -row.shares
        proceeds_per_share = (row.amount + row.fee) / to_sell
        tax_per_share = row.tax / to_sell
        queue = queues[row.isin]
        while to_sell > SHARE_EPSILON:
            if not queue:
                raise ValueError(f"{row.date:%Y-%m-%d} {row.name}: sold more shares than bought")
            lot = queue[0]
            take = min(lot["shares"], to_sell)
            cost = take * lot["cost_per_share"]
            proceeds = take * proceeds_per_share
            realized.append({
                "isin": row.isin, "name": row.name, "asset_class": row.asset_class,
                "buy_date": lot["buy_date"], "sell_date": row.date,
                "buy_id": lot["buy_id"], "sell_id": row.transaction_id,
                "shares": take, "cost": cost, "proceeds": proceeds,
                "gain": proceeds - cost, "return_pct": proceeds / cost - 1,
                "holding_days": (row.date - lot["buy_date"]).days,
                "tax": take * tax_per_share,
            })
            lot["shares"] -= take
            to_sell -= take
            if lot["shares"] <= SHARE_EPSILON:
                queue.popleft()

    open_lots = [
        {**lot, "cost": lot["shares"] * lot["cost_per_share"]}
        for queue in queues.values() for lot in queue
    ]
    return (
        pd.DataFrame(open_lots, columns=OPEN_LOT_COLUMNS),
        pd.DataFrame(realized, columns=REALIZED_COLUMNS),
    )


def apply_splits(tx: pd.DataFrame, splits: dict[str, pd.Series]) -> pd.DataFrame:
    """Restate pre-split shares and prices in post-split units.

    ``splits`` maps ISIN -> Series of split ratios indexed by effective date
    (e.g. 10.0 for a 10:1 split). Cash amounts are unchanged by a split.
    """
    tx = tx.copy()
    for isin, ratios in splits.items():
        for split_date, ratio in ratios.items():
            mask = (tx["isin"] == isin) & (tx["date"] < split_date) & tx["shares"].notna()
            tx.loc[mask, "shares"] *= ratio
            tx.loc[mask, "price"] /= ratio
    return tx
