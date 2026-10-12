"""Reusable dashboard building blocks shared by several pages."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import common as c
from portfolio_tracker.ordercheck import simulate
from portfolio_tracker.portfolio import Portfolio

SIGNAL_ICON = {"buy": "🟢", "hold": "⚪", "trim": "🟠", "none": "–"}


def order_check(p: Portfolio, ticker: str, name: str, default_amount: float, key: str) -> None:
    """Before/after view of a planned buy: concentration, currency, risk."""
    amount = st.number_input("Planned buy amount (€)", min_value=10.0, max_value=1e7,
                             value=float(max(default_amount, 10.0)), step=50.0, key=f"oc_amount_{key}")
    try:
        with st.spinner("Simulating …"):
            inp = c.order_inputs(c.portfolio_eur(), ticker)   # orders are placed in euros
            before, after, hints = simulate(inp, ticker, amount)
    except Exception as exc:
        st.warning(f"Order check not possible: {exc}")
        return

    def row(label, b, a, kind):
        fmt = {"pct": lambda x: c.pct(x, 1, False), "num": lambda x: c.num(x, 2), "eur": lambda x: c.eur(x, ccy="EUR"),
               "pct1": lambda x: c.pct(x, 1, False)}[kind]
        delta = "" if b is None or a is None or not np.isfinite(b) or not np.isfinite(a) else (
            c.pct(a - b, 1).replace("%", " pp") if kind.startswith("pct") else
            (c.num(a - b, 2) if kind == "num" else c.eur(a - b, sign=True, ccy="EUR")))
        return {"Metric": label, "Before": fmt(b), "After": fmt(a), "Change": delta}

    sector = after["sector"] or "–"
    table = pd.DataFrame([
        row(f"Weight {name}", before["weight"], after["weight"], "pct"),
        row("Largest position", before["max_weight"], after["max_weight"], "pct"),
        row(f"Sector {sector}", before["sector_share"], after["sector_share"], "pct"),
        row("Foreign currency share", before["foreign_share"], after["foreign_share"], "pct"),
        row("Expected volatility p.a.", before["volatility"], after["volatility"], "pct1"),
        row("Beta vs. MSCI World", before["beta"], after["beta"], "num"),
        row(f"Risk contribution {name}", before["risk_contribution"], after["risk_contribution"], "pct"),
        row("Value at Risk 95% (1 day)", before["var95"], after["var95"], "eur"),
    ])
    left, right = st.columns([3, 2], gap="medium")
    with left:
        c.table(table, {"Before": "rtext", "After": "rtext", "Change": "rtext"}, compact=True)
    with right:
        if not hints:
            c.callout("No red flags: the order barely changes the portfolio structure.", "good")
        for kind, text in hints:
            c.callout(text, kind)
