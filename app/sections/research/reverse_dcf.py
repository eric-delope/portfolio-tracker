"""Step 5 – reverse DCF (Speedwell Research / Drew Cohen): what is priced in, and what return do you get?"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from i18n import tr

import charts as ch
import common as c
from common import num, pct, plot
from portfolio_tracker import reverse_dcf as rd

BASES = {"normalized": "Normalized (after-tax operating margin − reinvestment)", "fcf": "Free cash flow today"}


def render(x) -> None:
    f, a, cur, ticker = x.f, x.a, x.cur, x.ticker
    saved = x.inputs.get("rdcf", {})
    x.rdcf_result = {}
    c.lead("**What does today's price assume – and what would you earn?** Instead of guessing a fair value, the reverse "
           "DCF (after Drew Cohen, Speedwell Research) takes the market cap as given and shows the annual return for "
           "every mix of growth and margin.")
    ttm = f.ttm
    rev0, fcf_ttm, sbc_ttm = ttm.get("revenue"), ttm.get("fcf"), ttm.get("sbc") or 0.0
    if not rev0 or not f.market_cap or fcf_ttm is None:
        st.info("Revenue, free cash flow or market cap are missing for the reverse DCF.")
        return
    with st.expander("Model assumptions"):
        basis = st.segmented_control("Cash flow basis", list(BASES), format_func=BASES.get,
                                     default=saved.get("basis", "normalized"), required=True, key=f"rd_basis_{ticker}",
                                     help="Normalized: how much cash would remain once today's extraordinary investments "
                                          "run out – but growth has to be funded (reinvestment). Useful during capex booms "
                                          "(e.g. data centres). Free cash flow today: the simple variant without "
                                          "normalization.")
        normalized = basis == "normalized"
        i1, i2, i3, i4 = st.columns(4)
        hurdle = i1.number_input("Hurdle rate (% p.a.)", 4.0, 20.0, float(saved.get("hurdle", 0.09)) * 100, 0.5,
                                 key=f"rd_h_{ticker}", help="Long-run market return ≈ 9% p.a.") / 100
        life = i2.select_slider("Model life (years)", [20, 30, 40, 50], value=int(saved.get("life", 40)),
                                key=f"rd_life_{ticker}", help="Explicit cash flows without a terminal value – conservative.")
        mature = i3.number_input("Growth from year 21 (%)", 0.0, 4.0, float(saved.get("mature", 0.02)) * 100, 0.5,
                                 key=f"rd_mat_{ticker}") / 100
        sbc_on, s2c, tax = bool(saved.get("sbc", True)), None, None
        if normalized:
            tax = i4.number_input("Tax rate (%)", 0.0, 40.0, float(saved.get("tax", 0.18)) * 100, 1.0,
                                  key=f"rd_tax_{ticker}", help="Effective tax rate on operating income.") / 100
            ic = ((a["equity"] + a["debt"] - a["cash"]).dropna() if {"equity", "debt", "cash"} <= set(a.columns)
                  else pd.Series(dtype=float))
            s2c_default = float(np.clip(rev0 / ic.iloc[-1], 0.5, 4.0)) if len(ic) and ic.iloc[-1] > 0 else 1.5
            s2c = st.number_input("Revenue per unit of invested capital (sales-to-capital)", 0.2, 10.0,
                                  float(saved.get("s2c", round(s2c_default, 2))), 0.1, key=f"rd_s2c_{ticker}",
                                  help="How much additional revenue one unit of invested capital brings. Suggestion: today's "
                                       "revenue ÷ invested capital (equity + debt − cash). Higher = capital-light growth.")
            margin_now = (ttm.get("operating_income") or 0.0) / rev0 * (1 - tax)
        else:
            sbc_on = i4.toggle("Deduct stock-based comp. (SBC)", value=sbc_on, key=f"rd_sbc_{ticker}",
                               help="Stock-based compensation is a real cost (it dilutes shareholders) but does not show up "
                                    "in free cash flow. Professionals deduct it.")
            margin_now = (fcf_ttm - (sbc_ttm if sbc_on else 0.0)) / rev0
    kw = dict(life_years=life, mature_growth=mature, sales_to_capital=s2c)
    margin_label = "After-tax operating margin" if normalized else ("FCF margin after SBC" if sbc_on else "FCF margin")
    implied_g = rd.implied_growth(f.market_cap, rev0, margin_now, max(margin_now, 0.01), hurdle, **kw)

    others = " · ".join(f"{tr(n)} {pct(g, 0)}" for n, g in [("history", x.hist_rev), ("company", x.company_rev)]
                        if np.isfinite(g))
    c.stats([
        c.stat("Priced-in revenue growth", pct(implied_g) + " p.a." if np.isfinite(implied_g) else "–",
               f"years 1–5, for {pct(hurdle, 0, False)} p.a. at today's margin",
               help="Below what you consider realistic = the stock is cheap, and vice versa."),
        c.stat("Analysts expect", pct(x.ana_rev) if np.isfinite(x.ana_rev) else "–", others or None),
        c.stat(margin_label, pct(margin_now, 1, False),
               f"FCF margin {pct(fcf_ttm / rev0, 1, False)}" if normalized else
               (f"before SBC {pct(fcf_ttm / rev0, 1, False)}" if sbc_on and sbc_ttm else None)),
        c.stat("Market cap", f"{num(f.market_cap / 1e9, 0)} bn {cur}", f"revenue {num(rev0 / 1e9, 1)} bn"),
    ])

    # scenario grid: growth rows around the plausible range, margin columns around today's margin
    anchors = [g for g in (x.hist_rev, x.ana_rev, x.company_rev) if np.isfinite(g)]
    top = max(0.25, round((max(anchors) if anchors else 0.15) + 0.05, 2))
    growths = sorted({0.0, 0.05, 0.10, 0.15, 0.20, min(top, 0.40)})
    base_m = max(margin_now, 0.02)
    margins = sorted({round(max(base_m - 0.05, 0.01), 4), round(base_m, 4), round(base_m + 0.05, 4),
                      round(base_m + 0.10, 4)})
    grid = rd.scenario_grid(f.market_cap, rev0, margin_now, growths, margins, **kw)
    plot(ch.titled(ch.rdcf_heatmap(grid, hurdle, c.settings()["rf"], round(base_m, 4)),
                   "Return p.a. when buying at today's price",
                   f"rows: revenue growth in years 1–5 · columns: {margin_label.lower()} from year 5 · "
                   f"blue = above the {pct(hurdle, 0, False)} hurdle",
                   "40 years of explicit cash flows, no terminal value · details under “How the model works”"))

    draconian = rd.implied_return(f.market_cap, rev0, margin_now, rd.Assumptions(0.0, max(base_m - 0.05, 0.01), **kw))
    cons_g = min(anchors) / 2 if anchors else 0.05
    conservative = rd.implied_return(f.market_cap, rev0, margin_now, rd.Assumptions(cons_g, base_m, **kw))
    d1, d2 = st.columns(2, gap="medium")
    with d1:
        ok = np.isfinite(draconian) and draconian >= 0
        c.callout(f"**Draconian case** – no growth, margin 5 points lower: **{pct(draconian)} p.a.** No loss even then."
                  if ok else f"**Draconian case** – no growth, margin 5 points lower: **{pct(draconian)} p.a.** You would "
                  "lose money.", "good" if ok else "warn")
    with d2:
        ok2 = np.isfinite(conservative) and conservative >= hurdle
        head = f"**Conservative case** – {pct(cons_g, 0)} growth, margin as today: **{pct(conservative)} p.a.**"
        c.callout(f"{tr(head)} {tr('Earns the market return.')}" if ok2 else
                  f"{tr(head)} {tr(f'Below the {pct(hurdle, 0, False)} hurdle.')}", "good" if ok2 else "warn")
    st.caption("Rule of thumb: buy when the draconian case avoids a loss and the conservative case earns the market return.")

    if np.isfinite(implied_g) and "revenue" in a:
        hist_rev_s = a["revenue"].dropna()
        start_year = hist_rev_s.index[-1].year
        path = rd.cash_flows(float(hist_rev_s.iloc[-1]), margin_now, rd.Assumptions(implied_g, base_m, **kw))["revenue"].iloc[:10]
        path.index = [start_year + i for i in path.index]
        path = pd.concat([pd.Series({start_year: float(hist_rev_s.iloc[-1])}), path])
        cons_pts = {start_year + i + 1: f.revenue_estimates[k]["avg"] for i, k in enumerate(["0y", "+1y"])
                    if f.revenue_estimates.get(k, {}).get("avg")}
        plot(ch.titled(ch.implied_path(hist_rev_s, path, cons_pts, 1e9, "bn"),
                       "What revenue does today's price require?",
                       f"the path that earns exactly {pct(hurdle, 0, False)} p.a. at today's margin (dashed) vs. analysts"))
    with st.expander("How the model works"):
        st.markdown(
            tr(f"- **Start:** revenue over the last 12 months ({num(rev0 / 1e9, 1)} bn {cur}) and {margin_label} "
               f"({pct(margin_now, 1, False)}).\n")
            + (tr("- **Reinvestment:** every additional unit of revenue requires 1 ÷ sales-to-capital of investment "
               f"(here {num(1 / s2c, 2)}) – growth is not free. The operating margin already contains stock-based "
               "compensation as a cost.\n") if normalized else "")
            + tr("- **Growth:** years 1–5 as in the row, years 6–10 half of it, years 11–20 a quarter (max. 4%), "
            f"then {pct(mature, 1, False)} until year {life}.\n"
            "- **Margin:** moves linearly from today to the column's margin over 5 years.\n"
            "- **Return:** the discount rate at which the present value of all cash flows equals the market cap "
            "(internal rate of return). No terminal value – anything beyond the horizon is a bonus.\n"
            "- **Limits:** net cash, investments and options are not valued separately; dilution is approximated via "
            "the SBC deduction or the operating margin."))
    x.rdcf_result = {"sbc": sbc_on, "hurdle": hurdle, "life": life, "mature": mature, "implied_growth": implied_g,
                     "basis": basis, "s2c": s2c, "tax": tax, "margin_now": margin_now, "draconian": draconian,
                     "conservative": conservative}
