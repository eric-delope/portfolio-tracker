"""Entry ranking: where does the next euro earn the most, at acceptable quality and valuation?

Every valued company (watchlist and holdings) is ranked by the expected total
return p. a. from today's price, based on the user's own valuation rolled
forward to today. Quality, valuation relative to the company's own history and
current position weight qualify the verdict.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .watchlist import Watchlist, signal

POSITION_LIMIT = 0.20


def rank(wl: Watchlist, prices: dict[str, float], context: dict[str, dict] | None = None,
         weights: dict[str, float] | None = None, rf: float = 0.02) -> pd.DataFrame:
    """One row per valued company, best expected return first.

    ``context`` per ticker (all optional): quality_label, quality_passed, quality_total,
    pe_percentile, thesis ('intact' | 'broken' | ...).
    """
    context, weights = context or {}, weights or {}
    rows = []
    for e in wl:
        price = prices.get(e.ticker)
        if not e.fair_value or price is None:
            continue
        ctx = context.get(e.ticker, {})
        fair = e.fair_value_today()
        exp = e.expected_return(price)
        req = e.required_return or 0.10
        weight = weights.get(e.ticker)
        thesis = ctx.get("thesis")
        code, why = signal(e, price, weight, thesis_ok=None if thesis is None or thesis == "no KPIs"
                           else thesis == "intact")
        buys = [a for a in e.alerts if a.active and a.direction == "below"]
        in_zone = any(price <= a.price for a in buys) if buys else (fair and price <= fair * 0.9)
        verdict = _verdict(exp, req, rf, ctx.get("quality_label"), weight, thesis, bool(in_zone),
                           ctx.get("pe_percentile", np.nan))
        rows.append({
            "ticker": e.ticker, "name": e.name, "currency": e.currency, "price": price, "fair_value": fair,
            "margin_of_safety": 1 - price / fair if fair else np.nan, "expected_return": exp,
            "required_return": req, "excess_return": exp - req if np.isfinite(exp) else np.nan,
            "quality": ctx.get("quality_label"), "pe_percentile": ctx.get("pe_percentile", np.nan),
            "thesis": thesis, "weight": weight or 0.0, "signal": code, "verdict": verdict, "why": why,
            "valuation_age": e.valuation_age_days(),
        })
    if not rows:
        return pd.DataFrame()
    order = {"Buy": 0, "Buy (small)": 1, "Savings plan": 2, "Watch": 3, "Avoid": 4}
    df = pd.DataFrame(rows)
    df["_o"] = df["verdict"].map(order).fillna(9)
    return df.sort_values(["_o", "expected_return"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)


def _verdict(exp: float, req: float, rf: float, quality: str | None, weight: float | None, thesis: str | None,
             in_zone: bool = True, pe_percentile: float = np.nan) -> str:
    """Buy: return >= target and a buy tranche reached. Savings plan: attractive, but no tranche reached yet or
    the stock trades in the expensive third of its own valuation history – only the savings-plan part runs."""
    if not np.isfinite(exp):
        return "Watch"
    if thesis == "broken":
        return "Avoid"
    if exp < rf:
        return "Avoid"
    if exp < req:
        return "Watch"
    expensive_vs_history = np.isfinite(pe_percentile) and pe_percentile >= 2 / 3
    if not in_zone or expensive_vs_history:
        return "Savings plan"
    if quality == "low" or (weight or 0) >= POSITION_LIMIT:
        return "Buy (small)"
    return "Buy"
