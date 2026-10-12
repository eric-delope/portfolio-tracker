"""Portfolio analysis: the full analysis in seven tabs (performance, risk, dividends, trades, taxes, ...)."""

from __future__ import annotations

from types import SimpleNamespace

import streamlit as st

import common
from portfolio_tracker import decisions
from portfolio_tracker.market import BENCHMARKS
from sections.analysis import dividends_tab, methodology, overview, performance, positions, risk, taxes_costs, trades_tab

PERIODS = {"1M": "1m", "3M": "3m", "6M": "6m", "YTD": "ytd", "1Y": "1y", "Max": "all"}
source_label, tx_raw, p = common.load()

head, f1, f2 = st.columns([2.3, 1.7, 1], vertical_alignment="bottom")
with head:
    common.page_header("Portfolio analysis", "Performance, risk, dividends and your decisions.")
period_label = f1.segmented_control("Period", list(PERIODS), default="Max", required=True, key="period")
bench_name = f2.selectbox("Benchmark", list(BENCHMARKS), key="bench", help="Accumulating UCITS ETFs in EUR (Xetra) – "
                          "i.e. including reinvested dividends and from the view of a euro investor.")

start = p.period_start(PERIODS[period_label])
ps = p.period_summary(start, bench_name)
pos = p.positions
day_eur = pos["day_change_eur"].sum() if not pos.empty else 0.0
ctx = SimpleNamespace(
    p=p, tx_raw=tx_raw, start=start, period_label=period_label, bench=bench_name, ps=ps,
    rel=p.relative_metrics(start, bench_name), names=p.meta["name"], pos=pos, privacy=common.privacy(),
    allowance=common.settings()["allowance"], issues=common.issues(tx_raw, source_label), risk=p.ex_ante_risk(),
    stats=p.trade_statistics(), costs=p.cost_summary(), cash_now=p.cash_balance.iloc[-1], p_eur=common.portfolio_eur(),
    scorecard=decisions.scorecard(p, bench_name), day_eur=day_eur, prev_value=ps["value"] - day_eur,
)


SECTIONS = {"Overview": overview, "Positions": positions, "Performance": performance, "Risk": risk,
            "Dividends": dividends_tab, "Entries & trades": trades_tab, "Taxes & costs": taxes_costs}
tabs = st.tabs(list(SECTIONS), key="depot_tab", on_change="rerun")  # stateful: only the open section is computed
for tab, module in zip(tabs, SECTIONS.values()):
    with tab:
        if tab.open:
            module.render(ctx)

methodology.render(ctx)
