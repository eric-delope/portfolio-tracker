"""Return and risk metrics on daily return series. Pure functions, no I/O.

Conventions: returns are simple daily returns (0.01 = +1 %), 252 trading days
per year, the risk-free rate is an annual rate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq

TRADING_DAYS = 252
WEEKS = 52


def to_weekly(returns: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Compound daily returns to Friday-to-Friday weekly returns.

    Used for beta and correlation: US stocks close hours after the Xetra-listed
    benchmark, so same-day daily returns are not synchronous and bias beta down.
    """
    return (1 + returns.fillna(0)).resample("W-FRI").prod() - 1


def xirr(dates: pd.Series | list, amounts: pd.Series | list) -> float:
    """Annualized money-weighted return (internal rate of return on irregular dates).

    ``amounts`` from the investor's view: money paid in is negative, money
    received (and the final value) positive.
    """
    dates = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    amounts = pd.Series(amounts, dtype=float).reset_index(drop=True)
    if not ((amounts < 0).any() and (amounts > 0).any()):
        return float("nan")
    years = (dates - dates.min()).dt.days.to_numpy() / 365.0
    cf = amounts.to_numpy()

    def npv(rate: float) -> float:
        return float(np.sum(cf / (1.0 + rate) ** years))

    try:
        return brentq(npv, -0.9999, 100.0, maxiter=500)
    except ValueError:  # no sign change in the search interval
        return float("nan")


def cumulative(returns: pd.Series) -> pd.Series:
    """Growth index starting at 1.0."""
    return (1 + returns.fillna(0)).cumprod()


def total_return(returns: pd.Series) -> float:
    return float(cumulative(returns).iloc[-1] - 1) if len(returns) else float("nan")


def annualized_return(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    n = returns.count()
    if n == 0:
        return float("nan")
    return float((1 + total_return(returns)) ** (periods / n) - 1)


def annualized_volatility(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    return float(returns.std(ddof=1) * np.sqrt(periods))


def downside_deviation(returns: pd.Series, mar: float = 0.0) -> float:
    """Annualized downside deviation below the minimum acceptable (annual) return."""
    daily_mar = (1 + mar) ** (1 / TRADING_DAYS) - 1
    shortfall = np.minimum(returns - daily_mar, 0)
    return float(np.sqrt((shortfall**2).mean()) * np.sqrt(TRADING_DAYS))


def sharpe_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    vol = annualized_volatility(returns)
    return (annualized_return(returns) - rf) / vol if vol > 0 else float("nan")


def sortino_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    dd = downside_deviation(returns, rf)
    return (annualized_return(returns) - rf) / dd if dd > 0 else float("nan")


def drawdown(returns: pd.Series) -> pd.Series:
    """Distance from the running peak of the growth index (0 = at a new high)."""
    index = cumulative(returns)
    return index / index.cummax() - 1


def max_drawdown_info(returns: pd.Series) -> dict:
    """Depth, peak, trough and recovery date of the deepest drawdown."""
    dd = drawdown(returns)
    if dd.empty or dd.min() == 0:
        return {"depth": 0.0, "peak": None, "trough": None, "recovery": None, "days_underwater": 0}
    trough = dd.idxmin()
    peak = dd.loc[:trough][dd.loc[:trough] == 0].index.max()
    after = dd.loc[trough:]
    recovered = after[after == 0]
    recovery = recovered.index.min() if not recovered.empty else None
    end = recovery if recovery is not None else dd.index.max()
    return {
        "depth": float(dd.min()),
        "peak": peak,
        "trough": trough,
        "recovery": recovery,
        "days_underwater": int((end - peak).days) if peak is not None else 0,
    }


def calmar_ratio(returns: pd.Series) -> float:
    mdd = max_drawdown_info(returns)["depth"]
    return annualized_return(returns) / abs(mdd) if mdd < 0 else float("nan")


def beta_alpha(returns: pd.Series, benchmark: pd.Series, rf: float = 0.0,
               periods: int = TRADING_DAYS) -> tuple[float, float]:
    """CAPM beta and annualized Jensen's alpha versus a benchmark."""
    df = pd.concat([returns, benchmark], axis=1, keys=["p", "b"]).dropna()
    if len(df) < 12 or df["b"].var() == 0:
        return float("nan"), float("nan")
    beta = df["p"].cov(df["b"]) / df["b"].var()
    alpha = (annualized_return(df["p"], periods) - rf) - beta * (annualized_return(df["b"], periods) - rf)
    return float(beta), float(alpha)


def tracking_error(returns: pd.Series, benchmark: pd.Series, periods: int = TRADING_DAYS) -> float:
    active = (returns - benchmark).dropna()
    return annualized_volatility(active, periods)


def information_ratio(returns: pd.Series, benchmark: pd.Series, periods: int = TRADING_DAYS) -> float:
    df = pd.concat([returns, benchmark], axis=1, keys=["p", "b"]).dropna()
    te = tracking_error(df["p"], df["b"], periods)
    excess = annualized_return(df["p"], periods) - annualized_return(df["b"], periods)
    return excess / te if te > 0 else float("nan")


def capture_ratios(returns: pd.Series, benchmark: pd.Series) -> tuple[float, float]:
    """Up- and down-capture: share of the benchmark's up/down days' move the portfolio captured."""
    df = pd.concat([returns, benchmark], axis=1, keys=["p", "b"]).dropna()
    up, down = df[df["b"] > 0], df[df["b"] < 0]
    up_cap = up["p"].mean() / up["b"].mean() if len(up) else float("nan")
    down_cap = down["p"].mean() / down["b"].mean() if len(down) else float("nan")
    return float(up_cap), float(down_cap)


def historical_var(returns: pd.Series, level: float = 0.95) -> float:
    """Daily Value at Risk as a positive loss fraction (historical simulation)."""
    r = returns.dropna()
    return float(-np.quantile(r, 1 - level)) if len(r) else float("nan")


def expected_shortfall(returns: pd.Series, level: float = 0.95) -> float:
    """Average loss on the days beyond the VaR threshold (CVaR), positive fraction."""
    r = returns.dropna()
    if r.empty:
        return float("nan")
    threshold = np.quantile(r, 1 - level)
    return float(-r[r <= threshold].mean())


def monthly_returns(returns: pd.Series) -> pd.Series:
    """Compounded calendar-month returns."""
    return (1 + returns.fillna(0)).resample("ME").prod() - 1


def risk_contributions(weights: pd.Series, daily_returns: pd.DataFrame) -> pd.DataFrame:
    """Ex-ante volatility decomposition of the current portfolio.

    Returns per asset: weight, stand-alone vol, marginal contribution and the
    percentage contribution to total portfolio variance (sums to 100 %).
    """
    assets = [a for a in weights.index if a in daily_returns.columns]
    w = weights[assets] / weights[assets].sum()
    cov = daily_returns[assets].dropna(how="all").fillna(0).cov() * TRADING_DAYS
    port_var = float(w @ cov @ w)
    marginal = cov @ w
    contrib = w * marginal / port_var if port_var > 0 else w * np.nan
    return pd.DataFrame({
        "weight": w,
        "volatility": np.sqrt(np.diag(cov)),
        "risk_contribution": contrib,
    }, index=assets).assign(portfolio_volatility=np.sqrt(port_var))


def effective_positions(weights: pd.Series) -> float:
    """Inverse Herfindahl index: how many equally weighted positions the portfolio behaves like."""
    w = weights / weights.sum()
    return float(1 / (w**2).sum()) if len(w) else float("nan")
