"""Reverse DCF in the style of Speedwell Research (Drew Cohen).

Instead of choosing a discount rate and computing a "fair value", start from
today's market capitalisation and ask: under a given set of business
assumptions, which annual return does a buyer at today's price earn?

- Cash flows are modelled explicitly over the life of the business (default
  40 years) with growth in buckets: years 1-5, 6-10, 11-20 and a low mature
  rate afterwards. There is no terminal value – a deliberately conservative
  choice, since a terminal value hides most of the assumptions.
- Two cash-flow bases: (a) revenue x free-cash-flow margin, or (b) the
  normalised view used by Speedwell/Damodaran: revenue x after-tax operating
  margin minus the reinvestment growth requires (revenue increase divided by
  sales-to-capital). (b) avoids treating a temporary capex boom as permanent.
  The margin moves linearly from today's level to the target margin.
- The implied return is the discount rate at which the present value of those
  cash flows equals today's market capitalisation (an internal rate of return).

Results come as a grid: revenue growth (rows) x target margin (columns). The
investor then checks whether *draconian but plausible* assumptions still avoid
a loss and whether *conservative* assumptions earn roughly the market's
historical return (~9 % p. a.).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq

MARKET_RETURN = 0.09   # long-run equity market return used as the hurdle


@dataclass
class Assumptions:
    growth_1_5: float                  # revenue growth p. a., years 1-5
    target_margin: float               # free-cash-flow margin reached after the ramp
    growth_6_10: float | None = None   # default: half of growth_1_5
    growth_11_20: float | None = None  # default: a quarter of growth_1_5, capped at 4 %
    mature_growth: float = 0.02        # years 21+
    ramp_years: int = 5                # years until the target margin is reached
    life_years: int = 40               # explicit forecast horizon, no terminal value
    sales_to_capital: float | None = None  # if set: margin is an after-tax operating margin and growth must be
                                           # funded – reinvestment = revenue increase / sales_to_capital

    def growth_path(self) -> np.ndarray:
        g2 = self.growth_6_10 if self.growth_6_10 is not None else self.growth_1_5 / 2
        g3 = self.growth_11_20 if self.growth_11_20 is not None else min(self.growth_1_5 / 4, 0.04)
        rates = []
        for year in range(1, self.life_years + 1):
            rates.append(self.growth_1_5 if year <= 5 else g2 if year <= 10 else g3 if year <= 20
                         else self.mature_growth)
        return np.array(rates)


def cash_flows(revenue0: float, margin0: float, a: Assumptions) -> pd.DataFrame:
    """Year-by-year revenue, margin and free cash flow."""
    revenue = revenue0 * np.cumprod(1 + a.growth_path())
    years = np.arange(1, a.life_years + 1)
    ramp = np.clip(years / max(a.ramp_years, 1), 0, 1)
    margin = margin0 + (a.target_margin - margin0) * ramp
    earnings = revenue * margin
    reinvestment = np.zeros_like(revenue)
    if a.sales_to_capital:
        growth_in_revenue = np.diff(np.concatenate([[revenue0], revenue]))
        reinvestment = np.maximum(growth_in_revenue, 0) / a.sales_to_capital
    return pd.DataFrame({"revenue": revenue, "margin": margin, "earnings": earnings,
                         "reinvestment": reinvestment, "fcf": earnings - reinvestment}, index=years)


def implied_return(market_cap: float, revenue0: float, margin0: float, a: Assumptions) -> float:
    """Annual return at which the modelled cash flows are worth exactly today's market cap."""
    cf = cash_flows(revenue0, margin0, a)["fcf"].to_numpy()
    t = np.arange(1, len(cf) + 1)
    if market_cap <= 0 or cf.sum() <= 0:
        return float("nan")

    def gap(r: float) -> float:
        return float(np.sum(cf / (1 + r) ** t)) - market_cap

    try:
        return brentq(gap, -0.5, 2.0)
    except ValueError:
        return float("nan")


def scenario_grid(market_cap: float, revenue0: float, margin0: float, growths: list[float], margins: list[float],
                  **kwargs) -> pd.DataFrame:
    """Implied annual return for every combination: rows = growth years 1-5, columns = target FCF margin."""
    return pd.DataFrame(
        [[implied_return(market_cap, revenue0, margin0, Assumptions(g, m, **kwargs)) for m in margins] for g in growths],
        index=growths, columns=margins,
    )


def implied_growth(market_cap: float, revenue0: float, margin0: float, target_margin: float,
                   hurdle: float = MARKET_RETURN, **kwargs) -> float:
    """Revenue growth (years 1-5) the market price requires so that a buyer earns ``hurdle`` p. a."""
    def gap(g: float) -> float:
        r = implied_return(market_cap, revenue0, margin0, Assumptions(g, target_margin, **kwargs))
        return (r if np.isfinite(r) else -1.0) - hurdle

    try:
        return brentq(gap, -0.3, 1.5)
    except ValueError:
        return float("nan")


def present_value(revenue0: float, margin0: float, a: Assumptions, rate: float) -> float:
    """Value of the modelled cash flows at a given discount rate (used for the implied revenue path chart)."""
    cf = cash_flows(revenue0, margin0, a)["fcf"].to_numpy()
    return float(np.sum(cf / (1 + rate) ** np.arange(1, len(cf) + 1)))
