"""Fundamental data for company research (Yahoo Finance via yfinance, cached daily).

Per-share figures are converted into the trading currency when a company
reports in a different currency than its shares trade in.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import pickle
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import privacy
from .privacy import YAHOO

log = logging.getLogger(__name__)


@dataclass
class Fundamentals:
    ticker: str
    name: str
    currency: str
    financial_currency: str
    price: float
    shares: float
    market_cap: float | None
    enterprise_value: float | None
    sector: str | None
    industry: str | None
    country: str | None
    summary: str | None
    eps_ttm: float | None
    eps_forward: float | None
    pe_ttm: float | None
    pe_forward: float | None
    fcf: float | None                 # latest annual free cash flow (trading currency)
    revenue: float | None
    net_debt: float | None
    profit_margin: float | None
    roe: float | None
    dividend_rate: float | None
    growth_estimates: dict = field(default_factory=dict)   # '0y', '+1y', 'LTG' -> EPS growth
    eps_estimates: dict = field(default_factory=dict)      # '0y', '+1y' -> {avg, low, high, analysts}
    target_mean: float | None = None
    target_low: float | None = None
    target_high: float | None = None
    analysts: int | None = None
    recommendation: str | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    earnings_date: date | None = None
    annual: pd.DataFrame = field(default_factory=pd.DataFrame)   # revenue, net income, FCF, EPS, shares
    prices: pd.Series = field(default_factory=pd.Series)          # 5y daily close, trading currency
    fx_factor: float = 1.0           # financial currency -> trading currency
    fetched: datetime = field(default_factory=datetime.now)
    ebitda: float | None = None      # trading currency
    gross_margin: float | None = None
    operating_margin: float | None = None
    dividend_yield: float | None = None
    revenue_growth: float | None = None    # latest quarter vs. prior-year quarter
    earnings_growth: float | None = None
    revenue_estimates: dict = field(default_factory=dict)   # '0y', '+1y' -> avg, low, high, growth, analysts, year_ago
    eps_trend: dict = field(default_factory=dict)           # '0y', '+1y' -> current, 90d_ago
    eps_revisions: dict = field(default_factory=dict)       # '0y', '+1y' -> up_30d, down_30d
    recommendations: dict = field(default_factory=dict)     # strongBuy, buy, hold, sell, strongSell
    filings: list = field(default_factory=list)             # latest SEC filings: date, type, url
    website: str | None = None
    ir_website: str | None = None
    quarterly: pd.DataFrame = field(default_factory=pd.DataFrame)   # revenue, operating/net income, eps, fcf, sbc
    dividends_ps: pd.Series = field(default_factory=pd.Series)      # dividend per share per calendar year
    surprises: pd.DataFrame = field(default_factory=pd.DataFrame)   # EPS estimate vs. reported per quarter

    @property
    def ttm(self) -> dict:
        """Trailing-twelve-month sums from the last four quarters (falls back to the last fiscal year)."""
        q = self.quarterly
        out = {}
        for col in ["revenue", "operating_income", "net_income", "fcf", "sbc"]:
            if not q.empty and col in q and q[col].tail(4).notna().sum() == 4:
                out[col] = float(q[col].tail(4).sum())
            elif not self.annual.empty and col in self.annual and self.annual[col].notna().any():
                out[col] = float(self.annual[col].dropna().iloc[-1])
        return out

    @property
    def fcf_per_share(self) -> float | None:
        return self.fcf / self.shares if self.fcf is not None and self.shares else None

    @property
    def fcf_yield(self) -> float | None:
        return self.fcf / self.market_cap if self.fcf is not None and self.market_cap else None


def _num(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _scale(value, factor: float) -> float | None:
    v = _num(value)
    return v * factor if v is not None else None


def _consistent_eps(eps: float | None, pe: float | None, price: float | None, fx: float) -> float | None:
    """Return EPS in the trading currency.

    Yahoo sometimes reports EPS in the financial currency. If price / EPS does
    not match the reported P/E, the EPS is converted with ``fx``.
    """
    if eps is None or fx == 1.0 or not pe or not price:
        return eps
    return eps if abs(price / eps / pe - 1) < 0.2 else eps * fx


def _row(df: pd.DataFrame, *names: str) -> pd.Series:
    for n in names:
        if n in df.index:
            return df.loc[n]
    return pd.Series(dtype=float)


class Research:
    def __init__(self, cache_dir: str | Path = "data/cache"):
        self.cache_dir = Path(cache_dir) / "research"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        import yfinance as yf

        yf.set_tz_cache_location(str(Path(cache_dir) / "yf"))
        self.yf = yf

    def search(self, query: str) -> list[dict]:
        """Equities and ETFs matching a name, ticker or ISIN."""
        try:
            privacy.network(YAHOO, "company search", query)
            quotes = self.yf.Search(query, max_results=10).quotes
        except Exception as exc:
            log.warning("Search failed: %s", exc)
            return []
        return [
            {"symbol": q["symbol"], "name": q.get("longname") or q.get("shortname") or q["symbol"],
             "exchange": q.get("exchDisp") or q.get("exchange"), "type": q.get("quoteType")}
            for q in quotes if q.get("quoteType") in ("EQUITY", "ETF") and q.get("symbol")
        ]

    def fundamentals(self, ticker: str, refresh: bool = False) -> Fundamentals:
        cache = self.cache_dir / f"{ticker.replace('/', '_')}.pkl"
        if cache.exists() and not refresh:
            try:
                with cache.open("rb") as f:
                    cached: Fundamentals = pickle.load(f)
                # a cache written by an older version lacks newer fields -> fetch again
                complete = all(fld.name in cached.__dict__ for fld in dataclasses.fields(Fundamentals))
                if complete and cached.fetched.date() == date.today():
                    return cached
            except Exception:
                pass
        try:
            privacy.network(YAHOO, "fundamentals", ticker)
            data = self._fetch(ticker)
        except Exception:
            if cache.exists():  # offline or provider down: yesterday's fundamentals beat none
                with cache.open("rb") as f:
                    return pickle.load(f)
            raise
        with cache.open("wb") as f:
            pickle.dump(data, f)
        return data

    def _fetch(self, ticker: str) -> Fundamentals:
        t = self.yf.Ticker(ticker)
        info = t.info or {}
        if not info.get("currentPrice") and not info.get("regularMarketPrice"):
            raise ValueError(f"No price data found for '{ticker}'")
        currency = info.get("currency") or "USD"
        fin_cur = info.get("financialCurrency") or currency
        fx = self._fx(fin_cur, currency)

        def safe(attr):
            try:
                return getattr(t, attr)
            except Exception as exc:
                log.warning("%s.%s failed: %s", ticker, attr, exc)
                return None

        inc, cf = safe("income_stmt"), safe("cash_flow")
        annual = pd.DataFrame()
        if inc is not None and not inc.empty:
            annual = pd.DataFrame({
                "revenue": _row(inc, "Total Revenue"),
                "net_income": _row(inc, "Net Income", "Net Income Common Stockholders"),
                "operating_income": _row(inc, "Operating Income"),
                "eps": _row(inc, "Diluted EPS", "Basic EPS"),
                "shares": _row(inc, "Diluted Average Shares", "Basic Average Shares"),
            })
        if inc is not None and not inc.empty:
            annual = annual.join(pd.DataFrame({"ebitda": _row(inc, "EBITDA", "Normalized EBITDA")}), how="outer")
        if cf is not None and not cf.empty:
            annual = annual.join(pd.DataFrame({
                "fcf": _row(cf, "Free Cash Flow"), "sbc": _row(cf, "Stock Based Compensation"),
                "dividends_paid": _row(cf, "Cash Dividends Paid", "Common Stock Dividend Paid"),
                "buybacks": _row(cf, "Repurchase Of Capital Stock", "Common Stock Payments"),
            }), how="outer")
        bs = safe("balance_sheet")
        if bs is not None and not bs.empty:
            annual = annual.join(pd.DataFrame({
                "cash": _row(bs, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"),
                "debt": _row(bs, "Total Debt"), "equity": _row(bs, "Stockholders Equity"),
            }), how="outer")
        if not annual.empty:
            annual.index = pd.to_datetime(annual.index)
            annual = annual.sort_index().astype(float)
            for col in ["revenue", "net_income", "operating_income", "fcf", "eps", "ebitda", "sbc",
                        "dividends_paid", "buybacks", "cash", "debt", "equity"]:
                if col in annual:
                    annual[col] *= fx
            annual = annual.dropna(how="all")

        quarterly = pd.DataFrame()
        qi, qc = safe("quarterly_income_stmt"), safe("quarterly_cash_flow")
        if qi is not None and not qi.empty:
            quarterly = pd.DataFrame({
                "revenue": _row(qi, "Total Revenue"), "operating_income": _row(qi, "Operating Income"),
                "net_income": _row(qi, "Net Income", "Net Income Common Stockholders"),
                "eps": _row(qi, "Diluted EPS", "Basic EPS"),
            })
        if qc is not None and not qc.empty:
            quarterly = quarterly.join(pd.DataFrame({"fcf": _row(qc, "Free Cash Flow"),
                                                     "sbc": _row(qc, "Stock Based Compensation")}), how="outer")
        if not quarterly.empty:
            quarterly.index = pd.to_datetime(quarterly.index)
            quarterly = (quarterly.sort_index().astype(float) * fx).dropna(how="all")

        dividends_ps = pd.Series(dtype=float)
        try:
            dv = t.dividends
            if len(dv):
                dv.index = dv.index.tz_localize(None)
                dividends_ps = dv.groupby(dv.index.year).sum()
        except Exception as exc:
            log.warning("%s dividends failed: %s", ticker, exc)

        surprises = pd.DataFrame()
        try:
            ed = t.get_earnings_dates(limit=12)
            if ed is not None and not ed.empty:
                ed = ed.dropna(subset=["Reported EPS"])
                ed.index = ed.index.tz_localize(None)
                surprises = pd.DataFrame({"estimate": ed["EPS Estimate"], "reported": ed["Reported EPS"],
                                          "surprise": ed["Surprise(%)"] / 100}).sort_index().tail(8)
        except Exception as exc:
            log.warning("%s earnings dates failed: %s", ticker, exc)

        growth, eps_est = {}, {}
        ge = safe("growth_estimates")
        if ge is not None and not ge.empty and "stockTrend" in ge:
            growth = {k: _num(v) for k, v in ge["stockTrend"].items() if _num(v) is not None}
        ee = safe("earnings_estimate")
        if ee is not None and not ee.empty:
            for period in ["0y", "+1y"]:
                if period in ee.index:
                    r = ee.loc[period]
                    k = self._fx(r.get("currency") or fin_cur, currency)
                    eps_est[period] = {"avg": _scale(r.get("avg"), k), "low": _scale(r.get("low"), k),
                                       "high": _scale(r.get("high"), k), "analysts": _num(r.get("numberOfAnalysts"))}

        revenue_est, trend, revisions, recs, filings = {}, {}, {}, {}, []
        re_ = safe("revenue_estimate")
        if re_ is not None and not re_.empty:
            for period in ["0y", "+1y"]:
                if period in re_.index:
                    r = re_.loc[period]
                    k = self._fx(r.get("currency") or fin_cur, currency)
                    revenue_est[period] = {"avg": _scale(r.get("avg"), k), "low": _scale(r.get("low"), k),
                                           "high": _scale(r.get("high"), k), "growth": _num(r.get("growth")),
                                           "analysts": _num(r.get("numberOfAnalysts")),
                                           "year_ago": _scale(r.get("yearAgoRevenue"), k)}
        et = safe("eps_trend")
        if et is not None and not et.empty:
            for period in ["0y", "+1y"]:
                if period in et.index:
                    trend[period] = {"current": _num(et.loc[period].get("current")),
                                     "90d_ago": _num(et.loc[period].get("90daysAgo"))}
        ev = safe("eps_revisions")
        if ev is not None and not ev.empty:
            for period in ["0y", "+1y"]:
                if period in ev.index:
                    revisions[period] = {"up_30d": _num(ev.loc[period].get("upLast30days")),
                                         "down_30d": _num(ev.loc[period].get("downLast30days"))}
        rs = safe("recommendations_summary")
        if rs is not None and not rs.empty:
            row = rs.iloc[0]
            recs = {k: int(row.get(k, 0) or 0) for k in ["strongBuy", "buy", "hold", "sell", "strongSell"]}
        sf = safe("sec_filings")
        for item in (sf or [])[:40]:
            if item.get("type") in ("10-K", "10-Q", "8-K", "20-F", "6-K", "40-F"):
                filings.append({"date": item.get("date"), "type": item.get("type"), "title": item.get("title"),
                                "url": item.get("edgarUrl")})
        filings = filings[:8]

        earnings_date = None
        cal = safe("calendar")
        if isinstance(cal, dict) and cal.get("Earnings Date"):
            dates = cal["Earnings Date"]
            earnings_date = dates[0] if isinstance(dates, list) and dates else None

        prices = pd.Series(dtype=float)
        try:
            h = t.history(period="10y", auto_adjust=False)
            prices = h["Close"]
            prices.index = prices.index.tz_localize(None).normalize()
        except Exception as exc:
            log.warning("%s history failed: %s", ticker, exc)

        fcf = None
        if not annual.empty and "fcf" in annual and annual["fcf"].notna().any():
            fcf = float(annual["fcf"].dropna().iloc[-1])
        elif _num(info.get("freeCashflow")) is not None:
            fcf = _num(info.get("freeCashflow")) * fx

        cash, debt = _num(info.get("totalCash")), _num(info.get("totalDebt"))
        price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
        eps_ttm = _consistent_eps(_num(info.get("trailingEps")), _num(info.get("trailingPE")), price, fx)
        eps_fwd = _consistent_eps(_num(info.get("forwardEps")), _num(info.get("forwardPE")), price, fx)
        return Fundamentals(
            ticker=ticker, name=info.get("longName") or info.get("shortName") or ticker,
            currency=currency, financial_currency=fin_cur,
            price=price,
            shares=_num(info.get("sharesOutstanding")) or 0.0,
            market_cap=_num(info.get("marketCap")), enterprise_value=_num(info.get("enterpriseValue")),
            sector=info.get("sector"), industry=info.get("industry"), country=info.get("country"),
            summary=info.get("longBusinessSummary"),
            eps_ttm=eps_ttm, eps_forward=eps_fwd,
            pe_ttm=_num(info.get("trailingPE")), pe_forward=_num(info.get("forwardPE")),
            fcf=fcf, revenue=(_num(info.get("totalRevenue")) or 0) * fx or None,
            net_debt=(debt - cash) * fx if cash is not None and debt is not None else None,
            profit_margin=_num(info.get("profitMargins")), roe=_num(info.get("returnOnEquity")),
            dividend_rate=_num(info.get("dividendRate")),
            growth_estimates=growth, eps_estimates=eps_est,
            target_mean=_num(info.get("targetMeanPrice")), target_low=_num(info.get("targetLowPrice")),
            target_high=_num(info.get("targetHighPrice")), analysts=info.get("numberOfAnalystOpinions"),
            recommendation=info.get("recommendationKey"),
            high_52w=_num(info.get("fiftyTwoWeekHigh")), low_52w=_num(info.get("fiftyTwoWeekLow")),
            earnings_date=earnings_date, annual=annual, prices=prices, fx_factor=fx,
            ebitda=_scale(info.get("ebitda"), fx), gross_margin=_num(info.get("grossMargins")),
            operating_margin=_num(info.get("operatingMargins")),
            dividend_yield=(_num(info.get("dividendRate")) / price) if _num(info.get("dividendRate")) and price else None,
            revenue_growth=_num(info.get("revenueGrowth")), earnings_growth=_num(info.get("earningsGrowth")),
            revenue_estimates=revenue_est, eps_trend=trend, eps_revisions=revisions, recommendations=recs,
            filings=filings, website=info.get("website"), ir_website=info.get("irWebsite"),
            quarterly=quarterly, dividends_ps=dividends_ps, surprises=surprises,
        )

    def _fx(self, from_cur: str, to_cur: str) -> float:
        if from_cur == to_cur:
            return 1.0
        pair = f"{from_cur}{to_cur}"
        cache_file = self.cache_dir / "fx.json"
        rates = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        try:
            privacy.network(YAHOO, "exchange rate", pair)
            h = self.yf.Ticker(f"{pair}=X").history(period="5d")
            rates[pair] = float(h["Close"].dropna().iloc[-1])
            cache_file.write_text(json.dumps(rates))
        except Exception as exc:
            if pair not in rates:
                log.warning("FX %s failed (%s); assuming 1.0", pair, exc)
                return 1.0
        return rates[pair]

    def quotes(self, tickers: list[str]) -> pd.DataFrame:
        """Latest price, previous close and currency per ticker (live where available)."""
        rows = {}
        for tk in tickers:
            try:
                privacy.network(YAHOO, "live quote", tk)
                fi = self.yf.Ticker(tk).fast_info
                rows[tk] = {"price": _num(fi["lastPrice"]), "previous_close": _num(fi["previousClose"]),
                            "currency": fi["currency"]}
            except Exception as exc:
                rows[tk] = self._cached_quote(tk)
                if rows[tk]["price"] is None:
                    log.warning("Quote for %s failed: %s", tk, exc)
        return pd.DataFrame.from_dict(rows, orient="index")

    def fund_profile(self, ticker: str, max_age_days: int = 14):
        """Top holdings and sector weights of an ETF (Yahoo fund data), cached; None if unavailable."""
        from .lookthrough import FundProfile

        cache = self.cache_dir / f"fund_{ticker.replace('/', '_')}.pkl"
        cached = None
        if cache.exists():
            try:
                with cache.open("rb") as f:
                    cached = pickle.load(f)
                age = datetime.now() - datetime.fromtimestamp(cache.stat().st_mtime)
                if age.days < max_age_days or privacy.offline():
                    return cached
            except Exception:
                cached = None
        try:
            privacy.network(YAHOO, "ETF holdings", ticker)
            fd = self.yf.Ticker(ticker).funds_data
            top = fd.top_holdings
            holdings = (top.rename(columns={"Name": "name", "Holding Percent": "weight"})[["name", "weight"]]
                        if top is not None and len(top) else pd.DataFrame(columns=["name", "weight"]))
            profile = FundProfile(holdings=holdings, sectors=dict(fd.sector_weightings or {}))
        except Exception as exc:
            log.warning("Fund data for %s failed: %s", ticker, exc)
            return cached
        with cache.open("wb") as f:
            pickle.dump(profile, f)
        return profile

    def _cached_quote(self, ticker: str) -> dict:
        """Last close from the cached fundamentals (offline fallback)."""
        cache = self.cache_dir / f"{ticker.replace('/', '_')}.pkl"
        try:
            with cache.open("rb") as f:
                fund: Fundamentals = pickle.load(f)
            closes = fund.prices.dropna()
            return {"price": float(closes.iloc[-1]), "previous_close": float(closes.iloc[-2]), "currency": fund.currency}
        except Exception:
            return {"price": None, "previous_close": None, "currency": None}

    def eur_rate(self, currency: str) -> float:
        """Units of ``currency`` per 1 EUR (1.0 for EUR; GBp handled as pence)."""
        if currency in (None, "EUR"):
            return 1.0
        if currency == "GBp":
            return self.eur_rate("GBP") * 100
        return self._fx("EUR", currency)
