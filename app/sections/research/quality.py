"""Step 3 – quality: hard checks, management track record, own judgement -> margin of safety and hurdle."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import pct, plot
from portfolio_tracker.guidance import track_record
from portfolio_tracker.quality import JUDGEMENT_LEVELS, quality_checks, quality_score, recommend_margin

WHY = {
    "Revenue growth": "Growth is the source of future earnings.",
    "Operating margin": "Stable margins signal pricing power.",
    "Cash conversion (FCF ÷ net income)": "Only profit that arrives as cash is real.",
    "Leverage": "Little debt = room to manoeuvre in a crisis.",
    "Return on equity": "High returns on capital = a good business model.",
    "Share count": "Dilution spreads earnings over more shares.",
    "Profitable every year": "Losses make valuations uncertain.",
}


def render(x) -> None:
    f, a, ticker = x.f, x.a, x.ticker
    c.lead("**Would you want to own this business for five years or more?** The numbers give the hard half of the "
           "answer, your judgement the soft half – together they set the margin of safety you demand.")
    checks = quality_checks(a, f.net_debt, f.ebitda, f.roe)
    passed, evaluated, _ = quality_score(checks)
    x.quality_checks = checks
    c.table(pd.DataFrame([{
        "Criterion": f'<span title="{WHY.get(ch_.name, "")}">{ch_.name}</span>',
        "Value": ch_.value, "Rule of thumb": ch_.rule,
        "Result": c.pill("passed", "good") if ch_.passed else (c.pill("failed", "bad") if ch_.passed is False else "–"),
    } for ch_ in checks]), {"Criterion": "html", "Value": "text", "Rule of thumb": "text", "Result": "html"})

    q_rev = f.quarterly["revenue"] if "revenue" in f.quarterly else pd.Series(dtype=float)
    tr = track_record(x.releases, q_rev) if x.releases and f.fx_factor == 1.0 else pd.DataFrame()
    if not tr.empty:
        c.section_label("Does management deliver? Revenue guidance vs. result")
        tc1, tc2 = st.columns([3, 2], gap="medium")
        with tc1:
            plot(ch.titled(ch.guidance_track(tr.iloc[::-1], 1e9, "bn"), "Guided range and actual revenue",
                           "dot blue = above guidance · gray = within · red = below",
                           "Source: earnings releases (SEC 8-K/6-K) and quarterly reports"))
        with tc2:
            n_ok = int((tr["result"] != "below range").sum())
            c.stats([c.stat("Guidance met or beaten", f"{n_ok} of {len(tr)}", f"avg. {pct(tr['vs_mid'].mean())} vs. midpoint")])
            st.caption("Meeting or slightly beating guidance regularly is a sign of conservative, credible planning.")

    st.subheader("Your judgement")
    answers = x.inputs.get("quality_answers", {})
    levels = list(JUDGEMENT_LEVELS)
    q1, q2, q3 = st.columns(3)
    x.moat = q1.segmented_control("Competitive advantage (moat)", levels, default=answers.get("moat", "medium"),
                                  required=True, key=f"moat_{ticker}",
                                  help="Strong: network effects, brand, switching costs or cost advantages that "
                                       "competitors cannot copy for years.")
    x.predict = q2.segmented_control("Predictability of the business", levels,
                                     default=answers.get("predictability", "medium"), required=True, key=f"pred_{ticker}",
                                     help="Strong: recurring revenue, little cyclicality, stable demand.")
    x.mgmt = q3.segmented_control("Management & capital allocation", levels,
                                  default=answers.get("management", "medium"), required=True, key=f"mgmt_{ticker}",
                                  help="Strong: keeps promises, invests at high returns, sensible buybacks, no "
                                       "expensive acquisitions.")
    x.rec = rec = recommend_margin(passed / evaluated if evaluated else np.nan, JUDGEMENT_LEVELS[x.moat],
                                   JUDGEMENT_LEVELS[x.predict], JUDGEMENT_LEVELS[x.mgmt])
    c.stats([
        c.stat("Quality", rec["label"], f"numbers {passed}/{evaluated} · judgement {x.moat}/{x.predict}/{x.mgmt}"),
        c.stat("Margin of safety", pct(rec["margin_of_safety"], 0, False), "recommended",
               help="The more uncertain the forecast, the larger the buffer: 10% for the highest, 30% for low quality."),
        c.stat("Required return", pct(rec["required_return"], 1, False), "recommended",
               help="More uncertainty demands a higher return: 9% for the highest, 12% for low quality."),
    ])
    if rec["label"] == "low":
        c.callout("Low quality: even a low price rarely makes up for a weak business. Consider whether you want to "
                  "invest here at all.", "warn")
