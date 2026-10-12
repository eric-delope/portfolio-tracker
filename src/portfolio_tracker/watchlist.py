"""Watchlist with valuation snapshots and price alerts, stored as JSON.

Alert prices are kept in the stock's trading currency (the currency the
valuation is done in). For Trade Republic, which quotes in EUR, the dashboard
also shows the EUR equivalent at today's exchange rate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

NEAR_THRESHOLD = 0.05  # "approaching" when price is within 5 % above a buy alert


@dataclass
class Alert:
    price: float
    label: str = ""
    direction: str = "below"          # "below": buy zone; "above": e.g. take-profit or breakout
    amount_eur: float | None = None   # planned investment for this tranche
    active: bool = True
    triggered_at: str | None = None   # ISO timestamp of the first time the condition was met
    rel_to_fair: float | None = None  # price / fair value - 1 when created; lets the level grow with fair value

    def is_hit(self, price: float) -> bool:
        return price <= self.price if self.direction == "below" else price >= self.price

    def distance(self, price: float) -> float:
        """How far the price still has to move to hit the alert (positive = not yet reached)."""
        return price / self.price - 1 if self.direction == "below" else self.price / price - 1


@dataclass
class Entry:
    ticker: str
    name: str
    currency: str
    added: str = field(default_factory=lambda: date.today().isoformat())
    thesis: str = ""
    fair_value: float | None = None
    target_price: float | None = None        # expected price at the end of the horizon
    horizon_years: int | None = None
    required_return: float | None = None
    valuation_date: str | None = None
    valuation_inputs: dict = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)   # one snapshot per valuation day
    thesis_kpis: list[dict] = field(default_factory=list)  # [{'metric', 'operator', 'threshold'}]
    plan: dict = field(default_factory=dict)              # savings-plan part: {'monthly_eur', 'months', 'start'}

    # ----------------------------------------------------- long-term view
    def years_elapsed(self, today: date | None = None) -> float:
        if not self.valuation_date:
            return 0.0
        return ((today or date.today()) - date.fromisoformat(self.valuation_date[:10])).days / 365.25

    def fair_value_today(self, today: date | None = None) -> float | None:
        """Fair value rolled forward from the valuation date (grows with the required return)."""
        from .valuation import fair_value_at
        if not self.fair_value or self.required_return is None:
            return self.fair_value
        return fair_value_at(self.fair_value, self.required_return, self.years_elapsed(today),
                             self.valuation_inputs.get("dividends"))

    def expected_return(self, price: float | None, today: date | None = None) -> float:
        """Expected total return p. a. when buying at ``price`` today (dividends + target price)."""
        from .valuation import irr_times, remaining_flows
        if not price or not self.target_price or not self.horizon_years:
            return float("nan")
        flows = remaining_flows(self.target_price, self.horizon_years, self.years_elapsed(today),
                                self.valuation_inputs.get("dividends"))
        return irr_times(price, flows)

    def rolled_alerts(self, today: date | None = None, min_drift: float = 0.0) -> list[tuple[Alert, float]]:
        """(alert, new price) for alerts whose level should move with the rolled-forward fair value."""
        fair = self.fair_value_today(today)
        out = []
        for a in self.alerts:
            if a.active and a.rel_to_fair is not None and fair:
                new = fair * (1 + a.rel_to_fair)
                if abs(new / a.price - 1) >= min_drift:
                    out.append((a, new))
        return out

    def snapshot(self) -> dict:
        inp = self.valuation_inputs
        return {"date": (self.valuation_date or date.today().isoformat())[:10], "fair_value": self.fair_value,
                "price": inp.get("price_at_valuation"), "eps1": inp.get("eps1"), "eps0": inp.get("eps0"),
                "base_growth": inp.get("base_growth"), "base_pe": inp.get("base_pe"),
                "required_return": self.required_return}

    @classmethod
    def from_dict(cls, d: dict) -> Entry:
        d = dict(d)
        d["alerts"] = [Alert(**a) for a in d.get("alerts", [])]
        return cls(**d)

    def valuation_age_days(self) -> int | None:
        if not self.valuation_date:
            return None
        return (date.today() - date.fromisoformat(self.valuation_date[:10])).days


class Watchlist:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: dict[str, Entry] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            self.entries = {e["ticker"]: Entry.from_dict(e) for e in raw.get("entries", [])}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"updated": datetime.now().isoformat(timespec="seconds"),
                "entries": [asdict(e) for e in self.entries.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(self.path)  # atomic: never leaves a half-written file

    def upsert(self, entry: Entry) -> None:
        """Insert or replace; keeps thesis, added date and the valuation history of an existing entry."""
        old = self.entries.get(entry.ticker)
        if old and not entry.thesis:
            entry.thesis = old.thesis
        history = list(old.history) if old else []
        if old:
            entry.added = old.added
        if entry.fair_value is not None:
            snap = entry.snapshot()
            if history and history[-1].get("date") == snap["date"]:
                history[-1] = snap  # re-saved on the same day: keep only the latest
            else:
                history.append(snap)
        entry.history = history
        self.entries[entry.ticker] = entry

    def remove(self, ticker: str) -> None:
        self.entries.pop(ticker, None)

    def __iter__(self):
        return iter(self.entries.values())

    def __len__(self) -> int:
        return len(self.entries)


def alert_status(watchlist: Watchlist, prices: dict[str, float]) -> pd.DataFrame:
    """One row per active alert with distance and state: 'hit', 'near' or 'waiting'."""
    rows = []
    for e in watchlist:
        price = prices.get(e.ticker)
        for i, a in enumerate(e.alerts):
            if not a.active:
                continue
            if price is None:
                state, dist = "no_price", None
            else:
                dist = a.distance(price)
                state = "hit" if a.is_hit(price) else ("near" if dist <= NEAR_THRESHOLD else "waiting")
            rows.append({"ticker": e.ticker, "name": e.name, "currency": e.currency, "alert_index": i,
                         "label": a.label, "direction": a.direction, "alert_price": a.price, "price": price,
                         "distance": dist, "state": state, "amount_eur": a.amount_eur,
                         "triggered_at": a.triggered_at})
    return pd.DataFrame(rows)


def mark_triggered(watchlist: Watchlist, prices: dict[str, float], now: datetime | None = None) -> list[tuple[Entry, Alert]]:
    """Stamp alerts whose condition is met for the first time; return those newly triggered."""
    now = now or datetime.now()
    new = []
    for e in watchlist:
        price = prices.get(e.ticker)
        if price is None:
            continue
        for a in e.alerts:
            if a.active and a.triggered_at is None and a.is_hit(price):
                a.triggered_at = now.isoformat(timespec="seconds")
                new.append((e, a))
    return new


SIGNAL_LABELS = {"buy": "Buy zone", "hold": "Hold", "review": "Review / sell?", "trim": "Consider trimming",
                 "none": "Not valued"}
DEFAULT_BUY_DISCOUNT = 0.10   # without explicit alerts: buy zone 10 % below fair value
SELL_RETURN_FLOOR = 0.04      # long-term: consider selling only when the expected return falls below this


def signal(entry: Entry | None, price: float | None, weight: float | None = None, position_limit: float = 0.20,
           thesis_ok: bool | None = None, return_floor: float = SELL_RETURN_FLOOR) -> tuple[str, str]:
    """Long-term signal: 'buy' | 'hold' | 'review' | 'trim' | 'none', with an explanation.

    Selling is driven by the thesis (KPIs violated) or by valuation (expected
    return from today's price below ``return_floor``), never by price moves alone.
    """
    if entry is None or not entry.fair_value or price is None:
        return "none", "Not valued – determine a fair value in Company research"
    fair = entry.fair_value_today() or entry.fair_value
    gap = price / fair - 1
    gap_txt = f"{abs(gap) * 100:.0f}% {'above' if gap > 0 else 'below'} fair value"
    exp = entry.expected_return(price)
    held = bool(weight)
    if thesis_ok is False:
        return "review", "Thesis broken – check the KPIs, consider selling"
    sell_alerts = [a for a in entry.alerts if a.active and a.direction == "above"]
    if held and ((sell_alerts and any(price >= a.price for a in sell_alerts))
                 or (np.isfinite(exp) and exp < return_floor)):
        return "trim", f"Consider trimming – expected return only {_pct1(exp)} p.a. ({gap_txt})"
    buys = [a for a in entry.alerts if a.active and a.direction == "below"]
    in_buy = any(price <= a.price for a in buys) if buys else gap <= -DEFAULT_BUY_DISCOUNT
    if in_buy:
        if held and weight >= position_limit:
            return "hold", f"Hold – buy zone ({gap_txt}), but the position is already {weight * 100:.0f}% of the portfolio"
        return "buy", f"{'Add' if held else 'Buy'} – {gap_txt}, expected {_pct1(exp)} p.a."
    return "hold", f"Hold – {gap_txt}" + (f", expected {_pct1(exp)} p.a." if np.isfinite(exp) else "")


def _pct1(x: float) -> str:
    return f"{x * 100:.1f}%"

