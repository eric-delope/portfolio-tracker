from pathlib import Path

import pandas as pd
import pytest

from portfolio_tracker.importer import holdings, load_transactions, summary, validate

SAMPLE = Path(__file__).parents[1] / "data" / "sample" / "sample_export.csv"


@pytest.fixture
def tx() -> pd.DataFrame:
    return load_transactions(SAMPLE)


def test_all_sample_types_are_mapped(tx):
    assert "other" not in set(tx["event"])
    assert len(tx) == 12


def test_personal_columns_are_dropped(tx):
    for col in ["counterparty_name", "counterparty_iban", "payment_reference", "description", "mcc_code"]:
        assert col not in tx.columns


def test_net_cash_includes_fee_and_tax(tx):
    buy = tx.loc[tx["transaction_id"] == "t-03"].iloc[0]
    sell = tx.loc[tx["transaction_id"] == "t-05"].iloc[0]
    assert buy["net_cash"] == pytest.approx(-361.00)
    assert sell["net_cash"] == pytest.approx(193.72)


def test_savings_plan_flag(tx):
    assert set(tx.loc[tx["savings_plan"], "transaction_id"]) == {"t-02", "t-10"}


def test_sample_is_valid(tx):
    assert validate(tx) == []


def test_holdings(tx):
    pos = holdings(tx)
    assert pos.loc["IE00BFY0GT14", "shares"] == pytest.approx(4.04)
    assert pos.loc["US0378331005", "shares"] == pytest.approx(1.0)


def test_holdings_as_of_date(tx):
    pos = holdings(tx, as_of="2025-02-01")
    assert pos.loc["US0378331005", "shares"] == pytest.approx(2.0)


def test_cash_balance(tx):
    assert summary(tx)["cash balance"] == pytest.approx(549.57)


def test_validate_detects_oversell(tx):
    broken = tx.copy()
    broken.loc[broken["transaction_id"] == "t-05", ["shares", "amount"]] = [-5.0, 1000.0]
    assert any("position negative" in issue for issue in validate(broken))


def test_validate_detects_amount_mismatch(tx):
    broken = tx.copy()
    broken.loc[broken["transaction_id"] == "t-03", "amount"] = -300.0
    assert any("shares x price" in issue for issue in validate(broken))


def test_unknown_type_is_flagged(tmp_path, caplog):
    text = SAMPLE.read_text().replace('"CARD_TRANSACTION",', '"SOMETHING_NEW",')
    path = tmp_path / "export.csv"
    path.write_text(text)
    tx = load_transactions(path)
    assert (tx["event"] == "other").sum() == 1
    assert "SOMETHING_NEW" in caplog.text


def test_rejects_foreign_csv(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="missing columns"):
        load_transactions(path)
