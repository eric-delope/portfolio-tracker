"""Generate the synthetic demo portfolio and demo watchlist shipped with the repository.

The demo is a fictional long-term investor: a monthly deposit, ETF savings plans as the core, a handful of
quality stocks bought in tranches, one position sold, dividends, interest, card spending with Saveback.
All trades use real historical closing prices (Yahoo Finance), so every analysis in the dashboard behaves
like it would on a real Trade Republic export – without exposing anyone's personal data.

    python scripts/make_demo_data.py            # writes data/sample/demo_portfolio.csv + demo_watchlist.json
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portfolio_tracker import valuation as v  # noqa: E402
from portfolio_tracker.research import Research  # noqa: E402
from portfolio_tracker.watchlist import Alert, Entry  # noqa: E402

OUT_CSV = ROOT / "data" / "sample" / "demo_portfolio.csv"
OUT_WATCHLIST = ROOT / "data" / "sample" / "demo_watchlist.json"
START = pd.Timestamp("2023-10-02")
END = pd.Timestamp.today().normalize() - pd.offsets.BDay(1)  # up to the last trading day
RNG = np.random.default_rng(42)

# isin -> (ticker, name, asset class, Trade Republic description name)
ASSETS = {
    "IE00B4L5Y983": ("EUNL.DE", "Core MSCI World USD (Acc)", "FUND", "iShares Core MSCI World UCITS ETF"),
    "IE00BTJRMP35": ("XMME.DE", "MSCI Emerging Markets USD (Acc)", "FUND", "Xtrackers MSCI Emerging Markets UCITS ETF"),
    "NL0010273215": ("ASML.AS", "ASML", "STOCK", "ASML HOLDING N.V."),
    "DE0007164600": ("SAP.DE", "SAP", "STOCK", "SAP SE"),
    "US92826C8394": ("V", "Visa", "STOCK", "VISA INC."),
    "US22160K1051": ("COST", "Costco Wholesale", "STOCK", "COSTCO WHOLESALE CORP."),
    "DE0007236101": ("SIE.DE", "Siemens", "STOCK", "SIEMENS AG"),
    "FR0000121014": ("MC.PA", "LVMH", "STOCK", "LVMH MOET HENNESSY LOUIS VUITTON SE"),
}
SAVINGS_PLANS = {"IE00B4L5Y983": 250.0, "IE00BTJRMP35": 50.0, "DE0007164600": 50.0}
# (date, isin, EUR amount) – one-off buys in tranches, several after pullbacks
BUYS = [
    ("2023-10-23", "NL0010273215", 900), ("2023-11-14", "US92826C8394", 700), ("2024-01-09", "FR0000121014", 800),
    ("2024-02-20", "US22160K1051", 600), ("2024-04-19", "NL0010273215", 500), ("2024-05-07", "DE0007236101", 650),
    ("2024-07-25", "FR0000121014", 500), ("2024-08-05", "US92826C8394", 600), ("2024-10-16", "NL0010273215", 700),
    ("2025-01-28", "US22160K1051", 500), ("2025-04-07", "NL0010273215", 600), ("2025-04-08", "DE0007236101", 500),
    ("2025-06-17", "US92826C8394", 500), ("2025-11-04", "DE0007164600", 800), ("2026-03-10", "US22160K1051", 400),
]
# (date, isin, share of the position to sell)
SELLS = [("2025-02-12", "FR0000121014", 1.0), ("2026-05-14", "DE0007236101", 0.4)]
WITHDRAWALS = [("2025-07-01", 1500.0)]
TAX_RATE = 0.26375
MONTHLY_DEPOSIT = 1000.0


def prices_eur() -> pd.DataFrame:
    tickers = [a[0] for a in ASSETS.values()]
    raw = yf.download(tickers + ["EURUSD=X"], start=START - pd.Timedelta(days=10), end=END + pd.Timedelta(days=5),
                      auto_adjust=False, actions=False, progress=False, threads=False)["Close"]
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    raw = raw.reindex(pd.bdate_range(raw.index.min(), raw.index.max())).ffill()
    for tk in ("V", "COST"):
        raw[tk] = raw[tk] / raw["EURUSD=X"]
    return raw


def dividends_local() -> dict[str, pd.Series]:
    out = {}
    for isin, (tk, _, cls, _) in ASSETS.items():
        if cls == "STOCK":
            s = yf.Ticker(tk).dividends
            s.index = s.index.tz_localize(None).normalize()
            out[isin] = s[(s.index >= START) & (s.index <= END)]
    return out


class Book:
    def __init__(self):
        self.rows, self.cash, self.shares, self.n = [], 0.0, {i: 0.0 for i in ASSETS}, 0
        self.changes: dict[str, list[tuple[pd.Timestamp, float]]] = {i: [] for i in ASSETS}

    def shares_at(self, isin: str, day: pd.Timestamp) -> float:
        """Shares held before ``day`` (dividend eligibility at the ex-date)."""
        return round(sum(n for d, n in self.changes[isin] if d < day), 6)

    def add(self, day: pd.Timestamp, category: str, typ: str, amount: float, *, isin: str = "", shares: float | None = None,
            price: float | None = None, fee: float | None = None, tax: float | None = None, description: str = "",
            hour: int = 12) -> None:
        self.n += 1
        name, cls = (ASSETS[isin][1], ASSETS[isin][2]) if isin else ("", "")
        self.rows.append({
            "datetime": f"{day:%Y-%m-%d}T{hour:02d}:{RNG.integers(0, 60):02d}:00.000Z", "date": f"{day:%Y-%m-%d}",
            "account_type": "DEFAULT", "category": category, "type": typ, "asset_class": cls, "name": name,
            "symbol": isin, "shares": "" if shares is None else f"{shares:.10f}",
            "price": "" if price is None else f"{price:.6f}", "amount": f"{amount:.6f}",
            "fee": "" if fee is None else f"{fee:.2f}", "tax": "" if tax is None else f"{tax:.2f}", "currency": "EUR",
            "original_amount": "", "original_currency": "", "fx_rate": "", "description": description,
            "transaction_id": f"demo-{self.n:05d}", "counterparty_name": "", "counterparty_iban": "",
            "payment_reference": "", "mcc_code": "",
        })
        self.cash += amount + (fee or 0.0) + (tax or 0.0)

    def trade(self, day, isin: str, eur: float, px: float, savings_plan: bool = False) -> None:
        shares = round(eur / px, 6)
        amount = -round(shares * px, 2)
        fee = None if savings_plan else -1.0
        if self.cash + amount + (fee or 0) < 0:
            return
        kind = "Savings plan execution" if savings_plan else "Buy trade"
        self.add(day, "TRADING", "BUY", amount, isin=isin, shares=shares, price=px, fee=fee, hour=14 if savings_plan else 10,
                 description=f"{kind} {isin} {ASSETS[isin][3]}, quantity: {shares:g}")
        self.shares[isin] += shares
        self.changes[isin].append((day, shares))

    def sell(self, day, isin: str, share: float, px: float, cost_per_share: float) -> None:
        shares = round(self.shares[isin] * share, 6)
        proceeds = round(shares * px, 2)
        gain = proceeds - 1.0 - shares * cost_per_share
        tax = -round(max(gain, 0.0) * TAX_RATE, 2) or None
        self.add(day, "TRADING", "SELL", proceeds, isin=isin, shares=-shares, price=px, fee=-1.0, tax=tax, hour=11,
                 description=f"Sell trade {isin} {ASSETS[isin][3]}, quantity: {shares:g}")
        self.shares[isin] -= shares
        self.changes[isin].append((day, -shares))


def build() -> pd.DataFrame:
    px = prices_eur()
    divs = dividends_local()
    fx = px["EURUSD=X"]
    book = Book()
    cost = {i: [0.0, 0.0] for i in ASSETS}  # isin -> [shares, cost] for a rough average cost (tax estimate only)
    buys = {pd.Timestamp(d): (i, a) for d, i, a in BUYS}
    sells = {pd.Timestamp(d): (i, s) for d, i, s in SELLS}
    withdrawals = {pd.Timestamp(d): a for d, a in WITHDRAWALS}
    planned = set()
    payments = {(ex + pd.offsets.BDay(10)).normalize(): [] for s_ in divs.values() for ex in s_.index}
    for isin, s_ in divs.items():
        for ex, dps in s_.items():
            payments[(ex + pd.offsets.BDay(10)).normalize()].append((isin, ex, float(dps)))
    days = pd.bdate_range(START, END)
    for day in days:
        first_bday = day == days[days.to_period("M") == day.to_period("M")][0]
        if first_bday:
            book.add(day, "CASH", "TRANSFER_INSTANT_INBOUND", MONTHLY_DEPOSIT, description="Incoming transfer", hour=7)
            interest = round(max(book.cash, 0) * 0.02 / 12, 2) if day.year >= 2024 else 0.0
            if interest > 0:
                book.add(day, "CASH", "INTEREST_PAYMENT", interest, description="Interest payment Booking", hour=3)
        if day.day >= 2 and day.to_period("M") not in planned:  # savings plans run on the 2nd (or next business day)
            planned.add(day.to_period("M"))
            for isin, eur in SAVINGS_PLANS.items():
                if isin == "DE0007164600" and day < pd.Timestamp("2024-06-01"):
                    continue
                p_ = float(px.loc[day, ASSETS[isin][0]])
                book.trade(day, isin, eur, p_, savings_plan=True)
                cost[isin][0] += round(eur / p_, 6)
                cost[isin][1] += eur
        if day in buys:
            isin, eur = buys[day]
            p_ = float(px.loc[day, ASSETS[isin][0]])
            book.trade(day, isin, eur, p_)
            cost[isin][0] += round(eur / p_, 6)
            cost[isin][1] += eur + 1
        if day in sells:
            isin, share = sells[day]
            avg = cost[isin][1] / cost[isin][0]
            book.sell(day, isin, share, float(px.loc[day, ASSETS[isin][0]]), avg)
            cost[isin][0] *= 1 - share
            cost[isin][1] *= 1 - share
        if day in withdrawals:
            book.add(day, "CASH", "TRANSFER_OUTBOUND", -withdrawals[day], description="Outgoing transfer", hour=9)
        if day.weekday() in (1, 4) and RNG.random() < 0.8:  # card spending twice a week with 1 % Saveback
            spend = -round(float(RNG.uniform(8, 70)), 2)
            if book.cash + spend > 50:
                book.add(day, "CASH", "CARD_TRANSACTION", spend, description="Card payment", hour=18)
        if first_bday and day > START:  # last month's Saveback, invested into the MSCI World
            month_spend = -sum(float(r["amount"]) for r in book.rows if r["type"] == "CARD_TRANSACTION"
                               and r["date"][:7] == f"{(day - pd.DateOffset(months=1)):%Y-%m}")
            saveback = round(min(month_spend, 1500) * 0.01, 2)
            if saveback > 0:
                isin = "IE00B4L5Y983"
                book.add(day, "CASH", "BENEFITS_SAVEBACK", saveback, isin=isin, description="Your Saveback payment", hour=6)
                p_ = float(px.loc[day, ASSETS[isin][0]])
                book.trade(day, isin, saveback, p_, savings_plan=True)
        for isin, ex, dps in payments.get(day, []):  # paid ~2 weeks after the ex-date on shares held at the ex-date
            held = book.shares_at(isin, ex)
            if held > 1e-6:
                rate = float(fx.loc[day]) if ASSETS[isin][0] in ("V", "COST") else 1.0
                gross = round(held * dps / rate, 2)
                book.add(day, "CASH", "DIVIDEND", gross, isin=isin, shares=held, tax=-round(gross * TAX_RATE, 2),
                         description=f"Cash Dividend for ISIN {isin}", hour=8)
    return pd.DataFrame(book.rows)


def watchlist() -> dict:
    """Valuations made with the tool's own model, as of the generation date."""
    research = Research(ROOT / "data" / "cache")
    entries = []
    picks = [("ASML.AS", 0.12, 0.10), ("V", 0.10, 0.10), ("COST", 0.09, 0.10), ("SAP.DE", 0.11, 0.10),
             ("ADYEN.AS", 0.15, 0.11)]
    for ticker, growth, req in picks:
        f = research.fundamentals(ticker)
        hpe = v.historical_multiple(f.prices, f.annual["eps"]) if "eps" in f.annual else pd.Series(dtype=float)
        base_pe = float(np.clip(hpe.median() if len(hpe) > 20 else (f.pe_forward or 25), 15, 35))
        scen = [v.Scenario("Bear", 0.25, growth - 0.06, base_pe * 0.8), v.Scenario("Base", 0.5, growth, base_pe),
                v.Scenario("Bull", 0.25, growth + 0.05, base_pe * 1.2)]
        sv = v.scenario_valuation(f.eps_ttm, scen, 5, req, dividend0=f.dividend_rate or 0.0)
        fair = float(sv.loc["Expected", "fair_value"])
        target = v.future_price(fair, req, 5, float(sv.loc["Expected", "pv_dividends"]))
        mos = 0.15
        alerts = [Alert(price=round(fair * (1 - m), 2), label=f"Tranche {i + 1} (−{m * 100:.0f}%)", amount_eur=a,
                        rel_to_fair=-m) for i, (m, a) in enumerate([(mos, 400.0), (mos + 0.1, 400.0), (mos + 0.2, 500.0)])]
        e = Entry(ticker=ticker, name=f.name, currency=f.currency, fair_value=round(fair, 2), target_price=round(target, 2),
                  horizon_years=5, required_return=req, valuation_date=date.today().isoformat(),
                  thesis="Demo valuation generated with the tool's own scenario model.",
                  thesis_kpis=[{"metric": "Revenue growth", "operator": ">=", "threshold": 0.05},
                               {"metric": "Operating margin", "operator": ">=",
                                "threshold": round((f.operating_margin or 0.2) - 0.05, 3)}],
                  valuation_inputs={"eps0": f.eps_ttm, "required_return": req, "mos": mos, "horizon": 5,
                                    "dividends": sv.attrs["dividends"], "price_at_valuation": f.price,
                                    "base_growth": growth, "base_pe": base_pe,
                                    "scenarios": {"Scenario": ["Bear", "Base", "Bull"], "Probability %": [25.0, 50.0, 25.0],
                                                  "EPS growth % p.a.": [round((growth - 0.06) * 100, 1), growth * 100,
                                                                        round((growth + 0.05) * 100, 1)],
                                                  "Exit P/E": [round(base_pe * 0.8, 1), round(base_pe, 1),
                                                               round(base_pe * 1.2, 1)]}},
                  alerts=alerts)
        e.history = [e.snapshot()]
        entries.append(asdict(e))
        print(f"{ticker:9s} fair {fair:8.2f} {f.currency}  price {f.price:8.2f}")
    return {"updated": date.today().isoformat(), "entries": entries}


if __name__ == "__main__":
    df = build()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, quoting=csv.QUOTE_ALL)
    print(f"{len(df)} transactions -> {OUT_CSV.relative_to(ROOT)}")
    OUT_WATCHLIST.write_text(json.dumps(watchlist(), indent=1, ensure_ascii=False))
    print(f"watchlist -> {OUT_WATCHLIST.relative_to(ROOT)}")
