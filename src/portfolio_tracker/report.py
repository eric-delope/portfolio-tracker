"""Monthly report: what happened in one calendar month, and what to do next."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import metrics as m
from .fmt import SYMBOLS, eur, num, pct
from .importer import trades
from .portfolio import Portfolio

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
CONCENTRATION_LIMIT = 0.20
CASH_LIMIT = 0.15
STALE_VALUATION_DAYS = 90


@dataclass
class MonthReport:
    month: pd.Period
    base: pd.Timestamp | None       # last business day before the month (valuation base)
    end: pd.Timestamp               # last business day of the month with data
    complete: bool                  # False while the month is still running
    value_start: float
    value_end: float
    pnl: float
    twr: float
    benchmark: str
    benchmark_twr: float
    ytd_twr: float
    ytd_benchmark_twr: float
    flows: dict
    positions: pd.DataFrame         # per ISIN: value start/end, weight, contribution, price return
    trades: pd.DataFrame
    dividends: pd.DataFrame
    best_day: tuple[pd.Timestamp, float] | None
    worst_day: tuple[pd.Timestamp, float] | None
    actions: list[tuple[str, str]] = field(default_factory=list)   # (priority, text)
    events: list[tuple[date, str]] = field(default_factory=list)    # upcoming dates, e.g. earnings
    opportunities: pd.DataFrame | None = None                        # entry ranking (see opportunities.rank)
    currency: str = "EUR"           # reporting currency of all amounts (Portfolio.base)

    @property
    def title(self) -> str:
        return f"{MONTHS[self.month.month - 1]} {self.month.year}"


def available_months(p: Portfolio) -> list[pd.Period]:
    months = pd.period_range(p.index[0].to_period("M"), p.last_date.to_period("M"), freq="M")
    return list(reversed(months))


def build_report(p: Portfolio, month: pd.Period, benchmark: str = "MSCI World") -> MonthReport:
    idx = p.index
    before = idx[idx < month.start_time]
    base = before[-1] if len(before) else None
    end = idx[idx <= month.end_time][-1]
    complete = month < p.last_date.to_period("M")

    d = p.daily
    r = d["return"]
    r_month = r[(r.index > base) & (r.index <= end)] if base is not None else r[r.index <= end]
    b = p.benchmark_returns[benchmark]
    b_month = b.reindex(r_month.index)

    year_start = pd.Timestamp(year=month.year, month=1, day=1)
    r_ytd = r[(r.index >= year_start) & (r.index <= end)]

    pnl_start = d.loc[base, "pnl"] if base is not None else 0.0
    value_start = d.loc[base, "value"] if base is not None else 0.0

    tx = p.tx[(p.tx["date"] >= month.start_time) & (p.tx["date"] <= month.end_time)]
    t = trades(tx)
    by_event = tx.groupby("event")
    gross, net = by_event["amount"].sum(), by_event["net_cash"].sum()
    flows = {
        "deposits": gross.get("deposit", 0.0), "withdrawals": gross.get("withdrawal", 0.0),
        "bought": -gross.get("buy", 0.0), "sold": gross.get("sell", 0.0),
        "dividends": net.get("dividend", 0.0), "interest": net.get("interest", 0.0),
        "saveback": net.get("saveback", 0.0), "card": net.get("card", 0.0),
        "fees": -t["fee"].sum(), "taxes": -tx["tax"].sum(),
        "orders": len(t), "savings_plan_orders": int(t["savings_plan"].sum()),
    }
    flows["net_invested"] = flows["bought"] - flows["sold"]

    pp = p.position_pnl
    contrib = pp.loc[end] - (pp.loc[base] if base is not None else 0.0)
    v_start = p.values.loc[base] if base is not None else p.values.loc[end] * 0
    v_end = p.values.loc[end]
    px = p.price_eur
    price_ret = px.loc[end] / px.loc[base] - 1 if base is not None else px.loc[end] * np.nan
    pos = pd.DataFrame({
        "name": p.meta["name"], "value_start": v_start, "value_end": v_end,
        "weight_start": v_start / v_start.sum() if v_start.sum() else 0.0,
        "weight_end": v_end / v_end.sum() if v_end.sum() else 0.0,
        "contribution": contrib, "price_return": price_ret,
    })
    pos = pos[(pos["value_start"] > 0) | (pos["value_end"] > 0) | (pos["contribution"].abs() >= 0.5)]
    pos = pos.sort_values("contribution", ascending=False)

    trade_list = t[["date", "name", "event", "shares", "price", "amount", "fee", "savings_plan"]].sort_values("date")
    divs = tx[tx["event"] == "dividend"][["date", "name", "amount", "tax", "net_cash"]]

    active = r_month[r_month != 0]
    return MonthReport(
        month=month, base=base, end=end, complete=complete, currency=p.base,
        value_start=value_start, value_end=d.loc[end, "value"], pnl=d.loc[end, "pnl"] - pnl_start,
        twr=m.total_return(r_month), benchmark=benchmark, benchmark_twr=m.total_return(b_month),
        ytd_twr=m.total_return(r_ytd), ytd_benchmark_twr=m.total_return(b.reindex(r_ytd.index)),
        flows=flows, positions=pos, trades=trade_list, dividends=divs,
        best_day=(active.idxmax(), active.max()) if len(active) else None,
        worst_day=(active.idxmin(), active.min()) if len(active) else None,
    )


def action_items(p: Portfolio, report: MonthReport, cash: float, allowance_left: float | None,
                 alert_states: pd.DataFrame | None, valuations: dict[str, dict] | None,
                 earnings: dict[str, date] | None, names: dict[str, str] | None = None,
                 watchlist=None, prices: dict[str, float] | None = None,
                 thesis_status: dict[str, tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """Prioritized to-dos ('high' | 'medium' | 'info') derived from portfolio, watchlist and calendar."""
    items: list[tuple[str, str]] = []
    today = date.today()

    for ticker, (state, detail) in (thesis_status or {}).items():
        if state == "broken":
            items.append(("high", f"**{(names or {}).get(ticker, ticker)}**: thesis broken – {detail}."))
    if watchlist is not None:
        for e in watchlist:
            rolls = e.rolled_alerts(min_drift=0.03)
            if rolls:
                items.append(("medium", f"**{e.name}**: roll {len(rolls)} entry price{'s' if len(rolls) > 1 else ''} "
                                        "forward – fair value has grown since the valuation."))
            plan = e.plan or {}
            price = (prices or {}).get(e.ticker)
            fair = e.fair_value_today()
            if plan.get("monthly_eur") and price and fair:
                if price > fair:
                    items.append(("medium", f"**{e.name}**: pause the savings plan – price "
                                            f"{num((price / fair - 1) * 100, 0)}% above fair value."))
                else:
                    items.append(("info", f"**{e.name}**: savings plan on track – price "
                                          f"{num((1 - price / fair) * 100, 0)}% below fair value."))

    if alert_states is not None and not alert_states.empty:
        hits = alert_states[alert_states["state"] == "hit"]
        for (name, direction), g in hits.groupby(["name", "direction"], sort=False):
            cur, price = g["currency"].iloc[0], g["price"].iloc[0]
            if direction == "above":
                items.append(("high", f"**{name}** reached its sell line at {num(price, 2)} {cur} – consider trimming."))
            else:
                amount = g["amount_eur"].fillna(0).sum()
                n = f"{len(g)} tranche{'s' if len(g) > 1 else ''}"
                items.append(("high", f"**{name}** is in the buy zone at {num(price, 2)} {cur} – {n}, {eur(amount)} planned."
                              if amount else f"**{name}** is in the buy zone at {num(price, 2)} {cur} – {n}."))
        for _, a in alert_states[alert_states["state"] == "near"].iterrows():
            items.append(("medium", f"**{a['name']}** is {num(a['distance'] * 100, 1)}% from {a['label']}."))

    pos = p.positions
    if not pos.empty and valuations is not None:
        valued = set(valuations)
        unvalued = [row["name"] for isin, row in pos.iterrows()
                    if row["asset_class"] == "STOCK" and p.tickers.get(isin) not in valued]
        if unvalued:
            names = "**, **".join(unvalued)
            items.append(("medium", f"Value **{names}** – no fair value yet, so no basis to add or trim."))
    if not pos.empty:
        for _, row in pos[pos["weight"] > CONCENTRATION_LIMIT].iterrows():
            items.append(("medium", f"**{row['name']}** is {row['weight'] * 100:.0f}% of the portfolio "
                                    f"(limit {CONCENTRATION_LIMIT * 100:.0f}%)."))
        total = pos["value"].sum() + cash
        if total and cash / total > CASH_LIMIT:
            items.append(("info", f"Cash is {cash / total * 100:.0f}% of your assets – invest as planned?"))

    for ticker, info in (valuations or {}).items():
        age = info.get("age_days")
        if age is not None and age > STALE_VALUATION_DAYS:
            items.append(("medium", f"**{info['name']}**: valuation is {age} days old – update it."))
        ed = (earnings or {}).get(ticker)
        vd = info.get("valuation_date")
        if ed and vd and date.fromisoformat(vd[:10]) < ed <= today:
            items.append(("medium", f"**{info['name']}** reported on {ed:%d %b} – review your valuation."))

    if allowance_left is not None and allowance_left > 100 and today.month >= 11:
        items.append(("medium", f"{eur(allowance_left)} tax-free allowance left – realise gains before year end?"))

    if (p.last_date - p.tx["date"].max()).days > 7:
        items.append(("info", "The export is over a week old – download a fresh one."))

    excess_ytd = report.ytd_twr - report.ytd_benchmark_twr
    if np.isfinite(excess_ytd) and excess_ytd < -0.05:
        items.append(("medium", f"{num(abs(excess_ytd) * 100, 1)} pp behind the {report.benchmark} this year – is stock "
                                "picking worth it?"))

    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(items, key=lambda x: order[x[0]])


# ------------------------------------------------------------------ markdown
def to_markdown(rep: MonthReport) -> str:
    """Obsidian-ready monthly note (amounts in the report's currency)."""
    f = rep.flows
    sym = SYMBOLS.get(rep.currency, rep.currency)

    def money(x: float, decimals: int = 0, sign: bool = False) -> str:
        return eur(x, decimals, sign, sym)
    lines = [
        "---", "type: monthly-report", f"month: {rep.month}", f"created: {date.today().isoformat()}",
        f"portfolio_value: {round(rep.value_end, 2)}", f"return_twr: {round(rep.twr, 4)}",
        f"benchmark_twr: {round(rep.benchmark_twr, 4)}", "---", "",
        f"# Monthly report {rep.title}" + ("" if rep.complete else " (month to date)"), "",
        "## Key figures", "",
        "| | Value |", "|---|---:|",
        f"| Portfolio value at month end | {money(rep.value_end)} |",
        f"| Change | {money(rep.value_end - rep.value_start, sign=True)} |",
        f"| Profit in the month | {money(rep.pnl, sign=True)} |",
        f"| Return (TWR) | {pct(rep.twr)} |",
        f"| {rep.benchmark} | {pct(rep.benchmark_twr)} |",
        f"| Return YTD | {pct(rep.ytd_twr)} (benchmark {pct(rep.ytd_benchmark_twr)}) |",
        f"| Net invested | {money(f['net_invested'], sign=True)} |",
        f"| Dividends + interest | {money(f['dividends'] + f['interest'], 2)} |",
        f"| Fees | {money(f['fees'], 2)} |", "",
        "## Contribution by position", "",
        "| Position | Contribution | Price change | Weight at month end |", "|---|---:|---:|---:|",
    ]
    for _, r in rep.positions.iterrows():
        lines.append(f"| {r['name']} | {money(r['contribution'], sign=True)} | {pct(r['price_return'])} | "
                     f"{pct(r['weight_end'], 1, False)} |")
    lines += ["", "## Trades", ""]
    if rep.trades.empty:
        lines.append("No trades this month.")
    else:
        lines += ["| Date | Position | Type | Shares | Price | Amount |", "|---|---|---|---:|---:|---:|"]
        for _, t in rep.trades.iterrows():
            kind = ("Savings plan" if t["savings_plan"] else "Buy") if t["event"] == "buy" else "Sell"
            lines.append(f"| {t['date']:%d %b} | {t['name']} | {kind} | {num(abs(t['shares']), 4)} | "
                         f"{money(t['price'], 2)} | {money(abs(t['amount']), 2)} |")
    if rep.opportunities is not None and not rep.opportunities.empty:
        lines += ["", "## Entry opportunities", "", "| Company | Verdict | Exp. return p.a. | Below fair value |",
                  "|---|---|---:|---:|"]
        for _, o in rep.opportunities.head(8).iterrows():
            lines.append(f"| {o['name']} | {o['verdict']} | {pct(o['expected_return'])} | {pct(o['margin_of_safety'])} |")
    if rep.actions:
        lines += ["", "## To-dos", ""]
        lines += [f"- [ ] ({prio}) {text}" for prio, text in rep.actions]
    if rep.events:
        lines += ["", "## Upcoming", ""]
        lines += [f"- {d:%d %b %Y} · {text}" for d, text in rep.events]
    lines += ["", NOTES_HEADING, "", "- "]
    return "\n".join(lines) + "\n"


NOTES_HEADING = "## Notes"


def merge_notes(new_md: str, old_md: str | None) -> str:
    """Keep the user's own notes (everything below '## Notes') when regenerating a note."""
    if not old_md or NOTES_HEADING not in old_md:
        return new_md
    old_notes = old_md.split(NOTES_HEADING, 1)[1]
    return new_md.split(NOTES_HEADING, 1)[0] + NOTES_HEADING + old_notes
