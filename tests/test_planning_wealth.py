"""Monte Carlo wealth planning and the emergency fund."""

import numpy as np
import pytest
from test_analytics import SAMPLE, FakeMarket

from portfolio_tracker.importer import load_transactions
from portfolio_tracker.planning import (
    PlanInputs,
    bands,
    contributions,
    emergency_fund,
    goal_probability,
    monthly_saving_rate,
    saving_for_goal,
    simulate,
)
from portfolio_tracker.portfolio import Portfolio


def test_zero_volatility_matches_compound_interest():
    inp = PlanInputs(start_value=10_000, monthly_saving=0, years=10, expected_return=0.07, volatility=0.0)
    paths = simulate(inp, n_paths=10)
    assert paths[:, -1] == pytest.approx(10_000 * 1.07 ** 10, rel=1e-9)


def test_mean_wealth_compounds_at_expected_return():
    inp = PlanInputs(start_value=10_000, monthly_saving=0, years=10, expected_return=0.07, volatility=0.18)
    paths = simulate(inp, n_paths=40_000)
    assert paths[:, -1].mean() == pytest.approx(10_000 * 1.07 ** 10, rel=0.02)
    assert np.median(paths[:, -1]) < paths[:, -1].mean()          # volatility drag on the typical path


def test_savings_and_contributions_add_up():
    inp = PlanInputs(start_value=1_000, monthly_saving=100, years=2, expected_return=0.0, volatility=0.0)
    assert simulate(inp, n_paths=3)[0, -1] == pytest.approx(1_000 + 24 * 100)
    assert contributions(inp)[-1] == pytest.approx(3_400)


def test_real_values_deflate_by_inflation():
    nominal = PlanInputs(start_value=10_000, monthly_saving=0, years=10, volatility=0.0)
    real = PlanInputs(start_value=10_000, monthly_saving=0, years=10, volatility=0.0, real=True, inflation=0.02)
    ratio = simulate(real, 5)[0, -1] / simulate(nominal, 5)[0, -1]
    assert ratio == pytest.approx(1 / 1.02 ** 10)


def test_goal_probability_and_bands_are_ordered():
    inp = PlanInputs(start_value=20_000, monthly_saving=500, years=15)
    paths = simulate(inp, 4000)
    b = bands(paths)
    assert (b[0.1] <= b[0.5]).all() and (b[0.5] <= b[0.9]).all()
    median = b[0.5].iloc[-1]
    assert goal_probability(paths, median) == pytest.approx(0.5, abs=0.02)
    assert goal_probability(paths, 0) == 1.0


def test_saving_for_goal_reaches_probability():
    inp = PlanInputs(start_value=10_000, monthly_saving=200, years=15)
    need = saving_for_goal(inp, goal=200_000, probability=0.75)
    paths = simulate(PlanInputs(**{**inp.__dict__, "monthly_saving": need}), 3000)
    assert goal_probability(paths, 200_000) == pytest.approx(0.75, abs=0.03)
    assert saving_for_goal(inp, goal=1.0) == 0.0


def test_saving_rate_and_emergency_fund_from_export():
    p = Portfolio.build(load_transactions(SAMPLE), FakeMarket())
    assert monthly_saving_rate(p) > 0                    # 1000 deposited, 100 withdrawn in the sample
    ef = emergency_fund(p)
    assert ef["monthly_spending"] > 0 and ef["months_covered"] == pytest.approx(ef["cash"] / ef["monthly_spending"])
