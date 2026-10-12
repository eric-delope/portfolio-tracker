"""Data quality checks and a short methodology note (full version: docs/METHODOLOGY.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import common
from portfolio_tracker.importer import trades


def render(x) -> None:
    p, names = x.p, x.names
    with st.expander("Data quality & methodology"):
        left, right = st.columns(2, gap="large")
        with left:
            st.subheader("Data checks")
            if x.issues:
                for i in x.issues:
                    st.warning(i)
            else:
                st.success("No issues: amounts = shares × price, no negative holdings, no negative cash balance, "
                           "no duplicate bookings.")
            st.subheader("Price sources & data quality")
            tq = trades(p.tx).copy()
            tq["bday"] = tq["date"].map(pd.offsets.BDay().rollforward)
            rows = []
            for isin, g in tq.groupby("isin"):
                tk = p.tickers.get(isin)
                if tk in p.prices.eur:
                    yahoo = p.prices.eur[tk].reindex(g["bday"]).to_numpy()
                    dev = np.nanmedian(np.abs(g["price"].to_numpy() / yahoo - 1))
                else:
                    dev = np.nan
                rows.append({"Name": names[isin], "ISIN": isin, "Ticker": tk or "–",
                             "Currency": p.meta.loc[isin, "currency"], "Deviation TR vs. Yahoo": dev})
            common.table(pd.DataFrame(rows), {"Deviation TR vs. Yahoo": "pct:2"}, compact=True, max_height=420)
            st.caption("Deviation: median gap between your execution price and the Yahoo close (EUR) on the same day – "
                       "below 2% is normal intraday movement.")
            st.caption("Adjust the ticker mapping: create `config/tickers.json` with {\"ISIN\": \"TICKER\"}.")
            if not x.privacy:
                st.download_button("Cleaned transactions as CSV", x.tx_raw.to_csv(index=False).encode(),
                                   "transactions_clean.csv", "text/csv")
        with right:
            st.subheader("Methodology")
            st.markdown("""
**Perspective.** The securities account is analysed on its own. Money flows in with every buy (incl. fee) and out with
every sell (after fee) or dividend (gross). Profit = portfolio value + outflows − inflows.

**Time-weighted return (TWR).** Daily returns `r = (value + outflows) / (previous value + inflows) − 1`, chained.
Neutralizes timing and size of deposits – measures the quality of investment decisions and is comparable with funds.

**Money-weighted return (IRR/XIRR).** Internal rate of return of all cash flows – your personal return including
timing. Periods under one year are not annualized (GIPS standard).

**FIFO.** Sells reduce the oldest lots first (German tax rule, § 20 (4) EStG). Fees raise the cost basis or reduce
proceeds.

**Benchmarks.** Accumulating UCITS ETFs in EUR on Xetra (MSCI World: EUNL, S&P 500: SXR8, Nasdaq-100: SXRV) –
including dividends and currency effects, as for a euro investor.

**Shadow portfolio & KS-PME.** Public market equivalent from private equity: identical cash flows are invested
virtually in the benchmark.

**Beta, correlation.** On weekly returns: US exchanges close after Xetra, so daily closes are asynchronous and would
bias beta downwards.

**Currency effect.** Prices in trading currency + daily FX rates. Per lot:
`EUR return = (price_today / price_buy) × (FX_buy / FX_today) − 1`.

**Value at Risk.** Historical simulation: today's weights × daily returns over the last year; 5% quantile.

**Limits.** Yahoo Finance closes differ slightly from Lang & Schwarz quotes; the German *Vorabpauschale* and
withholding-tax credits are not modelled. Full write-up: `docs/METHODOLOGY.md`.
""")
