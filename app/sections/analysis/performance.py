"""Performance: relative metrics, benchmarks, shadow portfolio, monthly returns, P&L decomposition."""

from __future__ import annotations

import numpy as np
import streamlit as st

import charts as ch
import common as c
from common import eur, num, pct, plot
from portfolio_tracker import fmt
from portfolio_tracker import metrics as m
from portfolio_tracker.market import BENCHMARKS


def render(x) -> None:
    p, ps, rel, bench, start, pos = x.p, x.ps, x.rel, x.bench, x.start, x.pos
    c.stats([
        c.stat("Return (time-weighted)", pct(ps["twr"]),
               f"{pct(ps['twr_annualized'])} p.a." if ps["annualize"] else "period under one year"),
        c.stat(f"vs. {bench}", f"{fmt.num(rel['excess_return'] * 100, 1, True)} pp", "excess return",
               c.tone(rel["excess_return"])),
        c.stat("Alpha p.a.", pct(rel["alpha"]), "Jensen, weekly", c.tone(rel["alpha"]),
               help="Return above what market risk (beta) explains. Estimated on weekly returns."),
        c.stat("Beta", num(rel["beta"]),
               f"capture ↑ {num(rel['up_capture'] * 100, 0)} · ↓ {num(rel['down_capture'] * 100, 0)}",
               help="Beta: how strongly the portfolio moves with the market (1 = equally). Capture: share of the "
                    "market's up and down weeks you take part in – ideal is up > 100, down < 100."),
        c.stat("Information ratio", num(rel["information_ratio"]), "> 0.5 is good",
               help="Excess return per unit of deviation from the benchmark (tracking error)."),
    ])

    r = p.returns(start)
    series = {"Portfolio": m.cumulative(r) - 1}
    for b in BENCHMARKS:
        if b in p.benchmark_returns:
            series[b] = m.cumulative(p.benchmark_returns[b].reindex(r.index)) - 1
    plot(ch.titled(ch.performance_lines(series, 340), "Cumulative return vs. all benchmarks", "time-weighted"))

    sh = p.shadow_portfolio(bench, start)
    diff = sh["actual"].iloc[-1] - sh["shadow"].iloc[-1]
    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.two_lines(sh["actual"], sh["shadow"], "Your portfolio", f"All in {bench}",
                                    suffix=" €", scale=1, privacy=x.privacy),
                       f"Shadow portfolio: everything in the {bench}?",
                       f"same cash flows, invested in the benchmark · difference today {eur(diff, sign=True)} · "
                       f"KS-PME {num(p.ks_pme(bench))}"))
    with right:
        roll_d = (1 + p.daily["return"]).rolling(252).apply(np.prod, raw=True) - 1
        roll_b = (1 + p.benchmark_returns[bench]).rolling(252).apply(np.prod, raw=True) - 1
        plot(ch.titled(ch.two_lines(roll_d.loc[start:].dropna(), roll_b.loc[start:].dropna(), "Portfolio", bench),
                       "Rolling 12-month return", "is the outperformance persistent or a one-off?"))

    monthly = m.monthly_returns(p.daily["return"])
    mb = m.monthly_returns(p.benchmark_returns[bench])
    sel = monthly.loc[start:] if start > p.index[0] else monthly
    beat = (sel > mb.reindex(sel.index)).mean()
    plot(ch.titled(ch.monthly_heatmap(monthly), "Monthly returns",
                   f"ahead of the {bench} in {pct(beat, 0, False)} of months · best {pct(monthly.max())} · "
                   f"worst {pct(monthly.min())}"))

    unreal = pos["unrealized"].sum() if not pos.empty else 0.0
    fx = pos["fx_effect_eur"].sum() if not pos.empty else 0.0
    plot(ch.titled(ch.waterfall([
        ("Realized", p.realized["gain"].sum(), "relative"), ("Unrealized: price", unreal - fx, "relative"),
        ("Unrealized: currency", fx, "relative"), ("Dividends", p.tx.loc[p.tx["event"] == "dividend", "amount"].sum(), "relative"),
        ("Before tax", 0, "total"), ("Taxes", p.tx["tax"].sum(), "relative"), ("After tax", 0, "total"),
    ], x.privacy), "Where the profit comes from", f"since start · order fees ({eur(x.costs['fees'])}) already included"))
