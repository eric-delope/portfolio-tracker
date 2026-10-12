"""Shared state, data loading and formatting for all dashboard pages."""

from __future__ import annotations

import contextlib
import io
import itertools
import os
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from i18n import tr

from portfolio_tracker import fmt
from portfolio_tracker.importer import load_transactions, validate
from portfolio_tracker.market import MarketData
from portfolio_tracker.portfolio import Portfolio
from portfolio_tracker.research import Research
from portfolio_tracker.watchlist import Watchlist

ROOT = Path(__file__).parents[1]
RAW_DIR = ROOT / "data" / "raw"
DEMO_CSV = ROOT / "data" / "sample" / "demo_portfolio.csv"
DEMO_WATCHLIST = ROOT / "data" / "sample" / "demo_watchlist.json"
CACHE_DIR = ROOT / "data" / "cache"
# PORTFOLIO_DEMO=1 forces the demo even when a real export exists; its watchlist is kept apart from the real one.
FORCE_DEMO = os.environ.get("PORTFOLIO_DEMO") == "1"
WATCHLIST_FILE = Path(os.environ.get("PORTFOLIO_WATCHLIST",
                                     ROOT / "data" / "user" / ("demo_watchlist.json" if FORCE_DEMO else "watchlist.json")))
REPORT_DIR = ROOT / "reports"


# ---------------------------------------------------------------- settings
def privacy() -> bool:
    return bool(st.session_state.get("privacy", False))


def base() -> str:
    """Reporting currency: the sidebar choice ('EUR' or 'USD'), euros while no exchange rates are available."""
    chosen = st.session_state.get("base_ccy") or "EUR"
    return chosen if st.session_state.get("_fx_ok", True) else "EUR"


def symbol(ccy: str | None = None) -> str:
    return fmt.SYMBOLS.get(ccy or base(), ccy or base())


def settings() -> dict:
    return {"rf": st.session_state.get("rf_pct", 2.0) / 100,
            "allowance": st.session_state.get("allowance", 1000)}


# -------------------------------------------------------------- formatting
def _n(x: float, decimals: int = 0, sign: bool = False) -> str:
    return fmt.num(x, decimals, sign)


def _missing(x) -> bool:
    return x is None or (isinstance(x, (float, np.floating)) and (np.isnan(x) or np.isinf(x)))


def eur(x: float, decimals: int = 0, sign: bool = False, ccy: str | None = None) -> str:
    """Amount in the reporting currency (or in ``ccy``, e.g. 'EUR' for taxes and broker orders)."""
    if privacy():
        return f"{symbol(ccy)}••••"
    return fmt.eur(x, decimals, sign, symbol(ccy))


def money(x: float, currency: str, decimals: int = 2) -> str:
    """Price in its own currency (not hidden by privacy mode: prices are not personal)."""
    return fmt.money(x, currency, decimals)


def pct(x: float, decimals: int = 1, sign: bool = True) -> str:
    return fmt.pct(x, decimals, sign)


def num(x: float, decimals: int = 2) -> str:
    return fmt.num(x, decimals)


def bold_html(text: str) -> str:
    """Markdown **bold** -> <b> for use inside HTML blocks (where Markdown is not parsed)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def callout(text: str, kind: str = "info") -> None:
    st.markdown(f'<div class="insight {kind}">{_typeset(bold_html(tr(text)))}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------- layout blocks
_cards = itertools.count()


def reset_cards() -> None:
    """Restart card keys at the top of every run, so they stay stable between reruns."""
    global _cards
    _cards = itertools.count()


def card():
    """A white card (styled via the key prefix in style.css) – use as a context manager."""
    return st.container(key=f"card_{next(_cards)}")


def stat(label: str, value: str, sub: str | None = None, tone: str | None = None, help: str | None = None) -> dict:
    return {"label": label, "value": value, "sub": sub, "tone": tone, "help": help}


def tone(x: float | None, eps: float = 0.0) -> str | None:
    """'pos' / 'neg' colour class for a signed number."""
    if x is None or _missing(x):
        return None
    return "pos" if x > eps else ("neg" if x < -eps else None)


def _typeset(text: str) -> str:
    """Typographic minus for display (the ASCII hyphen looks detached with tabular figures)."""
    return re.sub(r"(?<![\w])-(?=[\d€.])", "−", text)


def stats(items: list[dict], cols: int | None = None) -> None:
    """Key figures side by side in one quiet card, separated by hairlines (instead of a row of boxed metrics)."""
    import html as _html

    n = cols or len(items)
    cells = []
    for i, it in enumerate(items):
        title = f' title="{_html.escape(tr(it["help"]), quote=True)}"' if it.get("help") else ""
        sub = (f'<div class="stat-sub {it.get("tone") or ""}">{bold_html(tr(it["sub"]))}</div>' if it.get("sub") else "")
        pos = (" row-start" if i % n == 0 else "") + (" row-next" if i >= n else "")
        cells.append(f'<div class="stat{pos}"><div class="stat-label"{title}>{tr(it["label"])}</div>'
                     f'<div class="stat-value">{_typeset(str(tr(it["value"])))}</div>{_typeset(sub)}</div>')
    st.markdown(f'<div class="stats" style="--cols:{n}">{"".join(cells)}</div>', unsafe_allow_html=True)


def valuation_card(price: float, fair: float, max_price: float, exp_return: float, required: float, mos: float,
                   currency: str) -> None:
    """Qualtrim-style summary: verdict badge, three plain sentences and a price-vs-value bar."""
    gap = fair / price - 1
    if price <= max_price:
        badge, kind = "Buy zone", "good"
    elif price <= fair:
        badge, kind = "Below fair value", "info"
    else:
        badge, kind = "Overvalued", "bad"
    gap_text = (f"Fair value is **{pct(abs(gap), 1, False)} above** today's price." if gap >= 0
                else f"Fair value is **{pct(abs(gap), 1, False)} below** today's price.")
    ret = pct(exp_return, 1, False) if exp_return >= 0 else pct(exp_return)
    sentences = [gap_text, f"Expected return from today's price: **{ret} p.a.**",
                 f"For your {pct(required, 0, False)} target with a {pct(mos, 0, False)} margin of safety, buy at or "
                 f"below **{money(max_price, currency)}**."]
    paragraphs = "".join(f"<p>{_typeset(bold_html(tr(t)))}</p>" for t in sentences)
    lo = min(price, max_price) * 0.85
    hi = max(price, fair) * 1.08
    pos = lambda v: max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))  # noqa: E731
    fill = "var(--pos)" if price <= fair else "var(--neg)"
    m = lambda v: money(v, currency)  # noqa: E731
    html = f"""
    <div class="valcard">
      <div class="valhead"><span class="chart-title">{tr("Valuation")}</span>{pill(badge, kind)}</div>
      {paragraphs}
      <div class="valbar">
        <div class="track"></div>
        <div class="fill" style="width:{pos(price):.1f}%; background:{fill}"></div>
        <div class="tick max" style="left:{pos(max_price):.1f}%"><span>{tr("Max.")} {m(max_price)}</span></div>
        <div class="tick fair" style="left:{pos(fair):.1f}%"><span>{tr("Fair")} {m(fair)}</span></div>
        <div class="dot" style="left:{pos(price):.1f}%; background:{fill}"><span>{tr("Today")} {m(price)}</span></div>
      </div>
    </div>"""
    st.markdown(html, unsafe_allow_html=True)


def kv_card(rows: list[tuple[str, str, str | None, str | None]]) -> None:
    """Label / value rows with an optional change pill – (label, value, pill text, pill kind)."""
    body = "".join(f'<div class="kv"><span>{tr(label)}</span><span>{pill(pt, pk) + " " if pt else ""}<b>{tr(value)}</b>'
                   f'</span></div>' for label, value, pt, pk in rows)
    st.markdown(f'<div class="kvcard">{_typeset(body)}</div>', unsafe_allow_html=True)


def lead(text: str) -> None:
    """Short introduction at the top of a step: the question it answers."""
    st.markdown(f'<div class="lead">{bold_html(tr(text))}</div>', unsafe_allow_html=True)


def card_title(title: str, sub: str | None = None) -> None:
    title, sub = tr(title), tr(sub)
    sub_html = f'<div class="chart-sub" style="margin-bottom:.35rem">{sub}</div>' if sub else ""
    st.markdown(f'<div class="chart-title">{title}</div>{sub_html}', unsafe_allow_html=True)


def todos(items: list[tuple[str, str]]) -> None:
    """Prioritised list (priority in {'high', 'medium', 'info', 'good'}) with a coloured dot per row."""
    rows = "".join(f'<div class="todo"><span class="dot {prio}"></span><div>{bold_html(tr(text))}</div></div>'
                   for prio, text in items)
    st.markdown(rows, unsafe_allow_html=True)


def facts(lines: list[str]) -> None:
    """A clean list of short statements (Markdown **bold** allowed)."""
    st.markdown('<ul class="facts">' + "".join(f"<li>{bold_html(tr(t))}</li>" for t in lines) + "</ul>",
                unsafe_allow_html=True)


def plot(fig, boxed: bool = True) -> None:
    """Render a chart in a card; a header set via charts.titled() appears above it, the source below."""
    import i18n

    meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
    if i18n.lang() != "en":
        fig = go.Figure(fig)   # translate a copy: cached figures must stay English for the next run
        i18n.figure(fig)
    with card() if boxed else contextlib.nullcontext():
        if meta.get("title"):
            sub = f'<div class="chart-sub">{tr(meta["subtitle"])}</div>' if meta.get("subtitle") else ""
            st.markdown(f'<div class="chart-title">{tr(meta["title"])}</div>{sub}', unsafe_allow_html=True)
        st.plotly_chart(fig, theme=None, config={"displayModeBar": False, "locale": i18n.lang(), "scrollZoom": False,
                                                 "doubleClick": False})
        if meta.get("source"):
            st.markdown(f'<div class="chart-source">{tr(meta["source"])}</div>', unsafe_allow_html=True)


def calc_table(rows: list[tuple[str, str]], total_from: int | None = None) -> None:
    """A clean two-column calculation (label left, value right); rows from ``total_from`` on are emphasized."""
    html = ['<table class="calc">']
    for i, (label, value) in enumerate(rows):
        cls = ' class="total"' if total_from is not None and i >= total_from else ""
        html.append(f"<tr{cls}><td>{tr(label)}</td><td>{value}</td></tr>")
    html.append("</table>")
    st.markdown("".join(html), unsafe_allow_html=True)


# -------------------------------------------------------------------- data
@st.cache_resource(show_spinner="Loading prices and reference data …")
def _build(data: bytes, rf: float) -> tuple[pd.DataFrame, Portfolio]:
    tx = load_transactions(io.BytesIO(data))
    market = MarketData(CACHE_DIR, overrides_file=ROOT / "config" / "tickers.json")
    return tx, Portfolio.build(tx, market, rf=rf)


def demo_mode() -> bool:
    """$PORTFOLIO_DEMO=1, or no upload, no $PORTFOLIO_CSV and no export in data/raw: run on the synthetic demo."""
    if st.session_state.get("upload"):
        return False
    return FORCE_DEMO or (not os.environ.get("PORTFOLIO_CSV") and not any(RAW_DIR.glob("*.csv")))


def _default_source() -> tuple[str, bytes]:
    """$PORTFOLIO_CSV if set, else the newest export in data/raw, else the synthetic demo portfolio."""
    if FORCE_DEMO:
        return "Demo portfolio (synthetic)", DEMO_CSV.read_bytes()
    if os.environ.get("PORTFOLIO_CSV"):
        path = Path(os.environ["PORTFOLIO_CSV"])
        return path.name, path.read_bytes()
    csvs = sorted(RAW_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if csvs:
        return csvs[0].name, csvs[0].read_bytes()
    return "Demo portfolio (synthetic)", DEMO_CSV.read_bytes()


@st.cache_resource(show_spinner=False)
def _in_currency(data: bytes, rf: float, ccy: str) -> Portfolio:
    return _build(data, rf)[1].in_currency(ccy)


def load(ccy: str | None = None) -> tuple[str, pd.DataFrame, Portfolio]:
    """(source label, raw transactions, portfolio in the reporting currency – or in ``ccy``)."""
    upload = st.session_state.get("upload")
    label, data = (upload.name, upload.getvalue()) if upload else _default_source()
    try:
        tx, p = _build(data, settings()["rf"])
    except Exception as exc:  # readable error instead of a stack trace
        st.error(f"The file could not be processed: {exc}")
        st.stop()
    target = ccy or st.session_state.get("base_ccy") or "EUR"
    try:
        p = _in_currency(data, settings()["rf"], target)
        ok = True
    except ValueError as exc:  # e.g. no exchange rates right now: stay in euros rather than fail
        ok = False
        st.warning(f"Showing euros – {exc}. Try “Reload prices” later.", icon=":material/currency_exchange:")
    if ccy is None:
        st.session_state["_fx_ok"] = ok
    return label, tx, p


def portfolio_eur() -> Portfolio:
    """The portfolio in euros – the account and tax currency (taxes, broker orders)."""
    return load("EUR")[2]


@st.cache_data(show_spinner=False)
def issues(_tx: pd.DataFrame, key: str) -> list[str]:
    return validate(_tx)


@st.cache_resource
def research() -> Research:
    return Research(CACHE_DIR)


def watchlist() -> Watchlist:
    if not WATCHLIST_FILE.exists() and demo_mode():  # start the demo with a few valued companies
        WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        WATCHLIST_FILE.write_text(DEMO_WATCHLIST.read_text())
    return Watchlist(WATCHLIST_FILE)


@st.cache_data(ttl=900, show_spinner="Loading current quotes …")
def quotes(tickers: tuple[str, ...]) -> pd.DataFrame:
    return research().quotes(list(tickers)) if tickers else pd.DataFrame(columns=["price", "previous_close", "currency"])


@st.cache_data(ttl=3600, show_spinner=False)
def eur_rate(currency: str) -> float:
    return research().eur_rate(currency)


@st.cache_data(ttl=86400, show_spinner="Loading earnings dates …")
def earnings_dates(tickers: tuple[str, ...]) -> dict[str, date]:
    out = {}
    for tk in tickers:
        try:
            ed = research().fundamentals(tk).earnings_date
            if ed:
                out[tk] = ed
        except Exception:
            continue
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def price_history(ticker: str, period: str = "1y") -> pd.Series:
    try:
        f = research().fundamentals(ticker)
        s = f.prices
        cutoff = s.index.max() - pd.DateOffset(years=int(period[:-1]) if period.endswith("y") else 1)
        return s[s.index >= cutoff]
    except Exception:
        return pd.Series(dtype=float)


# -------------------------------------------------------------- order check
def order_inputs(p: Portfolio, ticker: str):
    """Holdings keyed by ticker plus the target's EUR returns, for portfolio_tracker.ordercheck."""
    from portfolio_tracker.market import BENCHMARKS
    from portfolio_tracker.ordercheck import OrderInputs

    pos = p.positions
    to_ticker = {isin: tk for isin, tk in p.tickers.items() if tk}
    values = pd.Series({to_ticker[i]: v for i, v in pos["value"].items() if i in to_ticker}, dtype=float)
    returns = p.holding_returns.rename(columns=to_ticker)
    meta = pd.DataFrame({to_ticker[i]: {"name": r["name"], "sector": r["sector"], "country": r["country"],
                                        "currency": r["currency"]}
                         for i, r in p.meta.iterrows() if i in to_ticker}).T
    if ticker not in returns.columns:
        f = research().fundamentals(ticker)
        local = f.prices.copy()
        code = "GBP" if f.currency == "GBp" else f.currency
        fx = p.prices.fx[code].reindex(local.index).ffill() if code in p.prices.fx else 1.0
        eur = (local / fx).reindex(returns.index.union(local.index)).ffill().reindex(returns.index)
        returns = returns.assign(**{ticker: eur.pct_change()})
        meta.loc[ticker] = {"name": f.name, "sector": f.sector or "Unknown", "country": f.country,
                            "currency": f.currency}
    bench = p.prices.eur[BENCHMARKS["MSCI World"]].pct_change().reindex(returns.index)
    return OrderInputs(values=values, returns=returns, meta=meta, benchmark=bench)


def position_of(p: Portfolio, ticker: str) -> pd.Series | None:
    """The open position row for a ticker, if held."""
    for isin, tk in p.tickers.items():
        if tk == ticker and isin in p.positions.index:
            return p.positions.loc[isin]
    return None


# ------------------------------------------------------------ long-term context
def _fmt_kpi(value: float | None, unit: str) -> str:
    if value is None or not np.isfinite(value):
        return "–"
    return f"{_n(value * 100, 1)}%" if unit == "%" else f"{_n(value, 1)}×"


@st.cache_data(ttl=6 * 3600, show_spinner="Checking company data …")
def company_context(ticker: str, kpis_json: str = "[]") -> dict:
    """Quality, valuation vs. own history and thesis status for one company (cached)."""
    import json

    from portfolio_tracker import thesis as th
    from portfolio_tracker import valuation as v
    from portfolio_tracker.quality import quality_checks, quality_score

    try:
        f = research().fundamentals(ticker)
    except Exception:
        return {}
    passed, total, label = quality_score(quality_checks(f.annual, f.net_debt, f.ebitda, f.roe))
    a = f.annual
    hpe = v.historical_multiple(f.prices, a["eps"]) if "eps" in a else pd.Series(dtype=float)
    pfcf = (v.historical_multiple(f.prices, a["fcf"] / a["shares"])
            if {"fcf", "shares"} <= set(a.columns) else pd.Series(dtype=float))
    cur_pfcf = f.price / f.fcf_per_share if f.fcf_per_share and f.fcf_per_share > 0 else None
    results = th.evaluate(json.loads(kpis_json), f)
    broken = [f"{r.metric} {_fmt_kpi(r.value, r.unit)} (threshold {r.operator} {_fmt_kpi(r.threshold, r.unit)})"
              for r in results if r.ok is False]
    return {
        "quality_label": label, "quality_passed": passed, "quality_total": total,
        "pe_percentile": v.percentile_rank(hpe, f.pe_ttm), "pfcf_percentile": v.percentile_rank(pfcf, cur_pfcf),
        "thesis": th.status(results), "thesis_detail": "; ".join(broken),
        "earnings_date": f.earnings_date,
    }


def watchlist_ranking(p: Portfolio, wl: Watchlist) -> tuple[pd.DataFrame, dict, dict]:
    """(ranking, prices, context) for all valued watchlist entries."""
    import json

    from portfolio_tracker.opportunities import rank

    tickers = tuple(sorted(e.ticker for e in wl))
    q = quotes(tickers)
    prices = {tk: float(q.loc[tk, "price"]) for tk in tickers if tk in q.index and pd.notna(q.loc[tk, "price"])}
    context = {e.ticker: company_context(e.ticker, json.dumps(e.thesis_kpis, sort_keys=True)) for e in wl}
    weights = {}
    for isin, tk in p.tickers.items():
        if tk and isin in p.positions.index:
            weights[tk] = float(p.positions.loc[isin, "weight"])
    return rank(wl, prices, context, weights, rf=settings()["rf"]), prices, context


def fair_value_series_eur(p: Portfolio, wl: Watchlist) -> dict[str, pd.Series]:
    """Your past fair values per ticker (from the valuation history), converted to EUR at the time."""
    out = {}
    for e in wl:
        h = pd.DataFrame(e.history)
        if h.empty or "fair_value" not in h:
            continue
        h["date"] = pd.to_datetime(h["date"])
        s = h.dropna(subset=["fair_value"]).set_index("date")["fair_value"].sort_index()
        code = "GBP" if e.currency == "GBp" else e.currency
        if code in p.prices.fx:
            fx = p.prices.fx[code].reindex(s.index, method="ffill")
            s = s / fx.fillna(1.0)
        out[e.ticker] = s
    return out


def page_header(title: str, subtitle: str | None = None) -> None:
    st.title(title)
    if subtitle:
        st.markdown(f'<div class="page-sub">{tr(subtitle)}</div>', unsafe_allow_html=True)


def section_label(text: str) -> None:
    st.markdown(f'<div class="section-label">{tr(text)}</div>', unsafe_allow_html=True)


def pill(text: str, kind: str = "neutral") -> str:
    return f'<span class="pill {kind}">{tr(text)}</span>'


@st.cache_data(ttl=6 * 3600, show_spinner="Parsing earnings releases …")
def guidance_releases(ticker: str, name: str) -> list:
    """Latest earnings releases with parsed outlook (cached; releases themselves are cached on disk)."""
    from portfolio_tracker.guidance import Guidance
    try:
        return Guidance(CACHE_DIR).releases(ticker, name, limit=5)
    except Exception:
        return []


@st.cache_data(ttl=86400, show_spinner="Opening up your ETFs …")
def fund_profiles(tickers: tuple[str, ...]) -> dict:
    """Top holdings and sector weights per ETF ticker (cached on disk for two weeks)."""
    out = {}
    for tk in tickers:
        prof = research().fund_profile(tk)
        if prof is not None:
            out[tk] = prof
    return out


@st.cache_data(ttl=86400, show_spinner="Loading dividend history …")
def dividend_history(tickers: tuple[str, ...]) -> dict:
    from portfolio_tracker.market import dividend_history as fetch
    return fetch(MarketData(CACHE_DIR), list(tickers))


# ------------------------------------------------------------------ tables
def _cell(value, fmt: str) -> tuple[str, str]:
    """(html, css class) for one table cell."""
    import html as _html

    if fmt == "text":
        return ("–" if _missing(value) or value is None else _html.escape(str(tr(value)))), "t"
    if fmt == "html":
        return ("–" if value is None else str(value)), "t"
    if fmt == "rtext":
        return ("–" if value is None else _html.escape(str(value))), "n"
    if _missing(value) or value is None:
        return "–", "n muted"
    if fmt == "date":
        try:
            return tr(pd.Timestamp(value).strftime("%d %b %Y")), "n"
        except Exception:
            return str(value), "n"
    if fmt == "bar":  # share 0..1 with an inline bar
        w = max(min(float(value), 1.0), 0.0) * 100
        return (f'<span class="bar"><span style="width:{w:.1f}%"></span></span>'
                f'<span class="barval">{_n(float(value) * 100, 1)}%</span>'), "n"
    kind, _, dec = fmt.partition(":")
    d = int(dec) if dec else (0 if kind in ("eur0", "int") else 2 if kind in ("eur", "num", "money") else 1)
    v = float(value)
    if kind in ("eur", "eur0"):
        return eur(v, d), "n"
    if kind in ("euro", "euro0"):  # always euros (taxes, broker amounts)
        return eur(v, 0 if kind == "euro0" else d, ccy="EUR"), "n"
    if kind == "seur":
        cls = "n pos" if v > 0 else ("n neg" if v < 0 else "n")
        return eur(v, d, sign=True), cls
    if kind == "pct":
        return pct(v, d, sign=False), "n"
    if kind == "spct":
        cls = "n pos" if v > 0.0005 else ("n neg" if v < -0.0005 else "n")
        return pct(v, d), cls
    if kind == "pp":
        cls = "n pos" if v > 0 else ("n neg" if v < 0 else "n")
        return f"{_n(v * 100, d, True)} pp", cls
    if kind == "x":
        return f"{_n(v, d)}×", "n"
    if kind == "int":
        return _n(v, 0), "n"
    return _n(v, d), "n"


def table(df: pd.DataFrame, fmt: dict[str, str] | None = None, total: bool = False, compact: bool = False,
          max_height: int | None = None) -> None:
    """Minimal, elegant read-only table: no grid, right-aligned tabular numbers, colored signs.

    ``fmt`` maps column -> 'text' | 'html' | 'date' | 'bar' | 'eur[:d]' | 'eur0' | 'seur[:d]' | 'pct[:d]' |
    'spct[:d]' | 'pp[:d]' | 'num[:d]' | 'x[:d]' | 'int'. Percent formats expect fractions (0.12 = 12%).
    ``total`` emphasises the last row.
    """
    fmt = fmt or {}
    cols = list(df.columns)
    heads = []
    for col in cols:
        f_ = fmt.get(col, "num" if pd.api.types.is_numeric_dtype(df[col]) else "text")
        align = "t" if f_ in ("text", "html") else "n"
        heads.append(f'<th class="{align}">{tr(str(col))}</th>')
    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        cells = []
        for col in cols:
            f_ = fmt.get(col, "num" if pd.api.types.is_numeric_dtype(df[col]) else "text")
            html_, cls = _cell(r[col], f_)
            html_ = _typeset(html_) if f_ not in ("text", "html") else html_
            cells.append(f'<td class="{cls}">{html_}</td>')
        cls = ' class="total"' if total and i == len(df) - 1 else ""
        rows.append(f"<tr{cls}>{''.join(cells)}</tr>")
    style = f' style="max-height:{max_height}px"' if max_height else ""
    st.markdown(f'<div class="tblwrap"{style}><table class="tbl{" compact" if compact else ""}"><thead><tr>'
                f'{"".join(heads)}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>', unsafe_allow_html=True)


def step_nav(key: str, labels: list[str], current_index: int) -> None:
    """'← Back' / 'Next →' buttons that switch a stateful st.tabs (key) to the neighbouring step."""
    def go(target: str) -> None:
        st.session_state[key] = target
        st.session_state["_scroll_to"] = key  # bring the step bar back into view after the rerun

    left, mid, right = st.columns([1, 2, 1], vertical_alignment="center")
    if current_index > 0:
        left.button(f"← {tr(labels[current_index - 1])}", key=f"{key}_back_{current_index}", on_click=go,
                    args=(labels[current_index - 1],), width="stretch")
    mid.markdown(f'<div class="stepinfo">{tr(f"Step {current_index + 1} of {len(labels)}")}</div>',
                 unsafe_allow_html=True)
    if current_index < len(labels) - 1:
        right.button(f"{tr(labels[current_index + 1])} →", key=f"{key}_next_{current_index}", on_click=go,
                     args=(labels[current_index + 1],), type="primary", width="stretch")


VERDICT_PILL = {"Buy": "good", "Buy (small)": "good", "Savings plan": "info", "Watch": "warn", "Avoid": "bad"}
SIGNAL_PILL = {"buy": ("Buy zone", "good"), "hold": ("Hold", "neutral"), "review": ("Review / sell?", "bad"),
               "trim": ("Consider trimming", "warn"), "none": ("Not valued", "neutral")}


def verdict_pill(v: str | None) -> str:
    return pill(v, VERDICT_PILL.get(v, "neutral")) if v else "–"


def signal_pill(code: str | None) -> str:
    label, kind = SIGNAL_PILL.get(code or "none", ("–", "neutral"))
    return pill(label, kind)


def thesis_pill(state: str | None) -> str:
    return {"intact": pill("intact", "good"), "broken": pill("broken", "bad")}.get(state or "", "–")


THEME_SYNC = """<script>
  /* Mirror Streamlit's active theme (light/dark) as a data-theme attribute on the root element, so style.css
     can switch its palette instantly – also when the theme changes in the settings menu. Installed once. */
  (function () {
    if (window.__ptThemeSync) return;
    window.__ptThemeSync = true;
    function sync() {
      const app = document.querySelector(".stApp");
      if (!app) return;
      const rgb = (getComputedStyle(app).color.match(/[0-9.]+/g) || [0, 0, 0]).map(Number);
      const want = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 140 ? "dark" : "light";   /* light text */
      if (document.documentElement.dataset.theme !== want) document.documentElement.dataset.theme = want;
    }
    sync();
    setInterval(sync, 300);
  })();
</script>"""


def sync_theme() -> None:
    st.html(THEME_SYNC, unsafe_allow_javascript=True)


def scroll_into_view_if_requested(key: str) -> None:
    """After a 'Next/Back' click, scroll smoothly to the stateful tabs with this key."""
    if st.session_state.pop("_scroll_to", None) != key:
        return
    st.html(f"""<script>
      (function () {{
        const el = document.querySelector('.st-key-{key}');
        const main = document.querySelector('[data-testid="stMain"]');
        if (el && main) {{
          const top = el.getBoundingClientRect().top + main.scrollTop - 72;   /* clear of the fixed header */
          main.scrollTo({{top: Math.max(top, 0), behavior: 'smooth'}});
        }}
      }})();
    </script>""", unsafe_allow_javascript=True)


# ----------------------------------------------------------------- backtest
@st.cache_data(ttl=86400, show_spinner="Loading ten years of prices …")
def total_return_prices(ticker: str) -> pd.Series:
    """Ten years of daily prices with dividends reinvested (trading currency) – the backtest's input."""
    from portfolio_tracker.backtest import total_return_index
    from portfolio_tracker.market import dividend_history as fetch

    try:
        prices = research().fundamentals(ticker).prices
    except Exception:
        return pd.Series(dtype=float)
    divs = fetch(MarketData(CACHE_DIR), [ticker]).get(ticker, pd.Series(dtype=float))
    return total_return_index(prices, divs)


@st.cache_data(show_spinner="Testing every start month …")
def backtest_windows(ticker: str, drops: tuple[float, ...], max_wait: int | None, years: int, rf: float) -> pd.DataFrame:
    from portfolio_tracker.backtest import DipRule, rolling

    return rolling(total_return_prices(ticker), 100.0, DipRule(drops, max_wait), rf, years)
