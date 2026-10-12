"""Order check: how would a planned buy change concentration, currency mix and risk?

Works on a generic set of positions keyed by ticker, so it handles both adding
to an existing holding and opening a new one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import metrics as m

POSITION_LIMIT = 0.20
SECTOR_LIMIT = 0.40
FEE_PER_ORDER = 1.0


@dataclass
class OrderInputs:
    values: pd.Series        # EUR market value per ticker (current holdings)
    returns: pd.DataFrame    # daily EUR returns per ticker, last ~year, including the target
    meta: pd.DataFrame       # per ticker: name, sector, country, currency
    benchmark: pd.Series     # daily EUR returns of the benchmark (same index as returns)


def snapshot(values: pd.Series, inp: OrderInputs, target: str) -> dict:
    """Portfolio statistics for a given set of position values."""
    values = values[values > 0]
    total = values.sum()
    w = values / total
    meta = inp.meta.reindex(w.index)
    r = inp.returns.reindex(columns=w.index).fillna(0.0)
    port = r @ w
    contrib = m.risk_contributions(w, r)
    # the target's sector comes from the full metadata: before a first buy it is not among the holdings yet
    sector = inp.meta.loc[target, "sector"] if target in inp.meta.index else None
    beta, _ = m.beta_alpha(m.to_weekly(port), m.to_weekly(inp.benchmark.reindex(port.index)), periods=m.WEEKS)
    return {
        "value": total,
        "weight": float(w.get(target, 0.0)),
        "max_weight": float(w.max()),
        "max_name": meta["name"].get(w.idxmax(), w.idxmax()),
        "top3": float(w.nlargest(3).sum()),
        "sector": sector,
        "sector_share": float(w[meta["sector"] == sector].sum()) if sector else np.nan,
        "foreign_share": float(w[meta["currency"].fillna("EUR") != "EUR"].sum()),
        "usd_share": float(w[meta["currency"] == "USD"].sum()),
        "volatility": float(contrib["portfolio_volatility"].iloc[0]),
        "beta": beta,
        "risk_contribution": float(contrib["risk_contribution"].get(target, 0.0)),
        "effective_positions": m.effective_positions(w),
        "var95": m.historical_var(port) * total,
    }


def simulate(inp: OrderInputs, target: str, amount: float) -> tuple[dict, dict, list[tuple[str, str]]]:
    """(before, after, hints) for buying ``amount`` EUR of ``target``."""
    before = snapshot(inp.values, inp, target)
    after_values = inp.values.copy()
    after_values[target] = after_values.get(target, 0.0) + amount
    after = snapshot(after_values, inp, target)
    return before, after, hints(inp, target, amount, before, after)


def _n(x: float, decimals: int = 0) -> str:
    return f"{x:,.{decimals}f}"


def hints(inp: OrderInputs, target: str, amount: float, before: dict, after: dict) -> list[tuple[str, str]]:
    """(kind, text) with kind in {'warn', 'info', 'good'}."""
    out: list[tuple[str, str]] = []
    name = inp.meta["name"].get(target, target)
    if after["weight"] > POSITION_LIMIT:
        out.append(("warn", f"{name} would be **{_n(after['weight'] * 100, 0)}%** of the portfolio "
                            f"(limit {_n(POSITION_LIMIT * 100, 0)}%)."))
    if after["sector"] and after["sector_share"] > SECTOR_LIMIT:
        out.append(("warn", f"Sector **{after['sector']}** would reach {_n(after['sector_share'] * 100, 0)}% "
                            f"(limit {_n(SECTOR_LIMIT * 100, 0)}%)."))
    if after["weight"] > 0 and after["risk_contribution"] > 1.5 * after["weight"]:
        out.append(("warn", f"{name} would carry {_n(after['risk_contribution'] * 100, 0)}% of portfolio risk at only "
                            f"{_n(after['weight'] * 100, 0)}% weight – disproportionately volatile."))
    others = [c for c in inp.values.index if c != target and c in inp.returns]
    if target in inp.returns and others:
        w = inp.values[others] / inp.values[others].sum()
        rest = inp.returns[others].fillna(0.0) @ w
        corr = m.to_weekly(inp.returns[target]).corr(m.to_weekly(rest))
        if np.isfinite(corr):
            if corr > 0.7:
                out.append(("info", f"Correlation with the rest of the portfolio **{_n(corr, 2)}**: moves almost "
                                    "like your existing holdings – little diversification."))
            elif corr < 0.4:
                out.append(("good", f"Correlation with the rest of the portfolio only **{_n(corr, 2)}**: "
                                    "improves diversification."))
    dv = after["volatility"] - before["volatility"]
    if abs(dv) >= 0.005:
        out.append(("info" if dv > 0 else "good",
                    f"Expected portfolio volatility {'rises' if dv > 0 else 'falls'} from "
                    f"{_n(before['volatility'] * 100, 1)}% to {_n(after['volatility'] * 100, 1)}%."))
    fee_share = FEE_PER_ORDER / amount if amount > 0 else np.nan
    if fee_share > 0.005:
        out.append(("info", f"The €1 order fee is {_n(fee_share * 100, 1)}% of the order – executed as a "
                            "savings plan it would be free."))
    return out
