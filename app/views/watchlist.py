"""Watchlist & entries: ranking of entry opportunities, alerts and signals for every watched company."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import money, pct, plot
from portfolio_tracker.watchlist import SIGNAL_LABELS, Alert, alert_status, mark_triggered, signal
from sections import backtest
from widgets import order_check

STATE_LABEL = {"hit": "Buy zone reached", "near": "Less than 5% away", "waiting": "Waiting", "no_price": "No price"}

c.page_header("Watchlist & entries", "Your valued companies, ranked by what they would return at today's price.")
wl = c.watchlist()
_, _, p = c.load()
if not len(wl):
    st.info("The watchlist is empty. Analyse a company under **Company research** and save it there – "
            "fair value, entry tranches and thesis KPIs then show up here.")
    backtest.render(p, wl)
    st.stop()

ranking, prices, context = c.watchlist_ranking(p, wl)
newly = mark_triggered(wl, prices)
if newly:
    wl.save()
status = alert_status(wl, prices)
hits = status[status["state"] == "hit"] if not status.empty else status
near = status[status["state"] == "near"] if not status.empty else status
rolls = {e.ticker: e.rolled_alerts(min_drift=0.01) for e in wl}
n_rolls = sum(len(r_) for r_ in rolls.values())

n_buy = int(ranking["verdict"].str.startswith("Buy").sum()) if not ranking.empty else 0
n_plan = int((ranking["verdict"] == "Savings plan").sum()) if not ranking.empty else 0
c.stats([
    c.stat("Companies valued", str(len(wl))),
    c.stat("Verdict “Buy”", str(n_buy), f"{n_plan} via savings plan",
           help="Expected return at least your target, a buy tranche reached and the thesis intact."),
    c.stat("Alerts reached", str(len(hits)), f"{len(near)} almost"),
    c.stat("Alerts to roll forward", str(n_rolls), "fair value has grown" if n_rolls else "all up to date",
           help="Fair value grows over time – entry prices should grow with it."),
])
alerts_hit = sorted(set(hits["name"])) if not hits.empty else []
broken = [wl.entries[tk].name for tk, ctx in context.items() if ctx.get("thesis") == "broken"]
if alerts_hit or broken:
    c.callout(" · ".join(([f"In the buy zone: **{', '.join(alerts_hit)}**"] if alerts_hit else [])
                         + ([f"Thesis broken: **{', '.join(broken)}**"] if broken else [])), "high")

# ---------------------------------------------------------------- ranking
st.subheader("Ranking")
earnings = {tk: ctx.get("earnings_date") for tk, ctx in context.items()}
if not ranking.empty:
    view = pd.DataFrame({
        "Company": ranking["name"], "Verdict": ranking["verdict"].map(c.verdict_pill),
        "Expected return": ranking["expected_return"], "Below fair value": ranking["margin_of_safety"],
        "Thesis": ranking["thesis"].map(c.thesis_pill), "In portfolio": ranking["weight"].replace(0, np.nan),
        "Next earnings": ranking["ticker"].map(earnings),
    })
    c.table(view, {"Verdict": "html", "Expected return": "spct", "Below fair value": "spct", "Thesis": "html",
                   "In portfolio": "pct:1", "Next earnings": "date"})
with st.expander("How the verdicts work"):
    st.markdown(
        "Expected total return p.a. at today's price, from your own valuation rolled forward to today.\n\n"
        "- **Buy** – return ≥ your target and a buy tranche reached\n"
        "- **Buy (small)** – as Buy, but low quality or the position is already large\n"
        "- **Savings plan** – return ≥ target, but no tranche reached yet or the P/E is in the expensive third of its "
        "own history\n"
        "- **Watch** – return below target\n"
        "- **Avoid** – return below the risk-free rate, or the thesis is broken"
    )

unvalued = [(isin, row) for isin, row in p.positions.iterrows()
            if row["asset_class"] == "STOCK" and p.tickers.get(isin) not in wl.entries]
if unvalued:
    st.caption("Holdings without a valuation – no add or sell signal until you value them:")
    cols = st.columns(min(len(unvalued), 5))
    for col, (isin, row) in zip(cols * 10, unvalued):
        if col.button(f"Value {row['name']}", key=f"value_{isin}", icon=":material/add:"):
            st.session_state["research_ticker"] = p.tickers[isin]
            st.switch_page("views/research.py")

# ---------------------------------------------------------------- roll forward
if n_rolls:
    st.subheader("Roll entry prices forward")
    st.caption("Fair value has grown since your valuation – the entry prices grow with it.")
    roll_rows = []
    for tk, items in rolls.items():
        e_ = wl.entries[tk]
        fx_ = c.eur_rate(e_.currency)
        for a_, new in items:
            roll_rows.append({"Company": e_.name, "Alert": a_.label, "Current": a_.price, "New": new,
                              "Change": new / a_.price - 1, "New ≈ EUR (TR app)": new / fx_,
                              "Currency": e_.currency})
    rr = pd.DataFrame(roll_rows)
    c.table(rr, {"Current": "num:2", "New": "num:2", "Change": "spct", "New ≈ EUR (TR app)": "eur:2"}, compact=True)
    if st.button("Apply all new prices", type="primary"):
        for items in rolls.values():
            for a_, new in items:
                a_.price = round(new, 4)
                a_.triggered_at = None
        wl.save()
        st.success("Applied – please update the price alerts in the Trade Republic app as well.")
        st.rerun()

# ---------------------------------------------------------------- detail view
st.subheader("Company detail")
order = list(ranking["ticker"]) + [e_.ticker for e_ in wl if e_.ticker not in set(ranking.get("ticker", []))]
pick = st.selectbox("Company", order, format_func=lambda t: wl.entries[t].name, label_visibility="collapsed")
e = wl.entries[pick]
price = prices.get(pick)
fx_eur = c.eur_rate(e.currency)
fair_now = e.fair_value_today()
holding = c.position_of(p, pick)
ctx = context.get(pick, {})
thesis_ok = None if ctx.get("thesis") in (None, "no KPIs") else ctx.get("thesis") == "intact"
code, why = signal(e, price, float(holding["weight"]) if holding is not None else None, thesis_ok=thesis_ok)

c.stats([
    c.stat("Price", money(price, e.currency), f"≈ {money(price / fx_eur, 'EUR')}" if price and e.currency != "EUR" else None),
    c.stat("Fair value today", money(fair_now, e.currency),
           f"price {pct(price / fair_now - 1)} vs. fair" if price and fair_now else None,
           c.tone(1 - price / fair_now) if price and fair_now else None,
           help=f"Valued at {money(e.fair_value, e.currency)} on {(e.valuation_date or '–')[:10]}, rolled forward since."),
    c.stat("Expected return", pct(e.expected_return(price)), f"target {pct(e.required_return, 0, False)} p.a."),
    c.stat(f"Expected price in {e.horizon_years}y", money(e.target_price, e.currency)),
])
c.callout(f"**{SIGNAL_LABELS[code]}** – {why.split(' – ', 1)[-1]}",
          {"buy": "good", "trim": "medium", "review": "high", "hold": "info", "none": "info"}[code])
hist = c.price_history(pick, "1y")
levels = [(a.label or f"Alert {i + 1}", a.price, bool(price and a.is_hit(price)))
          for i, a in enumerate(e.alerts) if a.active]
if len(hist):
    plot(ch.titled(ch.watch_chart(hist, e.currency, fair_now, levels), f"{e.name}: price, fair value and alerts",
                   f"one year · savings plan {c.eur(e.plan['monthly_eur'])}/month while below fair value"
                   if e.plan.get("monthly_eur") else "one year"))
if st.button("Open in company research", icon=":material/query_stats:"):
    st.session_state["research_ticker"] = pick
    st.switch_page("views/research.py")

st.subheader("Price alerts")
st.caption("Prices in trading currency – enter the EUR column 1:1 as a price alert in the Trade Republic app.")
alerts_df = pd.DataFrame([{
    "Active": a.active, "Label": a.label, "Direction": "falls below" if a.direction == "below" else "rises above",
    f"Price ({e.currency})": a.price, "≈ EUR": a.price / fx_eur, "Amount €": a.amount_eur,
    "Status": (("Trim zone reached" if a.direction == "above" else STATE_LABEL["hit"]) if price and a.is_hit(price) else None) or
              (STATE_LABEL["near"] if price and a.distance(price) <= 0.05 else STATE_LABEL["waiting"]),
    "Reached on": (a.triggered_at or "")[:10],
} for a in e.alerts]) if e.alerts else pd.DataFrame(columns=["Active", "Label", "Direction", f"Price ({e.currency})",
                                                              "≈ EUR", "Amount €", "Status", "Reached on"])
edited = st.data_editor(alerts_df, hide_index=True, num_rows="dynamic", key=f"alerts_{pick}",
                        disabled=["≈ EUR", "Status", "Reached on"], column_config={
    "Direction": st.column_config.SelectboxColumn(options=["falls below", "rises above"], required=True),
    f"Price ({e.currency})": st.column_config.NumberColumn(format="%.2f", min_value=0.0, required=True),
    "≈ EUR": st.column_config.NumberColumn(format="€%.2f"),
    "Amount €": st.column_config.NumberColumn(format="€%.0f"),
})
with st.expander("Investment thesis"):
    thesis = st.text_area("Investment thesis", value=e.thesis, height=110, key=f"wl_thesis_{pick}",
                          label_visibility="collapsed")

b1, b2, b3, _ = st.columns([1.3, 1.3, 1.3, 3])
if b1.button("Save changes", type="primary"):
    old = {(a.price, a.direction): a for a in e.alerts}
    new_alerts = []
    for _, r in edited.dropna(subset=[f"Price ({e.currency})"]).iterrows():
        direction = "below" if r["Direction"] == "falls below" else "above"
        price_level = float(r[f"Price ({e.currency})"])
        prev_alert = old.get((price_level, direction))
        new_alerts.append(Alert(
            price=price_level, label=str(r["Label"] or ""), direction=direction,
            amount_eur=None if pd.isna(r["Amount €"]) else float(r["Amount €"]), active=bool(r["Active"]),
            triggered_at=prev_alert.triggered_at if prev_alert else None,
            # unchanged levels keep their link to fair value; edited ones are re-linked to today's fair value
            rel_to_fair=prev_alert.rel_to_fair if prev_alert else (price_level / (e.fair_value_today() or price_level) - 1),
        ))
    e.alerts, e.thesis = new_alerts, thesis
    wl.save()
    st.success("Saved.")
    st.rerun()
if b2.button("Reset alerts", help="Clears 'reached' so notifications fire again."):
    for a in e.alerts:
        a.triggered_at = None
    wl.save()
    st.rerun()
confirm = b3.checkbox("Confirm removal")
if confirm and b3.button("Remove from watchlist"):
    wl.remove(pick)
    wl.save()
    st.rerun()

if e.history:
    with st.expander("Valuation history: price vs. your fair value"):
        plot(ch.valuation_history(c.price_history(pick, "2y"), e.history, e.currency))
with st.expander("Order check: what would a buy change in my portfolio?"):
    nxt_amount = next((a.amount_eur for a in e.alerts if a.active and a.direction == "below" and a.amount_eur), 500.0)
    order_check(p, pick, e.name, nxt_amount, key=f"wl_{pick}")

backtest.render(p, wl)
