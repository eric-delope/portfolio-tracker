"""Number formatting shared by reports and the dashboard.

English conventions (1,234.56 · €1,234 · 12.3%) by default, German ones (1.234,56 · 1.234 € · 12,3 %) after
``set_language("de")``. An ASCII minus is kept, so Streamlit metric deltas still detect negative values.
"""

from __future__ import annotations

import contextvars
import math

_LANG: contextvars.ContextVar[str] = contextvars.ContextVar("language", default="en")
_SWAP = str.maketrans({",": ".", ".": ","})


def set_language(lang: str) -> None:
    """'en' or 'de' – per session (context variable), so two browser tabs can use different languages."""
    _LANG.set("de" if lang == "de" else "en")


def language() -> str:
    return _LANG.get()


def _local(text: str) -> str:
    """English digits (1,234.5) -> German (1.234,5) when the language is German."""
    return text.translate(_SWAP) if _LANG.get() == "de" else text


def _missing(x) -> bool:
    try:
        return x is None or math.isnan(float(x)) or math.isinf(float(x))
    except (TypeError, ValueError):
        return True


def num(x: float, decimals: int = 0, sign: bool = False) -> str:
    if _missing(x):
        return "–"
    return _local(f"{x:{'+' if sign else ''},.{decimals}f}")


SYMBOLS = {"EUR": "€", "USD": "$"}


def eur(x: float, decimals: int = 0, sign: bool = False, symbol: str = "€") -> str:
    """€1,234 / +€1,234 / -€56 (or with another currency symbol, e.g. $1,234); German: 1.234 € / +1.234 €."""
    if _missing(x):
        return "–"
    prefix = ("+" if x > 0 else "-" if x < 0 else "") if sign else ("-" if x < 0 else "")
    if _LANG.get() == "de":
        return f"{prefix}{_local(f'{abs(x):,.{decimals}f}')} {symbol}"
    return f"{prefix}{symbol}{abs(x):,.{decimals}f}"


def pct(x: float, decimals: int = 1, sign: bool = True) -> str:
    """Fraction to percent: 0.123 -> +12.3%."""
    if _missing(x):
        return "–"
    text = f"{x * 100:{'+' if sign else ''},.{decimals}f}"
    return f"{_local(text)} %" if _LANG.get() == "de" else f"{text}%"


def money(x: float, currency: str, decimals: int = 2) -> str:
    """Price in its own currency: 718.67 USD."""
    if _missing(x):
        return "–"
    return f"{_local(f'{x:,.{decimals}f}')} {currency}"


def spec(x, format_spec: str) -> str:
    """``format(x, spec)`` in the current language – for f-string formats like ``{x:,.2f}`` in UI texts."""
    return _local(format(x, format_spec))
