"""Wealth planning: Monte Carlo projection of the portfolio, goal probabilities and the emergency fund.

The projection is a monthly simulation of many possible futures. Each month the portfolio earns a random
return drawn from a log-normal distribution with the chosen expected return and volatility, then the
monthly savings are added. Percentiles across all paths give the range "bad case / typical / good case";
the share of paths above a goal is the probability of reaching it.

Deliberately simple and transparent: constant expected return and volatility, independent months, no
taxes or fees inside the simulation. Real markets have fatter tails and regimes – the bands are a
planning aid, not a promise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .portfolio import Portfolio

LONG_RUN_EQUITY_RETURN = 0.07   # nominal p.a., a common long-run assumption for global equities
DEFAULT_INFLATION = 0.02


@dataclass
class PlanInputs:
    start_value: float               # invested today
    monthly_saving: float            # added at the end of every month
    years: int
    expected_return: float = LONG_RUN_EQUITY_RETURN   # arithmetic mean p.a.
    volatility: float = 0.15         # p.a.
    saving_growth: float = 0.0       # yearly increase of the monthly saving (e.g. salary growth)
    inflation: float = DEFAULT_INFLATION
    real: bool = False               # express results in today's money


def simulate(inp: PlanInputs, n_paths: int = 5000, seed: int = 7) -> np.ndarray:
    """Wealth paths, shape (n_paths, months + 1), column 0 = today."""
    months = inp.years * 12
    rng = np.random.default_rng(seed)
    # log-normal monthly growth whose mean compounds to 1 + expected_return per year; the typical (median)
    # path grows slower – the "volatility drag" of sigma²/2 per year
    sigma_m = inp.volatility / np.sqrt(12)
    mu_m = np.log(1 + inp.expected_return) / 12 - sigma_m ** 2 / 2
    growth = np.exp(rng.normal(mu_m, sigma_m, size=(n_paths, months)))
    saving = inp.monthly_saving * (1 + inp.saving_growth) ** (np.arange(months) // 12)
    wealth = np.empty((n_paths, months + 1))
    wealth[:, 0] = inp.start_value
    for t in range(months):
        wealth[:, t + 1] = wealth[:, t] * growth[:, t] + saving[t]
    if inp.real:
        wealth = wealth / (1 + inp.inflation) ** (np.arange(months + 1) / 12)
    return wealth


def contributions(inp: PlanInputs) -> np.ndarray:
    """Cumulative money paid in (start value + savings), per month – the line the market has to beat."""
    months = inp.years * 12
    saving = inp.monthly_saving * (1 + inp.saving_growth) ** (np.arange(months) // 12)
    paid = np.concatenate([[inp.start_value], inp.start_value + np.cumsum(saving)])
    if inp.real:
        paid = paid / (1 + inp.inflation) ** (np.arange(months + 1) / 12)
    return paid


def bands(paths: np.ndarray, quantiles=(0.1, 0.25, 0.5, 0.75, 0.9)) -> pd.DataFrame:
    """Percentiles of wealth per month (columns = quantiles)."""
    return pd.DataFrame(np.quantile(paths, quantiles, axis=0).T, columns=list(quantiles))


def goal_probability(paths: np.ndarray, goal: float) -> float:
    """Share of paths at or above ``goal`` at the end of the horizon."""
    return float((paths[:, -1] >= goal).mean())


def saving_for_goal(inp: PlanInputs, goal: float, probability: float = 0.75, n_paths: int = 3000) -> float:
    """Monthly saving needed to reach ``goal`` with the given probability (same random draws for every try)."""
    def gap(saving: float) -> float:
        trial = PlanInputs(**{**inp.__dict__, "monthly_saving": saving})
        return float(np.quantile(simulate(trial, n_paths)[:, -1], 1 - probability)) - goal
    if gap(0.0) >= 0:
        return 0.0
    hi = max(inp.monthly_saving, 100.0)
    while gap(hi) < 0 and hi < 1e7:
        hi *= 2
    return float(brentq(gap, 0.0, hi, xtol=1.0))


def historical_assumptions(p: Portfolio) -> dict:
    """What the portfolio itself suggests: realised return and ex-ante volatility of today's holdings."""
    r = p.daily["return"]
    years = max((p.last_date - p.index[0]).days / 365.25, 1 / 12)
    realised = float((1 + r).prod() ** (1 / years) - 1)
    risk = p.ex_ante_risk() or {}
    return {"realised_return": realised, "volatility": float(risk.get("volatility", np.nan)), "years": years}


def monthly_saving_rate(p: Portfolio, months: int = 12) -> float:
    """Average net money paid into the account per month over the last ``months`` (deposits − withdrawals)."""
    tx = p.tx[p.tx["date"] > p.last_date - pd.DateOffset(months=months)]
    net = tx.loc[tx["event"].isin(["deposit", "withdrawal"]), "amount"].sum()
    span = min(months, max((p.last_date - p.tx["date"].min()).days / 30.44, 1))
    return float(net / span)


def emergency_fund(p: Portfolio, months: int = 6) -> dict:
    """Cash on the account measured in months of card spending (a proxy for living costs)."""
    tx = p.tx[(p.tx["date"] > p.last_date - pd.DateOffset(months=months)) & (p.tx["event"] == "card")]
    span = min(months, max((p.last_date - p.tx["date"].min()).days / 30.44, 1))
    spending = float(-tx["net_cash"].sum() / span) if len(tx) else 0.0
    cash = float(p.cash_balance.iloc[-1])
    covered = cash / spending if spending > 0 else np.inf
    status = "no card data" if spending <= 0 else ("solid" if covered >= 6 else ("ok" if covered >= 3 else "thin"))
    return {"cash": cash, "monthly_spending": spending, "months_covered": covered, "status": status}
