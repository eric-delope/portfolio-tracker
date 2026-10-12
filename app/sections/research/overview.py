"""Step 1 – overview: business model, key figures, latest company outlook and sources."""

from __future__ import annotations

import streamlit as st
from i18n import tr

import common as c
from common import money, num, pct


def unit_label(unit: str) -> str:
    return "%" if unit == "%" else ("bn" if unit == "billion" else "m")


def render(x) -> None:
    f, cur, latest = x.f, x.cur, x.latest
    left, right = st.columns([3, 2], gap="medium")
    with left, c.card():
        c.card_title("Business model", "only buy what you can explain in two sentences")
        if f.summary:
            short = f.summary if len(f.summary) < 520 else f.summary[:520].rsplit(". ", 1)[0] + "."
            st.markdown(f'<div class="prose">{short}</div>', unsafe_allow_html=True)
            if len(f.summary) >= 520:
                with st.expander("Full description"):
                    st.markdown(f'<div class="prose">{f.summary}</div>', unsafe_allow_html=True)
    with right, c.card():
        c.card_title("At a glance", "last twelve months")
        ttm = f.ttm
        rows = [
            ("Revenue", f"{num(ttm['revenue'] / 1e9, 1)} bn {cur}" if ttm.get("revenue") else "–"),
            ("Operating margin", pct(ttm["operating_income"] / ttm["revenue"], 1, False)
             if ttm.get("revenue") and ttm.get("operating_income") is not None else "–"),
            ("Free cash flow", f"{num(ttm['fcf'] / 1e9, 1)} bn {cur}" if ttm.get("fcf") is not None else "–"),
            ("Stock-based compensation", f"{num(ttm['sbc'] / 1e9, 1)} bn {cur}" if ttm.get("sbc") else "–"),
            ("Net cash / (net debt)", f"{num(-f.net_debt / 1e9, 1)} bn {cur}" if f.net_debt is not None else "–"),
            ("Analysts", f"{f.analysts or '–'} · avg. target {money(f.target_mean, cur, 0)}" if f.target_mean else "–"),
        ]
        c.calc_table(rows)
    if latest and latest.items:
        c.section_label(f"Company outlook · earnings release of {latest.date:%d %b %Y}")
        c.stats([c.stat(it.label[:48], f"{num(it.low, 1)}–{num(it.high, 1)}%" if it.unit == "%" else
                        f"{it.currency or ''}{num(it.low, 1)}–{num(it.high, 1)} {unit_label(it.unit)}", help=it.label)
                 for it in latest.items[:4]])
    links = []
    if f.ir_website or f.website:
        links.append(f"[Investor relations]({f.ir_website or f.website})")
    if latest:
        links.append(f"[Latest earnings release]({latest.url})")
    for fl in f.filings[:3]:
        links.append(f"[{fl['type']} of {fl['date']:%d %b %Y}]({fl['url']})")
    if links:
        st.caption(tr("Sources: ") + " · ".join(links))
