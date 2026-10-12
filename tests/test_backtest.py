"""Entry backtest: waiting for pullbacks vs. a monthly savings plan."""

import numpy as np
import pandas as pd
import pytest

from portfolio_tracker.backtest import DipRule, rolling, simulate, summary, total_return_index, verdict


def series(values, start="2015-01-01") -> pd.Series:
    return pd.Series(np.asarray(values, dtype=float), index=pd.bdate_range(start, periods=len(values)))


def test_flat_price_without_interest_ends_equal():
    p = series([100.0] * 800)
    run = simulate(p, 100, DipRule(), rf=0.0, start=p.index[300])
    assert run["savings_plan"].iloc[-1] == pytest.approx(run["pullbacks"].iloc[-1])
    assert run["paid_in"].iloc[-1] == pytest.approx(run["savings_plan"].iloc[-1])


def test_rising_market_punishes_waiting():
    p = series(100 * 1.0004 ** np.arange(1500))          # ~10% a year, never a pullback
    run = simulate(p, 100, DipRule(max_wait_months=None), rf=0.0, start=p.index[300])
    assert run["buy"].sum() == 0                          # never bought
    assert run["pullbacks"].iloc[-1] == pytest.approx(run["paid_in"].iloc[-1])
    assert run["savings_plan"].iloc[-1] > run["pullbacks"].iloc[-1]
    # with a 12-month fallback the money gets invested, but late
    late = simulate(p, 100, DipRule(max_wait_months=12), rf=0.0, start=p.index[300])
    assert late["buy"].sum() > 0
    assert run["pullbacks"].iloc[-1] < late["pullbacks"].iloc[-1] < late["savings_plan"].iloc[-1]


def test_crash_and_recovery_rewards_the_ladder():
    flat, down, up = [100.0] * 400, list(np.linspace(100, 60, 120)), list(np.linspace(60, 100, 250))
    p = series(flat + down + up)
    run = simulate(p, 100, DipRule(max_wait_months=None), rf=0.0, start=p.index[260])
    assert run["pullbacks"].iloc[-1] > run["savings_plan"].iloc[-1]


def test_ladder_spends_a_third_then_half_then_rest():
    # one deposit at the start of a month, then the price steps down through -10%, -20%, -30% within that month
    idx = pd.bdate_range("2015-01-01", periods=400)
    i = next(j for j in range(260, 400) if idx[j].month != idx[j - 1].month)
    p = pd.Series([100.0] * (i + 2) + [89.0] * 3 + [79.0] * 3 + [69.0] * 3, index=idx[: i + 11])
    run = simulate(p, 300, DipRule(max_wait_months=None), rf=0.0, start=p.index[i])
    buys = run.loc[run["buy"] > 0, "buy"]
    assert list(buys.round(6)) == [100.0, 100.0, 100.0]


def test_total_return_index_adds_dividends():
    p = series([100.0] * 10)
    d = pd.Series([5.0], index=[p.index[5]])
    tr = total_return_index(p, d)
    assert tr.iloc[4] == pytest.approx(100.0)
    assert tr.iloc[-1] == pytest.approx(105.0)


def test_rolling_windows_and_verdict():
    rng = np.random.default_rng(1)
    p = series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, 2600))))
    w = rolling(p, 100, DipRule(), rf=0.02, years=5)
    assert 40 <= len(w) <= 60
    v = verdict(w)
    assert 0 <= v["win_rate"] <= 1 and v["worst"] <= v["median"] <= v["best"]
    s = summary(simulate(p, 100, DipRule(), 0.02, start=p.index[300]))
    assert set(s.index) == {"savings_plan", "pullbacks"} and np.isfinite(s.loc["savings_plan", "irr"])
