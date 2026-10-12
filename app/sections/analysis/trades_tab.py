"""Entries & trades: entry quality, decision scorecard, trader statistics, sells and closed positions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import num, pct, plot
from portfolio_tracker import decisions, fmt


def render(x) -> None:
    _entry_quality(x)
    _scorecard(x)
    with st.expander("Sells, closed positions and trading statistics"):
        _sells(x)


def _entry_quality(x) -> None:
    p, privacy = x.p, x.privacy
    eq = decisions.entry_quality(p, x.bench, fair_values=c.fair_value_series_eur(p, c.watchlist()))
    es = decisions.entry_summary(eq)
    if not es:
        st.info("No stock purchases yet.")
        return
    c.stats([
        c.stat("Position in the following range", pct(es["range_position"], 0, False), "0% = bought at the low · 50% = random",
               help="Where your buy price sat within the price range of the following 6 months."),
        c.stat("vs. a 3-month savings plan", pct(es["vs_dca"]), f"{pct(es['cheaper_than_dca'], 0, False)} of buys cheaper",
               help="Buy price compared with the average price of the following 3 months."),
        c.stat("Bought after a pullback", pct(es["share_after_dip"], 0, False), "more than 15% below the 52w high"),
        c.stat("Bought below fair value", pct(es["below_fair"], 0, False) if es["n_fair"] else "–",
               f"{es['n_fair']} buys with a valuation" if es["n_fair"] else "measurable once you value companies"),
    ])
    left, right = st.columns([3, 2], gap="medium")
    with left:
        if es["n_edge"]:
            plot(ch.titled(ch.entry_scatter(eq, privacy), "Were your entries good?",
                           "distance to the 52-week high at purchase vs. result 12 months later"))
    with right:
        st.markdown("<div style='height:.2rem'></div>", unsafe_allow_html=True)
        lines = []
        if np.isfinite(es["edge_after_dip"]) and np.isfinite(es["edge_near_high"]):
            better = es["edge_after_dip"] > es["edge_near_high"]
            lines.append(f"Buys **after a pullback**: **{fmt.num(es['edge_after_dip'] * 100, 1, True)} pp** vs. the market "
                         f"12 months later; buys **near the high**: **{fmt.num(es['edge_near_high'] * 100, 1, True)} pp**.")
            lines.append("Pullbacks have been good entries for you so far." if better else
                         "A falling price alone has not been a good signal – price relative to value matters.")
        if np.isfinite(es["range_position"]):
            t = es["range_position"]
            lines.append("No timing edge, but no disadvantage either." if 0.4 <= t <= 0.6 else
                         ("You tend to buy at good moments." if t < 0.4 else
                          "You tend to buy too early – more patience or a larger savings-plan share."))
        with c.card():
            c.card_title("What this says")
            c.facts(lines)


def _scorecard(x) -> None:
    scorecard = x.scorecard
    st.subheader("Decision scorecard")
    st.caption(f"Every buy and sell compared with the {x.bench} over the following months. Positive = better than "
               "doing nothing. Single stocks only.")
    hz = st.segmented_control("Horizon", list(decisions.HORIZONS), default="12M", required=True, key="sc_horizon",
                              label_visibility="collapsed")
    summ = decisions.summarize(scorecard, hz)
    if summ.empty:
        st.info("Not enough trades with sufficient price history for this horizon yet.")
        return
    c.stats([c.stat(f"{group}s" if group != "Savings plan" else "Savings plans",
                    f"{fmt.num(s_['edge_weighted'] * 100, 1, True)} pp",
                    f"{int(s_['n'])} decision{'s' if int(s_['n']) != 1 else ''} · {s_['verdict']}",
                    c.tone(s_["edge_weighted"]) if s_["verdict"].startswith("clearly") else None,
                    help="Amount-weighted edge vs. the market. Below 20 decisions or with |t| < 2 the result cannot "
                         "be told apart from luck.")
             for group, s_ in summ.iterrows()])
    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.decision_dots(scorecard[scorecard["asset_class"] != "FUND"], f"edge_{hz}", x.privacy),
                       "Every decision", f"edge vs. market after {hz}"))
    with right:
        plot(ch.titled(ch.quarter_bars(decisions.by_quarter(scorecard, hz)), "Per quarter", "amount-weighted"))


def _sells(x) -> None:
    p, stats, costs, scorecard, privacy = x.p, x.stats, x.costs, x.scorecard, x.privacy
    if not stats:
        st.info("No sells yet.")
        return
    sells = p.sell_analysis
    sell_edge = scorecard.loc[scorecard["group"] == "Sell", "edge_today"]
    c.stats([
        c.stat("Sells", str(stats["sells"]), f"hit rate {pct(stats['hit_rate'], 0, False)}"),
        c.stat("Profit factor", num(stats["profit_factor"]), "gains ÷ losses"),
        c.stat("Held: winners / losers",
               f"{fmt.num(stats['avg_days_winners'], 0)} / {fmt.num(stats['avg_days_losers'], 0)} d",
               help="Disposition effect: many investors sell winners too early and hold losers too long."),
        c.stat("Sold stocks since", f"{fmt.num(-sell_edge.mean() * 100, 1, True)} pp" if len(sell_edge) else "–",
               "vs. market – negative = good sale"),
    ])
    sv = pd.DataFrame({
        "Position": sells["name"], "Date": sells["date"], "Proceeds": sells["proceeds"], "P&L %": sells["return_pct"],
        "Held (days)": sells["holding_days"],
        "vs. market since": -scorecard.set_index("transaction_id")["edge_today"].reindex(sells.index),
    })
    if privacy:
        sv = sv.drop(columns=["Proceeds"])
    c.table(sv, {"Date": "date", "Proceeds": "eur0", "P&L %": "spct", "Held (days)": "int", "vs. market since": "pp"},
            max_height=420)
    plot(ch.titled(ch.holding_vs_return(sells, privacy), "Holding period vs. return", "bubble size = proceeds"))
    cp = p.closed_positions
    if not cp.empty:
        cv = pd.DataFrame({"Position": cp["name"], "First buy": cp["first_buy"], "Last sell": cp["last_sell"],
                           "P&L": cp["pnl"], "Return": cp["return_on_invested"], "IRR p.a.": cp["irr"]})
        if privacy:
            cv = cv.drop(columns=["P&L"])
        c.table(cv, {"First buy": "date", "Last sell": "date", "P&L": "seur:0", "Return": "spct", "IRR p.a.": "spct"})
    st.caption(f"Turnover {num(costs['turnover'], 1)}× per year.")
