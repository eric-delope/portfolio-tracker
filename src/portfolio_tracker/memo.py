"""One-page investment memo (PDF) from a company valuation: thesis, numbers, price discipline, plan.

Built with ReportLab only (no browser, no LaTeX), so it runs anywhere the dashboard runs. Layout follows a
classic buy-side one-pager: verdict up top, then the evidence (quality, growth, what the price implies),
the valuation bridge to the maximum price, and the entry plan with the conditions that would end the thesis.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date
from html import escape

import pandas as pd
from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK, MUTED, RULE, ACCENT, WARN = (colors.HexColor(c) for c in ("#0b0b0b", "#6b6a65", "#dcdad3", "#2a78d6", "#eb6834"))

BASE = ParagraphStyle("base", fontName="Helvetica", fontSize=8.2, leading=10.4, textColor=INK)
SMALL = ParagraphStyle("small", parent=BASE, fontSize=7.4, leading=9.4, textColor=MUTED)
H1 = ParagraphStyle("h1", parent=BASE, fontName="Helvetica-Bold", fontSize=15, leading=18)
H2 = ParagraphStyle("h2", parent=BASE, fontName="Helvetica-Bold", fontSize=9.2, leading=11.5, spaceBefore=6, spaceAfter=2)
RIGHT = ParagraphStyle("right", parent=BASE, alignment=TA_RIGHT)


# The built-in PDF fonts (WinAnsi) lack a few typographic characters used across the app.
_ASCII = str.maketrans({"−": "-", "≈": "~", "≥": ">=", "≤": "<=", "→": "->", "←": "<-", "★": "*"})


def P(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(str(text).translate(_ASCII), style)


@dataclass
class Memo:
    name: str
    ticker: str
    currency: str
    price: float
    fair_value: float
    max_price: float
    expected_return: float          # p.a. when buying today
    required_return: float
    margin_of_safety: float
    horizon: int
    verdict: str                     # one line, Markdown **bold** allowed
    thesis: str = ""
    quality: list[tuple[str, str, str]] = field(default_factory=list)   # (criterion, value, passed/failed/–)
    quality_verdict: str = ""
    growth: list[tuple[str, str]] = field(default_factory=list)         # (source, growth text)
    scenarios: pd.DataFrame | None = None                                # Scenario, Probability %, EPS growth, Exit P/E
    bridge: list[tuple[str, str]] = field(default_factory=list)         # valuation bridge rows
    reverse_dcf: list[tuple[str, str]] = field(default_factory=list)    # (label, value)
    tranches: list[tuple[str, str, str, str]] = field(default_factory=list)  # (tranche, price, amount, exp. return)
    tranche_levels: list[float] = field(default_factory=list)            # tranche prices for the chart
    kpis: list[str] = field(default_factory=list)                        # "Revenue growth >= 5.0%"
    guidance: str = ""
    prices: pd.Series | None = None                                      # ~2 years of closes for the chart
    as_of: date = field(default_factory=date.today)


def _fmt(x: float, decimals: int = 2) -> str:
    return f"{x:,.{decimals}f}"


def _pct(x: float, decimals: int = 1, sign: bool = True) -> str:
    return f"{x * 100:{'+' if sign else ''}.{decimals}f}%"


def _table(rows: list[list], widths: list[float], header: bool = True, align_right_from: int = 1) -> Table:
    data = [[P(escape(str(c)), BASE if j < align_right_from else RIGHT) for j, c in enumerate(r)] for r in rows]
    t = Table(data, colWidths=widths, hAlign="LEFT")
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
             ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
             ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]
    if header:
        style += [("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
        for j in range(len(rows[0])):
            data[0][j] = P(f"<font color='#6b6a65'>{escape(str(rows[0][j]))}</font>", SMALL if j < align_right_from else
                                   ParagraphStyle("hr", parent=SMALL, alignment=TA_RIGHT))
    t.setStyle(TableStyle(style))
    return t


def _price_chart(m: Memo, width: float, height: float = 34 * mm) -> Drawing:
    """Price line with fair value (orange), maximum price (blue) and tranche levels (dotted)."""
    d = Drawing(width, height)
    s = m.prices.dropna() if m.prices is not None else pd.Series(dtype=float)
    if len(s) < 2:
        return d
    levels = [m.fair_value, m.max_price, *m.tranche_levels]
    lo, hi = min(s.min(), *levels) * 0.95, max(s.max(), *levels) * 1.04
    left, right, bottom, top = 34, width - 4, 12, height - 4

    def y(v: float) -> float:
        return bottom + (v - lo) / (hi - lo) * (top - bottom)

    xs = [left + i / (len(s) - 1) * (right - left) for i in range(len(s))]
    for frac in (0, 0.5, 1):
        v = lo + frac * (hi - lo)
        d.add(Line(left, y(v), right, y(v), strokeColor=RULE, strokeWidth=0.4))
        d.add(String(left - 3, y(v) - 2.5, _fmt(v, 0), fontName="Helvetica", fontSize=6.2, fillColor=MUTED,
                     textAnchor="end"))
    for v in m.tranche_levels:
        d.add(Line(left, y(v), right, y(v), strokeColor=ACCENT, strokeWidth=0.5, strokeDashArray=[1.5, 2]))
    d.add(Line(left, y(m.fair_value), right, y(m.fair_value), strokeColor=WARN, strokeWidth=1))
    d.add(String(left + 3, y(m.fair_value) + 2, f"fair value {_fmt(m.fair_value)}", fontName="Helvetica", fontSize=6.4,
                 fillColor=WARN, textAnchor="start"))
    d.add(Line(left, y(m.max_price), right, y(m.max_price), strokeColor=ACCENT, strokeWidth=1))
    d.add(String(left + 3, y(m.max_price) + 2, f"max. price {_fmt(m.max_price)}", fontName="Helvetica", fontSize=6.4,
                 fillColor=ACCENT, textAnchor="start"))
    d.add(PolyLine([c for pt in zip(xs, [y(v) for v in s.values]) for c in pt], strokeColor=INK, strokeWidth=1.1))
    for i in (0, len(s) - 1):
        d.add(String(xs[i], 2, f"{s.index[i]:%b %Y}", fontName="Helvetica", fontSize=6.2, fillColor=MUTED,
                     textAnchor="start" if i == 0 else "end"))
    return d


def build_pdf(m: Memo) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=12 * mm,
                            bottomMargin=11 * mm, title=f"Investment memo – {m.name}", author="Portfolio Tracker")
    W = doc.width
    cur = m.currency
    story = [
        P(f"Investment memo · {escape(m.name)} <font color='#6b6a65' size=10>({escape(m.ticker)})</font>", H1),
        P(f"As of {m.as_of:%d %B %Y} · price {_fmt(m.price)} {cur} · horizon {m.horizon} years · "
                  f"required return {_pct(m.required_return, 1, False)}", SMALL),
        Spacer(1, 6),
    ]
    head = [["Fair value", "Maximum price", "Price today", "Expected return p.a."],
            [f"{_fmt(m.fair_value)} {cur}", f"{_fmt(m.max_price)} {cur}", f"{_fmt(m.price)} {cur}",
             _pct(m.expected_return)]]
    kpi = Table([[P(f"<font color='#6b6a65' size=7>{a}</font><br/><b>{b}</b>", BASE) for a, b in zip(*head)]],
                colWidths=[W / 4] * 4)
    kpi.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, RULE), ("INNERGRID", (0, 0), (-1, -1), 0.6, RULE),
                             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    verdict = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(m.verdict))
    story += [kpi, Spacer(1, 4), P(f"<b>Verdict:</b> {verdict}", BASE)]
    if m.thesis:
        story += [P("Thesis", H2), P(escape(m.thesis).replace("\n", "<br/>"), BASE)]

    half = (W - 6 * mm) / 2
    left, right = [], []
    if m.quality:
        left += [P(f"Quality – {escape(m.quality_verdict)}", H2),
                 _table([["Criterion", "Value", ""]] + [list(r) for r in m.quality], [half * 0.52, half * 0.33, half * 0.15])]
    if m.growth:
        left += [P("Growth: who expects what?", H2),
                 _table([["Source", "Growth p.a."]] + [list(r) for r in m.growth], [half * 0.65, half * 0.35])]
    if m.scenarios is not None and len(m.scenarios):
        sc = m.scenarios
        rows = [["Scenario", "Prob.", "EPS growth", "Exit P/E"]] + [
            [r["Scenario"], f"{r['Probability %']:.0f}%", f"{r['EPS growth % p.a.']:+.1f}%", f"{r['Exit P/E']:.1f}"]
            for _, r in sc.iterrows()]
        right += [P("Scenarios", H2), _table(rows, [half * 0.34, half * 0.2, half * 0.25, half * 0.21])]
    if m.bridge:
        right += [P("From earnings to the maximum price", H2),
                  _table([list(r) for r in m.bridge], [half * 0.7, half * 0.3], header=False)]
    if m.reverse_dcf:
        right += [P("Reverse DCF: what the price implies", H2),
                  _table([list(r) for r in m.reverse_dcf], [half * 0.7, half * 0.3], header=False)]
    cols = Table([[left, right]], colWidths=[half + 3 * mm, half + 3 * mm])
    cols.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (0, 0), 6 * mm), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    story.append(cols)

    plan = [P("Entry plan & price history", H2)]
    if m.tranches:
        plan.append(_table([["Tranche", "Price", "Amount", "Exp. return p.a."]] + [list(t) for t in m.tranches],
                           [W * 0.4, W * 0.2, W * 0.2, W * 0.2]))
    if m.prices is not None and len(m.prices):
        plan += [Spacer(1, 4), _price_chart(m, W)]
    story.append(KeepTogether(plan))
    if m.kpis or m.guidance:
        story.append(P("What would change my mind", H2))
        if m.kpis:
            story.append(P("Thesis KPIs, re-checked after every report: " + escape(" · ".join(m.kpis)) + ".", BASE))
        if m.guidance:
            story.append(P(f"Latest company guidance: “{escape(m.guidance)}”", BASE))
    story += [Spacer(1, 8), P(
        "Generated with Portfolio Tracker from the author's own assumptions and public data (Yahoo Finance, company "
        "filings). Not investment advice; figures can be incomplete or delayed.", SMALL)]
    doc.build(story)
    return buf.getvalue()
