"""Market data: ISIN -> ticker resolution, daily prices in EUR, splits, metadata.

All data comes from Yahoo Finance via ``yfinance`` and is cached on disk under
``data/cache`` so the dashboard works offline after the first run.

Prices are fetched in the listing currency and converted to EUR with daily
ECB-style FX closes. Keeping local price and FX apart lets us split a stock's
EUR return into "the stock moved" and "the currency moved".
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from . import privacy
from .privacy import YAHOO

log = logging.getLogger(__name__)

# UCITS ETFs: Yahoo's ISIN search returns USD listings in London; the Xetra EUR
# listings match the prices Trade Republic shows.
DEFAULT_TICKER_OVERRIDES = {
    "IE00BFY0GT14": "SPPW.DE",  # SPDR MSCI World
    "IE00BTJRMP35": "XMME.DE",  # Xtrackers MSCI Emerging Markets
    "IE00B4L5Y983": "EUNL.DE",  # iShares Core MSCI World
    # listings used by the synthetic demo portfolio (data/sample/demo_portfolio.csv)
    "NL0010273215": "ASML.AS", "DE0007164600": "SAP.DE", "DE0007236101": "SIE.DE", "FR0000121014": "MC.PA",
    "US92826C8394": "V", "US22160K1051": "COST",
}

# Accumulating UCITS ETFs quoted in EUR on Xetra: total-return benchmarks for a
# EUR investor, no FX conversion needed.
BENCHMARKS = {
    "MSCI World": "EUNL.DE",
    "S&P 500": "SXR8.DE",
    "Nasdaq-100": "SXRV.DE",
}

METADATA_MAX_AGE = timedelta(days=14)


@dataclass
class PriceData:
    eur: pd.DataFrame       # close in EUR, columns = tickers, business-day index
    local: pd.DataFrame     # close in listing currency (GBp converted to GBP)
    fx: pd.DataFrame        # units of currency per 1 EUR, columns = currency codes
    currency: dict[str, str]


class MarketData:
    def __init__(self, cache_dir: str | Path = "data/cache", overrides_file: str | Path | None = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.overrides = dict(DEFAULT_TICKER_OVERRIDES)
        if overrides_file and Path(overrides_file).exists():
            self.overrides.update(json.loads(Path(overrides_file).read_text()))
        self._yf = None

    @property
    def yf(self):
        if self._yf is None:
            import yfinance as yf

            yf.set_tz_cache_location(str(self.cache_dir / "yf"))
            self._yf = yf
        return self._yf

    # ------------------------------------------------------------------ tickers
    def resolve_tickers(self, isins: list[str]) -> dict[str, str | None]:
        """Map ISINs to Yahoo tickers; results are cached, overrides win."""
        cache_file = self.cache_dir / "tickers.json"
        cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        result = {}
        for isin in isins:
            if isin in self.overrides:
                result[isin] = self.overrides[isin]
                continue
            if isin not in cache:
                found = self._search_ticker(isin)
                if found:  # failed lookups are retried on the next run
                    cache[isin] = found
            result[isin] = cache.get(isin)
        cache_file.write_text(json.dumps(cache, indent=2, sort_keys=True))
        return result

    def _search_ticker(self, isin: str) -> str | None:
        try:
            privacy.network(YAHOO, "ISIN → ticker lookup", isin)
            quotes = self.yf.Search(isin, max_results=5).quotes
        except Exception as exc:  # network errors must not break the import
            log.warning("Ticker search failed for %s: %s", isin, exc)
            return None
        # Stuttgart pseudo-tickers ("<ISIN>.SG") have sparse data; prefer real listings.
        symbols = [q["symbol"] for q in quotes if q.get("symbol") and not q["symbol"].startswith(isin)]
        if not symbols:
            log.warning("No ticker found for %s", isin)
            return None
        return symbols[0]

    # --------------------------------------------------------------- metadata
    def metadata(self, tickers: list[str]) -> pd.DataFrame:
        """Sector, industry, country, currency and type per ticker (cached)."""
        cache_file = self.cache_dir / "metadata.json"
        cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        now = datetime.now()
        for ticker in tickers:
            entry = cache.get(ticker)
            if entry and now - datetime.fromisoformat(entry["fetched"]) < METADATA_MAX_AGE:
                continue
            try:
                privacy.network(YAHOO, "company metadata", ticker)
                info = self.yf.Ticker(ticker).info
            except Exception as exc:
                log.warning("Metadata failed for %s: %s", ticker, exc)
                if entry:
                    continue
                info = {}
            cache[ticker] = {
                "fetched": now.isoformat(timespec="seconds"),
                "long_name": info.get("longName") or info.get("shortName"),
                "quote_type": info.get("quoteType"),
                "currency": info.get("currency"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "country": info.get("country"),
                "market_cap": info.get("marketCap"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
            }
        cache_file.write_text(json.dumps(cache, indent=2, sort_keys=True))
        return pd.DataFrame.from_dict({t: cache[t] for t in tickers if t in cache}, orient="index")

    def splits(self, tickers: list[str]) -> dict[str, pd.Series]:
        """Split ratios per ticker (index = effective date), cached with the metadata."""
        cache_file = self.cache_dir / "splits.pkl"
        cache = _load_pickle(cache_file, max_age=METADATA_MAX_AGE) or {}
        for ticker in tickers:
            if ticker in cache:
                continue
            try:
                privacy.network(YAHOO, "stock splits", ticker)
                s = self.yf.Ticker(ticker).splits
                s.index = s.index.tz_localize(None).normalize()
                cache[ticker] = s[s > 0]
            except Exception as exc:
                log.warning("Split history failed for %s: %s", ticker, exc)
                cache[ticker] = pd.Series(dtype=float)
        _dump_pickle(cache_file, cache)
        return {t: cache[t] for t in tickers}

    # ----------------------------------------------------------------- prices
    def prices(self, tickers: list[str], start: date | str, currencies: dict[str, str]) -> PriceData:
        """Daily closes from ``start`` to today, in EUR and in listing currency.

        ``Close`` from Yahoo is split-adjusted but not dividend-adjusted, which
        is what we need: dividends enter the analysis as cash flows.
        """
        start = pd.Timestamp(start) - pd.Timedelta(days=10)  # warm-up for forward fill
        fx_codes = sorted({_fx_code(c) for c in currencies.values()} - {"EUR", None})
        fx_tickers = [f"EUR{c}=X" for c in fx_codes]
        raw = self._download(sorted(set(tickers)) + fx_tickers, start)

        index = pd.bdate_range(start, pd.Timestamp.today().normalize())
        raw = raw.reindex(raw.index.union(index)).sort_index().ffill().reindex(index)

        fx = raw[fx_tickers].rename(columns=lambda c: c[3:6]) if fx_tickers else pd.DataFrame(index=index)
        fx["EUR"] = 1.0
        local = pd.DataFrame(index=index)
        eur = pd.DataFrame(index=index)
        for ticker in tickers:
            if ticker not in raw:
                continue
            currency = currencies.get(ticker) or "EUR"
            series = raw[ticker]
            if currency == "GBp":  # London quotes in pence
                series = series / 100
            code = _fx_code(currency)
            local[ticker] = series
            eur[ticker] = series / fx[code] if code in fx else series
        return PriceData(eur=eur, local=local, fx=fx, currency=currencies)

    def _download(self, symbols: list[str], start: pd.Timestamp) -> pd.DataFrame:
        """Daily closes, cached for the day. The cache remembers from which date each symbol was loaded, so
        portfolios with different start dates (your export, the demo) can share it without cutting history."""
        cache_file = self.cache_dir / "prices.pkl"
        cached = _load_pickle(cache_file)
        today = pd.Timestamp.today().normalize()
        same_day = cached is not None and cached.get("fetched") == today and "starts" in cached
        starts = dict(cached["starts"]) if same_day else {}
        if same_day and all(s in starts and starts[s] <= start for s in symbols):
            return cached["data"].reindex(columns=symbols)
        # load requested symbols far enough back for every portfolio that asked for them today
        start = min([start] + [starts[s] for s in symbols if s in starts])
        try:
            privacy.network(YAHOO, "price history", *symbols)
            data = self.yf.download(
                symbols, start=start, auto_adjust=False, actions=False,
                progress=False, threads=False,
            )["Close"]
            if isinstance(data, pd.Series):
                data = data.to_frame(symbols[0])
            data = data.reindex(columns=symbols)
            data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
        except Exception as exc:
            if cached is None:
                raise
            log.warning("Price download failed (%s), using cache from %s", exc, cached["fetched"].date())
            return cached["data"].reindex(columns=symbols)
        starts.update({s: start for s in symbols})
        old = cached["data"] if cached is not None else pd.DataFrame()
        # a symbol the provider skipped this time (throttling, hiccup) keeps its last good history
        skipped = [s for s in symbols if data[s].isna().all()]
        rescued = [s for s in skipped if s in old and old[s].notna().any()]
        if skipped:
            log.warning("No fresh prices for: %s%s", skipped, f" – using cached history for {rescued}" if rescued else "")
        # symbols other portfolios loaded today stay in the cache
        others = [s for s in old.columns if s not in symbols] if same_day else []
        extra = old[rescued + others] if rescued or others else None
        if extra is not None:
            data = data.drop(columns=rescued).join(extra, how="outer")
        starts = {s: v for s, v in starts.items() if s in data.columns}
        _dump_pickle(cache_file, {"fetched": today, "data": data, "starts": starts})
        return data.reindex(columns=symbols)


def _fx_code(currency: str | None) -> str | None:
    if currency is None:
        return None
    return "GBP" if currency == "GBp" else currency.upper()


def _load_pickle(path: Path, max_age: timedelta | None = None):
    if not path.exists():
        return None
    stale = max_age and datetime.now() - datetime.fromtimestamp(path.stat().st_mtime) > max_age
    if stale and not privacy.offline():  # offline, an old cache beats no data
        return None
    try:
        with path.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _dump_pickle(path: Path, obj) -> None:
    with path.open("wb") as f:
        pickle.dump(obj, f)


def dividend_history(market: MarketData, tickers: list[str]) -> dict[str, pd.Series]:
    """Dividend per share history (listing currency, ex-date index) per ticker, cached for a day."""
    cache_file = market.cache_dir / "dividends.pkl"
    cached = _load_pickle(cache_file, max_age=timedelta(days=1)) or {}
    out = {}
    for tk in tickers:
        if tk not in cached:
            try:
                privacy.network(YAHOO, "dividend history", tk)
                s = market.yf.Ticker(tk).dividends
                s.index = s.index.tz_localize(None).normalize()
                cached[tk] = s[s > 0]
            except Exception as exc:
                log.warning("Dividends failed for %s: %s", tk, exc)
                cached[tk] = pd.Series(dtype=float)
        out[tk] = cached[tk]
    _dump_pickle(cache_file, cached)
    return out
