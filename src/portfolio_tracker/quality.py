"""Quality check: simple, transparent criteria to spot value traps before buying.

Each check is pass / fail / not evaluable (missing data), with the number that
decided it. Thresholds are deliberately conventional rules of thumb.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

REVENUE_GROWTH_MIN = 0.05
MARGIN_DROP_MAX = 0.02
FCF_CONVERSION_MIN = 0.80
LEVERAGE_MAX = 2.5
ROE_MIN = 0.15
DILUTION_MAX = 0.01


@dataclass
class Check:
    name: str
    value: str
    passed: bool | None
    rule: str


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _cagr(first: float, last: float, years: float) -> float:
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return np.nan
    return (last / first) ** (1 / years) - 1


def quality_checks(annual: pd.DataFrame, net_debt: float | None, ebitda: float | None,
                   roe: float | None) -> list[Check]:
    a = annual.sort_index() if annual is not None else pd.DataFrame()
    checks: list[Check] = []

    def series(col: str) -> pd.Series:
        return a[col].dropna() if col in a else pd.Series(dtype=float)

    rev = series("revenue")
    if len(rev) >= 2:
        yrs = (rev.index[-1] - rev.index[0]).days / 365.25
        g = _cagr(rev.iloc[0], rev.iloc[-1], yrs)
        checks.append(Check("Revenue growth", f"{_pct(g)} p.a. ({rev.index[0].year}–{rev.index[-1].year})",
                            bool(g > REVENUE_GROWTH_MIN) if np.isfinite(g) else None, "> 5% p.a."))
    else:
        checks.append(Check("Revenue growth", "–", None, "> 5% p.a."))

    op = series("operating_income")
    both = pd.concat([op, rev], axis=1, keys=["op", "rev"]).dropna()
    both = both[both["rev"] > 0]
    if len(both) >= 2:
        first, last = both["op"].iloc[0] / both["rev"].iloc[0], both["op"].iloc[-1] / both["rev"].iloc[-1]
        checks.append(Check("Operating margin", f"{last * 100:.1f}% (was {first * 100:.1f}%)",
                            bool(last >= first - MARGIN_DROP_MAX), "stable or rising"))
    else:
        checks.append(Check("Operating margin", "–", None, "stable or rising"))

    fn = pd.concat([series("fcf"), series("net_income")], axis=1, keys=["fcf", "ni"]).dropna()
    if len(fn) >= 2 and fn["ni"].sum() > 0:
        conv = fn["fcf"].sum() / fn["ni"].sum()
        checks.append(Check("Cash conversion (FCF ÷ net income)", f"{conv * 100:.0f}%",
                            bool(conv >= FCF_CONVERSION_MIN), "≥ 80% – earnings turn into cash"))
    else:
        checks.append(Check("Cash conversion (FCF ÷ net income)", "–", None, "≥ 80%"))

    if net_debt is not None and ebitda:
        lev = net_debt / ebitda
        value = "Net cash" if lev < 0 else f"{lev:.1f}× EBITDA"
        checks.append(Check("Leverage", value, bool(lev < LEVERAGE_MAX), "Net debt < 2.5× EBITDA"))
    else:
        checks.append(Check("Leverage", "–", None, "Net debt < 2.5× EBITDA"))

    if roe is not None:
        checks.append(Check("Return on equity", f"{roe * 100:.0f}%", bool(roe > ROE_MIN), "> 15%"))
    else:
        checks.append(Check("Return on equity", "–", None, "> 15%"))

    sh = series("shares")
    if len(sh) >= 2:
        yrs = (sh.index[-1] - sh.index[0]).days / 365.25
        d = _cagr(sh.iloc[0], sh.iloc[-1], yrs)
        checks.append(Check("Share count", f"{_pct(d)} p.a. (buybacks)" if d < 0 else f"{_pct(d)} p.a.",
                            bool(d <= DILUTION_MAX) if np.isfinite(d) else None, "no dilution (≤ +1% p.a.)"))
    else:
        checks.append(Check("Share count", "–", None, "no dilution"))

    eps = series("eps")
    if len(eps):
        checks.append(Check("Profitable every year", f"{(eps > 0).sum()} of {len(eps)} years positive",
                            bool((eps > 0).all()), "consistently profitable"))
    else:
        checks.append(Check("Profitable every year", "–", None, "consistently profitable"))
    return checks


def quality_score(checks: list[Check]) -> tuple[int, int, str]:
    """(passed, evaluated, label)."""
    evaluated = [c for c in checks if c.passed is not None]
    passed = sum(c.passed for c in evaluated)
    if not evaluated:
        return 0, 0, "no data"
    share = passed / len(evaluated)
    label = "high" if share >= 0.8 else ("medium" if share >= 0.5 else "low")
    return passed, len(evaluated), label


# Qualitative judgement: 2 = strong, 1 = medium, 0 = weak
JUDGEMENT_LEVELS = {"strong": 2, "medium": 1, "weak": 0}


def recommend_margin(checks_passed_share: float, moat: int, predictability: int, management: int) -> dict:
    """Margin of safety and required return from hard numbers (50 %) and your own judgement (50 %).

    High quality businesses deserve a smaller discount: their value is more
    predictable. Weak ones need a large cushion for errors in the forecast.
    """
    hard = checks_passed_share if np.isfinite(checks_passed_share) else 0.5
    soft = (moat + predictability + management) / 6
    score = 0.5 * hard + 0.5 * soft
    label = "high" if score >= 0.75 else ("medium" if score >= 0.45 else "low")
    margin = round(0.30 - 0.20 * score, 2)          # 10 % (best) .. 30 % (worst)
    required = round(0.12 - 0.03 * score, 3)        # 9 % (best) .. 12 % (worst)
    return {"score": score, "label": label, "margin_of_safety": margin, "required_return": required}
