"""Tests for FIFO, metrics, taxes and the portfolio engine (offline, synthetic prices)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_tracker import metrics as m
from portfolio_tracker.importer import load_transactions
from portfolio_tracker.lots import apply_splits, fifo
from portfolio_tracker.market import BENCHMARKS, PriceData
from portfolio_tracker.portfolio import Portfolio
from portfolio_tracker.taxes import TAX_RATE, latent_tax, yearly_tax_estimate

SAMPLE = Path(__file__).parents[1] / "data" / "sample" / "sample_export.csv"


@pytest.fixture
def tx() -> pd.DataFrame:
    return load_transactions(SAMPLE)


def make_tx(rows: list[dict]) -> pd.DataFrame:
    """Minimal transaction table in the importer's output format."""
    base = {"category": "TRADING", "raw_type": "", "asset_class": "STOCK", "currency": "EUR",
            "savings_plan": False, "fee": 0.0, "tax": 0.0, "price": np.nan, "shares": np.nan}
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["datetime"] = df["date"].dt.tz_localize("UTC")
    df["transaction_id"] = [f"id{i}" for i in range(len(df))]
    df["net_cash"] = df["amount"] + df["fee"] + df["tax"]
    return df


# ------------------------------------------------------------------ FIFO
def test_fifo_consumes_oldest_lot_first():
    tx = make_tx([
        {"date": "2025-01-02", "event": "buy", "isin": "X", "name": "X", "shares": 10, "price": 10, "amount": -100, "fee": -1},
        {"date": "2025-02-03", "event": "buy", "isin": "X", "name": "X", "shares": 10, "price": 20, "amount": -200, "fee": -1},
        {"date": "2025-03-03", "event": "sell", "isin": "X", "name": "X", "shares": -15, "price": 30, "amount": 450, "fee": -1},
    ])
    open_lots, realized = fifo(tx)
    assert len(realized) == 2
    first, second = realized.iloc[0], realized.iloc[1]
    assert first["shares"] == 10 and first["cost"] == pytest.approx(101)       # fee in cost basis
    assert second["shares"] == 5 and second["cost"] == pytest.approx(100.5)
    assert realized["proceeds"].sum() == pytest.approx(449)                    # sell fee reduces proceeds
    assert realized["gain"].sum() == pytest.approx(449 - 101 - 100.5)
    assert open_lots.iloc[0]["shares"] == pytest.approx(5)
    assert open_lots.iloc[0]["cost"] == pytest.approx(100.5)


def test_fifo_rejects_oversell():
    tx = make_tx([
        {"date": "2025-01-02", "event": "buy", "isin": "X", "name": "X", "shares": 1, "price": 10, "amount": -10},
        {"date": "2025-01-03", "event": "sell", "isin": "X", "name": "X", "shares": -2, "price": 10, "amount": 20},
    ])
    with pytest.raises(ValueError, match="sold more"):
        fifo(tx)


def test_apply_splits_restates_shares_and_price():
    tx = make_tx([
        {"date": "2025-01-02", "event": "buy", "isin": "X", "name": "X", "shares": 1, "price": 1000, "amount": -1000},
        {"date": "2025-03-03", "event": "buy", "isin": "X", "name": "X", "shares": 10, "price": 100, "amount": -1000},
    ])
    adj = apply_splits(tx, {"X": pd.Series([10.0], index=[pd.Timestamp("2025-02-01")])})
    assert adj["shares"].tolist() == [10, 10]
    assert adj["price"].tolist() == [100, 100]
    assert adj["amount"].tolist() == [-1000, -1000]


# --------------------------------------------------------------- metrics
def test_xirr_one_year_ten_percent():
    assert m.xirr(["2024-01-01", "2025-01-01"], [-100, 110]) == pytest.approx(0.10, abs=1e-3)


def test_xirr_needs_both_signs():
    assert np.isnan(m.xirr(["2024-01-01", "2025-01-01"], [-100, -10]))


def test_drawdown_info():
    r = pd.Series([0.10, -0.50, 0.0, 1.20], index=pd.bdate_range("2025-01-01", periods=4))
    info = m.max_drawdown_info(r)
    assert info["depth"] == pytest.approx(-0.5)
    assert info["peak"] == r.index[0] and info["trough"] == r.index[1]
    assert info["recovery"] == r.index[3]


def test_beta_of_scaled_series_is_scale():
    rng = np.random.default_rng(0)
    b = pd.Series(rng.normal(0, 0.01, 300), index=pd.bdate_range("2024-01-01", periods=300))
    beta, _ = m.beta_alpha(2 * b, b)
    assert beta == pytest.approx(2.0)


def test_risk_contributions_sum_to_one():
    rng = np.random.default_rng(1)
    r = pd.DataFrame(rng.normal(0, 0.01, (250, 3)), columns=list("ABC"))
    rc = m.risk_contributions(pd.Series({"A": 0.5, "B": 0.3, "C": 0.2}), r)
    assert rc["risk_contribution"].sum() == pytest.approx(1.0)


def test_effective_positions():
    assert m.effective_positions(pd.Series([1, 1, 1, 1])) == pytest.approx(4)
    assert m.effective_positions(pd.Series([1, 0, 0])) == pytest.approx(1)


def test_weekly_compounding():
    idx = pd.bdate_range("2025-01-06", periods=5)  # Mon-Fri
    w = m.to_weekly(pd.Series([0.1] * 5, index=idx))
    assert w.iloc[0] == pytest.approx(1.1**5 - 1)


# ----------------------------------------------------------------- taxes
def test_stock_losses_only_offset_stock_gains():
    tx = make_tx([{"date": "2025-06-01", "event": "interest", "isin": None, "name": None, "amount": 2000.0}])
    realized = pd.DataFrame({
        "asset_class": ["STOCK"], "gain": [-500.0], "sell_date": [pd.Timestamp("2025-05-01")],
    })
    est = yearly_tax_estimate(tx, realized).loc[2025]
    assert est["stock_loss_carryforward"] == pytest.approx(-500)          # not used against interest
    assert est["estimated_tax"] == pytest.approx((2000 - 1000) * TAX_RATE)


def test_fund_gains_partially_exempt():
    tx = make_tx([{"date": "2025-06-01", "event": "interest", "isin": None, "name": None, "amount": 0.0}])
    realized = pd.DataFrame({
        "asset_class": ["FUND"], "gain": [3000.0], "sell_date": [pd.Timestamp("2025-05-01")],
    })
    est = yearly_tax_estimate(tx, realized).loc[2025]
    assert est["fund_gains_taxable"] == pytest.approx(2100)
    assert est["estimated_tax"] == pytest.approx(1100 * TAX_RATE)


def test_latent_tax():
    lots = pd.DataFrame({"isin": ["A", "F"], "name": ["A", "F"], "asset_class": ["STOCK", "FUND"],
                         "shares": [1.0, 1.0], "cost": [100.0, 100.0]})
    lt = latent_tax(lots, pd.Series({"A": 200.0, "F": 200.0}))
    assert lt.loc["A", "latent_tax"] == pytest.approx(100 * TAX_RATE)
    assert lt.loc["F", "latent_tax"] == pytest.approx(70 * TAX_RATE)


# ------------------------------------------------------- portfolio engine
class FakeMarket:
    """Deterministic prices: Apple +0.1 %/day from 180, MSCI World flat, benchmarks +0.05 %/day."""

    def resolve_tickers(self, isins):
        return {"US0378331005": "AAPL", "IE00BFY0GT14": "SPPW.DE"}

    def metadata(self, tickers):
        return pd.DataFrame({"currency": ["USD", "EUR"], "sector": ["Technology", None],
                             "country": ["United States", None]}, index=["AAPL", "SPPW.DE"])

    def splits(self, tickers):
        return {t: pd.Series(dtype=float) for t in tickers}

    def prices(self, tickers, start, currencies):
        idx = pd.bdate_range("2024-12-02", "2025-06-30")
        n = np.arange(len(idx))
        fx = pd.DataFrame({"USD": 1.0, "EUR": 1.0}, index=idx)
        local = pd.DataFrame({"AAPL": 180 * 1.001**n, "SPPW.DE": 37.5}, index=idx)
        for tk in BENCHMARKS.values():
            local[tk] = 100 * 1.0005**n
        return PriceData(eur=local.copy(), local=local, fx=fx, currency=currencies)


@pytest.fixture
def portfolio(tx) -> Portfolio:
    return Portfolio.build(tx, FakeMarket())


def test_pnl_identity(portfolio):
    d = portfolio.daily
    assert d["pnl"].iloc[-1] == pytest.approx(portfolio.position_pnl.iloc[-1].sum())
    assert d["pnl"].iloc[-1] == pytest.approx(
        d["value"].iloc[-1] + d["outflow"].sum() - d["inflow"].sum())


def test_positions_match_holdings(portfolio):
    pos = portfolio.positions
    assert pos.loc["US0378331005", "shares"] == pytest.approx(1.0)
    assert pos.loc["IE00BFY0GT14", "shares"] == pytest.approx(4.04)
    assert pos["weight"].sum() == pytest.approx(1.0)


def test_unrealized_plus_realized_plus_dividends_equals_total(portfolio):
    pos = portfolio.positions.loc["US0378331005"]
    assert pos["total_pnl"] == pytest.approx(pos["unrealized"] + pos["realized"] + pos["dividends"])


def test_twr_ignores_cash_flows():
    """A flat-priced asset must show 0 % TWR no matter how much money flows in."""
    tx = make_tx([
        {"date": "2025-01-02", "event": "buy", "isin": "IE00BFY0GT14", "name": "W", "asset_class": "FUND",
         "shares": 1, "price": 37.5, "amount": -37.5},
        {"date": "2025-03-03", "event": "buy", "isin": "IE00BFY0GT14", "name": "W", "asset_class": "FUND",
         "shares": 100, "price": 37.5, "amount": -3750},
    ])
    p = Portfolio.build(tx, FakeMarket())
    assert m.total_return(p.daily["return"]) == pytest.approx(0.0, abs=1e-12)


def test_twr_matches_price_return_for_single_buy():
    k = pd.bdate_range("2024-12-02", "2025-06-30").get_loc(pd.Timestamp("2025-01-02"))
    price = 180 * 1.001**k  # buy exactly at the fake close of that day
    tx = make_tx([{"date": "2025-01-02", "event": "buy", "isin": "US0378331005", "name": "A",
                   "shares": 1, "price": price, "amount": -price}])
    p = Portfolio.build(tx, FakeMarket())
    days_after = len(p.index) - 1
    assert m.total_return(p.daily["return"]) == pytest.approx(1.001**days_after - 1, rel=1e-6)


def test_shadow_portfolio_equals_actual_when_holding_benchmark_like_asset(portfolio):
    shadow = portfolio.shadow_portfolio("MSCI World")
    assert shadow["shadow"].iloc[-1] > 0
    assert set(shadow.columns) == {"actual", "shadow"}


def test_sell_analysis_and_trade_stats(portfolio):
    s = portfolio.sell_analysis
    assert len(s) == 1
    assert s.iloc[0]["gain"] == pytest.approx(199 - 180.5)  # proceeds after fee - FIFO cost (361 / 2 shares)
    stats = portfolio.trade_statistics()
    assert stats["hit_rate"] == 1.0


def test_period_summary_short_period_not_annualized(portfolio):
    s = portfolio.period_summary(portfolio.period_start("3m"))
    assert s["annualize"] is False


# ------------------------------------------------------- reporting currency
class DollarMarket(FakeMarket):
    """Same prices, but the euro strengthens steadily from 1.00 to ~1.15 dollars."""

    def __init__(self, drift: float = 0.001):
        self.drift = drift

    def prices(self, tickers, start, currencies):
        data = super().prices(tickers, start, currencies)
        data.fx["USD"] = (1 + self.drift) ** np.arange(len(data.fx))
        return data


def test_reporting_currency_converts_at_daily_rates(tx):
    p = Portfolio.build(tx, DollarMarket())
    u = p.in_currency("USD")
    fx = p.prices.fx["USD"].reindex(p.index).ffill()
    assert u.base == "USD" and u.in_currency("EUR") is p and u.in_currency("USD") is u
    assert np.allclose(u.daily["value"], p.daily["value"] * fx)
    assert u.cash_balance.iloc[-1] == pytest.approx(p.cash_balance.iloc[-1] * fx.iloc[-1])
    # accounting identity still holds in dollars
    d = u.daily
    assert d["value"].iloc[-1] + d["outflow"].sum() - d["inflow"].sum() == pytest.approx(d["pnl"].iloc[-1], abs=1e-6)


def test_constant_rate_changes_amounts_not_returns(tx):
    p = Portfolio.build(tx, DollarMarket(drift=0.0))
    u = p.in_currency("USD")
    assert u.daily["value"].iloc[-1] == pytest.approx(p.daily["value"].iloc[-1])   # rate 1.0 throughout
    p2 = Portfolio.build(tx, DollarMarket(drift=0.0))
    p2.prices.fx["USD"] = 1.10
    u2 = p2.in_currency("USD")
    assert u2.daily["value"].iloc[-1] == pytest.approx(p2.daily["value"].iloc[-1] * 1.10)
    assert m.cumulative(u2.returns(p2.index[0])).iloc[-1] == pytest.approx(m.cumulative(p2.returns(p2.index[0])).iloc[-1])


def test_stronger_euro_raises_dollar_returns(tx):
    p = Portfolio.build(tx, DollarMarket(drift=0.001))
    u = p.in_currency("USD")
    assert m.cumulative(u.returns(u.index[0])).iloc[-1] > m.cumulative(p.returns(p.index[0])).iloc[-1]


def test_reporting_currency_without_rates_raises_clearly():
    tx = load_transactions(SAMPLE)
    p = Portfolio.build(tx, FakeMarket())
    p.prices.fx["USD"] = float("nan")
    with pytest.raises(ValueError, match="exchange rates"):
        p.in_currency("USD")


def test_price_cache_keeps_symbols_the_provider_skipped(tmp_path):
    from portfolio_tracker.market import MarketData

    idx = pd.bdate_range("2026-01-01", periods=5)
    good = pd.DataFrame({"AAA": range(5), "EURUSD=X": [1.1] * 5}, index=idx, dtype=float)

    class Yahoo:
        def __init__(self, frame):
            self.frame = frame

        def download(self, symbols, **_):
            return {"Close": self.frame.reindex(columns=symbols)}

    m = MarketData(tmp_path)
    m._yf = Yahoo(good)
    m._download(["AAA", "EURUSD=X"], idx[0])
    m._yf = Yahoo(good.assign(**{"EURUSD=X": float("nan")}, BBB=1.0))
    out = m._download(["AAA", "BBB", "EURUSD=X"], idx[0])   # new symbol forces a fresh download
    assert out["EURUSD=X"].notna().all()                     # skipped symbol keeps its last good history
    assert out["BBB"].notna().all()


def test_price_cache_serves_portfolios_with_different_start_dates(tmp_path):
    from portfolio_tracker.market import MarketData

    idx = pd.bdate_range("2023-01-02", "2026-01-30")
    full = pd.DataFrame({"AAA": 1.0, "BBB": 2.0, "EURUSD=X": 1.1}, index=idx)
    calls = []

    class Yahoo:
        def download(self, symbols, start, **_):
            calls.append((tuple(symbols), pd.Timestamp(start)))
            return {"Close": full.loc[start:, symbols]}

    m = MarketData(tmp_path)
    m._yf = Yahoo()
    old_start, new_start = pd.Timestamp("2023-02-01"), pd.Timestamp("2025-02-01")
    m._download(["AAA", "EURUSD=X"], old_start)            # e.g. the demo, since 2023
    m._download(["BBB", "EURUSD=X"], new_start)            # e.g. your export, since 2025
    out = m._download(["AAA", "EURUSD=X"], old_start)      # back to the demo: served from cache, full history
    assert len(calls) == 2
    assert calls[1][1] == old_start                         # EURUSD=X was reloaded from the earliest start
    assert out.loc[old_start:, "EURUSD=X"].notna().all() and out.loc[old_start:, "AAA"].notna().all()
