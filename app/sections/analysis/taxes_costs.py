"""Taxes & costs: German capital gains tax estimate, latent tax, money flows and cost check."""

from __future__ import annotations

import numpy as np
import streamlit as st

import charts as ch
import common as c
from common import eur, num, pct, plot
from portfolio_tracker import taxes
from portfolio_tracker.importer import summary, trades


def render(x) -> None:
    _taxes(x)
    _cashflows(x)


def _taxes(x) -> None:
    # taxes are assessed in euros, whatever the reporting currency
    p, allowance, privacy = x.p_eur, x.allowance, x.privacy
    pos = p.positions

    def eur(v: float, decimals: int = 0, sign: bool = False) -> str:
        return c.eur(v, decimals, sign, ccy="EUR")
    est = taxes.yearly_tax_estimate(p.tx, p.realized, allowance=allowance)
    year = p.last_date.year
    cur = est.loc[year] if year in est.index else None
    lt = taxes.latent_tax(p.open_lots, p.current_prices) if not pos.empty else None
    remaining = max(allowance - (cur["allowance_used"] if cur is not None else 0), 0)
    items = []
    if cur is not None:
        items += [
            c.stat(f"Taxable gains {year}", eur(cur["taxable_before_allowance"]),
                   f"stocks {eur(cur['stock_gains'], sign=True)} / {eur(cur['stock_losses'], sign=True)}"),
            c.stat("Estimated tax", eur(cur["estimated_tax"], 2), f"withheld {eur(cur['withheld_tax'], 2)}",
                   help="Withheld according to the export, incl. withholding tax on dividends, net of refunds."),
            c.stat("Allowance left", eur(remaining), f"of {eur(allowance)}"),
        ]
    if lt is not None:
        net_tax = max(max(lt["taxable"].sum(), 0) - remaining, 0) * taxes.TAX_RATE
        items.append(c.stat("Tax if sold today", eur(net_tax), f"value after tax {eur(pos['value'].sum() - net_tax)}"))
    st.caption("Simplified German rules: 25% flat tax + solidarity surcharge, separate loss pot for stocks, 30% partial "
               "exemption for equity ETFs. Always in euros. Not tax advice.")
    if items:
        c.stats(items)

    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.subheader("Year by year")
        if privacy:
            st.caption("Hidden in privacy mode.")
        else:
            ev = est.rename(columns={
                "stock_gains": "Stock gains", "stock_losses": "Stock losses", "fund_gains_taxable": "ETF gains (70%)",
                "dividends": "Dividends", "interest": "Interest", "taxable_before_allowance": "Taxable",
                "estimated_tax": "Tax (estimate)", "withheld_tax": "Withheld",
            })[["Stock gains", "Stock losses", "ETF gains (70%)", "Dividends", "Interest", "Taxable", "Tax (estimate)",
                "Withheld"]].T
            ev.columns = [str(col) for col in ev.columns]
            c.table(ev.reset_index().rename(columns={"index": " "}), {col: "euro0" for col in ev.columns}, compact=True)
    with right:
        st.subheader("Ideas")
        lines = []
        if remaining > 0:
            lines.append(f"**{eur(remaining)}** allowance left: realise gains of that size tax-free and buy back – "
                         "this raises your cost basis (tax-gain harvesting).")
        if lt is not None:
            for _, row in lt[lt["unrealized"] < 0].sort_values("unrealized").head(3).iterrows():
                lines.append(f"**{row['name']}**: {eur(row['unrealized'], sign=True)} paper loss could offset gains "
                             f"(up to {eur(-row['taxable'] * taxes.TAX_RATE)} tax).")
        with c.card():
            c.facts(lines or ["Nothing to optimise right now."])


def _cashflows(x) -> None:
    p, ps, costs, start, privacy = x.p, x.ps, x.costs, x.start, x.privacy
    st.subheader("Cash flows & costs")
    s = summary(p.tx)   # flows in the reporting currency, converted at each day's rate
    mc = p.monthly_cashflows
    avg_order = trades(p.tx)["amount"].abs().mean()
    avg_order_eur = trades(x.p_eur.tx)["amount"].abs().mean()   # the €1 fee is charged in euros
    c.stats([
        c.stat("Deposited", eur(s["deposits"]), f"withdrawn {eur(abs(s['withdrawals']))}"),
        c.stat("Interest & Saveback", eur(s["interest (net)"] + s["saveback"], 2)),
        c.stat("Order fees", eur(costs["fees"], 0), f"{pct(costs['fee_ratio'], 2, False)} of volume",
               help=f"{costs['orders']} orders, {costs['savings_plan_orders']} of them free savings-plan executions."),
        c.stat("Average order", eur(avg_order), f"€1 fee = {pct(1 / avg_order_eur, 2, False)}" if avg_order_eur else None),
        c.stat("Turnover", f"{num(costs['turnover'], 1)}×", "per year"),
    ])

    period_tx = p.tx[p.tx["date"] > start] if start > p.index[0] else p.tx
    net_by = period_tx.groupby("event")["net_cash"].sum()
    sources = {"Deposits": net_by.get("deposit", 0.0), "Sales": net_by.get("sell", 0.0),
               "Dividends": net_by.get("dividend", 0.0), "Interest": net_by.get("interest", 0.0),
               "Saveback": net_by.get("saveback", 0.0), "Tax refunds": net_by.get("tax_refund", 0.0)}
    uses = {"Portfolio (buys)": -net_by.get("buy", 0.0), "Card payments": -net_by.get("card", 0.0),
            "Withdrawals": -net_by.get("withdrawal", 0.0),
            "Other": -(net_by.get("account_fee", 0.0) + net_by.get("other", 0.0))}
    sources = {k_: v_ for k_, v_ in sources.items() if v_ > 0}
    uses = {k_: v_ for k_, v_ in uses.items() if v_ > 0}
    delta_cash = sum(sources.values()) - sum(uses.values())
    if delta_cash > 0:
        uses["Cash increase"] = delta_cash
    elif delta_cash < 0:
        sources["Cash drawdown"] = -delta_cash
    inv_share = ps["value"] / (ps["value"] + x.cash_now) if ps["value"] + x.cash_now else np.nan
    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.money_flow(sources, uses, privacy), "Where your money went",
                       f"period {x.period_label}: sources left, uses right"))
    with right:
        plot(ch.titled(ch.net_worth(p.daily["value"].loc[start:], p.cash_balance.loc[start:], privacy),
                       "Assets at Trade Republic", f"portfolio and cash · {pct(inv_share, 0, False)} invested today"))
    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.signed_monthly_bars({"Net invested": -(mc["Buys"] + mc["Sells"])}, privacy),
                       "Net invested per month", "buys minus sale proceeds"))
    with right:
        plot(ch.titled(ch.single_bars(-mc["Card payments"], "Card payments", ch.DEPOT, privacy), "Card spending per month",
                       f"Saveback earned in total: {eur(s['saveback'], 2)}"))
