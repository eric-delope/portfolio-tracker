"""Privacy & data: what stays on this computer, what left it (and why), and what is stored where."""

from __future__ import annotations

import shutil

import pandas as pd
import streamlit as st

import common as c
from portfolio_tracker import privacy

c.page_header("Privacy & data", "The hosted demo: what it does with data, and how the real tool keeps yours on your own "
                                "computer." if c.HOSTED else "Your portfolio is processed on this computer. This page shows "
                                "exactly what was sent to the internet – and what never is.")

offline = privacy.offline()
local_only = st.get_option("server.address") in ("localhost", "127.0.0.1", "::1")
log = privacy.summary()
if c.HOSTED:
    c.callout("**This is the hosted live demo.** It runs on Streamlit's servers with a synthetic portfolio and a bundled "
              "market-data snapshot: uploads are disabled, nothing you enter is saved, and no request goes to a third "
              f"party. The real tool is installed on your own computer and reads your broker export there – "
              f"[setup on GitHub]({c.REPO_URL}).", "info")
c.stats([
    c.stat("Processing", "Hosted demo", "synthetic data only, uploads disabled") if c.HOSTED else
    c.stat("Processing", "Local", "your export is never uploaded",
           help="The CSV is read from data/raw/ or held in memory after an upload – never sent to a server."),
    c.stat("Network", "Offline" if offline else "Prices only", "no requests at all" if offline else "public tickers to Yahoo",
           help="Start with PORTFOLIO_OFFLINE=1 to block every request and work from the local cache."),
    c.stat("Dashboard access", "Public demo", "anyone with the link") if c.HOSTED else
    c.stat("Dashboard access", "This computer" if local_only else "Network-wide",
           "bound to localhost" if local_only else "check server.address"),
    c.stat("Requests since start", str(sum(g["requests"] for g in log)), "all listed below"),
])
if not local_only and not c.HOSTED:
    c.callout("The dashboard is reachable from other devices on your network. Set `address = \"localhost\"` in "
              "`.streamlit/config.toml`.", "high")

left, right = st.columns([3, 2], gap="medium")
with left:
    st.subheader("What left this computer")
    if offline:
        c.callout("Offline mode is on: no request was made. Prices, fundamentals and guidance come from the local "
                  "cache (`data/cache/`).", "good")
    elif not log:
        st.caption("No requests yet in this session – everything shown came from the local cache.")
    else:
        rows = [{"Recipient": g["host"], "Purpose": g["purpose"], "Requests": g["requests"],
                 "Identifiers sent": ", ".join(g["sent"][:8]) + (f" … (+{len(g['sent']) - 8})" if len(g["sent"]) > 8 else "")}
                for g in log]
        table = pd.DataFrame(rows)
        if c.privacy():  # tickers would reveal the holdings in a screenshot
            table["Identifiers sent"] = [f"{len(g['sent'])} identifiers (hidden in privacy mode)" for g in log]
        c.table(table, {"Requests": "int"}, compact=True)
        st.caption("Since the app was started. Identifiers are public ticker symbols, ISINs or what you typed into the "
                   "company search. Like any website, the recipient also sees your IP address.")
with right:
    st.subheader("What never leaves")
    with c.card():
        c.facts([
            "Amounts, share counts, buy prices, cash balance",
            "Transactions, savings plans, dividends, taxes",
            "Names, IBANs, card merchants – **removed on import**",
            "Your valuations, theses, watchlist and notes",
            "Usage statistics and font requests – none at all",
        ])

def _storage() -> None:
    """What is stored where on this computer (not shown in the hosted demo, which stores nothing)."""
    st.subheader("What is stored on this computer")


    def _inventory(folder) -> tuple[int, float]:
        files = [f for f in folder.rglob("*") if f.is_file()] if folder.exists() else []
        return len(files), sum(f.stat().st_size for f in files) / 1e6


    places = [
        ("data/raw/", c.RAW_DIR, "your Trade Republic exports", "never published (git-ignored)"),
        ("data/user/", c.WATCHLIST_FILE.parent, "watchlist, valuations, theses", "never published (git-ignored)"),
        ("reports/", c.REPORT_DIR, "saved monthly notes", "never published (git-ignored)"),
        ("data/cache/", c.CACHE_DIR, "public market data (prices, fundamentals)", "safe to delete, re-downloaded"),
    ]
    inv = []
    for label, folder, content, note in places:
        n, mb = _inventory(folder)
        inv.append({"Folder": label, "Content": content, "Files": n, "Size (MB)": mb, "Note": note})
    c.table(pd.DataFrame(inv), {"Files": "int", "Size (MB)": "num:1"}, compact=True)
    st.caption("Uploads in the sidebar are kept in memory only and disappear when the app stops. Use disk encryption "
               "(FileVault/BitLocker) to protect the folders above at rest.")

    with st.expander("Delete cached market data"):
        st.caption("Removes everything in `data/cache/` (only public market data). Your exports, watchlist and notes "
                   "are not touched.")
        if st.checkbox("I understand – delete the cache", key="confirm_cache_delete") and st.button("Delete cache"):
            shutil.rmtree(c.CACHE_DIR, ignore_errors=True)
            st.cache_data.clear()
            st.cache_resource.clear()
            st.success("Cache deleted.")


if not c.HOSTED:
    _storage()

with st.expander("How the privacy guarantees are enforced"):
    st.markdown(
        "- **One gate for every request** (`portfolio_tracker.privacy`): each call to the internet passes through it – "
        "that is how this page can list them, and how offline mode can block them all.\n"
        "- **Automated tests in CI**: personal details from a sample export must not appear in any output; the "
        "analytics core must run with all sockets blocked; offline mode must make zero requests; the files that would "
        "be published must contain no exports, IBANs or e-mail addresses.\n"
        "- **Privacy mode** (sidebar) hides every euro amount for screenshots and screen sharing.\n"
        "- Details and limits: `docs/PRIVACY.md`."
    )
