"""Planning: where today's portfolio and saving plan can lead – a range of outcomes, not a promise."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import eur, num, pct, plot
from portfolio_tracker import fmt
from portfolio_tracker.planning import (
    LONG_RUN_EQUITY_RETURN,
    PlanInputs,
    bands,
    contributions,
    emergency_fund,
    historical_assumptions,
    monthly_saving_rate,
    saving_for_goal,
    simulate,
)

PRIVACY = c.privacy()
_, _, p = c.load()


@st.cache_data(show_spinner="Simulating 5,000 possible futures …")
def run(inp_dict: dict) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    inp = PlanInputs(**inp_dict)
    paths = simulate(inp)
    return bands(paths), paths[:, -1], contributions(inp)


@st.cache_data(show_spinner=False)
def needed(inp_dict: dict, goal: float, probability: float) -> float:
    return saving_for_goal(PlanInputs(**inp_dict), goal, probability)


def nice(x: float) -> float:
    """Round to a friendly goal: 1, 2 or 5 × a power of ten."""
    if x <= 0:
        return 0.0
    mag = 10 ** np.floor(np.log10(x))
    return float(min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= x), default=x))


c.page_header("Planning", "Where your portfolio and saving plan can lead – thousands of possible futures, "
                          "summarised as a range.")

hist = historical_assumptions(p)
rate = max(monthly_saving_rate(p), 0.0)
value_now = float(p.daily["value"].iloc[-1])
cash_now = float(p.cash_balance.iloc[-1])

# ----------------------------------------------------------------- inputs
with c.card():
    c.card_title("Your plan", "pre-filled from your account – adjust freely")
    i1, i2, i3, i4 = st.columns(4)
    include_cash = i1.toggle("Include cash", value=False, key="plan_cash",
                             help=f"Count the {eur(cash_now)} on the cash account as invested from today.")
    start = value_now + (cash_now if include_cash else 0.0)
    saving = i2.number_input(f"Monthly saving ({c.symbol()})", 0.0, 1e6, float(round(rate / 25) * 25), 25.0,
                             key="plan_saving", help=f"Your average net deposits over the last 12 months: {eur(rate)}.")
    years = i3.slider("Years", 1, 40, 20, key="plan_years")
    goal = i4.number_input(f"Goal ({c.symbol()})", 0.0, 1e9, nice((start + saving * 12 * years) * 1.6), 5000.0,
                           key="plan_goal")
    with st.expander("Assumptions"):
        a1, a2, a3, a4 = st.columns(4)
        exp_ret = a1.number_input("Expected return p.a. (%)", -5.0, 20.0, LONG_RUN_EQUITY_RETURN * 100, 0.5,
                                  key="plan_ret", help=f"Long-run equity assumption. Your portfolio so far: "
                                                       f"{pct(hist['realised_return'])} p.a. over "
                                                       f"{fmt.spec(hist['years'], '.1f')} years – too short to extrapolate.") / 100
        default_vol = hist["volatility"] if np.isfinite(hist["volatility"]) else 0.15
        vol = a2.number_input("Volatility p.a. (%)", 0.0, 60.0, round(float(np.clip(default_vol, 0.08, 0.35)) * 100, 1),
                              0.5, key="plan_vol", help="Default: the expected volatility of your current holdings.") / 100
        grow = a3.number_input("Saving increase p.a. (%)", 0.0, 15.0, 0.0, 0.5, key="plan_grow",
                               help="E.g. 2–3% if your saving grows with your salary.") / 100
        real = a4.toggle("In today's money", value=True, key="plan_real",
                         help="Deflate by 2% inflation per year, so amounts are comparable with today's prices.")

inp = PlanInputs(start_value=start, monthly_saving=saving, years=years, expected_return=exp_ret, volatility=vol,
                 saving_growth=grow, real=real)
b, final, paid = run(inp.__dict__)
prob = float((final >= goal).mean()) if goal else np.nan
end = b.iloc[-1]

c.stats([
    c.stat("Typical outcome", eur(end[0.5]), f"in {years} years · today's money" if real else f"in {years} years"),
    c.stat("Bad case", eur(end[0.1]), "1 in 10 ends lower"),
    c.stat("Good case", eur(end[0.9]), "1 in 10 ends higher"),
    c.stat("Chance of reaching goal", pct(prob, 0, False) if goal else "–", f"goal {eur(goal)}" if goal else None,
           "pos" if prob >= 0.75 else ("neg" if prob < 0.5 else None)),
    c.stat("Paid in", eur(paid[-1]), f"growth {eur(end[0.5] - paid[-1], sign=True)} (typical)"),
])

dates = pd.date_range(p.last_date, periods=years * 12 + 1, freq="MS")
plot(ch.titled(ch.wealth_fan(dates, b, paid, goal or None, PRIVACY), "Your wealth over time",
               "dark band: the middle half of outcomes · light band: 8 in 10 outcomes · dashed: money paid in",
               (f"{num(5000, 0)} simulated paths · {pct(exp_ret, 1, False)} expected return · "
                f"{pct(vol, 0, False)} volatility · after 2% inflation") if real else
               f"{num(5000, 0)} simulated paths · {pct(exp_ret, 1, False)} expected return · {pct(vol, 0, False)} volatility"))

# ----------------------------------------------------------------- what moves the needle
left, right = st.columns([3, 2], gap="medium")
with left:
    st.subheader("What moves the needle")
    if goal and prob < 0.75:
        need = needed(inp.__dict__, goal, 0.75)
        c.callout(f"For a **75% chance** of reaching {eur(goal)} you would need to save **{eur(need)} per month** "
                  f"({eur(need - saving, sign=True)} vs. today).", "info")
    elif goal:
        c.callout(f"You are on track: a **{pct(prob, 0, False)}** chance of reaching {eur(goal)}.", "good")
    variants = [("Your plan", inp),
                (f"+{c.symbol()}100 per month", PlanInputs(**{**inp.__dict__, "monthly_saving": saving + 100})),
                ("5 years longer", PlanInputs(**{**inp.__dict__, "years": years + 5})),
                ("1 point lower return", PlanInputs(**{**inp.__dict__, "expected_return": exp_ret - 0.01})),
                ("Saving +3% a year", PlanInputs(**{**inp.__dict__, "saving_growth": grow + 0.03}))]
    rows = []
    for label, v in variants:
        vb, vfinal, _ = run(v.__dict__)
        rows.append({"Change": label, "Typical outcome": vb.iloc[-1][0.5], "Bad case": vb.iloc[-1][0.1],
                     "Chance to reach goal": float((vfinal >= goal).mean()) if goal else np.nan})
    c.table(pd.DataFrame(rows), {"Typical outcome": "eur0", "Bad case": "eur0", "Chance to reach goal": "pct:0"},
            compact=True)
with right:
    st.subheader("Emergency fund")
    ef = emergency_fund(p)
    kind = {"solid": "good", "ok": "info", "thin": "warn"}.get(ef["status"], "neutral")
    months_txt = f"{fmt.spec(ef['months_covered'], '.1f')} months" if np.isfinite(ef["months_covered"]) else "–"
    c.kv_card([
        ("Cash on the account", eur(ef["cash"]), None, None),
        ("Card spending per month", eur(ef["monthly_spending"]), None, None),
        ("Covered", months_txt, ef["status"], kind),
    ])
    st.caption("Rule of thumb: 3–6 months of living costs as cash before investing more. Card spending is a proxy – "
               "rent paid from another account is not included.")

with st.expander("How the simulation works"):
    st.markdown(
        "- **5,000 paths, month by month.** Each month the portfolio earns a random return from a log-normal "
        "distribution with your expected return and volatility; then the monthly saving is added.\n"
        "- **Bands** are percentiles across all paths: the dark band holds the middle half of outcomes, the light "
        "band 8 in 10. The typical outcome is the median – lower than the average, because losses weigh more when "
        "compounding (volatility drag).\n"
        "- **Chance to reach your goal** is the share of paths that end above it.\n"
        "- **Not modelled:** taxes and fees, changing risk over time, fat tails and crisis clusters. Real markets have "
        "had worse decades than a log-normal model suggests – treat the bad case as optimistic, not as a floor.\n"
        "- Full write-up in `docs/METHODOLOGY.md`."
    )
