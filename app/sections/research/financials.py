"""Step 2 – financials: Qualtrim-style tiles, valuation multiples over time, earnings surprises."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import num, pct, plot
from portfolio_tracker import valuation as v


def render(x) -> None:
    f, a, cur, ticker = x.f, x.a, x.cur, x.ticker
    view = st.segmented_control("View", ["Annual", "Quarterly"], default="Annual", required=True,
                                key=f"fin_view_{ticker}", label_visibility="collapsed")
    quarterly = view == "Quarterly"
    data = f.quarterly if quarterly and not f.quarterly.empty else a
    if quarterly and f.quarterly.empty:
        st.caption("No quarterly data available – showing annual figures.")
        quarterly = False
    unit_bn = f"bn {cur}"

    tiles = []
    if "revenue" in data:
        tiles.append(("Revenue", unit_bn, ch.small_bars(data["revenue"], quarterly, 1e9, "")))
    if "operating_income" in data:
        tiles.append(("Operating income", unit_bn, ch.small_bars(data["operating_income"], quarterly, 1e9, "")))
    if "net_income" in data:
        tiles.append(("Net income", unit_bn, ch.small_bars(data["net_income"], quarterly, 1e9, "")))
    if "fcf" in data:
        fcf_series = data["fcf"] - (data["sbc"].fillna(0) if "sbc" in data else 0)
        tiles.append(("Free cash flow after SBC", f"{unit_bn} · FCF minus stock-based compensation",
                      ch.small_bars(fcf_series, quarterly, 1e9, "")))
    if "eps" in data:
        tiles.append(("Earnings per share", f"diluted, {cur}", ch.small_bars(data["eps"], quarterly)))
    tiles.append(("Margins", "operating · net · FCF", ch.margin_tile(data, quarterly)))
    if not quarterly and "shares" in a and a["shares"].notna().sum() >= 2:
        tiles.append(("Share count", "bn shares · falling = buybacks",
                      ch.small_bars(a["shares"], False, 1e9, "")))
    if not quarterly and {"cash", "debt"} <= set(a.columns):
        tiles.append(("Net cash", f"{unit_bn} · cash minus debt", ch.small_bars(a["cash"] - a["debt"], False, 1e9, "")))
    if not quarterly and len(f.dividends_ps):
        dps = f.dividends_ps[f.dividends_ps.index < pd.Timestamp.today().year].tail(10)
        if len(dps):
            idx = pd.to_datetime([f"{y}-12-31" for y in dps.index])
            tiles.append(("Dividend per share", f"{cur} per calendar year", ch.small_bars(pd.Series(dps.values, index=idx))))
    for i in range(0, len(tiles), 3):
        cols = st.columns(3, gap="medium")
        for col, (title, sub, fig) in zip(cols, tiles[i:i + 3]):
            with col:
                plot(ch.titled(fig, title, sub))

    c.section_label("Valuation over time")
    mcols = st.columns(3, gap="medium")
    multiples = [("P/E", x.hpe, f.pe_ttm)]
    if {"revenue", "shares"} <= set(a.columns):
        multiples.append(("Price / sales", v.historical_multiple(f.prices, a["revenue"] / a["shares"]), None))
    if {"fcf", "shares"} <= set(a.columns):
        multiples.append(("Price / free cash flow", v.historical_multiple(f.prices, a["fcf"] / a["shares"]), None))
    for col, (title, hist, cur_val) in zip(mcols, multiples):
        if len(hist) > 20:
            with col:
                plot(ch.titled(ch.multiple_tile(hist[hist < hist.quantile(0.99)], cur_val), title,
                               f"since {hist.index.min():%Y} · today {num(hist.iloc[-1], 1)}×"))
    if not f.surprises.empty:
        c.section_label("Earnings surprises")
        beat = (f.surprises["surprise"] > 0).mean()
        plot(ch.titled(ch.surprise_bars(f.surprises), "Earnings per share: expected vs. reported",
                       f"last {len(f.surprises)} quarters · {pct(beat, 0, False)} above expectations · adjusted EPS",
                       "Source: Yahoo Finance"))
