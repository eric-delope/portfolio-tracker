"""Overview: headline figures, value vs. invested capital, return vs. benchmark."""

from __future__ import annotations

import streamlit as st

import charts as ch
import common as c
from common import eur, pct, plot
from portfolio_tracker import metrics as m
from portfolio_tracker.fmt import num


def render(x) -> None:
    p, ps, bench = x.p, x.ps, x.bench
    edge = ps["twr"] - ps["benchmark_twr"]
    c.stats([
        c.stat("Portfolio value", eur(ps["value"]), f"{eur(x.day_eur, sign=True)} today", c.tone(x.day_eur)),
        c.stat("Profit", eur(ps["pnl"], sign=True), "after fees, before taxes",
               help="Price gains (realized + unrealized) plus dividends, after fees, before taxes."),
        c.stat("Return (time-weighted)", pct(ps["twr"]), f"{num(edge * 100, 1, True)} pp vs. {bench}", c.tone(edge),
               help="Measures the investment decisions independent of when and how much you deposited – comparable "
                    "with fund performance."),
        c.stat("Your return (IRR)", pct(ps["mwr"]),
               f"{pct(ps['mwr_annualized'])} p.a." if ps["annualize"] else "period under one year",
               help="Internal rate of return (XIRR): accounts for when and how much money was invested."),
        c.stat("Max. drawdown", pct(ps["max_drawdown"]), "largest fall from a peak"),
    ])

    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.value_vs_invested(p.daily.loc[x.start:], x.privacy), "Value and invested capital",
                       "the gap between the lines is your profit"))
    with right:
        r = p.returns(x.start)
        series = {"Portfolio": m.cumulative(r) - 1,
                  bench: m.cumulative(p.benchmark_returns[bench].reindex(r.index)) - 1}
        plot(ch.titled(ch.performance_lines(series, 360), f"Return vs. {bench}", "time-weighted, cumulative"))
    st.caption(f"Cash on the account: {eur(x.cash_now)} · prices from Yahoo Finance · benchmark: accumulating UCITS ETF"
               + ("" if p.base == "EUR" else f", converted to {p.base} at each day's rate"))
