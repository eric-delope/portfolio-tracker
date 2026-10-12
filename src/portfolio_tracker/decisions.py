"""Decision scorecard: did each buy or sell beat simply holding the benchmark?

For every trade we compare the traded stock with the benchmark over fixed
horizons after the trade date (EUR closes, so currency effects are included):

    buy  edge = stock return - benchmark return   (positive: good pick)
    sell edge = benchmark return - stock return   (positive: good exit, the stock lagged)

This measures decision quality relative to the market instead of "did the
market go up", which is what an absolute hindsight figure mostly captures.
Caveat: horizons of consecutive trades overlap and the same stocks recur, so
observations are not independent; the t-statistic is only a rough guide.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .importer import trades
from .portfolio import Portfolio

HORIZONS = {"6M": 126, "12M": 252, "24M": 504}     # long-term view; 12M is the default
SHORT_HORIZONS = {"1M": 21, "3M": 63}
MIN_OBSERVATIONS = 20


def scorecard(p: Portfolio, benchmark: str = "MSCI World", horizons: dict[str, int] = HORIZONS) -> pd.DataFrame:
    """One row per trade with the edge vs. the benchmark per horizon and until today."""
    t = trades(p.tx).copy()
    if t.empty:
        return pd.DataFrame()
    t["bday"] = t["date"].map(pd.offsets.BDay().rollforward)
    px = p.price_eur
    bench = p.benchmark_prices[benchmark].reindex(p.index).ffill().bfill()
    pos = p.index.get_indexer(t["bday"])
    last = len(p.index) - 1

    rows = []
    for (_, r), i in zip(t.iterrows(), pos):
        if i < 0:
            continue
        sign = 1.0 if r["event"] == "buy" else -1.0
        row = {
            "transaction_id": r["transaction_id"], "date": r["date"], "isin": r["isin"], "name": r["name"],
            "asset_class": r["asset_class"],
            "event": r["event"], "savings_plan": bool(r["savings_plan"]), "amount": abs(r["amount"]),
            "group": "Sell" if r["event"] == "sell" else ("Savings plan" if r["savings_plan"] else "Buy"),
        }
        start_px, start_b = px.iat[i, px.columns.get_loc(r["isin"])], bench.iat[i]
        for label, h in {**horizons, "today": last - i}.items():
            j = i + h
            if h <= 0 or j > last or not np.isfinite(start_px) or start_px <= 0:
                row[f"edge_{label}"] = np.nan
                continue
            stock = px.iat[j, px.columns.get_loc(r["isin"])] / start_px - 1
            market = bench.iat[j] / start_b - 1
            row[f"edge_{label}"] = sign * (stock - market)
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(sc: pd.DataFrame, horizon: str = "12M", stocks_only: bool = True) -> pd.DataFrame:
    """Per decision group: count, amount-weighted and plain average edge, hit rate, t-stat, verdict."""
    col = f"edge_{horizon}"
    if sc.empty or col not in sc:
        return pd.DataFrame()
    df = sc[sc[col].notna()]
    if stocks_only:
        df = df[df["asset_class"] != "FUND"]
    out = {}
    for group, g in df.groupby("group"):
        e = g[col]
        n = len(e)
        sd = e.std(ddof=1) if n > 1 else np.nan
        t_stat = e.mean() / (sd / np.sqrt(n)) if n > 1 and sd > 0 else np.nan
        out[group] = {
            "n": n,
            "edge_weighted": float(np.average(e, weights=g["amount"])) if g["amount"].sum() > 0 else float(e.mean()),
            "edge_mean": float(e.mean()),
            "hit_rate": float((e > 0).mean()),
            "t_stat": float(t_stat),
            "verdict": verdict(n, t_stat, e.mean()),
        }
    order = [g for g in ["Buy", "Savings plan", "Sell"] if g in out]
    return pd.DataFrame.from_dict(out, orient="index").loc[order]


def verdict(n: int, t_stat: float, mean: float) -> str:
    if n < MIN_OBSERVATIONS:
        return "too little data"
    if not np.isfinite(t_stat) or abs(t_stat) < 2:
        return "not yet conclusive"
    return "clearly positive" if mean > 0 else "clearly negative"


def by_quarter(sc: pd.DataFrame, horizon: str = "12M", stocks_only: bool = True) -> pd.DataFrame:
    """Amount-weighted edge per calendar quarter and decision group (for a trend view)."""
    col = f"edge_{horizon}"
    df = sc[sc[col].notna()] if col in sc else pd.DataFrame()
    if stocks_only and not df.empty:
        df = df[df["asset_class"] != "FUND"]
    if df.empty:
        return pd.DataFrame()
    df = df.assign(quarter=df["date"].dt.to_period("Q"), w=df[col] * df["amount"])
    g = df.groupby(["quarter", "group"])[["w", "amount"]].sum()
    return (g["w"] / g["amount"]).unstack("group")


DIP_THRESHOLD = -0.15   # "bought after a pullback": more than 15 % below the 52-week high


def entry_quality(p: Portfolio, benchmark: str = "MSCI World", window_days: int = 126,
                  dca_days: int = 63, fair_values: dict[str, pd.Series] | None = None) -> pd.DataFrame:
    """Per stock buy: how good was the entry price?

    - range_position: where the buy price sat in the following ``window_days`` range
      (0 = bought at the low, 1 = at the high; 0.5 = no timing skill)
    - vs_dca: buy price vs. the average close of the next ``dca_days`` (negative = cheaper
      than spreading the same amount as a savings plan)
    - off_high: distance to the 52-week high at the time of buying
    - vs_fair: buy price vs. the user's own fair value at that time (if a valuation existed)
    - edge_12M: 12-month return vs. benchmark (from the scorecard)
    """
    t = trades(p.tx)
    t = t[(t["event"] == "buy") & (t["asset_class"] != "FUND")].copy()
    if t.empty:
        return pd.DataFrame()
    t["bday"] = t["date"].map(pd.offsets.BDay().rollforward)
    px, idx = p.price_eur, p.index
    tickers = p.tickers
    history = p.prices.eur
    edges = scorecard(p, benchmark).set_index("transaction_id")
    rows = []
    for _, r in t.iterrows():
        i = idx.get_indexer([r["bday"]])[0]
        if i < 0:
            continue
        s = px[r["isin"]]
        row = {"transaction_id": r["transaction_id"], "date": r["date"], "isin": r["isin"], "name": r["name"],
               "amount": abs(r["amount"]), "price": r["price"], "savings_plan": bool(r["savings_plan"])}
        if i + window_days < len(idx):
            fut = s.iloc[i:i + window_days + 1]
            # the execution price is part of the range (it can differ slightly from the closing prices)
            lo, hi = min(fut.min(), r["price"]), max(fut.max(), r["price"])
            row["range_position"] = (r["price"] - lo) / (hi - lo) if hi > lo else np.nan
        if i + dca_days < len(idx):
            row["vs_dca"] = r["price"] / s.iloc[i:i + dca_days + 1].mean() - 1
        tk = tickers.get(r["isin"])
        full = history[tk].dropna() if tk in history else s.dropna()
        past = full[(full.index <= r["bday"]) & (full.index > r["bday"] - pd.DateOffset(years=1))]
        row["off_high"] = r["price"] / past.max() - 1 if len(past) else np.nan
        fv = (fair_values or {}).get(tk)
        if fv is not None and len(fv[fv.index <= r["bday"]]):
            row["vs_fair"] = r["price"] / fv[fv.index <= r["bday"]].iloc[-1] - 1
        row["edge_12M"] = edges["edge_12M"].get(r["transaction_id"], np.nan) if "edge_12M" in edges else np.nan
        rows.append(row)
    df = pd.DataFrame(rows)
    df["after_dip"] = df["off_high"] < DIP_THRESHOLD
    return df


def entry_summary(eq: pd.DataFrame) -> dict:
    """Amount-weighted entry statistics."""
    if eq.empty:
        return {}

    def wavg(col: str, mask=None) -> float:
        d = eq if mask is None else eq[mask]
        d = d[d[col].notna()] if col in d else d.iloc[0:0]
        return float(np.average(d[col], weights=d["amount"])) if len(d) and d["amount"].sum() > 0 else np.nan

    return {
        "n": len(eq),
        "range_position": wavg("range_position"),
        "vs_dca": wavg("vs_dca"),
        "cheaper_than_dca": float((eq["vs_dca"] < 0).mean()) if "vs_dca" in eq and eq["vs_dca"].notna().any() else np.nan,
        "off_high": wavg("off_high"),
        "share_after_dip": float(eq["after_dip"].mean()),
        "edge_after_dip": wavg("edge_12M", eq["after_dip"]),
        "edge_near_high": wavg("edge_12M", ~eq["after_dip"]),
        "n_edge": int(eq["edge_12M"].notna().sum()),
        "below_fair": float((eq["vs_fair"] < 0).mean()) if "vs_fair" in eq and eq["vs_fair"].notna().any() else np.nan,
        "n_fair": int(eq["vs_fair"].notna().sum()) if "vs_fair" in eq else 0,
    }
