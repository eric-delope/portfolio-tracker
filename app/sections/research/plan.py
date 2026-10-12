"""Step 8 – plan: savings-plan share, limit tranches with hit probabilities, sell line, thesis KPIs, save."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import streamlit as st
from i18n import tr

import common as c
from common import eur, money, pct
from portfolio_tracker import thesis as th
from portfolio_tracker import valuation as v
from portfolio_tracker.memo import Memo, build_pdf
from portfolio_tracker.watchlist import Alert, Entry
from widgets import order_check


def render(x) -> None:
    f, cur, ticker, inputs, fair, req, fx_eur = x.f, x.cur, x.ticker, x.inputs, x.fair, x.req, x.fx_eur
    rf = c.settings()["rf"]
    c.lead("**How do you build the position?** A savings-plan part runs while the price is below fair value; limit "
           "tranches catch pullbacks, the first one at your maximum price.")
    l1, l2, l3 = st.columns(3)
    budget = l1.number_input("Planned total position size (€)", 0.0, 1e7, float(inputs.get("budget", 1500.0)), 100.0,
                             key=f"budget_{ticker}")
    plan_in = inputs.get("plan") or {}
    plan_share = l2.slider("Share via savings plan (%)", 0, 100,
                           int(plan_in.get("share", 30 if np.isfinite(x.exp_now) and x.exp_now >= req else 0)), 10,
                           key=f"plan_share_{ticker}", help="Savings plans are free of charge at Trade Republic.")
    plan_months = l3.slider("Savings plan duration (months)", 2, 24, int(plan_in.get("months", 6)),
                            key=f"plan_months_{ticker}")
    plan_budget = budget * plan_share / 100
    monthly = plan_budget / plan_months if plan_months else 0.0
    limit_budget = budget - plan_budget
    mos_pct = round(x.mos * 100, 1)
    ladder_default = pd.DataFrame(inputs.get("ladder") or {"Margin of safety %": [mos_pct, mos_pct + 10, mos_pct + 20],
                                                            "Share %": [30.0, 30.0, 40.0]})
    st.subheader(f"Limit tranches · {eur(limit_budget)}")
    with st.expander("Adjust tranches (margin of safety and share of the budget)"):
        ladder_in = st.data_editor(ladder_default, hide_index=True, num_rows="dynamic", key=f"ladder_{ticker}",
                                   column_config={
            "Margin of safety %": st.column_config.NumberColumn(min_value=-20, max_value=80, step=2.5, format="%.1f%%",
                                                                help="Distance of the buy price below fair value"),
            "Share %": st.column_config.NumberColumn(min_value=0, max_value=100, step=5, format="%.0f%%"),
        }).dropna()
    ladder = v.entry_ladder(fair, list(ladder_in["Margin of safety %"] / 100), list(ladder_in["Share %"]), limit_budget,
                            req, x.horizon, fx_to_eur=fx_eur, dividends=x.dividends, pv_dividends=x.pv_divs)
    ladder["probability"] = [v.hit_probability(f.prices, max(1 - pr / f.price, 0.0)) for pr in ladder["price"]]
    ladder["with_waiting"] = ladder["probability"] * ladder["expected_return"] + (1 - ladder["probability"]) * rf
    show = pd.DataFrame({
        "Tranche": ["Today (savings plan rate)" if plan_budget else "Buy today"] + list(ladder["tranche"]),
        "Below fair value": [(1 - f.price / fair)] + list(ladder["margin_of_safety"]),
        f"Price ({cur})": [f.price] + list(ladder["price"]),
        "≈ EUR (alert)": [f.price / fx_eur] + list(ladder["price_eur"]),
        "Amount": [monthly] + list(ladder["amount_eur"]),
        "Expected return": [x.exp_now] + list(ladder["expected_return"]),
        "Chance within 12M": [np.nan] + list(ladder["probability"]),
    })
    if cur == "EUR":
        show = show.drop(columns=["≈ EUR (alert)"])
    if c.privacy():
        show = show.drop(columns=["Amount"])
    c.table(show, {"Below fair value": "spct", f"Price ({cur})": "num:2", "≈ EUR (alert)": "eur:2", "Amount": "eur:2",
                   "Expected return": "spct", "Chance within 12M": "pct:0"})
    st.caption("Chance within 12M: how often, over the last 10 years, the stock fell at least this far within a year.")

    sell_on = st.toggle("Set a sell line (review a sale when the expected return gets too small)",
                        value=bool(inputs.get("sell_floor")), key=f"sell_on_{ticker}")
    sell_price, floor = None, None
    if sell_on:
        s1, s2 = st.columns([1, 2])
        floor = s1.number_input("Expected return threshold (% p.a.)", 0.0, 10.0,
                                float(inputs.get("sell_floor") or 0.04) * 100, 0.5, key=f"floor_{ticker}") / 100
        sell_price = v.price_for_return(v.remaining_flows(x.target, x.horizon, 0.0, x.dividends), floor)
        with s2:
            c.stats([c.stat("Sell line", money(sell_price, cur),
                            f"≈ {money(sell_price / fx_eur, 'EUR')} · {pct(sell_price / f.price - 1)} vs. today")])

    st.subheader("Investment thesis")
    prompt = "Why this company? What has to happen – and what would disprove the thesis?"
    thesis = st.text_area(prompt, value=x.saved.thesis if x.saved else "", height=100, key=f"thesis_{ticker}",
                          label_visibility="collapsed", placeholder=prompt)
    kpi_src = x.saved.thesis_kpis if x.saved and x.saved.thesis_kpis else th.suggest(f)
    kpi_df = pd.DataFrame([{"Metric": k_["metric"], "Condition": k_["operator"],
                            "Threshold": k_["threshold"] * 100 if th.METRICS[k_["metric"]][1] == "%" else k_["threshold"]}
                           for k_ in kpi_src if k_["metric"] in th.METRICS]) if kpi_src else pd.DataFrame(
        columns=["Metric", "Condition", "Threshold"])
    st.caption("Thesis KPIs – checked automatically after every earnings report (percentages in %, leverage as a factor):")
    kpi_df = st.data_editor(kpi_df, hide_index=True, num_rows="dynamic", key=f"kpis_{ticker}", column_config={
        "Metric": st.column_config.SelectboxColumn(options=list(th.METRICS), required=True),
        "Condition": st.column_config.SelectboxColumn(options=[">=", "<="], required=True),
        "Threshold": st.column_config.NumberColumn(format="%.1f", required=True),
    }).dropna()
    kpis = [{"metric": r_["Metric"], "operator": r_["Condition"],
             "threshold": float(r_["Threshold"]) / 100 if th.METRICS[r_["Metric"]][1] == "%" else float(r_["Threshold"])}
            for _, r_ in kpi_df.iterrows()]
    results = th.evaluate(kpis, f)
    if results:
        st.caption(tr("Currently: ") + " · ".join(f"{'✅' if r_.ok else ('❌' if r_.ok is False else '–')} {tr(r_.metric)} "
                                              f"{c._fmt_kpi(r_.value, r_.unit)}" for r_ in results))

    with st.expander("Order check: what would a buy change in my portfolio?"):
        first_tranche = float(ladder["amount_eur"].iloc[0]) if len(ladder) and ladder["amount_eur"].iloc[0] else 500.0
        order_check(x.p, ticker, f.name, first_tranche, key=ticker)

    b1, b2, _ = st.columns([1.1, 1.3, 2])
    with b2:
        _memo_download(x, thesis, ladder, results)
    if b1.button("Save to watchlist (update)" if x.saved else "Save to watchlist", type="primary",
                 icon=":material/bookmark_add:"):
        buy_alerts = [Alert(price=round(float(row["price"]), 4),
                            label=f"{row['tranche']} (−{row['margin_of_safety'] * 100:.0f}%)",
                            amount_eur=round(float(row["amount_eur"]), 2),
                            rel_to_fair=round(float(row["price"]) / fair - 1, 6)) for _, row in ladder.iterrows()]
        sell_alerts = [Alert(price=round(sell_price, 4), direction="above",
                             label=f"Sell line (exp. < {floor * 100:.0f}% p.a.)",
                             rel_to_fair=round(sell_price / fair - 1, 6))] if sell_price else []
        base = x.scenarios[1]
        entry = Entry(
            ticker=ticker, name=f.name, currency=cur, thesis=thesis, fair_value=round(fair, 4),
            target_price=round(x.target, 4), horizon_years=x.horizon, required_return=req,
            valuation_date=date.today().isoformat(), thesis_kpis=kpis,
            plan={"monthly_eur": round(monthly, 2), "months": plan_months, "start": date.today().isoformat()}
            if plan_budget else {},
            valuation_inputs={
                "horizon": x.horizon, "required_return": req, "mos": x.mos, "eps0": x.eps0, "eps1": x.eps1,
                "use_consensus": x.use_consensus, "dividend0": x.div0, "eps_weight": x.eps_weight,
                "scenarios": x.scen_df.to_dict(orient="list"), "fcf0": x.fcf0, "dcf_growth": x.dcf_g,
                "terminal_growth": x.tg, "budget": budget, "plan": {"share": plan_share, "months": plan_months},
                "ladder": ladder_in.to_dict(orient="list"), "sell_floor": floor if sell_price else None,
                "quality_answers": {"moat": x.moat, "predictability": x.predict, "management": x.mgmt},
                "guidance": {"revenue_growth": x.g_rev, "revenue_growth_mid": x.g_mid, "margin_target": x.g_margin,
                             "date": x.g_date, "note": x.g_note},
                "eps_fair": x.eps_fair, "dcf_fair": x.dcf_fair, "price_at_valuation": f.price, "max_price": x.max_price,
                "rdcf": {k_: v_ for k_, v_ in x.rdcf_result.items()
                         if k_ in ("sbc", "hurdle", "life", "mature", "basis", "s2c", "tax") and v_ is not None},
                "rdcf_implied_growth": x.rdcf_result.get("implied_growth"),
                "base_growth": base.eps_growth, "base_pe": base.exit_pe, "dividends": x.dividends,
            },
            alerts=buy_alerts + sell_alerts,
        )
        x.wl.upsert(entry)
        x.wl.save()
        c.company_context.clear()
        st.success(f"{f.name} saved: fair value {money(fair, cur)}, maximum price {money(x.max_price, cur)}, "
                   f"{len(buy_alerts)} entry alerts" + (f", sell line {money(sell_price, cur)}" if sell_price else "")
                   + (f", savings plan {eur(monthly)}/month" if plan_budget else "") + ".")


def _memo_download(x, thesis: str, ladder: pd.DataFrame, results: list) -> None:
    """One-page PDF of this valuation – the format an analyst would hand to a portfolio manager."""
    f, cur, r = x.f, x.cur, x.rdcf_result
    memo = Memo(
        name=f.name, ticker=x.ticker, currency=cur, price=f.price, fair_value=x.fair, max_price=x.max_price,
        expected_return=x.exp_now, required_return=x.req, margin_of_safety=x.mos, horizon=x.horizon,
        verdict=x.verdict_text, thesis=thesis,
        quality=[(q.name, q.value, "passed" if q.passed else ("failed" if q.passed is False else "–"))
                 for q in x.quality_checks],
        quality_verdict=x.rec["label"], growth=x.growth_rows, scenarios=x.scen_df, bridge=x.bridge_rows,
        reverse_dcf=[(label, value) for label, value in [
            ("Priced-in revenue growth (years 1–5)", pct(r.get("implied_growth")) if r else "–"),
            ("Return, draconian case (no growth)", pct(r.get("draconian")) if r else "–"),
            ("Return, conservative case", pct(r.get("conservative")) if r else "–"),
            ("Hurdle rate", pct(r.get("hurdle"), 1, False) if r else "–")]] if r else [],
        tranches=[(t["tranche"] + f" (−{t['margin_of_safety'] * 100:.0f}%)", f"{t['price']:,.2f} {cur}",
                   c.eur(t["amount_eur"]), pct(t["expected_return"])) for _, t in ladder.iterrows()],
        tranche_levels=[float(p_) for p_ in ladder["price"]],
        kpis=[f"{k.metric} {k.operator} {c._fmt_kpi(k.threshold, k.unit)}" for k in results],
        guidance=x.latest.sentences[0] if x.latest and x.latest.sentences else "",
        prices=f.prices[f.prices.index >= f.prices.index.max() - pd.DateOffset(years=2)],
    )
    try:
        pdf = build_pdf(memo)
    except Exception as exc:  # a broken memo must never block saving the valuation
        st.caption(f"Investment memo unavailable: {exc}")
        return
    st.download_button("Download investment memo (PDF)", pdf, f"{x.ticker} investment memo {date.today()}.pdf",
                       "application/pdf", icon=":material/description:")
