"""Look-through: what the portfolio really owns once every ETF is opened up.

An MSCI World ETF holds Microsoft, Apple, Nvidia, ... – if you also hold Microsoft directly, your real
Microsoft weight is the direct position *plus* its share inside the ETF. This module combines the
direct holdings with each fund's published top holdings and sector weights (Yahoo Finance fund data).

Limits, stated in the UI as well: fund data covers the ten largest holdings per ETF (the rest is shown as
"other holdings"), and gives sectors but no country split, so funds keep their region label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

# Yahoo's fund sector keys -> the sector names used for single stocks
SECTOR_NAMES = {
    "technology": "Technology", "financial_services": "Financial Services", "healthcare": "Healthcare",
    "consumer_cyclical": "Consumer Cyclical", "communication_services": "Communication Services",
    "industrials": "Industrials", "consumer_defensive": "Consumer Defensive", "energy": "Energy",
    "basic_materials": "Basic Materials", "realestate": "Real Estate", "utilities": "Utilities",
}
_GENERIC = {"the", "american", "united", "bank", "first", "general", "international", "national"}
_SUFFIX = re.compile(r"\b(inc|corp|corporation|co|company|ltd|limited|plc|nv|n v|ag|se|sa|holdings?|group|class [abc]|"
                     r"cl [abc]|[abc])\b")


_TRAILING = re.compile(r"(,?\s+(inc\.?|corp\.?|corporation|co\.?|ltd\.?|limited|plc|n\.?v\.?|ag|se|sa|"
                       r"holdings?|group|class [abc]|cl [abc]))+\s*$", re.IGNORECASE)


def display_name(name: str) -> str:
    """Readable company name from a fund listing: 'NVIDIA Corp' -> 'NVIDIA', 'Alphabet Inc Class A' -> 'Alphabet'."""
    short = _TRAILING.sub("", str(name)).strip()
    return short or str(name)


def company_key(name: str) -> str:
    """Loose identity of a company across listings: 'Microsoft Corp' == 'Microsoft', 'Alphabet Inc Class A' == 'Alphabet'."""
    s = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
    s = _SUFFIX.sub(" ", s)
    words = [w for w in s.split() if w]
    if not words:
        return str(name).lower()
    return " ".join(words[:2]) if words[0] in _GENERIC and len(words) > 1 else words[0]


@dataclass
class FundProfile:
    holdings: pd.DataFrame        # index = symbol; columns: name, weight (fraction of the fund)
    sectors: dict[str, float]     # Yahoo sector key -> fraction


@dataclass
class LookThrough:
    companies: pd.DataFrame       # per company: name, direct, via_funds, total (fractions of the portfolio), sources
    sectors: pd.DataFrame         # per sector: direct, via_funds, total
    other_fund_share: float       # portfolio share inside funds that is not itemised (beyond the top holdings)
    fund_share: float             # portfolio share held through funds
    covered_funds: list[str]      # funds with profile data
    missing_funds: list[str]      # funds without data (counted as "other")


def look_through(positions: pd.DataFrame, profiles: dict[str, FundProfile]) -> LookThrough:
    """``positions``: one row per holding with name, ticker, value, sector, is_fund (bool)."""
    total = float(positions["value"].sum())
    if total <= 0:
        empty = pd.DataFrame(columns=["name", "direct", "via_funds", "total", "sources"])
        return LookThrough(empty, pd.DataFrame(columns=["direct", "via_funds", "total"]), 0.0, 0.0, [], [])
    companies: dict[str, dict] = {}
    sectors: dict[str, dict] = {}
    other, fund_share, covered, missing = 0.0, 0.0, [], []

    def add_company(key: str, name: str, direct: float, via: float, source: str | None) -> None:
        c = companies.setdefault(key, {"name": name, "direct": 0.0, "via_funds": 0.0, "sources": []})
        if direct > 0:
            c["name"] = name   # the name you know from your own position wins over the fund's spelling
        c["direct"] += direct
        c["via_funds"] += via
        if source and source not in c["sources"]:
            c["sources"].append(source)

    def add_sector(name: str, direct: float, via: float) -> None:
        s = sectors.setdefault(name, {"direct": 0.0, "via_funds": 0.0})
        s["direct"] += direct
        s["via_funds"] += via

    for _, row in positions.iterrows():
        w = float(row["value"]) / total
        if not row.get("is_fund"):
            add_company(company_key(row["name"]), row["name"], w, 0.0, None)
            add_sector(row.get("sector") or "Unknown", w, 0.0)
            continue
        fund_share += w
        prof = profiles.get(row.get("ticker"))
        if prof is None or prof.holdings.empty:
            missing.append(row["name"])
            other += w
            add_sector("Funds without data", 0.0, w)
            continue
        covered.append(row["name"])
        itemised = 0.0
        for _, h in prof.holdings.iterrows():
            share = w * float(h["weight"])
            itemised += float(h["weight"])
            add_company(company_key(h["name"]), display_name(h["name"]), 0.0, share, row["name"])
        other += w * max(1.0 - itemised, 0.0)
        sector_sum = sum(prof.sectors.values()) or 1.0
        for key, frac in prof.sectors.items():
            add_sector(SECTOR_NAMES.get(key, key.replace("_", " ").title()), 0.0, w * frac / sector_sum)

    comp = pd.DataFrame.from_dict(companies, orient="index")
    comp["total"] = comp["direct"] + comp["via_funds"]
    comp = comp.sort_values("total", ascending=False)
    sec = pd.DataFrame.from_dict(sectors, orient="index")
    sec["total"] = sec["direct"] + sec["via_funds"]
    return LookThrough(comp, sec.sort_values("total", ascending=False), other, fund_share, covered, missing)
