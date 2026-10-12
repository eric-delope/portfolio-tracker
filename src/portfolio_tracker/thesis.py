"""Thesis check: a few business metrics per company with thresholds, re-checked after every report.

For a long-term investor the reason to sell is a broken thesis, not a price
move. Each KPI is read from the latest fundamentals (trailing twelve months
where Yahoo provides it), so the check refreshes automatically after earnings.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .research import Fundamentals


def _yoy(f: Fundamentals, col: str) -> float | None:
    a = f.annual
    if a is None or a.empty or col not in a:
        return None
    s = a[col].dropna()
    if len(s) < 2 or s.iloc[-2] <= 0:
        return None
    return float(s.iloc[-1] / s.iloc[-2] - 1)


def _fcf_margin(f: Fundamentals) -> float | None:
    return f.fcf / f.revenue if f.fcf is not None and f.revenue else None


def _leverage(f: Fundamentals) -> float | None:
    return f.net_debt / f.ebitda if f.net_debt is not None and f.ebitda else None


# name -> (getter, unit, explanation)
METRICS: dict[str, tuple[Callable[[Fundamentals], float | None], str, str]] = {
    "Revenue growth": (lambda f: f.revenue_growth if f.revenue_growth is not None else _yoy(f, "revenue"), "%",
                       "latest quarter vs. prior year (else last fiscal year)"),
    "EPS growth": (lambda f: f.earnings_growth if f.earnings_growth is not None else _yoy(f, "eps"), "%",
                   "latest quarter vs. prior year"),
    "Operating margin": (lambda f: f.operating_margin, "%", "trailing twelve months"),
    "Net margin": (lambda f: f.profit_margin, "%", "trailing twelve months"),
    "FCF margin": (_fcf_margin, "%", "free cash flow ÷ revenue, last fiscal year"),
    "Return on equity": (lambda f: f.roe, "%", "trailing twelve months"),
    "Net debt / EBITDA": (_leverage, "x", "negative = net cash"),
    "Share count (YoY)": (lambda f: _yoy(f, "shares"), "%", "negative = buybacks"),
}


@dataclass
class KpiResult:
    metric: str
    operator: str
    threshold: float
    value: float | None
    ok: bool | None
    unit: str


def evaluate(kpis: list[dict], f: Fundamentals) -> list[KpiResult]:
    """kpis: [{'metric': name, 'operator': '>=' | '<=', 'threshold': float}] (percent metrics as fractions)."""
    out = []
    for k in kpis:
        getter, unit, _ = METRICS.get(k.get("metric"), (lambda f: None, "", ""))
        value = getter(f)
        thr = float(k.get("threshold", 0.0))
        ok = None
        if value is not None and np.isfinite(value):
            ok = value >= thr if k.get("operator", ">=") == ">=" else value <= thr
        out.append(KpiResult(k.get("metric", "?"), k.get("operator", ">="), thr, value, ok, unit))
    return out


def status(results: list[KpiResult]) -> str:
    """'intact' | 'broken' | 'no KPIs'."""
    checked = [r for r in results if r.ok is not None]
    if not checked:
        return "no KPIs"
    return "intact" if all(r.ok for r in checked) else "broken"


def suggest(f: Fundamentals) -> list[dict]:
    """Starting points derived from today's values – deliberately loose, to be tightened by the user."""
    out = []
    g = METRICS["Revenue growth"][0](f)
    if g is not None:
        out.append({"metric": "Revenue growth", "operator": ">=", "threshold": round(max(g / 2, 0.0), 3)})
    om = f.operating_margin
    if om is not None:
        out.append({"metric": "Operating margin", "operator": ">=", "threshold": round(om - 0.05, 3)})
    lev = _leverage(f)
    out.append({"metric": "Net debt / EBITDA", "operator": "<=", "threshold": max(2.5, round((lev or 0) + 1, 1))})
    return out
