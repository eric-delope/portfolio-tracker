"""Look-through of ETFs into their holdings and sectors."""

import pandas as pd
import pytest

from portfolio_tracker.lookthrough import FundProfile, company_key, display_name, look_through


def world_fund() -> FundProfile:
    holdings = pd.DataFrame({"name": ["Microsoft Corp", "Apple Inc", "Alphabet Inc Class A"],
                             "weight": [0.05, 0.05, 0.02]}, index=["MSFT", "AAPL", "GOOGL"])
    return FundProfile(holdings, {"technology": 0.3, "financial_services": 0.2, "healthcare": 0.5})


def positions() -> pd.DataFrame:
    return pd.DataFrame([
        {"name": "Core MSCI World", "ticker": "EUNL.DE", "value": 6000.0, "sector": "ETF", "is_fund": True},
        {"name": "Microsoft", "ticker": "MSFT", "value": 2000.0, "sector": "Technology", "is_fund": False},
        {"name": "SAP", "ticker": "SAP.DE", "value": 2000.0, "sector": "Technology", "is_fund": False},
    ])


@pytest.mark.parametrize("a,b", [("Microsoft Corp", "Microsoft"), ("Alphabet Inc Class A", "Alphabet"),
                                 ("Meta Platforms Inc", "Meta Platforms"), ("ASML Holding N.V.", "ASML")])
def test_company_key_matches_listings(a, b):
    assert company_key(a) == company_key(b)


def test_overlap_adds_direct_and_fund_share():
    lt = look_through(positions(), {"EUNL.DE": world_fund()})
    msft = lt.companies.loc[company_key("Microsoft")]
    assert msft["direct"] == pytest.approx(0.20)
    assert msft["via_funds"] == pytest.approx(0.6 * 0.05)
    assert msft["total"] == pytest.approx(0.23) and msft["sources"] == ["Core MSCI World"]
    assert lt.companies.iloc[0]["name"] == "Microsoft"                      # largest true exposure first


def test_everything_adds_up_to_the_portfolio():
    lt = look_through(positions(), {"EUNL.DE": world_fund()})
    assert lt.companies["total"].sum() + lt.other_fund_share == pytest.approx(1.0)
    assert lt.sectors["total"].sum() == pytest.approx(1.0)
    assert lt.sectors.loc["Technology", "total"] == pytest.approx(0.4 + 0.6 * 0.3)
    assert lt.fund_share == pytest.approx(0.6)


def test_fund_without_data_is_counted_not_dropped():
    lt = look_through(positions(), {})
    assert lt.missing_funds == ["Core MSCI World"]
    assert lt.other_fund_share == pytest.approx(0.6)
    assert lt.companies["total"].sum() + lt.other_fund_share == pytest.approx(1.0)


@pytest.mark.parametrize("raw, short", [("NVIDIA Corp", "NVIDIA"), ("Alphabet Inc Class A", "Alphabet"),
                                        ("Amazon.com Inc", "Amazon.com"), ("Taiwan Semiconductor Manufacturing Co Ltd",
                                                                           "Taiwan Semiconductor Manufacturing"),
                                        ("ASML Holding NV", "ASML"), ("Coca-Cola", "Coca-Cola")])
def test_display_name(raw, short):
    assert display_name(raw) == short
