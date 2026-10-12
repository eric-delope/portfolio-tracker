"""Monthly report: the once-a-month check-in – what happened, what changed, what to do."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import eur, pct, plot
from portfolio_tracker import decisions, taxes
from portfolio_tracker import metrics as m
from portfolio_tracker.fmt import num
from portfolio_tracker.market import BENCHMARKS
from portfolio_tracker.report import MONTHS, action_items, available_months, build_report, merge_notes, to_markdown
from portfolio_tracker.watchlist import alert_status

PRIVACY = c.privacy()
label, tx, p = c.load()
months = available_months(p)

head, f1, f2 = st.columns([2.6, 1.15, 1], vertical_alignment="bottom")
with head:
    c.page_header("Monthly report", "Where the next euro goes, what needs doing, and how the month went.")
# Default: the last complete month during the first days of a new month, else the running month.
default = months[1] if len(months) > 1 and date.today().day <= 10 else months[0]
month = f1.selectbox("Month", months, index=months.index(default),
                     format_func=lambda mo: (f"{MONTHS[mo.month - 1]} {mo.year} (to date)" if mo == months[0]
                                            else f"{MONTHS[mo.month - 1]} {mo.year}"))
bench = f2.selectbox("Benchmark", list(BENCHMARKS), key="month_bench")

rep = build_report(p, month, bench)
f = rep.flows

# ----------------------------------------------------------------- inputs for to-dos
wl = c.watchlist()
wl_tickers = tuple(sorted(e.ticker for e in wl))
ranking, wl_prices, context = c.watchlist_ranking(p, wl) if len(wl) else (pd.DataFrame(), {}, {})
states = alert_status(wl, wl_prices) if len(wl) else None
thesis_status = {tk: (ctx.get("thesis"), ctx.get("thesis_detail", "")) for tk, ctx in context.items()}
hold_tickers = tuple(sorted(tk for i, tk in p.tickers.items() if tk and i in p.positions.index
                            and p.meta.loc[i, "asset_class"] == "STOCK"))
earnings = c.earnings_dates(tuple(sorted(set(hold_tickers) | set(wl_tickers))))
names = {tk: p.meta.loc[i, "name"] for i, tk in p.tickers.items() if tk} | {e.ticker: e.name for e in wl}
valuations = {e.ticker: {"name": e.name, "age_days": e.valuation_age_days(), "valuation_date": e.valuation_date} for e in wl}
p_eur = c.portfolio_eur()   # taxes are assessed in euros
est = taxes.yearly_tax_estimate(p_eur.tx, p_eur.realized, allowance=c.settings()["allowance"])
year = date.today().year
allowance_left = (c.settings()["allowance"] - est.loc[year, "allowance_used"]) if year in est.index else None
cash = p.cash_balance.iloc[-1]
rep.actions = action_items(p, rep, cash, allowance_left, states, valuations, earnings, names,
                           watchlist=wl, prices=wl_prices, thesis_status=thesis_status)
rep.opportunities = ranking

# ----------------------------------------------------------------- key figures
since_start = p.period_summary(p.period_start("all"), bench)
annual = since_start["annualize"]
bench_since_start = (m.annualized_return(p.benchmark_returns[bench].loc[p.index[0]:]) if annual
                     else since_start["benchmark_twr"])
ytd_edge = rep.ytd_twr - rep.ytd_benchmark_twr
c.stats([
    c.stat("Portfolio value", eur(rep.value_end), f"{eur(rep.value_end - rep.value_start, sign=True)} this month",
           c.tone(rep.value_end - rep.value_start)),
    c.stat(f"{MONTHS[month.month - 1]}", pct(rep.twr), f"{bench} {pct(rep.benchmark_twr)}", c.tone(rep.twr - rep.benchmark_twr)),
    c.stat("Year to date", pct(rep.ytd_twr), f"{num(ytd_edge * 100, 1, True)} pp vs. {bench}", c.tone(ytd_edge)),
    c.stat("Since start p.a." if annual else "Since start",
           pct(since_start["twr_annualized"]) if annual else pct(since_start["twr"]), f"{bench} {pct(bench_since_start)}",
           help="Time-weighted return since the first buy – more meaningful for long-term investors than single months."),
    c.stat("Dividends & interest", eur(f["dividends"] + f["interest"], 2),
           f"{f['orders']} orders · {eur(f['net_invested'], sign=True)} invested"),
])

# ----------------------------------------------------------------- entry opportunities
st.subheader("Where the next euro goes")
if ranking.empty:
    c.callout("No valued companies yet. Set a fair value and an entry plan in **Company research** – the ranking then "
              "appears here every month.", "info")
else:
    buys = ranking[ranking["verdict"].str.startswith("Buy")]
    if len(buys):
        top = buys.iloc[0]
        c.callout(f"**{top['name']}** offers the best entry: an expected **{pct(top['expected_return'])} p.a.** at today's "
                  f"price, {pct(top['margin_of_safety'], 0, False)} below your fair value.", "good")
    elif (ranking["verdict"] == "Savings plan").any():
        names_ = ", ".join(ranking.loc[ranking["verdict"] == "Savings plan", "name"].head(3))
        c.callout(f"No buy zone reached. Attractive via savings plan only: **{names_}**.", "info")
    else:
        c.callout("No valued company meets your return target right now – patience is a decision too.", "info")
    c.table(pd.DataFrame({
        "Company": ranking["name"], "Verdict": ranking["verdict"].map(c.verdict_pill),
        "Expected return": ranking["expected_return"], "Below fair value": ranking["margin_of_safety"],
        "Thesis": ranking["thesis"].map(c.thesis_pill), "In portfolio": ranking["weight"].replace(0, np.nan),
    }).head(5), {"Verdict": "html", "Expected return": "spct", "Below fair value": "spct", "Thesis": "html",
                 "In portfolio": "pct:1"})

# ----------------------------------------------------------------- what happened / to-dos
pos = rep.positions
notes = [f"The portfolio returned **{pct(rep.twr)}**, the {bench} **{pct(rep.benchmark_twr)}**."]
if len(pos):
    top, flop = pos.iloc[0], pos.iloc[-1]
    if top["contribution"] > 0:
        notes.append(f"Top contributor: **{top['name']}** ({pct(top['price_return'])}).")
    if flop["contribution"] < 0:
        notes.append(f"Biggest drag: **{flop['name']}** ({pct(flop['price_return'])}).")
if f["orders"]:
    notes.append(f"{f['orders']} orders, {eur(f['bought'])} bought, {eur(f['sold'])} sold." if f["sold"]
                 else f"{f['orders']} orders, {eur(f['bought'])} bought.")
sc = decisions.scorecard(p, bench)
summ = decisions.summarize(sc, "12M")
if not summ.empty and "Buy" in summ.index:
    notes.append(f"Your buys beat the market by **{num(summ.loc['Buy', 'edge_weighted'] * 100, 1, True)} pp** "
                 "12 months later (amount-weighted).")

left, right = st.columns(2, gap="medium")
with left:
    st.subheader("What happened")
    with c.card():
        c.facts(notes)
        r = p.daily["return"]
        r = r[(r.index > rep.base) & (r.index <= rep.end)] if rep.base is not None else r[r.index <= rep.end]
        if len(r) > 1:
            plot(ch.performance_lines({"Portfolio": m.cumulative(r) - 1,
                                       bench: m.cumulative(p.benchmark_returns[bench].reindex(r.index)) - 1}, 230),
                 boxed=False)
with right:
    st.subheader("To-dos")
    main = [a_ for a_ in rep.actions if a_[0] in ("high", "medium")][:4]
    rest = [a_ for a_ in rep.actions if a_ not in main]
    with c.card():
        c.todos(main or [("good", "Nothing open – everything is on plan.")])
    if rest:
        with st.expander(f"{len(rest)} more notes"):
            c.todos(rest)

# ----------------------------------------------------------------- positions and trades
st.subheader("Positions this month")
view = pd.DataFrame({
    "Position": pos["name"], "Weight": pos["weight_end"], "Price": pos["price_return"],
    "Contribution": pos["contribution"], "Value": pos["value_end"],
})
if PRIVACY:
    view = view.drop(columns=["Contribution", "Value"])
c.table(view, {"Weight": "bar", "Price": "spct", "Contribution": "seur:0", "Value": "eur0"})

left, right = st.columns([3, 2], gap="medium")
with left:
    st.subheader("Trades")
    if rep.trades.empty:
        st.caption("No trades this month.")
    else:
        t = rep.trades
        tv = pd.DataFrame({
            "Position": t["name"], "Date": t["date"],
            "Type": np.where(t["event"] == "sell", "Sell", np.where(t["savings_plan"], "Savings plan", "Buy")),
            "Amount": t["amount"].abs(),
        })
        if PRIVACY:
            tv = tv.drop(columns=["Amount"])
        c.table(tv, {"Date": "date", "Amount": "eur:2"}, compact=True, max_height=380)
with right:
    st.subheader("Coming up")
    upcoming = sorted([(d, tk) for tk, d in earnings.items() if 0 <= (d - date.today()).days <= 31])
    rep.events = [(d, f"Earnings {names.get(tk, tk)}") for d, tk in upcoming]
    with c.card():
        lines = [f"**{d:%d %b}** · {names.get(tk, tk)} reports" + (" · watchlist" if tk not in hold_tickers else "")
                 for d, tk in upcoming]
        if states is not None and not states.empty:
            lines.append(f"**{(states['state'] == 'hit').sum()}** of {len(states)} price alerts in the buy zone, "
                         f"{(states['state'] == 'near').sum()} almost reached")
        c.facts(lines or ["No earnings dates in the next 31 days."])

# ----------------------------------------------------------------- journal
st.divider()
note_path = c.REPORT_DIR / f"{month} Monthly report.md"
b1, b2 = st.columns([1, 3], vertical_alignment="center")
if b1.button("Save as Markdown note", icon=":material/edit_note:"):
    c.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    old = note_path.read_text(encoding="utf-8") if note_path.exists() else None
    note_path.write_text(merge_notes(to_markdown(rep), old), encoding="utf-8")
    st.toast(f"Saved: {note_path.name}")
b2.caption(f"Saves `reports/{note_path.name}` – an investment journal that also works in Obsidian. Already exists: "
           "figures are updated, your own notes are kept." if note_path.exists() else
           f"Saves `reports/{note_path.name}` – an investment journal that also works in Obsidian.")
with st.expander("How to use the monthly report"):
    st.markdown(
        "1. Export your transactions (CSV) in the Trade Republic app and put the file into `data/raw/`.\n"
        "2. Start at the top: where should new money go, and what needs doing?\n"
        "3. Save the month as a note – over time this becomes your investment journal.\n"
        "4. Under **Watchlist & entries**, roll alerts forward and refresh stale valuations."
    )
