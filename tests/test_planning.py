"""Tests for valuation models, watchlist alerts and the monthly report."""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_analytics import SAMPLE, FakeMarket

from portfolio_tracker import valuation as v
from portfolio_tracker.importer import load_transactions
from portfolio_tracker.portfolio import Portfolio
from portfolio_tracker.report import available_months, build_report, merge_notes, to_markdown
from portfolio_tracker.watchlist import Alert, Entry, Watchlist, alert_status, mark_triggered


# -------------------------------------------------------------- valuation
def test_eps_model_by_hand():
    # EPS 10 growing 10 % for 5 years = 16.105; x P/E 20 = 322.1; discounted at 10 % = 200
    target = v.eps_target(10, 0.10, 20, 5)
    assert target == pytest.approx(10 * 1.1**5 * 20)
    assert v.present_value(target, 0.10, 5) == pytest.approx(200.0)


def test_buying_at_fair_value_earns_required_return():
    fair = v.present_value(v.eps_target(5, 0.08, 18, 5), 0.09, 5)
    target = fair * 1.09**5
    assert v.implied_return(fair, target, 5) == pytest.approx(0.09)


def test_scenario_weighting():
    sv = v.scenario_valuation(10, [v.Scenario("Bear", 1, 0.0, 10), v.Scenario("Bull", 1, 0.0, 30)], 1, 0.0)
    assert sv.loc["Expected", "fair_value"] == pytest.approx(200)   # 50/50 of 100 and 300
    assert sv.loc["Bear", "probability"] == pytest.approx(0.5)            # normalized


def test_dcf_without_growth_is_perpetuity():
    # zero growth everywhere: value = FCF / r
    res = v.dcf_value(10, 0.0, 0.10, 0.0, years=5, fade_years=5)
    assert res["value"] == pytest.approx(100.0)


def test_dcf_rejects_terminal_growth_above_discount_rate():
    with pytest.raises(ValueError):
        v.dcf_value(10, 0.05, 0.03, 0.04)


def test_reverse_dcf_recovers_growth():
    value = v.dcf_value(5, 0.12, 0.09, 0.025)["value"]
    assert v.reverse_dcf(value, 5, 0.09, 0.025) == pytest.approx(0.12, abs=1e-6)


def test_entry_ladder():
    lad = v.entry_ladder(100, [0.1, 0.2], [1, 3], 1000, 0.10, 5, fx_to_eur=1.25)
    assert lad["price"].tolist() == pytest.approx([90, 80])
    assert lad["price_eur"].tolist() == pytest.approx([72, 64])
    assert lad["amount_eur"].tolist() == pytest.approx([250, 750])
    assert lad["expected_return"].iloc[1] > lad["expected_return"].iloc[0] > 0.10


def test_sensitivity_monotonic():
    grid = v.sensitivity(10, 5, 0.1, [0.0, 0.1], [10, 20])
    assert grid.loc[0.1, 20] > grid.loc[0.1, 10] > grid.loc[0.0, 10]


def test_historical_pe_uses_last_reported_eps():
    prices = pd.Series([100.0, 120.0], index=pd.to_datetime(["2024-06-01", "2025-06-01"]))
    eps = pd.Series([5.0, 6.0], index=pd.to_datetime(["2023-12-31", "2024-12-31"]))
    pe = v.historical_pe(prices, eps)
    assert pe.tolist() == pytest.approx([20.0, 20.0])


# --------------------------------------------------------------- watchlist
def test_watchlist_roundtrip(tmp_path):
    path = tmp_path / "wl.json"
    wl = Watchlist(path)
    wl.upsert(Entry("ASML.AS", "ASML", "EUR", fair_value=700, alerts=[Alert(630, "T1"), Alert(560, "T2")]))
    wl.save()
    again = Watchlist(path)
    assert again.entries["ASML.AS"].alerts[1].price == 560
    assert again.entries["ASML.AS"].fair_value == 700


def test_upsert_keeps_thesis_and_added_date(tmp_path):
    wl = Watchlist(tmp_path / "wl.json")
    wl.upsert(Entry("X", "X", "USD", added="2026-01-01", thesis="Moat"))
    wl.upsert(Entry("X", "X", "USD", fair_value=10))
    assert wl.entries["X"].thesis == "Moat" and wl.entries["X"].added == "2026-01-01"


def test_alert_states_and_trigger_once(tmp_path):
    wl = Watchlist(tmp_path / "wl.json")
    wl.upsert(Entry("X", "X", "USD", alerts=[Alert(100, "T1"), Alert(90, "T2"), Alert(150, "TP", direction="above")]))
    st = alert_status(wl, {"X": 98.0}).set_index("label")
    assert st.loc["T1", "state"] == "hit"
    assert st.loc["T2", "state"] == "waiting"           # 98 is 8.9 % above 90
    assert st.loc["TP", "state"] == "waiting"
    first = mark_triggered(wl, {"X": 98.0}, now=datetime(2026, 10, 1))
    second = mark_triggered(wl, {"X": 97.0}, now=datetime(2026, 10, 2))
    assert [a.label for _, a in first] == ["T1"] and second == []
    assert wl.entries["X"].alerts[0].triggered_at.startswith("2026-10-01")


def test_near_state():
    wl = Watchlist(Path("/nonexistent/wl.json"))
    wl.upsert(Entry("X", "X", "USD", alerts=[Alert(100, "T1")]))
    assert alert_status(wl, {"X": 104.0}).iloc[0]["state"] == "near"


# ------------------------------------------------------------------ report
@pytest.fixture
def portfolio() -> Portfolio:
    return Portfolio.build(load_transactions(SAMPLE), FakeMarket())


def test_month_report_pnl_adds_up(portfolio):
    months = available_months(portfolio)
    total = sum(build_report(portfolio, mo).pnl for mo in months)
    assert total == pytest.approx(portfolio.daily["pnl"].iloc[-1])


def test_month_report_twr_compounds_to_total(portfolio):
    months = sorted(available_months(portfolio))
    chained = np.prod([1 + build_report(portfolio, mo).twr for mo in months]) - 1
    assert chained == pytest.approx((1 + portfolio.daily["return"]).prod() - 1)


def test_month_report_trades(portfolio):
    rep = build_report(portfolio, pd.Period("2025-01", "M"))
    assert rep.flows["orders"] == 2 and rep.flows["deposits"] == pytest.approx(1000)
    assert "Monthly report January 2025" in to_markdown(rep)


def test_merge_notes_keeps_user_text():
    old = "# Old\n\n## Notes\n\n- My thoughts\n"
    new = "# New\n\nFigures\n\n## Notes\n\n- \n"
    merged = merge_notes(new, old)
    assert merged.startswith("# New") and "My thoughts" in merged


# -------------------------------------------------------- valuation (v2)
def test_year1_eps_path():
    assert v.eps_path(10, 0.10, 3) == pytest.approx([11, 12.1, 13.31])
    assert v.eps_path(10, 0.10, 3, eps1=12) == pytest.approx([12, 13.2, 14.52])


def test_dividends_raise_fair_value_and_keep_consistency():
    no_div = v.scenario_valuation(10, [v.Scenario("x", 1, 0.05, 15)], 5, 0.09)
    with_div = v.scenario_valuation(10, [v.Scenario("x", 1, 0.05, 15)], 5, 0.09, dividend0=3)
    assert with_div.loc["x", "fair_value"] > no_div.loc["x", "fair_value"]
    fair = with_div.loc["Expected", "fair_value"]
    future = v.future_price(fair, 0.09, 5, with_div.loc["Expected", "pv_dividends"])
    # buying at fair value with dividends still earns exactly the required return
    assert v.total_return_irr(fair, with_div.attrs["dividends"], future) == pytest.approx(0.09, abs=1e-6)


def test_total_return_irr_without_dividends_equals_cagr():
    assert v.total_return_irr(100, [0, 0, 0], 133.1) == pytest.approx(0.10)


# ------------------------------------------------------------- signals
def test_signal_buy_hold_trim():
    from portfolio_tracker.watchlist import signal
    e = Entry("X", "X", "USD", fair_value=100, alerts=[Alert(90, "T1"), Alert(130, "R1", direction="above")])
    assert signal(e, 85)[0] == "buy"
    assert signal(e, 100)[0] == "hold"
    assert signal(e, 135)[0] == "hold"                  # not held: nothing to reduce
    assert signal(e, 135, weight=0.1)[0] == "trim"      # held and above the sell line
    assert signal(e, 85, weight=0.25)[0] == "hold"     # buy zone, but position limit reached
    assert signal(e, 85, thesis_ok=False)[0] == "review"
    assert signal(None, 85)[0] == "none"


def test_signal_trim_when_expected_return_below_floor():
    from datetime import date as d

    from portfolio_tracker.watchlist import signal
    e = Entry("X", "X", "USD", fair_value=100, target_price=110, horizon_years=5, required_return=0.10,
              valuation_date=d.today().isoformat())
    assert e.expected_return(105) < 0.04
    assert signal(e, 105, weight=0.1)[0] == "trim"
    assert signal(e, 60, weight=0.1)[0] == "buy"        # 60 -> 110 in 5 years is > 12 % p. a.


def test_valuation_history_one_snapshot_per_day(tmp_path):
    wl = Watchlist(tmp_path / "wl.json")
    wl.upsert(Entry("X", "X", "USD", fair_value=100, valuation_date="2026-09-01"))
    wl.upsert(Entry("X", "X", "USD", fair_value=110, valuation_date="2026-10-01"))
    wl.upsert(Entry("X", "X", "USD", fair_value=120, valuation_date="2026-10-01"))
    assert [h["fair_value"] for h in wl.entries["X"].history] == [100, 120]


# ------------------------------------------------------------- quality
def test_quality_checks():
    from portfolio_tracker.quality import quality_checks, quality_score
    idx = pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31"])
    annual = pd.DataFrame({"revenue": [100, 110, 121], "operating_income": [20, 22, 25], "net_income": [10, 11, 12],
                           "fcf": [9, 10, 11], "eps": [1.0, 1.1, 1.2], "shares": [10, 10, 9.8]}, index=idx)
    checks = {c.name: c for c in quality_checks(annual, net_debt=-5, ebitda=30, roe=0.2)}
    assert checks["Revenue growth"].passed is True
    assert checks["Leverage"].value == "Net cash"
    assert checks["Share count"].passed is True
    assert quality_score(list(checks.values()))[2] == "high"
    assert quality_checks(pd.DataFrame(), None, None, None)[0].passed is None


# ------------------------------------------------------------ decisions
def test_scorecard_signs(portfolio):
    from portfolio_tracker import decisions
    sc = decisions.scorecard(portfolio, "MSCI World", horizons={"1M": 21})
    # Fake prices: Apple +0.1 %/day, benchmark +0.05 %/day -> buying Apple beats the market, selling it lags
    apple = sc[sc["isin"] == "US0378331005"].set_index("event")
    assert apple.loc["buy", "edge_1M"] > 0
    assert apple.loc["sell", "edge_1M"] < 0
    summary = decisions.summarize(sc, "1M")
    assert summary.loc["Sell", "verdict"] == "too little data"


# ----------------------------------------------------------- order check
def test_order_check_new_position():
    from portfolio_tracker.ordercheck import OrderInputs, simulate
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2025-01-01", periods=260)
    rets = pd.DataFrame(rng.normal(0, 0.01, (260, 3)), index=idx, columns=["A", "B", "NEW"])
    inp = OrderInputs(values=pd.Series({"A": 600.0, "B": 400.0}), returns=rets,
                      meta=pd.DataFrame({"name": ["A", "B", "New"], "sector": ["Tech", "Health", "Tech"],
                                         "currency": ["USD", "EUR", "USD"]}, index=["A", "B", "NEW"]),
                      benchmark=rets.mean(axis=1))
    before, after, hints = simulate(inp, "NEW", 1000)
    assert before["weight"] == 0 and after["weight"] == pytest.approx(0.5)
    assert after["sector_share"] == pytest.approx(0.8)            # A + NEW are Tech
    assert before["sector_share"] == pytest.approx(0.6)           # A alone, before NEW is bought
    assert any("limit 20%" in t for _, t in hints)
    assert any("Sector" in t for _, t in hints)


# ------------------------------------------------------- long-term entries
def test_fair_value_rolls_forward_with_required_return():
    assert v.fair_value_at(100, 0.10, 1.0) == pytest.approx(110)
    assert v.fair_value_at(100, 0.10, 1.0, dividends=[5]) == pytest.approx(105)   # dividend paid out at year 1
    assert v.fair_value_at(100, 0.10, 0.0) == pytest.approx(100)


def test_price_for_return_inverts_irr():
    flows = v.remaining_flows(target=200, horizon=5, years_elapsed=0, dividends=[2, 2, 2, 2, 2])
    price = v.price_for_return(flows, 0.04)
    assert v.irr_times(price, flows) == pytest.approx(0.04, abs=1e-6)


def test_remaining_flows_after_one_year():
    flows = v.remaining_flows(target=150, horizon=5, years_elapsed=1.0, dividends=[1, 2, 3, 4, 5])
    assert flows[0] == (pytest.approx(1.0), 2)          # year-1 dividend already paid
    assert flows[-1] == (pytest.approx(4.0), 150)


def test_hit_probability_on_known_path():
    # steady decline of 1 % per day: every start day sees a 10 % drop within 252 days
    falling = pd.Series(100 * 0.99 ** np.arange(600), index=pd.bdate_range("2020-01-01", periods=600))
    assert v.hit_probability(falling, 0.10) == pytest.approx(1.0)
    rising = pd.Series(100 * 1.01 ** np.arange(600), index=falling.index)
    assert v.hit_probability(rising, 0.10) == pytest.approx(0.0)
    assert v.hit_probability(rising, 0.0) == 1.0


def test_percentile_and_zone():
    hist = pd.Series(range(1, 101), dtype=float)
    assert v.percentile_rank(hist, 25.5) == pytest.approx(0.25)
    assert v.valuation_zone(0.25) == "lower third"
    assert v.valuation_zone(0.9) == "upper third"


def test_rolled_alerts_grow_with_fair_value():
    from datetime import date as d
    from datetime import timedelta
    one_year_ago = (d.today() - timedelta(days=365)).isoformat()
    e = Entry("X", "X", "USD", fair_value=100, required_return=0.10, valuation_date=one_year_ago,
              alerts=[Alert(90, "T1", rel_to_fair=-0.10), Alert(80, "manuell")])
    rolls = e.rolled_alerts()
    assert len(rolls) == 1                                  # only alerts linked to fair value move
    assert rolls[0][1] == pytest.approx(99.0, rel=0.01)     # 110 * 0.9


# ------------------------------------------------------------------ thesis
def test_thesis_evaluation():
    from portfolio_tracker import thesis as th
    from portfolio_tracker.research import Fundamentals
    f = Fundamentals(ticker="X", name="X", currency="USD", financial_currency="USD", price=10, shares=1,
                     market_cap=None, enterprise_value=None, sector=None, industry=None, country=None, summary=None,
                     eps_ttm=1, eps_forward=1, pe_ttm=10, pe_forward=10, fcf=1, revenue=10, net_debt=-1,
                     profit_margin=0.1, roe=0.2, dividend_rate=None, operating_margin=0.3, ebitda=3, revenue_growth=0.12)
    res = th.evaluate([{"metric": "Revenue growth", "operator": ">=", "threshold": 0.10},
                       {"metric": "Operating margin", "operator": ">=", "threshold": 0.35}], f)
    assert [r.ok for r in res] == [True, False]
    assert th.status(res) == "broken"
    assert th.status(th.evaluate([{"metric": "Revenue growth", "operator": ">=", "threshold": 0.1}], f)) == "intact"
    assert th.status([]) == "no KPIs"


# ----------------------------------------------------------------- ranking
def test_opportunity_ranking_verdicts(tmp_path):
    from datetime import date as d

    from portfolio_tracker.opportunities import rank
    today = d.today().isoformat()
    wl = Watchlist(tmp_path / "wl.json")
    wl.upsert(Entry("CHEAP", "Cheap", "USD", fair_value=100, target_price=161, horizon_years=5, required_return=0.10,
                    valuation_date=today))
    wl.upsert(Entry("FAIR", "Fair", "USD", fair_value=100, target_price=161, horizon_years=5, required_return=0.10,
                    valuation_date=today))
    wl.upsert(Entry("RICH", "Rich", "USD", fair_value=100, target_price=161, horizon_years=5, required_return=0.10,
                    valuation_date=today))
    r = rank(wl, {"CHEAP": 70, "FAIR": 105, "RICH": 150}, context={"CHEAP": {"thesis": "intact"}})
    assert list(r["ticker"]) == ["CHEAP", "FAIR", "RICH"]
    assert r.set_index("ticker").loc["CHEAP", "verdict"] == "Buy"   # 30% under fair value: default buy zone
    assert r.set_index("ticker").loc["FAIR", "verdict"] == "Watch"     # ~8.9% p.a. < 10% target
    assert r.set_index("ticker").loc["RICH", "verdict"] == "Avoid"   # ~1.4% p.a. < 2% risk-free
    broken = rank(wl, {"CHEAP": 70}, context={"CHEAP": {"thesis": "broken"}})
    assert broken.iloc[0]["verdict"] == "Avoid"


# ------------------------------------------------------------ entry quality
def test_entry_quality(portfolio):
    from portfolio_tracker import decisions
    eq = decisions.entry_quality(portfolio, window_days=21, dca_days=10)
    apple = eq[eq["isin"] == "US0378331005"].iloc[0]
    # fake Apple rises every day: buying at the start of the window is the cheapest point
    assert apple["range_position"] == pytest.approx(0.0, abs=0.05)
    assert apple["vs_dca"] < 0
    s = decisions.entry_summary(eq)
    assert s["n"] == len(eq)


def test_verdict_savings_plan_mode():
    from portfolio_tracker.opportunities import _verdict
    assert _verdict(0.12, 0.10, 0.02, "high", None, "intact", in_zone=False) == "Savings plan"
    assert _verdict(0.12, 0.10, 0.02, "high", None, "intact", in_zone=True, pe_percentile=0.8) == "Savings plan"
    assert _verdict(0.12, 0.10, 0.02, "high", None, "intact", in_zone=True, pe_percentile=0.2) == "Buy"
    assert _verdict(0.12, 0.10, 0.02, "low", None, None, in_zone=True) == "Buy (small)"


def test_recommend_margin_scales_with_quality():
    from portfolio_tracker.quality import recommend_margin
    best = recommend_margin(1.0, 2, 2, 2)
    worst = recommend_margin(0.0, 0, 0, 0)
    mid = recommend_margin(0.5, 1, 1, 1)
    assert best["margin_of_safety"] == pytest.approx(0.10) and best["required_return"] == pytest.approx(0.09)
    assert worst["margin_of_safety"] == pytest.approx(0.30) and worst["required_return"] == pytest.approx(0.12)
    assert best["label"] == "high" and worst["label"] == "low" and mid["label"] == "medium"


# ------------------------------------------------------------- reverse DCF
def test_reverse_dcf_flat_business_is_cash_yield():
    from portfolio_tracker import reverse_dcf as r
    # no growth, constant 10 % margin on 100 revenue -> 10 per year for 40 years; at a price equal to the
    # 40-year annuity at 8 %, the implied return must be 8 %
    a = r.Assumptions(0.0, 0.10, growth_6_10=0.0, growth_11_20=0.0, mature_growth=0.0, life_years=40)
    price = sum(10 / 1.08 ** t for t in range(1, 41))
    assert r.implied_return(price, 100, 0.10, a) == pytest.approx(0.08, abs=1e-6)


def test_reverse_dcf_grid_monotonic_and_implied_growth_consistent():
    from portfolio_tracker import reverse_dcf as r
    grid = r.scenario_grid(1000, 100, 0.15, [0.0, 0.05, 0.10], [0.10, 0.20])
    assert grid.loc[0.10, 0.20] > grid.loc[0.05, 0.20] > grid.loc[0.0, 0.20]   # more growth -> more return
    assert grid.loc[0.05, 0.20] > grid.loc[0.05, 0.10]                         # more margin -> more return
    g = r.implied_growth(1000, 100, 0.15, 0.20, hurdle=0.09)
    assert r.implied_return(1000, 100, 0.15, r.Assumptions(g, 0.20)) == pytest.approx(0.09, abs=1e-6)


def test_margin_ramps_to_target():
    from portfolio_tracker import reverse_dcf as r
    cf = r.cash_flows(100, 0.10, r.Assumptions(0.0, 0.20, ramp_years=5))
    assert cf.loc[1, "margin"] == pytest.approx(0.12)
    assert cf.loc[5, "margin"] == pytest.approx(0.20) and cf.loc[30, "margin"] == pytest.approx(0.20)


# ---------------------------------------------------------------- guidance
def test_guidance_extraction_from_press_release_text():
    from portfolio_tracker.guidance import Release, extract_outlook, revenue_guidance
    text = ("Second Quarter 2026 Results. Revenue was $58.8 billion. CFO Outlook Commentary We expect third quarter "
            "2026 total revenue to be in the range of $61-64 billion. We now expect full year 2026 total expenses to "
            "be in the range of $165-169 billion, narrowed from our prior outlook of $160-170 billion. We expect our "
            "tax rate to be between 15-17%. Webcast and Conference Call Information follows.")
    section, sentences, items = extract_outlook(text)
    assert section.startswith("CFO Outlook Commentary")
    labels = {i.label: (i.low, i.high, i.unit) for i in items}
    assert labels["third quarter 2026 total revenue"] == (61, 64, "billion")
    assert labels["full year 2026 total expenses"] == (165, 169, "billion")
    assert not any("prior" in k for k in labels)
    rel = Release(date=None, form="8-K", url="", outlook_text=section, sentences=sentences, items=items)
    assert revenue_guidance(rel).label == "third quarter 2026 total revenue"


def test_guidance_euro_range_and_track_record():
    from datetime import date as d

    from portfolio_tracker.guidance import Release, extract_outlook, track_record
    _, s1, items = extract_outlook("Outlook: ASML expects Q3 total net sales to be between €7.4 billion and €7.9 billion. "
                                   "Forward-Looking Statements")
    assert (items[0].low, items[0].high, items[0].currency) == (7.4, 7.9, "€")
    rel = Release(date=d(2025, 7, 16), form="6-K", url="", outlook_text="", sentences=s1, items=items)
    q = pd.Series([7.0e9, 8.1e9], index=pd.to_datetime(["2025-06-30", "2025-09-30"]))
    tr = track_record([rel], q)
    assert tr.iloc[0]["result"] == "above range" and tr.iloc[0]["quarter_end"] == d(2025, 9, 30)


def test_reverse_dcf_reinvestment_lowers_cash_flow_and_return():
    from portfolio_tracker import reverse_dcf as r
    plain = r.Assumptions(0.10, 0.20)
    funded = r.Assumptions(0.10, 0.20, sales_to_capital=2.0)
    cf = r.cash_flows(100, 0.20, funded)
    assert cf.loc[1, "reinvestment"] == pytest.approx(10 / 2.0)   # revenue +10 funded at 2 € sales per € capital
    assert r.implied_return(500, 100, 0.20, funded) < r.implied_return(500, 100, 0.20, plain)


def test_dividend_forecast_repeats_last_pattern(portfolio):
    from portfolio_tracker import dividends as dv
    hist = {"AAPL": pd.Series([0.25, 0.25, 0.25, 0.25],
                              index=pd.to_datetime(["2024-08-01", "2024-11-01", "2025-02-01", "2025-05-01"]))}
    per_pos, upcoming = dv.forecast(portfolio, hist)
    apple = per_pos.loc["US0378331005"]
    assert apple["payments_per_year"] == 4                       # all four within the last year
    assert apple["income"] == pytest.approx(1.0 * 1.0)           # 1 share x 1.00 per year (fx 1.0 in the fake)
    assert len(upcoming) >= 3 and upcoming["date"].min() > portfolio.last_date
    assert dv.received(portfolio)["gross"].sum() == pytest.approx(0.8)


def test_guidance_ignores_legal_boilerplate():
    from portfolio_tracker.guidance import extract_outlook
    _, sentences, items = extract_outlook(
        "Guidance The following forward-looking statements reflect our expectations as of July 30, 2026 and are "
        "subject to substantial uncertainty. Net sales are expected to be between $174.0 billion and $179.5 billion. "
        "Webcast information follows.")
    assert all("forward-looking" not in s_ for s_ in sentences)
    assert (items[0].low, items[0].high) == (174.0, 179.5)


def test_guidance_growth_uses_quarter_after_release_even_if_data_lags():
    from datetime import date as d

    from portfolio_tracker.guidance import GuidanceItem, implied_growth
    # data ends one quarter early (Q2 2026 missing), release on 30 July 2026 guides Q3 2026
    q = pd.Series([167.7e9, 180.2e9, 213.4e9, 181.5e9],
                  index=pd.to_datetime(["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]))
    item = GuidanceItem("Third Quarter 2026 Net sales", 197.0, 202.0, "billion", "$")
    growth, basis = implied_growth(item, d(2026, 7, 30), q, pd.Series(dtype=float))
    assert growth == pytest.approx(199.5 / 180.2 - 1)      # vs. Q3 2025, not Q2 2025


# ------------------------------------------------------------ investment memo
def test_investment_memo_pdf():
    from portfolio_tracker.memo import Memo, build_pdf
    prices = pd.Series(np.linspace(80, 120, 300), index=pd.bdate_range("2024-10-01", periods=300))
    scen = pd.DataFrame({"Scenario": ["Bear", "Base", "Bull"], "Probability %": [25.0, 50.0, 25.0],
                         "EPS growth % p.a.": [4.0, 10.0, 15.0], "Exit P/E": [16.0, 20.0, 24.0]})
    memo = Memo(name="Example & Co <AG>", ticker="EXA.DE", currency="EUR", price=118.0, fair_value=130.0, max_price=110.5,
                expected_return=0.11, required_return=0.10, margin_of_safety=0.15, horizon=5,
                verdict="Between maximum price and fair value – savings plan only.", thesis="Durable moat.",
                quality=[("Revenue growth", "+9.5% p.a.", "passed")], quality_verdict="high",
                growth=[("Analysts (next FY)", "+10.0%")], scenarios=scen, bridge=[("Fair value", "130.00 EUR")],
                reverse_dcf=[("Priced-in growth", "+8.0% p.a.")], tranches=[("Tranche 1 (−15%)", "110.50", "€400", "+12.0%")],
                tranche_levels=[110.5], kpis=["Revenue growth >= 5.0%"], guidance="Revenue up 8-10%.", prices=prices)
    pdf = build_pdf(memo)
    assert pdf.startswith(b"%PDF") and len(pdf) > 3000
