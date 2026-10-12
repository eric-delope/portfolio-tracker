"""Company valuation models and entry-price planning. Pure functions, no I/O.

Two independent models, both driven by the user's own forecasts:

1. Earnings model (EPS x P/E) with scenarios: forecast earnings per share N
   years ahead, apply an exit P/E, discount the resulting target price back at
   the required return. Bear/base/bull scenarios are probability-weighted.
2. Two-stage DCF on free cash flow per share: explicit growth, linear fade to
   the terminal growth rate, Gordon terminal value.

Consistency rule used throughout: buying at the fair value earns exactly the
required return p.a. (fair value = expected price in N years / (1 + r)^N).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq


@dataclass
class Scenario:
    name: str
    probability: float
    eps_growth: float   # EPS growth p.a. over the horizon
    exit_pe: float      # P/E multiple at the end of the horizon


def eps_target(eps0: float, growth: float, exit_pe: float, years: int) -> float:
    """Expected share price in ``years``: EPS grown at ``growth`` times the exit P/E."""
    return eps0 * (1 + growth) ** years * exit_pe


def present_value(future_price: float, required_return: float, years: int) -> float:
    return future_price / (1 + required_return) ** years


def implied_return(price: float, future_price: float, years: int) -> float:
    """Annual return from buying at ``price`` and selling at ``future_price`` after ``years``."""
    if price <= 0 or future_price <= 0:
        return float("nan")
    return (future_price / price) ** (1 / years) - 1


def eps_path(eps0: float, growth: float, years: int, eps1: float | None = None) -> list[float]:
    """EPS for years 1..N: either eps0 grown from today, or a given year-1 EPS grown from year 2 on."""
    if eps1 is not None:
        return [eps1 * (1 + growth) ** (t - 1) for t in range(1, years + 1)]
    return [eps0 * (1 + growth) ** t for t in range(1, years + 1)]


def scenario_valuation(eps0: float, scenarios: list[Scenario], years: int, required_return: float,
                       eps1: float | None = None, dividend0: float = 0.0) -> pd.DataFrame:
    """One row per scenario plus a probability-weighted 'Expected' row.

    ``eps1`` (optional): EPS expected in year 1, e.g. analyst consensus; scenario
    growth then applies from year 2. ``dividend0``: today's dividend per share; it
    grows in line with EPS (constant payout ratio) and its present value is part
    of the fair value. The expected dividend path is stored in ``df.attrs['dividends']``.
    """
    total_p = sum(s.probability for s in scenarios)
    if total_p <= 0:
        raise ValueError("Scenario probabilities must sum to more than zero")
    base_eps = eps0 if eps0 > 0 else (eps1 or 1.0)
    discount = [(1 + required_return) ** t for t in range(1, years + 1)]
    rows, div_paths = [], []
    for s in scenarios:
        path = eps_path(eps0, s.eps_growth, years, eps1)
        divs = [dividend0 * e / base_eps for e in path] if dividend0 else [0.0] * years
        target = path[-1] * s.exit_pe
        pv_divs = float(sum(d / k for d, k in zip(divs, discount)))
        rows.append({
            "scenario": s.name, "probability": s.probability / total_p, "eps_growth": s.eps_growth,
            "exit_pe": s.exit_pe, "eps_final": path[-1], "target_price": target,
            "dividends_total": float(sum(divs)), "pv_dividends": pv_divs,
            "fair_value": present_value(target, required_return, years) + pv_divs,
        })
        div_paths.append(np.array(divs))
    df = pd.DataFrame(rows).set_index("scenario")
    p = df["probability"].to_numpy()
    expected = {"probability": 1.0, "eps_growth": np.nan, "exit_pe": np.nan}
    for col in ["eps_final", "target_price", "dividends_total", "pv_dividends", "fair_value"]:
        expected[col] = float((df[col] * df["probability"]).sum())
    df.loc["Expected"] = expected
    df.attrs["dividends"] = [float(x) for x in np.sum([w * d for w, d in zip(p, div_paths)], axis=0)]
    return df


def future_price(fair_value: float, required_return: float, years: int, pv_dividends: float = 0.0) -> float:
    """Price in ``years`` that, together with the dividends, makes ``fair_value`` earn exactly the required return."""
    return (fair_value - pv_dividends) * (1 + required_return) ** years


def total_return_irr(price: float, dividends: list[float], terminal_price: float) -> float:
    """Annual total return of buying at ``price``, receiving ``dividends`` (years 1..N) and selling at the end."""
    if price <= 0 or terminal_price <= 0:
        return float("nan")
    years = max(len(dividends), 1)
    divs = list(dividends) + [0.0] * (years - len(dividends))
    cash = np.array(divs, dtype=float)
    cash[-1] += terminal_price

    def npv(r: float) -> float:
        return float(np.sum(cash / (1 + r) ** np.arange(1, years + 1))) - price

    try:
        return brentq(npv, -0.99, 10.0)
    except ValueError:
        return float("nan")


def dcf_value(fcf0: float, growth: float, required_return: float, terminal_growth: float,
              years: int = 5, fade_years: int = 5) -> dict:
    """Two-stage DCF per share.

    Stage 1: ``growth`` for ``years``. Stage 2: growth fades linearly to
    ``terminal_growth`` over ``fade_years``. Then a Gordon growth terminal value.
    """
    if required_return <= terminal_growth:
        raise ValueError("Required return must exceed terminal growth")
    rates = [growth] * years + list(np.linspace(growth, terminal_growth, fade_years + 2)[1:-1])
    fcf, cash_flows = fcf0, []
    for g in rates:
        fcf *= 1 + g
        cash_flows.append(fcf)
    discount = (1 + required_return) ** np.arange(1, len(cash_flows) + 1)
    pv_explicit = float(np.sum(np.array(cash_flows) / discount))
    terminal = cash_flows[-1] * (1 + terminal_growth) / (required_return - terminal_growth)
    pv_terminal = terminal / discount[-1]
    value = pv_explicit + pv_terminal
    return {
        "value": value, "pv_explicit": pv_explicit, "pv_terminal": pv_terminal,
        "terminal_share": pv_terminal / value if value else np.nan,
        "cash_flows": pd.Series(cash_flows, index=range(1, len(cash_flows) + 1)),
    }


def reverse_dcf(price: float, fcf0: float, required_return: float, terminal_growth: float,
                years: int = 5, fade_years: int = 5) -> float:
    """Stage-1 growth the market implies at ``price`` (other DCF inputs held fixed)."""
    if fcf0 <= 0 or price <= 0:
        return float("nan")

    def gap(g: float) -> float:
        return dcf_value(fcf0, g, required_return, terminal_growth, years, fade_years)["value"] - price

    try:
        return brentq(gap, -0.5, 2.0)
    except ValueError:
        return float("nan")


def blended_fair_value(eps_fair: float, dcf_fair: float | None, eps_weight: float) -> float:
    if dcf_fair is None or not np.isfinite(dcf_fair) or dcf_fair <= 0:
        return eps_fair
    return eps_weight * eps_fair + (1 - eps_weight) * dcf_fair


def entry_ladder(fair_value: float, margins: list[float], weights: list[float], budget: float,
                 required_return: float, years: int, fx_to_eur: float = 1.0,
                 dividends: list[float] | None = None, pv_dividends: float = 0.0) -> pd.DataFrame:
    """Buy tranches below fair value.

    ``margins`` are margins of safety (0.15 = buy 15 % below fair value),
    ``weights`` the share of ``budget`` (EUR) per tranche. The expected return
    of each tranche follows from the consistency rule: at fair value it equals
    ``required_return``, below it more.
    """
    if len(margins) != len(weights):
        raise ValueError("margins and weights must have the same length")
    w = np.array(weights, dtype=float)
    w = w / w.sum() if w.sum() > 0 else w
    future = future_price(fair_value, required_return, years, pv_dividends)
    divs = dividends or [0.0] * years
    rows = []
    for i, (mos, share) in enumerate(zip(margins, w), start=1):
        price = fair_value * (1 - mos)
        amount = budget * share
        rows.append({
            "tranche": f"Tranche {i}", "margin_of_safety": mos, "price": price,
            "price_eur": price / fx_to_eur if fx_to_eur else np.nan,
            "amount_eur": amount, "shares": amount / (price / fx_to_eur) if price > 0 else np.nan,
            "expected_return": total_return_irr(price, divs, future),
        })
    return pd.DataFrame(rows)


def sensitivity(eps0: float, years: int, required_return: float, growths: list[float], pes: list[float],
                eps1: float | None = None, dividend0: float = 0.0) -> pd.DataFrame:
    """Fair value grid: rows = EPS growth p.a., columns = exit P/E."""
    def fair(g: float, pe: float) -> float:
        sv = scenario_valuation(eps0, [Scenario("x", 1.0, g, pe)], years, required_return, eps1, dividend0)
        return float(sv.loc["x", "fair_value"])

    return pd.DataFrame([[fair(g, pe) for pe in pes] for g in growths], index=growths, columns=pes)


def historical_pe(prices: pd.Series, eps_by_year: pd.Series) -> pd.Series:
    """Approximate daily trailing P/E: price divided by the last reported annual EPS."""
    eps = eps_by_year.dropna().sort_index()
    eps = eps[eps > 0]
    if eps.empty or prices.empty:
        return pd.Series(dtype=float)
    eps_daily = eps.reindex(prices.index.union(eps.index)).ffill().reindex(prices.index)
    return (prices / eps_daily).dropna()


# ------------------------------------------------------------ long-term entries
def irr_times(price: float, cash_flows: list[tuple[float, float]]) -> float:
    """Annual return of paying ``price`` today for ``(years_from_now, amount)`` cash flows."""
    flows = [(t, a) for t, a in cash_flows if a]
    if price <= 0 or not flows or all(a <= 0 for _, a in flows):
        return float("nan")
    times = np.array([max(t, 1e-6) for t, _ in flows])
    amounts = np.array([a for _, a in flows])

    def npv(r: float) -> float:
        return float(np.sum(amounts / (1 + r) ** times)) - price

    try:
        return brentq(npv, -0.99, 10.0)
    except ValueError:
        return float("nan")


def fair_value_at(fair0: float, required_return: float, years_elapsed: float,
                  dividends: list[float] | None = None) -> float:
    """Fair value rolled forward: it compounds at the required return, minus dividends already paid.

    A growing business is worth more every year; entry prices fixed at the
    valuation date would otherwise drift ever further below fair value.
    """
    t = max(years_elapsed, 0.0)
    paid = sum(d * (1 + required_return) ** (t - k)
               for k, d in enumerate(dividends or [], start=1) if k <= t)
    return fair0 * (1 + required_return) ** t - paid


def remaining_flows(target: float, horizon: float, years_elapsed: float,
                    dividends: list[float] | None = None) -> list[tuple[float, float]]:
    """Dividends still to come and the target price, timed from today."""
    t = max(years_elapsed, 0.0)
    flows = [(k - t, d) for k, d in enumerate(dividends or [], start=1) if k > t]
    flows.append((max(horizon - t, 0.5), target))  # an expired horizon still counts half a year
    return flows


def price_for_return(target_flows: list[tuple[float, float]], annual_return: float) -> float:
    """Price at which buying yields exactly ``annual_return`` (used as a valuation-based sell line)."""
    return float(sum(a / (1 + annual_return) ** max(t, 1e-6) for t, a in target_flows))


def hit_probability(prices: pd.Series, drop: float, horizon_days: int = 252) -> float:
    """Share of historical start days after which the price fell by ``drop`` at some point within the horizon.

    Empirical, from the stock's own history: a realistic check whether an entry
    level far below today's price is ever likely to be reached.
    """
    if drop <= 0:
        return 1.0
    p = prices.dropna()
    if len(p) <= horizon_days + 20:
        return float("nan")
    future_min = p[::-1].rolling(horizon_days, min_periods=horizon_days).min()[::-1].shift(-1)
    valid = future_min.notna()
    return float((future_min[valid] <= p[valid] * (1 - drop)).mean())


def historical_multiple(prices: pd.Series, per_share_by_year: pd.Series) -> pd.Series:
    """Daily price ÷ last reported annual per-share figure (EPS -> P/E, FCF per share -> P/FCF)."""
    return historical_pe(prices, per_share_by_year)


def percentile_rank(history: pd.Series, value: float | None) -> float:
    """Share of history below ``value`` (0 = cheapest ever, 1 = most expensive)."""
    h = history.dropna()
    if value is None or not np.isfinite(value) or h.empty:
        return float("nan")
    return float((h < value).mean())


def valuation_zone(percentile: float) -> str:
    if not np.isfinite(percentile):
        return "–"
    return "lower third" if percentile < 1 / 3 else ("middle third" if percentile < 2 / 3 else "upper third")
