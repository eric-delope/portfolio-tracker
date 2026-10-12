"""Streamlit entry point: ``streamlit run app/dashboard.py``."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))  # runs without `pip install -e .` (e.g. Streamlit Cloud)
import i18n  # noqa: E402
from i18n import tr  # noqa: E402

import charts as ch  # noqa: E402
import common as c  # noqa: E402
from portfolio_tracker import privacy  # noqa: E402

st.set_page_config(page_title="Portfolio Tracker", page_icon="📈", layout="wide")
i18n.install()
i18n.activate()
st.markdown(f"<style>{(Path(__file__).parent / 'style.css').read_text()}</style>", unsafe_allow_html=True)
c.reset_cards()

with st.sidebar:
    st.segmented_control("Language", list(i18n.LANGUAGES), default="en", required=True, key="lang",
                         format_func=i18n.LANGUAGES.get, label_visibility="collapsed")
    st.segmented_control("Currency", ["EUR", "USD"], default="EUR", required=True, key="base_ccy",
                         help="Reporting currency. Every price, trade and dividend is converted at the exchange rate "
                              "of its own day, so values and returns are those of a euro or a dollar investor. Taxes, "
                              "order amounts and broker alerts stay in euros – your account currency.")
    st.toggle("Privacy mode", key="privacy",
              help="Hides all euro amounts – only percentages remain. Ideal for screenshots.")
    with st.expander("Settings"):
        st.number_input("Risk-free rate p.a. (%)", 0.0, 10.0, 2.0, 0.25, key="rf_pct",
                        help="Used for Sharpe, Sortino and alpha. Reference: ECB deposit rate or overnight savings.")
        st.number_input("Tax-free allowance (€)", 0, 2000, 1000, 100, key="allowance",
                        help="German Sparerpauschbetrag: €1,000 for singles, €2,000 for joint filers.")
        st.file_uploader("Load a broker export", type="csv", key="upload",
                         help="Trade Republic and Scalable Capital exports are recognised automatically. Any other "
                              "broker: copy your transactions into the generic template (docs/IMPORT_FORMATS.md).")
        if st.button("Reload prices", help="Clears the cache and fetches current prices."):
            st.cache_resource.clear()
            st.cache_data.clear()
            (c.CACHE_DIR / "prices.pkl").unlink(missing_ok=True)

pages = st.navigation([
    st.Page("views/monthly.py", title=tr("Monthly report"), icon=":material/calendar_month:", default=True),
    st.Page("views/analysis.py", title=tr("Portfolio analysis"), icon=":material/monitoring:"),
    st.Page("views/planning.py", title=tr("Planning"), icon=":material/trending_up:"),
    st.Page("views/watchlist.py", title=tr("Watchlist & entries"), icon=":material/notifications_active:"),
    st.Page("views/research.py", title=tr("Company research"), icon=":material/query_stats:"),
    st.Page("views/privacy.py", title=tr("Privacy & data"), icon=":material/shield_lock:"),
])

label, tx, p = c.load()
ch.set_currency(c.symbol())   # after load: falls back to euros if no exchange rates
found = c.issues(tx, label)
with st.sidebar:
    status = tr("Data checks passed" if not found else f"{len(found)} data issue(s) – see Methodology")
    network = tr("offline – no requests" if privacy.offline() else "prices via Yahoo Finance")
    count = tr(f"{len(tx)} transactions")
    source = tr(tx.attrs.get("format", "Trade Republic"))
    until = tr(f"prices to {p.last_date:%d %b %Y}")
    st.markdown((f'<span class="badge">{tr("Demo portfolio")}</span><br>' if c.demo_mode() else "")
                + f'<div class="side-note"><b>{count}</b> · {until}<br>'
                f'{source} · {status}<br>{tr("Processed on this computer")} · {network}</div>', unsafe_allow_html=True)
    if c.demo_mode():
        st.caption("Synthetic data on real prices. Add your broker export to `data/raw/` or upload it under Settings.")
    st.caption("Light or dark: follows your system – switch under ⋮ (top right) → Settings.")
    c.sync_theme()

pages.run()
