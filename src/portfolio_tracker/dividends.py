"""Dividend dashboard: income received, expected income and the personal dividend yield."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .portfolio import Portfolio


def received(p: Portfolio) -> pd.DataFrame:
    """Dividends booked in the account: date, name, gross, withholding tax, net."""
    d = p.tx[p.tx["event"] == "dividend"]
    return pd.DataFrame({"date": d["date"], "isin": d["isin"], "name": d["name"], "gross": d["amount"],
                         "tax": d["tax"], "net": d["net_cash"]}).sort_values("date")


def forecast(p: Portfolio, history: dict[str, pd.Series], horizon_days: int = 365) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per position, upcoming payments) for today's holdings.

    Expected payments repeat the last year's pattern: the most recent dividend per
    share is assumed to be paid again at the usual interval. Amounts are converted
    to EUR at today's exchange rate. Payment dates are approximated by ex-dates.
    """
    pos = p.positions
    today = p.last_date
    rows, upcoming = [], []
    for isin, row in pos.iterrows():
        tk = p.tickers.get(isin)
        h = history.get(tk, pd.Series(dtype=float)) if tk else pd.Series(dtype=float)
        h = h.sort_index() if len(h) else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        last_year = h[h.index > today - pd.Timedelta(days=365)]
        code = "GBP" if row["currency"] == "GBp" else row["currency"]
        fx = float(p.prices.fx[code].dropna().iloc[-1]) if code in p.prices.fx else 1.0
        scale = 0.01 if row["currency"] == "GBp" else 1.0
        dps_eur = last_year.sum() * scale / fx
        income = dps_eur * row["shares"]
        rows.append({"isin": isin, "name": row["name"], "payments_per_year": len(last_year),
                     "dps_eur": dps_eur, "income": income, "value": row["value"], "cost": row["cost"],
                     "yield": income / row["value"] if row["value"] else np.nan,
                     "yield_on_cost": income / row["cost"] if row["cost"] else np.nan})
        if len(last_year):
            interval = (pd.Series(h.index).diff().dt.days.tail(4).median() if len(h) > 1 else 365) or 365
            next_date = h.index[-1] + pd.Timedelta(days=float(interval))
            amount = float(h.iloc[-1]) * scale / fx * row["shares"]
            while next_date <= today + pd.Timedelta(days=horizon_days):
                if next_date > today:
                    upcoming.append({"date": next_date, "name": row["name"], "amount": amount,
                                     "per_share": float(h.iloc[-1]) * scale / fx})
                next_date += pd.Timedelta(days=float(interval))
    per_position = pd.DataFrame(rows).set_index("isin") if rows else pd.DataFrame()
    return per_position, pd.DataFrame(upcoming).sort_values("date") if upcoming else pd.DataFrame(
        columns=["date", "name", "amount", "per_share"])
