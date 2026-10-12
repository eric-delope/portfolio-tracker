"""Positions: holdings table, portfolio map, single-position drill-down and allocation."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import eur, pct, plot
from portfolio_tracker.importer import trades


def render(x) -> None:
    pos, privacy = x.pos, x.privacy
    if pos.empty:
        st.info("No open positions right now.")
    else:
        unreal = pos["unrealized"].sum()
        c.stats([
            c.stat("Open positions", str(len(pos)), f"cost basis {eur(pos['cost'].sum())}"),
            c.stat("Unrealized", eur(unreal, sign=True), pct(unreal / pos["cost"].sum()), c.tone(unreal)),
            c.stat("of which currency", eur(pos["fx_effect_eur"].sum(), sign=True), "exchange-rate effect",
                   help="Change in value caused by the exchange rate alone since each purchase."),
            c.stat("Today", eur(x.day_eur, sign=True), pct(x.day_eur / x.prev_value if x.prev_value else 0),
                   c.tone(x.day_eur)),
        ])

        st.subheader("Holdings")
        view = st.segmented_control("View", ["Overview", "Returns", "Risk", "Lots"],
                                    default="Overview", required=True, key="pos_view", label_visibility="collapsed")
        base = {"Position": pos["name"], "Weight": pos["weight"]}
        groups = {
            "Overview": ({**base, "Value": pos["value"], "Today": pos["day_change"], "Unrealized": pos["unrealized_pct"],
                          "Total P&L": pos["total_pnl"]},
                         {"Weight": "bar", "Value": "eur0", "Today": "spct", "Unrealized": "spct", "Total P&L": "seur:0"}),
            "Returns": ({**base, "Price": pos["local_return"], "Currency": pos["fx_return"], "Dividends": pos["dividends"],
                         "IRR p.a.": pos["irr"], "YTD": pos["ret_ytd"]},
                        {"Weight": "bar", "Price": "spct", "Currency": "spct", "Dividends": "eur:2", "IRR p.a.": "spct",
                         "YTD": "spct"}),
            "Risk": ({**base, "vs. 52w high": pos["off_52w_high"], "Volatility": pos["volatility_1y"],
                      "Beta": pos["beta_1y"], "Fwd P/E": pos["forward_pe"], "Sector": pos["sector"]},
                     {"Weight": "bar", "vs. 52w high": "spct", "Volatility": "pct:0", "Beta": "num:2", "Fwd P/E": "num:1",
                      "Sector": "text"}),
            "Lots": ({**base, "Shares": pos["shares"], "Avg. cost": pos["avg_cost"], "Price": pos["price"],
                      "Held (days)": pos["holding_days"]},
                     {"Weight": "bar", "Shares": "num:4", "Avg. cost": "eur:2", "Price": "eur:2", "Held (days)": "int"}),
        }
        data, fmt_ = groups[view]
        tbl = pd.DataFrame(data)
        if privacy:
            tbl = tbl.drop(columns=[k_ for k_, f_ in fmt_.items() if "eur" in f_ or k_ == "Shares"])
        c.table(tbl, fmt_)
        st.caption("IRR only for holdings of a year or more. Beta and volatility over one year (beta on weekly returns).")

        left, right = st.columns(2, gap="medium")
        with left:
            plot(ch.titled(ch.treemap(pos, privacy), "Portfolio map", "area = weight · colour = unrealized return"))
        with right:
            fx = pos[pos["currency"] != x.p.base] if (pos["currency"] != x.p.base).any() else pos
            plot(ch.titled(ch.return_decomposition(fx), "Where the return comes from",
                           "since purchase: price in trading currency vs. exchange rate"))

    _single_position(x)
    _allocation(x)
    _look_through(x)


def _single_position(x) -> None:
    p, pos, names, privacy = x.p, x.pos, x.names, x.privacy
    st.subheader("Single position")
    ever = list(pos.index) + [i for i in p.meta.index if i not in pos.index]
    pick = st.selectbox("Position", ever, format_func=lambda i: names[i] + ("" if i in pos.index else " (sold)"),
                        label_visibility="collapsed")
    tk = p.tickers.get(pick)
    tp = trades(p.tx)
    tp = tp[tp["isin"] == pick]
    lo = tp["date"].min() - pd.Timedelta(days=30)
    price = (p.prices.eur[tk] if tk in p.prices.eur else p.price_eur[pick]).loc[lo:].dropna()
    in_pos = pick in pos.index
    row = pos.loc[pick] if in_pos else None
    pnl_total = p.position_pnl[pick].iloc[-1]
    invested = p.inflows[pick].sum()
    divs = p.tx[(p.tx["event"] == "dividend") & (p.tx["isin"] == pick)]["amount"].sum()
    c.stats([
        c.stat("Total P&L", eur(pnl_total, sign=True), f"{pct(pnl_total / invested)} on invested", c.tone(pnl_total)),
        c.stat("Unrealized", eur(row["unrealized"], sign=True) if in_pos else "–",
               pct(row["unrealized_pct"]) if in_pos else "position closed", c.tone(row["unrealized"]) if in_pos else None),
        c.stat("Realized", eur(p.realized.loc[p.realized["isin"] == pick, "gain"].sum(), sign=True)),
        c.stat("Dividends", eur(divs, 2)),
        c.stat("Orders", str(len(tp)), f"fees {eur(-tp['fee'].sum(), 2)}"),
    ])
    plot(ch.titled(ch.price_with_trades(price, tp, row["avg_cost"] if in_pos else None, names[pick]),
                   f"{names[pick]}: price and your trades", "marker size = order amount · line = average cost"))
    if in_pos:
        lots = p.open_lots[p.open_lots["isin"] == pick].copy()
        lots["Value"] = lots["shares"] * row["price"]
        lots["P&L"] = lots["Value"] - lots["cost"]
        lots["P&L %"] = lots["Value"] / lots["cost"] - 1
        lot_table = lots.rename(columns={"buy_date": "Bought", "shares": "Shares", "cost_per_share": "Cost/share"})[
            ["Bought", "Shares", "Cost/share", "Value", "P&L", "P&L %"]]
        if privacy:
            lot_table = lot_table.drop(columns=["Shares", "Value", "P&L"])
        with st.expander(f"Open lots (FIFO) · {len(lots)}"):
            c.table(lot_table, {"Bought": "date", "Shares": "num:4", "Cost/share": "eur:2", "Value": "eur:2",
                                "P&L": "seur:2", "P&L %": "spct"}, compact=True)
            st.caption("Sells reduce the oldest lots first (FIFO) – the rule the German tax office applies.")


def _allocation(x) -> None:
    p, pos, names = x.p, x.pos, x.names
    st.subheader("Allocation")
    if pos.empty:
        st.info("No open positions.")
        return
    w = pos["weight"]
    c.stats([
        c.stat("Largest position", pct(w.max(), 1, False), names[w.idxmax()]),
        c.stat("Top 3", pct(w.nlargest(3).sum(), 1, False)),
        c.stat("Single stocks", pct(w[pos["asset_class"] == "STOCK"].sum(), 1, False), "rest in ETFs"),
        c.stat("Foreign currency", pct(w[pos["currency"] != p.base].sum(), 1, False), f"not in {p.base}"),
    ])
    tot = pos["value"].sum()
    blocks = [("By position", pos.set_index("name")["value"]), ("By sector", p.allocation("sector")),
              ("By country", p.allocation("country")), ("By currency", p.allocation("currency"))]
    for row_blocks in (blocks[:2], blocks[2:]):
        cols = st.columns(2, gap="medium")
        for col, (title, s) in zip(cols, row_blocks):
            with col:
                plot(ch.titled(ch.share_bars((s / tot).nlargest(7), height=250), title))
    plot(ch.titled(ch.allocation_area(p.values.loc[x.start:], names, list(pos.index)), "Composition over time",
                   "share of each current position; earlier positions in grey"))


def _look_through(x) -> None:
    """What the portfolio really owns once the ETFs are opened up."""
    from portfolio_tracker.lookthrough import look_through

    p, pos = x.p, x.pos
    st.subheader("What you really own")
    if pos.empty:
        return
    holdings = pd.DataFrame({
        "name": pos["name"], "ticker": [p.tickers.get(i) for i in pos.index], "value": pos["value"],
        "sector": pos["sector"], "is_fund": pos["asset_class"].eq("FUND"),
    })
    funds = tuple(sorted(tk for tk, f in zip(holdings["ticker"], holdings["is_fund"]) if f and tk))
    if not funds:
        st.caption("No ETFs in the portfolio – your positions are already everything you own.")
        return
    lt = look_through(holdings, c.fund_profiles(funds))
    lt.companies = lt.companies[lt.companies["total"] >= 0.0005]      # hide rounding dust
    top = lt.companies.head(12)
    if lt.fund_share < 0.01:
        st.caption(f"ETFs are only {pct(lt.fund_share, 1, False)} of your portfolio, so opening them up changes little.")
    overlaps = lt.companies[(lt.companies["direct"] > 0) & (lt.companies["via_funds"] > 0)]
    tech = lt.sectors["total"].idxmax() if not lt.sectors.empty else "–"
    c.stats([
        c.stat("Largest single company", pct(top["total"].iloc[0], 1, False) if len(top) else "–",
               top["name"].iloc[0] if len(top) else None),
        c.stat("Top 10 companies", pct(lt.companies["total"].head(10).sum(), 1, False), "direct and through ETFs"),
        c.stat("Largest sector", pct(lt.sectors["total"].max(), 1, False) if not lt.sectors.empty else "–", tech,
               help="Including the sector mix inside your ETFs."),
        c.stat("Overlaps", str(len(overlaps)), "held directly and in an ETF" if len(overlaps) else "none"),
    ])
    if len(overlaps):
        o = overlaps.iloc[0]
        c.callout(f"**{o['name']}** is {pct(o['direct'], 1, False)} of your portfolio directly and another "
                  f"{pct(o['via_funds'], 1, False)} through {', '.join(o['sources'])} – "
                  f"**{pct(o['total'], 1, False)} in total**.", "info")
    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.exposure_bars(top), "Largest companies, ETFs opened up",
                       "dark: held directly · light: inside your ETFs"))
    with right:
        sec = lt.sectors.head(11).reset_index(names="name")
        plot(ch.titled(ch.exposure_bars(sec), "Sectors, ETFs opened up", "your real sector mix"))
    note = (f"ETFs make up {pct(lt.fund_share, 0, False)} of the portfolio; their ten largest holdings are itemised, "
            f"the remaining {pct(lt.other_fund_share, 0, False)} is spread over hundreds of smaller positions. "
            "Source: Yahoo Finance fund data (no country split for ETFs).")
    if lt.missing_funds:
        note += " No fund data for: " + ", ".join(lt.missing_funds) + "."
    st.caption(note)
