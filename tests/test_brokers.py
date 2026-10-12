"""Broker formats: detection, sign conventions and privacy of the Scalable Capital and generic adapters."""

import io

import pandas as pd
import pytest

from portfolio_tracker.brokers import detect, guess_asset_class
from portfolio_tracker.importer import holdings, load_transactions, summary, validate

SCALABLE = """date;time;status;reference;description;assetType;type;isin;shares;price;amount;fee;tax;currency
2025-01-02;09:00:00;Executed;REF-1;Deposit from Max Mustermann DE00000000000000000000;Cash;Deposit;;;;"1.000,00";;;EUR
2025-01-03;10:15:00;Executed;REF-2;iShares Core MSCI World UCITS ETF;Security;Savings plan;IE00B4L5Y983;"2,5";"80";"-200";"0";"0";EUR
2025-01-10;15:30:00;Executed;REF-3;ASML Holding;Security;Buy;NL0010273215;"1";"650,00";"-650,00";"0,99";"0,00";EUR
2025-02-01;15:30:00;Cancelled;REF-4;ASML Holding;Security;Buy;NL0010273215;"1";"600,00";"-600,00";"0,99";"0,00";EUR
2025-03-01;08:00:00;Executed;REF-5;ASML Holding;Security;Distribution;NL0010273215;;;"1,52";;"-0,40";EUR
2025-04-01;11:00:00;Executed;REF-6;ASML Holding;Security;Sell;NL0010273215;"0,5";"700,00";"350,00";"0,99";"-12,00";EUR
2025-04-30;06:00:00;Executed;REF-7;Interest;Cash;Interest;;;;"2,10";;;EUR
"""

GENERIC_DE = """Date;Type;ISIN;Name;Shares;Price;Amount;Fee;Tax;Currency
02.01.2025;Einzahlung;;;;;1.000,00;;;EUR
03.01.2025;Kauf;US0378331005;Apple;2;180,50;;1,00;;EUR
01.02.2025;Dividende;US0378331005;Apple;;;0,48;;0,12;EUR
01.03.2025;Verkauf;US0378331005;Apple;1;200,00;;1,00;3,50;EUR
"""

GENERIC_EN = """date,type,isin,name,shares,price,amount,fee,tax,currency,asset_class
2025-01-02,deposit,,,,,500,,,EUR,
2025-01-03,buy,IE00B4L5Y983,Core MSCI World,4,75.25,,1,,EUR,FUND
"""


def load(text: str) -> pd.DataFrame:
    return load_transactions(io.BytesIO(text.encode()))


def test_detects_formats():
    assert detect(SCALABLE)[0] == "Scalable Capital"
    assert detect(GENERIC_DE)[0] == "Generic CSV"
    assert detect(GENERIC_EN)[0] == "Generic CSV"
    with pytest.raises(ValueError, match="missing columns"):
        detect("a;b\n1;2\n")


def test_scalable_capital_signs_and_events():
    tx = load(SCALABLE)
    assert tx.attrs["format"] == "Scalable Capital"
    assert "REF-4" not in set(tx["transaction_id"])                      # cancelled orders are skipped
    buy = tx[tx["transaction_id"] == "REF-3"].iloc[0]
    assert (buy["event"], buy["shares"], buy["amount"], buy["fee"]) == ("buy", 1.0, -650.0, -0.99)
    sell = tx[tx["transaction_id"] == "REF-6"].iloc[0]
    assert (sell["shares"], sell["amount"], sell["tax"]) == (-0.5, 350.0, -12.0)
    plan = tx[tx["transaction_id"] == "REF-2"].iloc[0]
    assert plan["savings_plan"] and plan["asset_class"] == "FUND" and plan["shares"] == 2.5
    div = tx[tx["event"] == "dividend"].iloc[0]
    assert (div["amount"], div["tax"]) == (1.52, -0.40)
    assert validate(tx) == []
    pos = holdings(tx)
    assert pos.loc["NL0010273215", "shares"] == pytest.approx(0.5)
    assert summary(tx)["deposits"] == 1000.0


def test_scalable_capital_drops_personal_details():
    tx = load(SCALABLE)
    text = tx.to_csv()
    assert "Mustermann" not in text and "DE0000000" not in text
    assert tx.loc[tx["event"] == "deposit", "name"].isna().all()


def test_generic_german_layout():
    tx = load(GENERIC_DE)
    assert list(tx["event"]) == ["deposit", "buy", "dividend", "sell"]
    buy = tx.iloc[1]
    assert (buy["shares"], buy["amount"], buy["fee"]) == (2.0, -361.0, -1.0)
    assert tx.iloc[0]["amount"] == 1000.0 and tx.iloc[0]["date"] == pd.Timestamp("2025-01-02")
    sell = tx.iloc[3]
    assert (sell["shares"], sell["amount"], sell["tax"]) == (-1.0, 200.0, -3.5)
    assert validate(tx) == []


def test_generic_english_layout_with_asset_class():
    tx = load(GENERIC_EN)
    buy = tx[tx["event"] == "buy"].iloc[0]
    assert buy["asset_class"] == "FUND" and buy["amount"] == pytest.approx(-301.0)


@pytest.mark.parametrize("name, kind", [("iShares Core MSCI World UCITS ETF", "FUND"), ("Vanguard FTSE All-World", "FUND"),
                                        ("ASML Holding", "STOCK"), ("Apple", "STOCK")])
def test_guess_asset_class(name, kind):
    assert guess_asset_class(name) == kind
