"""Backtest of the entry discipline: waiting for pullbacks vs. a plain monthly savings plan.

Both strategies receive the same money on the first trading day of every month. The **savings plan** invests it
at once. The **pullback strategy** parks it in cash (earning the risk-free rate) and invests in tranches when the
price falls a set distance below its 52-week high – the first level spends a share of the cash pot, the deepest
level spends the rest. Optionally, cash that has waited too long is invested anyway.

The question is the one every long-term investor with limit orders should ask: does the cheaper entry make up for
the months the money sat on the side? Run over every rolling window of the price history, so the answer does not
hinge on one lucky start date. Prices include reinvested dividends (total return).

Limits: the history is the stock as it is known today (survivorship), no taxes or fees, and pullbacks are
measured against the 52-week high – a fair-value rule cannot be backtested without the valuations of the time.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .metrics import xirr

TRADING_DAYS = 252


@dataclass(frozen=True)
class DipRule:
    drops: tuple[float, ...] = (0.10, 0.20, 0.30)   # distance below the 52-week high per tranche
    max_wait_months: int | None = 12                # invest cash that waited this long anyway (None = never)


DEFAULT_RULE = DipRule()


def total_return_index(prices: pd.Series, dividends: pd.Series | None = None) -> pd.Series:
    """Price series with dividends reinvested on their ex-date (same units as the price at the start)."""
    p = prices.dropna().sort_index()
    p = p[p > 0]
    if dividends is None or dividends.empty or p.empty:
        return p
    d = dividends[(dividends.index > p.index[0]) & (dividends.index <= p.index[-1])]
    # an ex-date on a holiday counts on the next trading day
    pos = p.index.searchsorted(d.index)
    paid = pd.Series(0.0, index=p.index)
    for i, amount in zip(pos, d.to_numpy()):
        if i < len(p):
            paid.iloc[i] += float(amount)
    growth = (p + paid) / p.shift(1)
    return (growth.fillna(1.0).cumprod() * p.iloc[0]).rename(prices.name)


def _first_days_of_month(index: pd.DatetimeIndex) -> np.ndarray:
    months = index.year * 12 + index.month
    first = np.ones(len(index), dtype=bool)
    first[1:] = months[1:] != months[:-1]
    return first


def simulate(prices: pd.Series, monthly: float, rule: DipRule = DEFAULT_RULE, rf: float = 0.02,
             start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Daily wealth of both strategies between ``start`` and ``end``.

    ``prices`` should reach back at least a year before ``start``: the 52-week high needs history.
    Returns columns ``savings_plan``, ``pullbacks``, ``paid_in``, ``cash`` (of the pullback strategy) and
    ``buy`` (amount the pullback strategy invested that day).
    """
    p = prices.dropna()
    high = p.rolling(TRADING_DAYS, min_periods=1).max()
    window = p.loc[start:end] if start is not None or end is not None else p
    hi = high.loc[window.index].to_numpy()
    px = window.to_numpy(dtype=float)
    first = _first_days_of_month(window.index)
    month_no = np.cumsum(first)
    deposit = np.where(first, monthly, 0.0)

    plan_value = np.cumsum(deposit / px) * px

    drops = sorted(rule.drops)
    k = len(drops)
    daily_rf = (1 + rf) ** (1 / TRADING_DAYS) - 1
    shares = cash = 0.0
    used, waiting_since = 0, None
    value, cash_path, bought = np.empty(len(px)), np.empty(len(px)), np.zeros(len(px))
    for i in range(len(px)):
        cash *= 1 + daily_rf
        if first[i]:
            cash += monthly
            if waiting_since is None:
                waiting_since = month_no[i]
        dd = px[i] / hi[i] - 1
        level = sum(dd <= -d for d in drops)
        if k and dd > -drops[0] / 2:    # recovered: the next pullback starts a new ladder
            used = 0
        spend = 0.0
        if level > used:
            keep = 1.0
            for tier in range(used + 1, level + 1):   # tier t of k spends 1/(k-t+1) of what is left
                keep *= 1 - 1 / (k - tier + 1)
            spend, used = cash * (1 - keep), level
        if k and level == k:              # in the deepest zone, new money goes straight in
            spend = cash
        if rule.max_wait_months is not None and waiting_since is not None \
                and month_no[i] - waiting_since >= rule.max_wait_months:
            spend = cash
        if spend > 0:
            shares += spend / px[i]
            cash -= spend
            bought[i] = spend
        if cash < 1e-9:
            cash, waiting_since = 0.0, None
        value[i] = shares * px[i] + cash
        cash_path[i] = cash
    return pd.DataFrame({"savings_plan": plan_value, "pullbacks": value, "paid_in": np.cumsum(deposit),
                         "cash": cash_path, "buy": bought, "deposit": deposit}, index=window.index)


def summary(run: pd.DataFrame) -> pd.DataFrame:
    """Final value, money-weighted return, idle cash and number of buys per strategy."""
    dates = run.index[run["deposit"] > 0]
    out = {}
    for col in ("savings_plan", "pullbacks"):
        final = float(run[col].iloc[-1])
        flows = list(-run.loc[dates, "deposit"]) + [final]
        out[col] = {
            "final": final,
            "irr": xirr(list(dates) + [run.index[-1]], flows),
            "idle_cash": float((run["cash"] / run[col].where(run[col] > 0)).mean()) if col == "pullbacks" else 0.0,
            "buys": int((run["buy"] > 0).sum()) if col == "pullbacks" else len(dates),
        }
    return pd.DataFrame(out).T


def rolling(prices: pd.Series, monthly: float, rule: DipRule = DEFAULT_RULE, rf: float = 0.02,
            years: int = 5) -> pd.DataFrame:
    """One row per start month: final wealth of both strategies over ``years`` and the difference."""
    p = prices.dropna()
    if p.empty:
        return pd.DataFrame(columns=["start", "end", "savings_plan", "pullbacks", "difference", "idle_cash"])
    first_start = p.index[0] + pd.DateOffset(years=1)          # a year of history for the 52-week high
    last_start = p.index[-1] - pd.DateOffset(years=years)
    rows = []
    for start in pd.date_range(first_start, last_start, freq="MS"):
        run = simulate(p, monthly, rule, rf, start, start + pd.DateOffset(years=years) - pd.Timedelta(days=1))
        if len(run) < TRADING_DAYS:
            continue
        plan, dip = float(run["savings_plan"].iloc[-1]), float(run["pullbacks"].iloc[-1])
        rows.append({"start": run.index[0], "end": run.index[-1], "savings_plan": plan, "pullbacks": dip,
                     "difference": dip / plan - 1,
                     "idle_cash": float((run["cash"] / run["pullbacks"].where(run["pullbacks"] > 0)).mean())})
    return pd.DataFrame(rows)


def verdict(windows: pd.DataFrame) -> dict:
    """Share of windows in which waiting won, and the typical, best and worst difference."""
    if windows.empty:
        return {"windows": 0, "win_rate": np.nan, "median": np.nan, "best": np.nan, "worst": np.nan,
                "idle_cash": np.nan}
    d = windows["difference"]
    return {"windows": len(d), "win_rate": float((d > 0).mean()), "median": float(d.median()),
            "best": float(d.max()), "worst": float(d.min()), "idle_cash": float(windows["idle_cash"].mean())}
