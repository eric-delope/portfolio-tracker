"""Step 6 – valuation: exit P/E per scenario from the stock's own history, horizon, dividends, DCF cross-check."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import num, plot
from portfolio_tracker import valuation as v


def render(x) -> None:
    f, cur, ticker, inputs, hpe, saved = x.f, x.cur, x.ticker, x.inputs, x.hpe, x.saved_val
    c.lead("**What P/E will the market pay in five years?** The stock's own history is the guide – assuming more than "
           "its average is a bet that it gets more expensive.")
    if len(hpe) > 20:
        q25, q50, q75 = (float(hpe.quantile(q)) for q in (0.25, 0.5, 0.75))
        base_pe_default = float(np.clip(min(q50, f.pe_forward or q50), 6, 30))
        # keep the order Bear <= Base <= Bull even when the history sits far above today's forward P/E
        bear_pe_default = float(np.clip(min(q25, base_pe_default * 0.8), 5, 40))
        bull_pe_default = float(np.clip(min(max(q75, base_pe_default * 1.2), base_pe_default * 1.5), 6, 45))
    else:
        base_pe_default = float(np.clip(f.pe_forward or f.pe_ttm or 18.0, 6, 30))
        bear_pe_default, bull_pe_default = base_pe_default * 0.8, base_pe_default * 1.2
    c1, c2 = st.columns([3, 2], gap="medium")
    with c2:
        pe_pct = v.percentile_rank(hpe, f.pe_ttm)
        c.stats([c.stat("P/E today", num(f.pe_ttm, 1),
                        f"{v.valuation_zone(pe_pct)} of its history" if np.isfinite(pe_pct) else None)])
        e1, e2, e3 = st.columns(3)
        col = "Exit P/E"
        x.pe_bear = e1.number_input("Exit P/E bear", 1.0, 200.0, saved("Bear", col, round(bear_pe_default, 1)), 0.5,
                                    key=f"peb_{ticker}")
        x.pe_base = e2.number_input("Exit P/E base", 1.0, 200.0, saved("Base", col, round(base_pe_default, 1)), 0.5,
                                    key=f"pem_{ticker}")
        x.pe_bull = e3.number_input("Exit P/E bull", 1.0, 200.0, saved("Bull", col, round(bull_pe_default, 1)), 0.5,
                                    key=f"peu_{ticker}")
        st.caption("Suggested: base = median of the history, bear = lower quartile, bull = upper quartile.")
        if not x.pe_bear <= x.pe_base <= x.pe_bull:
            st.warning("Exit P/Es should be ascending: bear ≤ base ≤ bull.")
        x.horizon = st.slider("Investment horizon (years)", 3, 10, int(inputs.get("horizon", 5)), key=f"hz_{ticker}")
        x.div0 = st.number_input(f"Dividend per share today ({cur})", min_value=0.0,
                                 value=float(inputs.get("dividend0", f.dividend_rate or 0.0)), step=0.05, format="%.2f",
                                 key=f"div_{ticker}", help="Grows with earnings and counts towards fair value.")
    with c1:   # drawn after the inputs on the right, so the chart can show your base exit P/E
        if len(hpe) > 20:
            plot(ch.titled(ch.pe_history(hpe, f.pe_ttm, yours=x.pe_base), "P/E within its own history",
                           f"price ÷ last annual EPS since {hpe.index.min():%Y} · dotted = your base exit P/E"))
        else:
            st.caption("Too few profitable years for a P/E history – suggestions are based on the forward P/E.")
    with st.expander("Cross-check: DCF on free cash flow"):
        d1, d2, d3, d4 = st.columns(4)
        x.fcf0 = d1.number_input(f"FCF per share ({cur})", value=float(inputs.get("fcf0", f.fcf_per_share or 0.0)),
                                 step=0.1, format="%.2f", key=f"fcf_{ticker}")
        x.dcf_g = d2.number_input("FCF growth years 1–5 (%)", -20.0, 60.0,
                                  float(inputs.get("dcf_growth", x.g_base / 100)) * 100, 0.5, key=f"dg_{ticker}") / 100
        x.tg = d3.number_input("Terminal growth (%)", 0.0, 4.0, float(inputs.get("terminal_growth", 0.025)) * 100, 0.25,
                               key=f"tg_{ticker}") / 100
        x.eps_weight = 1 - d4.slider("DCF weight in fair value (%)", 0, 100,
                                     int((1 - inputs.get("eps_weight", 1.0)) * 100), 10, key=f"w_{ticker}") / 100

    x.scen_df = pd.DataFrame({
        "Scenario": ["Bear", "Base", "Bull"],
        "Probability %": [float(x.p_bear), float(x.p_base), float(x.p_bull)],
        "EPS growth % p.a.": [x.g_bear, x.g_base, x.g_bull],
        "Exit P/E": [x.pe_bear, x.pe_base, x.pe_bull],
    })
    x.scenarios = [v.Scenario(r["Scenario"], r["Probability %"] / 100, r["EPS growth % p.a."] / 100, r["Exit P/E"])
                   for _, r in x.scen_df.iterrows()]
