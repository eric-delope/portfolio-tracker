"""Broker export formats -> one normalized transaction table.

Every adapter turns a broker's CSV into the same columns, so the rest of the package never needs to know
where the data came from:

    datetime, date, category, raw_type, event, isin, name, asset_class, currency, savings_plan,
    transaction_id, shares, price, amount, fee, tax, net_cash

Conventions (those of the Trade Republic export, verified against real data):
- ``shares`` is signed: positive for buys, negative for sells.
- ``amount`` is the gross cash amount *excluding* fees and taxes, signed from the account's view.
- ``fee`` and ``tax`` are separate signed cash amounts (negative = paid, positive = refunded).
- ``event`` is one of: buy, sell, dividend, interest, tax_refund, saveback, deposit, withdrawal, card,
  account_fee, other.

Privacy by design: only the columns above are kept. Counterparty names, IBANs, references to people and
free-text descriptions are dropped in the adapter, before anything else sees the data.

Supported formats (detected from the header line):
- **Trade Republic** – the CSV export from the app (Profile → Transactions → Export).
- **Scalable Capital** – the transactions CSV of the Scalable broker (semicolon separated, decimal comma).
- **Generic** – a documented ten-column layout any other broker export can be mapped to in a spreadsheet
  (see ``docs/IMPORT_FORMATS.md`` and ``data/sample/generic_template.csv``).
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Callable

import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = ["datetime", "date", "category", "raw_type", "event", "isin", "name", "asset_class", "currency",
           "savings_plan", "transaction_id", "shares", "price", "amount", "fee", "tax", "net_cash"]
TRADE_EVENTS = {"buy", "sell"}
_FUND_WORDS = re.compile(r"\b(ETF|ETC|UCITS|iShares|Vanguard|Xtrackers|Amundi|SPDR|Lyxor|Invesco|WisdomTree|"
                         r"VanEck|Fund|Fonds|MSCI|S&P 500|FTSE|STOXX|Acc|Dist)\b", re.IGNORECASE)


def guess_asset_class(name: str) -> str:
    """'FUND' for ETFs and funds (recognisable by issuer or index in the name), else 'STOCK'.

    Matters for German taxes (30% partial exemption) and the ETF look-through. Exports that state the
    asset class (Trade Republic, the generic format's optional column) do not need the guess.
    """
    return "FUND" if _FUND_WORDS.search(str(name or "")) else "STOCK"


def _finish(tx: pd.DataFrame) -> pd.DataFrame:
    for col in ("shares", "price", "amount", "fee", "tax"):
        tx[col] = pd.to_numeric(tx[col], errors="coerce")
    tx[["amount", "fee", "tax"]] = tx[["amount", "fee", "tax"]].fillna(0.0)
    tx["net_cash"] = tx["amount"] + tx["fee"] + tx["tax"]
    return tx[COLUMNS].sort_values("datetime", kind="stable").reset_index(drop=True)


def _number(value, decimal: str) -> float:
    """'1.234,56' / '1,234.56' / '-200,00 €' -> float; empty -> NaN."""
    s = re.sub(r"[^\d,.\-+]", "", str(value or "")).strip()
    if not s or s in "+-":
        return float("nan")
    if "," in s and "." in s:   # the last separator is the decimal mark
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif decimal == ",":
        s = s.replace(".", "").replace(",", ".") if s.count(",") <= 1 else s.replace(",", "")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _delimiter(header: str) -> str:
    return ";" if header.count(";") > header.count(",") else ","


def _header(text: str) -> tuple[list[str], str]:
    first = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    sep = _delimiter(first)
    return [h.strip().strip('"').strip() for h in first.split(sep)], sep


# ------------------------------------------------------------- Trade Republic
TR_EVENTS: dict[str, str] = {
    "BUY": "buy", "SELL": "sell", "DIVIDEND": "dividend", "INTEREST_PAYMENT": "interest",
    "TAX_OPTIMIZATION": "tax_refund", "BENEFITS_SAVEBACK": "saveback",
    "TRANSFER_INBOUND": "deposit", "TRANSFER_INSTANT_INBOUND": "deposit", "TRANSFER_DIRECT_DEBIT_INBOUND": "deposit",
    "CUSTOMER_INPAYMENT": "deposit", "TRANSFER_OUTBOUND": "withdrawal", "TRANSFER_INSTANT_OUTBOUND": "withdrawal",
    "CARD_TRANSACTION": "card", "CARD_TRANSACTION_INTERNATIONAL": "card", "CARD_ORDERING_FEE": "account_fee",
}
TR_COLUMNS = {"datetime", "date", "category", "type", "asset_class", "name", "symbol", "shares", "price", "amount",
              "fee", "tax", "currency", "description", "transaction_id"}


def trade_republic(text: str) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, na_values=[""])
    unknown = set(raw["type"]) - set(TR_EVENTS)
    if unknown:
        log.warning("Unknown transaction types mapped to 'other': %s", sorted(unknown))
    tx = pd.DataFrame({
        "datetime": pd.to_datetime(raw["datetime"], format="ISO8601", utc=True),
        "date": pd.to_datetime(raw["date"], format="%Y-%m-%d"),
        "category": raw["category"],
        "raw_type": raw["type"],
        "event": raw["type"].map(TR_EVENTS).fillna("other"),
        "isin": raw["symbol"],
        "name": raw["name"],
        "asset_class": raw["asset_class"],
        "currency": raw["currency"],
        # the description is read for this one flag and then dropped (it can contain names)
        "savings_plan": raw["description"].str.startswith("Savings plan", na=False),
        "transaction_id": raw["transaction_id"],
        **{col: raw[col] for col in ("shares", "price", "amount", "fee", "tax")},
    })
    return _finish(tx)


# ------------------------------------------------------------- Scalable Capital
SC_COLUMNS = {"date", "status", "assetType", "type", "isin", "shares", "price", "amount", "fee", "tax", "currency"}
SC_EVENTS: dict[str, str] = {
    "buy": "buy", "savings plan": "buy", "sell": "sell", "distribution": "dividend", "dividend": "dividend",
    "interest": "interest", "deposit": "deposit", "withdrawal": "withdrawal", "fee": "account_fee",
    "taxes": "tax", "tax": "tax",
}


def scalable_capital(text: str) -> pd.DataFrame:
    """Scalable Capital broker CSV: ``date;time;status;reference;description;assetType;type;isin;shares;...``.

    Only executed bookings are kept. Signs are derived from the type (exports differ in whether buys carry a
    minus), and trades are booked at shares × price with the fee separate – the same convention as above.
    Security transfers and corporate actions carry no cash price and are reported as 'other'.
    """
    raw = pd.read_csv(io.StringIO(text), sep=";", dtype=str, keep_default_na=False, na_values=[""])
    raw.columns = [c.strip() for c in raw.columns]
    status = raw["status"].fillna("").str.strip().str.lower()
    raw = raw[status.isin(["executed", "ausgeführt", ""])].copy()
    kind = raw["type"].fillna("").str.strip().str.lower()
    unknown = sorted(set(kind) - set(SC_EVENTS))
    if unknown:
        log.warning("Scalable Capital types mapped to 'other': %s", unknown)
    num = {col: raw[col].map(lambda v: _number(v, ",")) for col in ("shares", "price", "amount", "fee", "tax")}
    event = kind.map(SC_EVENTS).fillna("other")
    shares, price = num["shares"].abs(), num["price"].abs()
    gross = (shares * price).where(shares.notna() & price.notna(), num["amount"].abs())
    amount = pd.Series(0.0, index=raw.index)
    amount[event == "buy"] = -gross
    amount[event == "sell"] = gross
    for ev in ("dividend", "interest", "deposit"):
        amount[event == ev] = num["amount"].abs()
    for ev in ("withdrawal", "account_fee"):
        amount[event == ev] = -num["amount"].abs()
    tax = num["tax"].fillna(0.0).map(lambda v: -abs(v))
    is_tax = event == "tax"
    tax[is_tax] = num["amount"][is_tax]                      # a tax booking: the amount is the tax (refunds > 0)
    event = event.mask(is_tax, num["amount"].gt(0).map({True: "tax_refund", False: "other"}))
    other = event == "other"
    amount[other & ~is_tax] = num["amount"][other & ~is_tax].fillna(0.0)
    time = raw["time"].fillna("00:00:00") if "time" in raw else "00:00:00"
    stamp = pd.to_datetime(raw["date"].str.strip() + " " + time, errors="coerce")
    names = raw["description"].fillna("") if "description" in raw else pd.Series("", index=raw.index)
    tx = pd.DataFrame({
        "datetime": stamp.dt.tz_localize("Europe/Berlin", nonexistent="shift_forward",
                                         ambiguous="NaT").dt.tz_convert("UTC"),
        "date": stamp.dt.normalize(),
        "category": raw["assetType"].fillna("").str.upper().map({"SECURITY": "TRADING"}).fillna("CASH"),
        "raw_type": raw["type"],
        "event": event,
        "isin": raw["isin"].where(raw["isin"].fillna("").str.len() > 0),
        # for securities the description is the security's name; for cash bookings it is dropped
        "name": names.where(raw["isin"].fillna("").str.len() > 0),
        "asset_class": names.map(guess_asset_class).where(raw["isin"].fillna("").str.len() > 0, ""),
        "currency": raw["currency"].fillna("EUR"),
        "savings_plan": kind.eq("savings plan"),
        "transaction_id": raw["reference"] if "reference" in raw else [f"sc-{i}" for i in range(len(raw))],
        "shares": shares.where(event != "sell", -shares).where(event.isin(TRADE_EVENTS)),
        "price": price.where(event.isin(TRADE_EVENTS)),
        "amount": amount,
        "fee": num["fee"].fillna(0.0).map(lambda v: -abs(v)),
        "tax": tax,
    })
    return _finish(tx)


# ------------------------------------------------------------- generic
GENERIC_COLUMNS = {"date", "type", "isin", "name", "shares", "price", "amount", "fee", "tax", "currency"}
GENERIC_EVENTS: dict[str, str] = {
    "buy": "buy", "kauf": "buy", "savings plan": "buy", "sparplan": "buy", "sell": "sell", "verkauf": "sell",
    "dividend": "dividend", "dividende": "dividend", "distribution": "dividend", "ausschüttung": "dividend",
    "interest": "interest", "zinsen": "interest", "deposit": "deposit", "einzahlung": "deposit",
    "withdrawal": "withdrawal", "auszahlung": "withdrawal", "fee": "account_fee", "gebühr": "account_fee",
    "tax": "tax", "steuer": "tax", "tax refund": "tax_refund", "steuererstattung": "tax_refund",
}


def generic(text: str) -> pd.DataFrame:
    """The documented generic layout: one row per booking, positive numbers, the type gives the direction.

    Columns: date, type, isin, name, shares, price, amount, fee, tax, currency – optional: time, asset_class, id.
    Comma or semicolon separated, decimal point or comma. Types in English or German (buy/Kauf, sell/Verkauf,
    dividend/Dividende, interest/Zinsen, deposit/Einzahlung, withdrawal/Auszahlung, fee/Gebühr, tax/Steuer).
    """
    header, sep = _header(text)
    raw = pd.read_csv(io.StringIO(text.lstrip("﻿")), sep=sep, dtype=str, keep_default_na=False,
                      na_values=[""])
    raw.columns = [c.strip().lower() for c in raw.columns]
    sample = " ".join(raw[c].fillna("").str.cat(sep=" ") for c in ("shares", "price", "amount") if c in raw)
    decimal = "," if sep == ";" or re.search(r"\d,\d{1,2}(?!\d)", sample) and not re.search(r"\d\.\d", sample) else "."
    kind = raw["type"].fillna("").str.strip().str.lower()
    unknown = sorted(set(kind) - set(GENERIC_EVENTS))
    if unknown:
        log.warning("Generic import: types mapped to 'other': %s", unknown)
    event = kind.map(GENERIC_EVENTS).fillna("other")
    num = {col: raw[col].map(lambda v: _number(v, decimal)).abs() for col in ("shares", "price", "amount", "fee", "tax")}
    gross = (num["shares"] * num["price"]).where(num["shares"].notna() & num["price"].notna(), num["amount"])
    sign = event.map({"buy": -1, "sell": 1, "dividend": 1, "interest": 1, "deposit": 1, "tax_refund": 0,
                      "withdrawal": -1, "account_fee": -1, "tax": 0}).fillna(1)
    amount = gross.where(event.isin(TRADE_EVENTS), num["amount"]).fillna(0.0) * sign
    tax = -num["tax"].fillna(0.0)
    tax[event == "tax"] = -num["amount"][event == "tax"].fillna(0.0)
    tax[event == "tax_refund"] = num["amount"][event == "tax_refund"].fillna(0.0)
    event = event.replace({"tax": "other"})
    time = raw["time"].fillna("00:00") if "time" in raw else "00:00"
    german_dates = raw["date"].str.contains(r"^\d{1,2}\.").any()     # 31.12.2025
    stamp = pd.to_datetime(raw["date"].str.strip() + " " + time, errors="coerce", dayfirst=german_dates)
    has_isin = raw["isin"].fillna("").str.len() > 0
    asset = raw["asset_class"].str.upper() if "asset_class" in raw else raw["name"].map(guess_asset_class)
    tx = pd.DataFrame({
        "datetime": stamp.dt.tz_localize("Europe/Berlin", nonexistent="shift_forward",
                                         ambiguous="NaT").dt.tz_convert("UTC"),
        "date": stamp.dt.normalize(),
        "category": event.isin(TRADE_EVENTS | {"dividend"}).map({True: "TRADING", False: "CASH"}),
        "raw_type": raw["type"],
        "event": event,
        "isin": raw["isin"].where(has_isin),
        "name": raw["name"].where(has_isin),
        "asset_class": asset.where(has_isin, ""),
        "currency": raw["currency"].fillna("EUR"),
        "savings_plan": kind.isin(["savings plan", "sparplan"]),
        "transaction_id": raw["id"] if "id" in raw else [f"g-{i:05d}" for i in range(len(raw))],
        "shares": num["shares"].where(event != "sell", -num["shares"]).where(event.isin(TRADE_EVENTS)),
        "price": num["price"].where(event.isin(TRADE_EVENTS)),
        "amount": amount,
        "fee": -num["fee"].fillna(0.0),
        "tax": tax,
    })
    return _finish(tx)


# ------------------------------------------------------------- detection
FORMATS: list[tuple[str, set[str], Callable[[str], pd.DataFrame]]] = [
    ("Trade Republic", TR_COLUMNS, trade_republic),
    ("Scalable Capital", SC_COLUMNS, scalable_capital),
    ("Generic CSV", GENERIC_COLUMNS, generic),
]


def detect(text: str) -> tuple[str, Callable[[str], pd.DataFrame]]:
    """Format name and parser for an export, decided by its header line."""
    header, _ = _header(text)
    cols, lower = set(header), {h.lower() for h in header}
    for name, required, parser in FORMATS:
        if required <= cols or (parser is generic and required <= lower):
            return name, parser
    missing = sorted(GENERIC_COLUMNS - lower)
    raise ValueError("Unknown file format – expected a Trade Republic or Scalable Capital export or the generic "
                     f"CSV layout (docs/IMPORT_FORMATS.md); missing columns: {missing}")


def parse(text: str) -> tuple[str, pd.DataFrame]:
    name, parser = detect(text)
    return name, parser(text)
