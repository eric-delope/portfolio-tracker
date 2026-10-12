"""Risk: realized risk, drawdowns, ex-ante risk of today's holdings, correlations and stress tests."""

from __future__ import annotations

import numpy as np
import streamlit as st

import charts as ch
import common as c
from common import eur, num, pct, plot
from portfolio_tracker import metrics as m


def render(x) -> None:
    p, ps, bench, start, pos, risk, names = x.p, x.ps, x.bench, x.start, x.pos, x.risk, x.names
    r = p.returns(start)
    mdd = m.max_drawdown_info(r)
    bench_vol = m.annualized_volatility(p.benchmark_returns[bench].reindex(r.index))
    items = [
        c.stat("Volatility p.a.", pct(ps["volatility"], 1, False), f"{bench} {pct(bench_vol, 1, False)}"),
        c.stat("Sharpe ratio", num(ps["sharpe"]), f"Sortino {num(ps['sortino'])}",
               help="Return above the risk-free rate per unit of volatility (> 1 is very good). Sortino only counts "
                    "downside moves."),
        c.stat("Max. drawdown", pct(mdd["depth"]),
               f"{mdd['days_underwater']} days under water" + ("" if mdd["recovery"] else ", not recovered")),
    ]
    if risk:
        items.append(c.stat("Value at Risk 95%", eur(risk["var95_hist"]), f"expected shortfall {eur(risk['es95_hist'])}",
                            help="On 19 of 20 days the daily loss should be smaller (historical simulation of today's "
                                 "holdings). Expected shortfall: average loss on the worst 5% of days."))
    c.stats(items)

    left, right = st.columns(2, gap="medium")
    with left:
        sub = (f"deepest fall {pct(mdd['depth'])} from {mdd['peak']:%b %Y}" if mdd["peak"] is not None else None)
        plot(ch.titled(ch.underwater(m.drawdown(r), m.drawdown(p.benchmark_returns[bench].reindex(r.index)), bench),
                       "Drawdown", sub))
    with right:
        vol_d = p.daily["return"].rolling(63).std() * np.sqrt(252)
        vol_b = p.benchmark_returns[bench].rolling(63).std() * np.sqrt(252)
        plot(ch.titled(ch.two_lines(vol_d.loc[start:].dropna(), vol_b.loc[start:].dropna(), "Portfolio", bench,
                                    height=300), "Rolling volatility", "3 months, annualized"))

    if not risk:
        return
    st.subheader("Risk of today's holdings")
    c.stats([
        c.stat("Expected volatility", pct(risk["volatility"], 1, False), "p.a., current weights"),
        c.stat("Beta vs. MSCI World", num(risk["beta"])),
        c.stat("Diversification ratio", num(risk["diversification_ratio"]), "1 = no diversification",
               help="Average single-name volatility ÷ portfolio volatility – the higher, the more positions offset each other."),
        c.stat("Effective positions", num(risk["effective_positions"], 1), f"of {len(pos)} held",
               help="Inverse Herfindahl index: the number of equally sized positions your portfolio behaves like."),
    ])
    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.weight_vs_risk(risk["contributions"], names), "Weight vs. risk contribution",
                       "bars far apart = a position drives more risk than its weight suggests"))
    with right:
        corr = risk["correlation"]
        keep = [i for i in corr.index if pos.loc[i, "weight"] > 0.005] if not pos.empty else list(corr.index)
        plot(ch.titled(ch.correlation_heatmap(corr.loc[keep, keep], names), "Correlation",
                       "weekly returns, one year · dark blue = moves together"))
    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.return_histogram(r, m.historical_var(r[r != 0])), "Daily returns", "distribution in the period"))
    with right:
        plot(ch.titled(ch.stress_bars(p.stress_tests(), x.privacy), "Stress test",
                       "instant shock on today's portfolio (beta and currency exposure)"))
