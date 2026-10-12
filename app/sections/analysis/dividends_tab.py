"""Dividends: received, expected next 12 months, yield and yield on cost."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import eur, pct, plot
from portfolio_tracker import dividends


def render(x) -> None:
    p, pos, privacy = x.p, x.pos, x.privacy
    held_tickers = tuple(sorted(tk for i, tk in p.tickers.items() if tk and i in pos.index))
    per_pos, upcoming = dividends.forecast(p, c.dividend_history(held_tickers))
    rec_div = dividends.received(p)
    last12 = rec_div[rec_div["date"] > p.last_date - pd.DateOffset(years=1)]
    income = per_pos["income"].sum() if not per_pos.empty else 0.0
    c.stats([
        c.stat("Received, last 12 months", eur(last12["net"].sum(), 2), f"{eur(rec_div['net'].sum(), 2)} since start"),
        c.stat("Expected, next 12 months", eur(income, 2), "gross, before taxes"),
        c.stat("Dividend yield", pct(income / pos["value"].sum() if not pos.empty else np.nan, 2, False), "on today's value"),
        c.stat("Yield on cost", pct(income / pos["cost"].sum() if not pos.empty else np.nan, 2, False), "on what you paid",
               help="Grows with dividend increases over time."),
    ])
    months_back = pd.period_range(p.last_date.to_period("M") - 11, p.last_date.to_period("M"), freq="M")
    rec_m = last12.groupby(last12["date"].dt.to_period("M"))["net"].sum().reindex(months_back, fill_value=0.0)
    months_fwd = pd.period_range(p.last_date.to_period("M") + 1, p.last_date.to_period("M") + 12, freq="M")
    exp_m = (upcoming.groupby(upcoming["date"].dt.to_period("M"))["amount"].sum() if not upcoming.empty
             else pd.Series(dtype=float)).reindex(months_fwd, fill_value=0.0)
    plot(ch.titled(ch.dividend_months(rec_m, exp_m, privacy), "Dividends per month",
                   "received (net) and expected (gross)",
                   "Forecast: last dividend per share at its usual frequency × today's shares, today's FX rate"))

    left, right = st.columns([3, 2], gap="medium")
    payers = per_pos[per_pos["income"] > 0] if not per_pos.empty else per_pos
    with left:
        st.subheader("By position")
        if not payers.empty:
            tbl = pd.DataFrame({
                "Position": payers["name"], "Per year": payers["payments_per_year"], "Expected": payers["income"],
                "Yield": payers["yield"], "Yield on cost": payers["yield_on_cost"],
            }).sort_values("Expected", ascending=False)
            if privacy:
                tbl = tbl.drop(columns=["Expected"])
            c.table(tbl, {"Per year": "int", "Expected": "eur:2", "Yield": "pct:2", "Yield on cost": "pct:2"})
        if not per_pos.empty and len(payers) < len(per_pos):
            st.caption("No dividend: " + ", ".join(per_pos.loc[per_pos["income"] <= 0, "name"]))
    with right:
        st.subheader("Next payments")
        if upcoming.empty:
            st.caption("No dividend payers in the portfolio.")
        else:
            up = pd.DataFrame({"Position": upcoming["name"], "Date ≈": upcoming["date"],
                               "Amount": upcoming["amount"]}).head(8)
            if privacy:
                up = up.drop(columns=["Amount"])
            c.table(up, {"Date ≈": "date", "Amount": "eur:2"}, compact=True)
