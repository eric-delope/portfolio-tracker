"""Step 7 – my price: fair value bridge, maximum price after margin of safety, sensitivity."""

from __future__ import annotations

import streamlit as st
from i18n import tr

import charts as ch
import common as c
from common import money, num, pct, plot
from portfolio_tracker import valuation as v


def render(x) -> None:
    f, cur, ticker, inputs, rec, scenarios = x.f, x.cur, x.ticker, x.inputs, x.rec, x.scenarios
    if x.eps0 <= 0 or sum(s_.probability for s_ in scenarios) <= 0:
        st.warning("Please enter a positive EPS and probabilities > 0.")
        st.stop()
    m1, m2 = st.columns(2)
    x.req = req = m1.number_input("Required return p.a. (%)", 4.0, 25.0,
                                  float(inputs.get("required_return", rec["required_return"])) * 100, 0.5,
                                  key=f"rr_{ticker}",
                                  help=f"Recommendation from step 3: {pct(rec['required_return'], 1, False)}") / 100
    x.mos = mos = m2.number_input("Margin of safety (%)", 0.0, 60.0, float(inputs.get("mos", rec["margin_of_safety"])) * 100,
                                  2.5, key=f"mos_{ticker}",
                                  help=f"Recommendation from step 3: {pct(rec['margin_of_safety'], 0, False)}") / 100

    horizon = x.horizon
    sv = v.scenario_valuation(x.eps0, scenarios, horizon, req, eps1=x.eps1, dividend0=x.div0)
    x.dividends = sv.attrs["dividends"]
    x.eps_fair = eps_fair = float(sv.loc["Expected", "fair_value"])
    x.pv_divs = float(sv.loc["Expected", "pv_dividends"])
    dcf = v.dcf_value(x.fcf0, x.dcf_g, req, x.tg) if x.fcf0 > 0 and req > x.tg else None
    x.dcf_fair = dcf["value"] if dcf else None
    x.fair = fair = v.blended_fair_value(eps_fair, x.dcf_fair, x.eps_weight)
    x.max_price = max_price = fair * (1 - mos)
    x.target = v.future_price(fair, req, horizon, x.pv_divs)
    x.exp_now = exp_now = v.total_return_irr(f.price, x.dividends, x.target)

    ex = sv.loc["Expected"]
    if f.price <= max_price:
        x.verdict_text = (f"The price is **below your maximum price** – buy zone. Expected return when buying today: "
                          f"**{pct(exp_now)} p.a.**")
    elif f.price <= fair:
        x.verdict_text = (f"The price is between maximum price and fair value: fairly valued, but without a safety "
                          f"buffer. Expected {pct(exp_now)} p.a. – at most via savings plan, wait for the limit tranches.")
    else:
        x.verdict_text = (f"The price is **above fair value** (expected only {pct(exp_now)} p.a.). Patience – set "
                          "alerts and wait.")

    def change(to: float) -> tuple[str, str]:
        d = to / f.price - 1
        return (f"{'↑' if d >= 0 else '↓'} {pct(abs(d), 1, False)}", "good" if d >= 0 else "bad")

    left, right = st.columns([3, 2], gap="medium")
    with left:
        c.valuation_card(f.price, fair, max_price, exp_now, req, mos, cur)
    with right:
        c.kv_card([
            ("Today's price", money(f.price, cur), None, None),
            (f"Price in {horizon} years", money(x.target, cur), *change(x.target)),
            ("Dividends until then", money(ex["dividends_total"], cur) if x.div0 else "–", None, None),
            ("Fair value", money(fair, cur), *change(fair)),
            ("Expected return p.a.", pct(exp_now), "above target" if exp_now >= req else "below target",
             "good" if exp_now >= req else "warn"),
        ])

    with c.card():
        head, switch = st.columns([3, 2], vertical_alignment="center")
        with head:
            c.card_title("Projections", f"what your assumptions imply over {horizon} years – not a forecast")
        view = switch.segmented_control("Projection", ["Price", "P/E", "EPS"], default="Price", required=True,
                                        key=f"proj_{ticker}", label_visibility="collapsed")
        if view == "Price":
            targets = {name: float(sv.loc[name, "target_price"]) for name in ("Bear", "Base", "Bull") if name in sv.index}
            targets["Expected"] = float(ex["target_price"])
            plot(ch.price_projection(f.prices, horizon, targets, fair, max_price, cur), boxed=False)
        elif view == "P/E":
            if len(x.hpe) > 20:
                plot(ch.multiple_history(x.hpe, "P/E", float(scenarios[1].exit_pe)), boxed=False)
            else:
                st.caption("Too few profitable years for a P/E history.")
        else:
            paths = {s_.name: v.eps_path(x.eps0, s_.eps_growth, horizon, x.eps1) for s_ in scenarios}
            weights = [s_.probability for s_ in scenarios]
            paths["Expected"] = [sum(w * pth[k] for w, pth in zip(weights, paths.values())) / sum(weights)
                                 for k in range(horizon)]
            eps_hist = x.a["eps"].dropna() if "eps" in x.a else None
            if eps_hist is not None and len(eps_hist):
                plot(ch.eps_projection(eps_hist, paths, cur), boxed=False)

    rows = [r_ for r_ in [
        ("Earnings per share today", money(x.eps0, cur)),
        ("Earnings per share in 12 months (consensus)", money(x.eps1, cur)) if x.eps1 else None,
        (f"Earnings per share in {horizon} years (probability-weighted)", money(ex["eps_final"], cur)),
        ("× exit P/E (weighted)", num(ex["target_price"] / ex["eps_final"], 1) if ex["eps_final"] else "–"),
        (f"= expected price in {horizon} years", money(ex["target_price"], cur)),
        ("+ dividends until then", money(ex["dividends_total"], cur)) if x.div0 else None,
        (f"discounted at {pct(req, 1, False)} p.a. → fair value (earnings model)", money(eps_fair, cur)),
        (f"blended with DCF ({pct(1 - x.eps_weight, 0, False)} weight, DCF = {money(x.dcf_fair, cur)})", money(fair, cur))
        if x.eps_weight < 1 and x.dcf_fair else None,
        (f"− margin of safety {pct(mos, 0, False)} = your maximum price", money(max_price, cur)),
    ] if r_]
    x.bridge_rows = rows
    c1, c2 = st.columns([2, 3], gap="medium")
    with c1, c.card():
        c.card_title("How your price is built", "expected value across all scenarios")
        c.calc_table(rows, total_from=len(rows) - 1)
    with c2:
        total_p = sum(s_.probability for s_ in scenarios)
        shares = " · ".join(f"{tr(s_.name)} {pct(s_.probability / total_p, 0, False)}" for s_ in scenarios)
        plot(ch.titled(ch.scenario_bars(sv, f.price, cur), "Fair value per scenario",
                       f"probability: {shares}"))
    base = scenarios[1]
    growths = [round(base.eps_growth + d, 3) for d in (-0.06, -0.03, 0, 0.03, 0.06)]
    pes = [round(base.exit_pe * k_, 1) for k_ in (0.7, 0.85, 1.0, 1.15, 1.3)]
    plot(ch.titled(ch.sensitivity_heatmap(v.sensitivity(x.eps0, horizon, req, growths, pes, x.eps1, x.div0), f.price, cur),
                   "How sensitive is the fair value?",
                   "base scenario at different growth (rows) and exit P/E (columns); color = distance to today's price"))
