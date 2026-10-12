"""Company guidance, read directly from the earnings press releases (SEC exhibit 99.1).

US-listed companies (and foreign issuers with a US listing that file 6-K)
publish their results as an exhibit to an 8-K/6-K filing; the outlook sits in
a section such as "Outlook", "Guidance" or "CFO Outlook Commentary". Yahoo
Finance mirrors these exhibits, so they can be fetched without an SEC account.

The extraction is heuristic: it finds the outlook section, keeps the sentences
that state expectations and parses numeric ranges ("$61-64 billion",
"between 15-17%"). The original text is always shown alongside, so a wrong
parse is easy to spot.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from . import privacy
from .privacy import YAHOO

US_EXCHANGES = ("NMS", "NYQ", "NGM", "NCM", "ASE")

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (portfolio-tracker research)"}
SECTION_START = re.compile(r"(CFO Outlook Commentary|Business Outlook|Financial Outlook|Outlook|Guidance)", re.I)
SECTION_END = re.compile(r"(Webcast|Conference Call|Forward-Looking Statements|About [A-Z]|Non-GAAP Financial Measures"
                         r"|Safe Harbor|Investor Relations Contact|Contacts?:)", re.I)
BOILERPLATE = re.compile(r"forward-looking|securities laws|undertakes? no obligation|safe harbor|risks and uncertainties"
                         r"|actual results (?:could|may) differ|except for the company", re.I)
EXPECT_WORDS = re.compile(r"\b(expect|anticipate|project|forecast|outlook|guidance|target|plan to)\w*\b", re.I)
UNIT = r"(billion|million|bn|mn|%|percent)"
RANGE = re.compile(
    r"(?P<label>[A-Za-z][^.$%]{3,140}?)\s+(?:to be|of|at|will be|is expected to be)?\s*"
    r"(?:in the range of|between|range of|approximately)?\s*"
    r"(?P<cur>[$€£])?\s?(?P<low>\d+(?:[.,]\d+)?)\s*(?P<u1>" + UNIT + r")?\s*(?:-|–|to|and)\s*(?P=cur)?\s?"
    r"(?P<high>\d+(?:[.,]\d+)?)\s*(?P<u2>" + UNIT + r")", re.I)


@dataclass
class GuidanceItem:
    label: str
    low: float
    high: float
    unit: str                 # 'billion', 'million', '%'
    currency: str | None

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


@dataclass
class Release:
    date: date
    form: str
    url: str
    outlook_text: str | None
    sentences: list[str] = field(default_factory=list)
    items: list[GuidanceItem] = field(default_factory=list)


def _clean_number(x: str) -> float:
    return float(x.replace(",", ""))


def _norm_unit(u: str) -> str:
    u = u.lower()
    return {"bn": "billion", "mn": "million", "percent": "%"}.get(u, u)


def extract_outlook(text: str) -> tuple[str | None, list[str], list[GuidanceItem]]:
    """(outlook section, expectation sentences, parsed ranges) from a press release's plain text."""
    text = re.sub(r"\s+", " ", text)
    section = None
    for m in SECTION_START.finditer(text):
        chunk = text[m.start(): m.start() + 3000]
        end = SECTION_END.search(chunk, 80)
        chunk = chunk[: end.start()] if end else chunk[:2000]
        if EXPECT_WORDS.search(chunk) and re.search(r"\d", chunk):
            section = chunk.strip()
            break
    source = section or text
    # split on sentence ends and on dashes/semicolons that glue headline fragments together
    pieces = re.split(r"(?<=[.!?;])\s+(?=[A-Z])|\s[–—]\s", source)
    sentences = [s_.strip() for s_ in pieces
                 if EXPECT_WORDS.search(s_) and re.search(r"\d", s_) and 30 < len(s_) < 700
                 and not BOILERPLATE.search(s_)]
    if not section:
        sentences = sentences[:6]
    # drop a section heading glued to the first sentence ("CFO Outlook Commentary We expect ...")
    sentences = [re.sub(r"^(?:CFO Outlook Commentary|Business Outlook|Financial Outlook|Outlook|Guidance)[:\s]+(?=[A-Z])",
                        "", s_) for s_ in sentences]
    items = []
    for s_ in sentences:
        for m in RANGE.finditer(s_):
            label = m.group("label").strip()
            if re.search(r"\bprior\b|previous|previously", label, re.I):
                continue  # the superseded outlook, not the current one
            # keep only what follows the last "expect/anticipate/project" (drops headings and lead-ins)
            parts = re.split(r"\b(?:expect|anticipate|project|forecast|guide)s?\b", label, flags=re.I)
            label = parts[-1].strip(" ,:")
            label = re.sub(r"^(?:our|the|its)\s+", "", label, flags=re.I)
            label = re.sub(r"\s+(?:to be|of|at|will be|in the range|between|range)$", "", label, flags=re.I)
            label = re.sub(r"\s+(?:are|is)\s+expected$", "", label, flags=re.I)
            label = re.sub(r"\b(?:Guidance|Outlook)\s*[•·:\-–]\s*", "", label).strip(" •·:-–")
            if re.match(r"^(?:or\s+)?to\s+grow", label, re.I):
                label = "Growth (company guidance)"
            if len(label) < 4:
                continue
            try:
                low, high = _clean_number(m.group("low")), _clean_number(m.group("high"))
            except ValueError:
                continue
            unit = _norm_unit(m.group("u2"))
            if low > high or unit not in ("billion", "million", "%"):
                continue
            items.append(GuidanceItem(label[:120], low, high, unit, m.group("cur")))
    return section, sentences, items


class Guidance:
    """Fetches and caches earnings releases via yfinance's SEC filing index (mirrored exhibits)."""

    def __init__(self, cache_dir: str | Path = "data/cache"):
        self.cache_dir = Path(cache_dir) / "guidance"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        import yfinance as yf

        self.yf = yf

    def us_symbol(self, ticker: str, name: str) -> str:
        """US listing (ADR or ordinary) for non-US tickers, which is where the SEC filings live."""
        if "." not in ticker:
            return ticker
        cache_file = self.cache_dir / "us_symbols.json"
        known = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        if ticker in known:
            return known[ticker]
        try:
            privacy.network(YAHOO, "US listing lookup", name)
            for q in self.yf.Search(name, max_results=10).quotes:
                sym = q.get("symbol", "")
                if q.get("quoteType") == "EQUITY" and "." not in sym and q.get("exchange") in US_EXCHANGES:
                    cache_file.write_text(json.dumps({**known, ticker: sym}))
                    return sym
        except Exception as exc:
            log.warning("US symbol lookup failed for %s: %s", ticker, exc)
        return ticker

    def releases(self, ticker: str, name: str, limit: int = 5) -> list[Release]:
        """Latest earnings releases (newest first) with their parsed outlook."""
        symbol = self.us_symbol(ticker, name)
        index_cache = self.cache_dir / f"filings_{re.sub(r'[^A-Za-z0-9]+', '_', symbol)}.pkl"
        try:
            privacy.network(YAHOO, "SEC filing index", symbol)
            filings = self.yf.Ticker(symbol).sec_filings or []
            with index_cache.open("wb") as f:
                pickle.dump(filings, f)
        except Exception as exc:
            try:  # offline or provider down: the last known filing index
                with index_cache.open("rb") as f:
                    filings = pickle.load(f)
            except Exception:
                log.warning("No SEC filings for %s: %s", symbol, exc)
                return []
        out = []
        for fl in filings:
            if fl.get("type") not in ("8-K", "6-K"):
                continue
            url = (fl.get("exhibits") or {}).get("EX-99.1")
            if not url:
                continue
            rel = self._release(url, fl.get("date"), fl.get("type"))
            if rel is not None and _looks_like_results(rel):
                out.append(rel)
            if len(out) >= limit:
                break
        return out

    def _release(self, url: str, when, form: str) -> Release | None:
        cache = self.cache_dir / (re.sub(r"[^A-Za-z0-9]+", "_", url[-90:]) + ".pkl")
        if cache.exists():  # published releases never change
            try:
                with cache.open("rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
        try:
            import requests
            from bs4 import BeautifulSoup

            privacy.network("Yahoo Finance (SEC exhibit mirror)", "earnings release", url.rsplit("/", 1)[-1])
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            text = BeautifulSoup(r.text, "html.parser").get_text(" ")
        except Exception as exc:
            log.warning("Release download failed (%s): %s", url, exc)
            return None
        section, sentences, items = extract_outlook(text)
        rel = Release(date=when, form=form, url=url, outlook_text=section, sentences=sentences, items=items)
        rel.is_results = bool(re.search(r"(quarter|fiscal|full[- ]year)[^.]{0,80}(results|revenue)", text[:6000], re.I))
        with cache.open("wb") as f:
            pickle.dump(rel, f)
        return rel


def _looks_like_results(rel: Release) -> bool:
    return bool(getattr(rel, "is_results", False))


# ------------------------------------------------------------------ analysis
QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "q1": 1, "q2": 2, "q3": 3, "q4": 4}


def revenue_guidance(rel: Release) -> GuidanceItem | None:
    """The next-quarter (or full-year) revenue range, if the release gives one."""
    candidates = [i for i in rel.items if re.search(r"revenue|sales", i.label, re.I) and i.unit in ("billion", "million")]
    quarter = [i for i in candidates if re.search(r"quarter|\bq[1-4]\b", i.label, re.I)]
    return (quarter or candidates or [None])[0]


def to_amount(item: GuidanceItem) -> tuple[float, float]:
    factor = 1e9 if item.unit == "billion" else 1e6
    return item.low * factor, item.high * factor


def track_record(releases: list[Release], quarterly_revenue: pd.Series) -> pd.DataFrame:
    """For each release: guided next-quarter revenue range vs. the revenue later reported.

    ``quarterly_revenue`` is indexed by quarter-end date. The guided quarter is
    the first quarter ending after the release date.
    """
    q = quarterly_revenue.dropna().sort_index()
    rows = []
    for rel in releases:
        item = revenue_guidance(rel)
        if item is None or not re.search(r"quarter|\bq[1-4]\b", item.label, re.I) or rel.date is None:
            continue
        after = q[q.index > pd.Timestamp(rel.date)]
        if after.empty:
            continue
        quarter_end, actual = after.index[0], float(after.iloc[0])
        if (quarter_end - pd.Timestamp(rel.date)).days > 120:
            continue
        low, high = to_amount(item)
        result = "above range" if actual > high else ("below range" if actual < low else "within range")
        rows.append({"release": rel.date, "quarter_end": quarter_end.date(), "low": low, "high": high,
                     "actual": actual, "vs_mid": actual / ((low + high) / 2) - 1, "result": result})
    return pd.DataFrame(rows)


def implied_growth(item: GuidanceItem, release_date, quarterly_revenue: pd.Series,
                   annual_revenue: pd.Series) -> tuple[float, str] | None:
    """Growth vs. the comparable prior period implied by the midpoint of a revenue range.

    Quarter guidance is compared with the same quarter a year earlier, full-year guidance with the last
    reported fiscal year.
    """
    low, high = to_amount(item)
    mid = (low + high) / 2
    if re.search(r"quarter|\bq[1-4]\b", item.label, re.I):
        q = quarterly_revenue.dropna().sort_index()
        if release_date is None:
            return None
        # the guided quarter is the first quarter ending after the release – not the latest quarter in the data,
        # which can lag behind the release
        guided_end = pd.Timestamp(release_date) + pd.offsets.QuarterEnd(0)
        if guided_end <= pd.Timestamp(release_date):
            guided_end += pd.offsets.QuarterEnd(1)
        year_ago = guided_end - pd.DateOffset(years=1)
        prior = q[(q.index >= year_ago - pd.Timedelta(days=20)) & (q.index <= year_ago + pd.Timedelta(days=20))]
        if prior.empty:
            return None
        return mid / float(prior.iloc[-1]) - 1, "vs. prior-year quarter"
    a = annual_revenue.dropna().sort_index()
    if a.empty:
        return None
    return mid / float(a.iloc[-1]) - 1, f"vs. fiscal year {a.index[-1].year}"
