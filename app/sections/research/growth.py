"""Step 4 – growth: history, analyst consensus and company guidance -> your EPS growth scenarios."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import money, num, pct, plot
from portfolio_tracker.guidance import implied_growth as guidance_growth
from portfolio_tracker.guidance import revenue_guidance
from portfolio_tracker.quality import _cagr
from sections.research.overview import unit_label

LONG_RUN = 0.06  # long-run normal EPS growth the suggestion fades towards


def saved_scenario(inputs: dict):
    """Lookup of a value from the saved scenario table: saved(name, column, default)."""
    df = pd.DataFrame(inputs["scenarios"]) if inputs.get("scenarios") else None

    def get(name: str, col: str, default: float) -> float:
        if df is not None and col in df and name in set(df["Scenario"]):
            return float(df.loc[df["Scenario"] == name, col].iloc[0])
        return default
    return get


def render(x) -> None:
    f, a, cur, ticker, inputs, latest = x.f, x.a, x.cur, x.ticker, x.inputs, x.latest
    c.lead("**How fast will earnings per share grow?** Three views – the past, the analysts, the company – then "
           "your own assumption.")
    est0, est1 = f.eps_estimates.get("0y", {}), f.eps_estimates.get("+1y", {})
    rev0, rev1 = f.revenue_estimates.get("0y", {}), f.revenue_estimates.get("+1y", {})
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        if "revenue" in a and a["revenue"].notna().any():
            plot(ch.titled(ch.history_and_estimates(a["revenue"].dropna(), f.revenue_estimates, 1e9, "bn", cur),
                           "Revenue", "reported and analyst consensus (range = lowest to highest estimate)"))
    with c2:
        if "eps" in a and a["eps"].notna().any():
            plot(ch.titled(ch.history_and_estimates(a["eps"].dropna(), f.eps_estimates, 1, "", cur),
                           "Earnings per share", "reported and analyst consensus"))

    st.subheader("Analyst sentiment")
    trend = f.eps_trend.get("+1y", {})
    revs = f.eps_revisions.get("+1y", {})
    recs = f.recommendations or {}
    n_recs = sum(recs.get(k_, 0) for k_ in ("strongBuy", "buy", "hold", "sell", "strongSell"))
    c.stats([
        c.stat("Buy ratings", pct((recs.get("strongBuy", 0) + recs.get("buy", 0)) / n_recs, 0, False) if n_recs else "–",
               f"of {n_recs} analysts" if n_recs else None),
        c.stat("Consensus EPS, 90 days", pct(trend["current"] / trend["90d_ago"] - 1)
               if trend.get("current") and trend.get("90d_ago") else "–", "change in next year's estimate",
               c.tone(trend["current"] / trend["90d_ago"] - 1) if trend.get("current") and trend.get("90d_ago") else None,
               help="Rising estimates (positive revisions) often go along with good share price performance."),
        c.stat("Revisions, 30 days", f"↑ {int(revs.get('up_30d') or 0)}  ↓ {int(revs.get('down_30d') or 0)}" if revs else "–",
               "analysts raising / cutting"),
        c.stat("Avg. price target", money(f.target_mean, cur, 0) if f.target_mean else "–",
               f"{money(f.target_low, cur, 0)} – {money(f.target_high, cur, 0)}" if f.target_mean else None),
    ])

    st.subheader("Company guidance")
    auto_growth, auto_label = np.nan, ""
    if latest and latest.items:
        rg = revenue_guidance(latest)
        q_rev = f.quarterly["revenue"] if "revenue" in f.quarterly else pd.Series(dtype=float)
        if rg is not None:
            res = guidance_growth(rg, latest.date, q_rev, a["revenue"] if "revenue" in a else pd.Series(dtype=float))
            if res is not None:
                auto_growth, basis = res
                auto_label = (f"{rg.label}: {num(rg.low, 1)}–{num(rg.high, 1)} {unit_label(rg.unit)} "
                              f"→ midpoint {pct(auto_growth)} {basis}")
        gcols = st.columns([3, 2], gap="medium")
        with gcols[0]:
            st.caption(f"From the earnings release of {latest.date:%d %b %Y} · [original]({latest.url})")
            for sentence in latest.sentences[:2]:
                st.markdown(f'<div class="quote">{sentence}</div>', unsafe_allow_html=True)
        with gcols[1]:
            if auto_label:
                c.stats([c.stat("Revenue guidance", pct(auto_growth), auto_label)])
            for it in [i for i in latest.items if i is not rg][:3]:
                st.caption(f"• {it.label}: {it.currency or ''}{num(it.low, 1)}–{num(it.high, 1)} {unit_label(it.unit)}")
    elif x.releases:
        st.caption(f"The latest release ({x.releases[0].date:%d %b %Y}) contains no numeric outlook – many companies "
                   "only give it on the earnings call. Enter it yourself below.")
    else:
        st.caption("No SEC earnings releases for this company (no US listing). Please enter the outlook from the "
                   "quarterly report below.")
    guide = inputs.get("guidance", {})
    with st.expander("Your own guidance figures (override the automatic extraction)",
                     expanded=not np.isfinite(auto_growth) and not guide):
        g1, g2, g3 = st.columns(3)
        x.g_rev = g1.number_input("Company revenue growth, next FY (%)", value=guide.get("revenue_growth"),
                                  step=0.5, format="%.1f", placeholder="e.g. 12.0", key=f"g_rev_{ticker}")
        x.g_mid = g2.number_input("Medium-term revenue growth target p.a. (%)", value=guide.get("revenue_growth_mid"),
                                  step=0.5, format="%.1f", placeholder="e.g. 10.0", key=f"g_mid_{ticker}")
        x.g_margin = g3.number_input("Company margin target (%)", value=guide.get("margin_target"), step=0.5,
                                     format="%.1f", placeholder="e.g. 35.0", key=f"g_margin_{ticker}")
        g4, g5 = st.columns([1, 2])
        x.g_date = g4.text_input("As of", value=guide.get("date", ""), placeholder="e.g. Q2 report July 2026",
                                 key=f"g_date_{ticker}")
        x.g_note = g5.text_input("Source / note", value=guide.get("note", ""), placeholder="link or keywords",
                                 key=f"g_note_{ticker}")

    rev = a["revenue"].dropna() if "revenue" in a else pd.Series(dtype=float)
    eps_hist = a["eps"].dropna() if "eps" in a else pd.Series(dtype=float)

    def years(s_: pd.Series) -> float:
        return (s_.index[-1] - s_.index[0]).days / 365.25 if len(s_) >= 2 else 0

    x.hist_rev = _cagr(rev.iloc[0], rev.iloc[-1], years(rev)) if len(rev) >= 2 else np.nan
    hist_eps = _cagr(eps_hist.iloc[0], eps_hist.iloc[-1], years(eps_hist)) if len(eps_hist) >= 2 else np.nan
    ana_rev = rev1.get("growth") if rev1.get("growth") is not None else rev0.get("growth")
    ana_eps = (est1["avg"] / est0["avg"] - 1) if est0.get("avg") and est1.get("avg") and est0["avg"] > 0 else np.nan
    company_rev = x.g_mid if x.g_mid is not None else x.g_rev
    x.company_rev = company_rev / 100 if company_rev is not None else (auto_growth if np.isfinite(auto_growth) else np.nan)
    # EPS usually grows a bit faster than revenue (operating leverage, buybacks): +2 pp on revenue-based views.
    # If the analysts' EPS growth deviates strongly from their revenue growth, one-offs (e.g. investment gains)
    # distort the EPS base year – then the revenue view is the better anchor.
    x.ana_rev = float(ana_rev) if ana_rev is not None else np.nan
    eps_distorted = np.isfinite(ana_eps) and np.isfinite(x.ana_rev) and abs(ana_eps - x.ana_rev) > 0.15
    views = [g for g in [min(hist_eps, 0.30) if np.isfinite(hist_eps) else np.nan,
                         np.nan if eps_distorted else ana_eps,
                         x.ana_rev + 0.02 if np.isfinite(x.ana_rev) else np.nan,
                         x.company_rev + 0.02 if np.isfinite(x.company_rev) else np.nan] if np.isfinite(g)]
    suggested = float(np.clip(0.6 * np.median(views) + 0.4 * LONG_RUN, -0.05, 0.20)) if views else LONG_RUN
    hist_col = f"History {rev.index[0].year if len(rev) else ''}–{rev.index[-1].year if len(rev) else ''}"

    x.growth_rows = [(f"Revenue, {hist_col.lower()}", pct(x.hist_rev)), ("Revenue, analysts next FY", pct(x.ana_rev)),
                     ("Revenue, company guidance", pct(x.company_rev)), ("EPS, analysts next FY", pct(ana_eps)),
                     ("EPS, suggestion for 5 years", pct(suggested))]
    st.subheader("Who expects what?")
    c.table(pd.DataFrame({
        "Growth p.a.": ["Revenue", "Earnings per share"],
        hist_col: [x.hist_rev, hist_eps],
        "Analysts (next FY)": [x.ana_rev, ana_eps],
        "Company (guidance)": [x.company_rev, np.nan],
        "Suggestion for 5 years": [np.nan, suggested],
    }), {col: "spct" for col in [hist_col, "Analysts (next FY)", "Company (guidance)", "Suggestion for 5 years"]})
    st.caption(f"Suggestion = 60% median of the available forecasts + 40% long-run normal ({pct(LONG_RUN, 0, False)}), "
               "because high growth rarely lasts five years. Revenue-based views get +2 pp for operating leverage and "
               "buybacks.")
    if eps_distorted:
        c.callout(f"The analysts' expected EPS growth ({pct(ana_eps)}) deviates strongly from revenue growth "
                  f"({pct(x.ana_rev)}) – probably one-offs in the base year (e.g. investment gains, write-downs). The "
                  "suggestion therefore relies on revenue growth. Also check whether today's EPS contains one-time "
                  "gains.", "warn")

    st.subheader("Your assumption: EPS growth per year")
    x.saved_val = saved = saved_scenario(inputs)
    col = "EPS growth % p.a."
    w1, w2, w3, w4 = st.columns(4)
    x.g_bear = w1.number_input("Bear (%)", -30.0, 60.0, saved("Bear", col, round(max(suggested - 0.06, -0.10) * 100, 1)),
                               0.5, key=f"gb_{ticker}", help="What if things go badly?")
    x.g_base = w2.number_input("Base (%)", -30.0, 60.0, saved("Base", col, round(suggested * 100, 1)),
                               0.5, key=f"gm_{ticker}", help="Your realistic scenario.")
    x.g_bull = w3.number_input("Bull (%)", -30.0, 60.0, saved("Bull", col, round((suggested + 0.05) * 100, 1)),
                               0.5, key=f"gu_{ticker}", help="What if everything works out?")
    x.eps0 = w4.number_input(f"EPS today ({cur})", value=float(inputs.get("eps0", f.eps_ttm or est0.get("avg") or 1.0)),
                             step=0.1, format="%.2f", key=f"eps_{ticker}", help="Earnings per share over the last 12 months.")
    consensus_vals = [e for e in (est0.get("avg"), est1.get("avg")) if e]
    consensus_12m = float(np.mean(consensus_vals)) if consensus_vals else None
    u1, u2, u3 = st.columns([1, 1, 2])
    x.use_consensus = u1.toggle("Year 1 from analyst consensus",
                                value=bool(inputs.get("use_consensus", consensus_12m is not None)),
                                key=f"uc_{ticker}", disabled=consensus_vals == [],
                                help="The first year is the most predictable – the consensus is usually more accurate "
                                     "there. Your growth rates then apply from year 2.")
    x.eps1 = u2.number_input(f"EPS in 12 months ({cur})", value=float(inputs.get("eps1") or consensus_12m or x.eps0),
                             step=0.1, format="%.2f", key=f"eps1_{ticker}") if x.use_consensus else None
    with u3.expander("Scenario probabilities"):
        pcols = st.columns(3)
        col = "Probability %"
        x.p_bear = pcols[0].number_input("Bear %", 0, 100, int(saved("Bear", col, 25)), 5, key=f"pb_{ticker}")
        x.p_base = pcols[1].number_input("Base %", 0, 100, int(saved("Base", col, 50)), 5, key=f"pm_{ticker}")
        x.p_bull = pcols[2].number_input("Bull %", 0, 100, int(saved("Bull", col, 25)), 5, key=f"pu_{ticker}")
