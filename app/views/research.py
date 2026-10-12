"""Company research as a guided assistant: understand -> quality -> growth -> valuation -> my price -> plan."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import streamlit as st
from i18n import tr

import charts as ch
import common as c
from common import money, num, pct, plot
from portfolio_tracker import valuation as v
from sections.research import financials, growth, overview, plan, price, quality, reverse_dcf, valuation

c.page_header("Company research", "Eight steps to the maximum price you are willing to pay for a business. "
                                  "Everything is pre-filled – you make the decisions.")

wl = c.watchlist()
_, _, p = c.load()

# ------------------------------------------------------------------ choose
holdings = {tk: p.meta.loc[i, "name"] for i, tk in p.tickers.items()
            if tk and i in p.positions.index and p.meta.loc[i, "asset_class"] == "STOCK"}
watched = {e.ticker: e.name for e in wl}
quick = {**watched, **holdings}

left, right = st.columns([2, 3], vertical_alignment="bottom")
with left:
    query = st.text_input("Search a company (name, ticker or ISIN)", placeholder="e.g. ASML, Microsoft, DE0007164600")
with right:
    options: dict[str, str] = {}
    if query:
        for hit in c.research().search(query):
            options[hit["symbol"]] = f"{hit['name']} · {hit['symbol']} ({hit['exchange']})"
    for tk, name in quick.items():
        options.setdefault(tk, f"{name} · {tk}" + tr(" ★ watchlist" if tk in watched else " · in portfolio"))
    if not options:
        st.info("Search for a company to get started.")
        st.stop()
    default = st.session_state.get("research_ticker")
    keys = list(options)
    ticker = st.selectbox("Selection", keys, index=keys.index(default) if default in keys else 0,
                          format_func=lambda k: options[k])
st.session_state["research_ticker"] = ticker

try:
    with st.spinner("Loading fundamentals …"):
        f = c.research().fundamentals(ticker)
except Exception as exc:
    st.error(f"Data for {ticker} could not be loaded: {exc}")
    st.stop()

saved = wl.entries.get(ticker)
a = f.annual
releases = c.guidance_releases(ticker, f.name)
x = SimpleNamespace(
    p=p, wl=wl, ticker=ticker, f=f, a=a, cur=f.currency, fx_eur=c.eur_rate(f.currency), saved=saved,
    inputs=saved.valuation_inputs if saved else {}, holding=c.position_of(p, ticker),
    hpe=v.historical_multiple(f.prices, a["eps"]) if "eps" in a else pd.Series(dtype=float),
    releases=releases, latest=releases[0] if releases else None,
)

# ---------------------------------------------------------------- header
st.subheader(f"{f.name}")
st.caption(" · ".join(tr(s) for s in [ticker, f.sector, f.industry, f.country] if s)
           + (tr(f" · last valued {saved.valuation_date[:10]}") if saved and saved.valuation_date else ""))
c.stats([
    c.stat("Price", money(f.price, x.cur), f"≈ {money(f.price / x.fx_eur, 'EUR')}" if x.cur != "EUR" else None),
    c.stat("Market cap", f"{num(f.market_cap / 1e9, 0)} bn {x.cur}" if f.market_cap else "–"),
    c.stat("P/E", num(f.pe_ttm, 1), f"forward {num(f.pe_forward, 1)}"),
    c.stat("Dividend yield", pct(f.dividend_yield, 1, False) if f.dividend_yield else "–"),
    c.stat("In your portfolio", pct(x.holding["weight"], 1, False) if x.holding is not None else "–",
           f"unrealized {pct(x.holding['unrealized_pct'])}" if x.holding is not None else
           (f"reports {f.earnings_date:%d %b}" if f.earnings_date else None),
           c.tone(x.holding["unrealized_pct"]) if x.holding is not None else None),
])

STEPS = {"1 · Overview": overview, "2 · Financials": financials, "3 · Quality": quality, "4 · Growth": growth,
         "5 · Reverse DCF": reverse_dcf, "6 · Valuation": valuation, "7 · My price": price, "8 · Plan": plan}
STEP_LABELS = list(STEPS)
# Stateful tabs: the Next/Back buttons switch steps. Every step still runs on each rerun, because later steps
# build on the inputs of earlier ones (growth -> valuation -> price -> plan), so nothing gets lost.
tabs = st.tabs(STEP_LABELS, key="rstep", on_change="rerun")
c.scroll_into_view_if_requested("rstep")
for i, (tab, module) in enumerate(zip(tabs, STEPS.values())):
    with tab:
        module.render(x)
        st.divider()
        c.step_nav("rstep", STEP_LABELS, i)

if saved and saved.history:
    with st.expander(f"Valuation history ({len(saved.history)})"):
        plot(ch.titled(ch.valuation_history(f.prices[f.prices.index >= f.prices.index.max() - pd.DateOffset(years=2)],
                                            saved.history, x.cur), "Price and your fair value",
                       "every dot is a saved valuation"))
