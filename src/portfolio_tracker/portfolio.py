"""Daily valuation of the securities account and every analysis built on it.

Perspective: the securities account ("Depot") on its own. Money flows into it
with every buy (cost incl. fees) and out of it with every sell (proceeds after
fees) and every dividend (gross). All figures are pre-tax; taxes are reported
separately in :mod:`portfolio_tracker.taxes`.

Core identity, per position and in total:
    P&L(t) = market value(t) + cumulative outflows(t) - cumulative inflows(t)
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd

from . import metrics as m
from .importer import SHARE_EPSILON, trades
from .lots import apply_splits, fifo
from .market import BENCHMARKS, MarketData, PriceData

REPORTING_CURRENCIES = ("EUR", "USD")

RISK_LOOKBACK_DAYS = 252

CURRENCY_BY_SUFFIX = {".DE": "EUR", ".F": "EUR", ".PA": "EUR", ".AS": "EUR", ".MI": "EUR",
                      ".L": "GBp", ".CO": "DKK", ".OL": "NOK", ".ST": "SEK", ".SW": "CHF"}


def _guess_currency(ticker: str) -> str:
    for suffix, currency in CURRENCY_BY_SUFFIX.items():
        if ticker.endswith(suffix):
            return currency
    return "USD"


def _roll_to_business_day(dates: pd.Series) -> pd.Series:
    return dates.map(pd.offsets.BDay().rollforward)


@dataclass
class Portfolio:
    tx: pd.DataFrame                 # split-adjusted transactions
    tickers: dict[str, str | None]   # ISIN -> Yahoo ticker
    meta: pd.DataFrame               # per ISIN: name, ticker, currency, sector, ...
    prices: PriceData
    benchmark_prices: pd.DataFrame   # closes in the reporting currency, columns = benchmark names
    rf: float = 0.02                 # annual risk-free rate
    base: str = "EUR"                # reporting currency; all *_eur fields are in this currency (see in_currency)

    # ------------------------------------------------------------ construction
    @classmethod
    def build(cls, tx: pd.DataFrame, market: MarketData, rf: float = 0.02) -> Portfolio:
        t = trades(tx)
        isins = list(dict.fromkeys(t["isin"]))
        resolved = market.resolve_tickers(isins)
        tickers = {isin: resolved.get(isin) for isin in isins}
        valid = list(dict.fromkeys(tk for tk in tickers.values() if tk))

        meta_by_ticker = market.metadata(valid)
        names = t.groupby("isin")["name"].last()
        asset_class = t.groupby("isin")["asset_class"].last()
        rows = {}
        for isin in isins:
            tk = tickers.get(isin)
            info = meta_by_ticker.loc[tk].to_dict() if tk in meta_by_ticker.index else {}
            info = {k: (None if pd.isna(v) else v) for k, v in info.items()}
            currency = info.get("currency") or (_guess_currency(tk) if tk else "EUR")
            is_fund = asset_class[isin] == "FUND"
            rows[isin] = {
                "name": names[isin], "ticker": tk, "asset_class": asset_class[isin],
                "currency": currency,
                "sector": "ETF (diversified)" if is_fund else (info.get("sector") or "Unknown"),
                "industry": info.get("industry") or ("ETF" if is_fund else "Unknown"),
                "country": _fund_region(names[isin]) if is_fund else (info.get("country") or "Unknown"),
                "market_cap": info.get("market_cap"), "trailing_pe": info.get("trailing_pe"),
                "forward_pe": info.get("forward_pe"),
            }
        meta = pd.DataFrame.from_dict(rows, orient="index")

        splits = market.splits(valid)
        splits_by_isin = {isin: splits[tk] for isin, tk in tickers.items() if tk and len(splits.get(tk, []))}
        tx_adj = apply_splits(tx, splits_by_isin)

        currencies = {tk: meta.loc[isin, "currency"] for isin, tk in tickers.items() if tk}
        currencies.update({tk: "EUR" for tk in BENCHMARKS.values()})
        currencies.update({f"EUR{c}=X": c for c in REPORTING_CURRENCIES if c != "EUR"})  # FX for in_currency()
        start = t["date"].min()
        prices = market.prices(valid + list(BENCHMARKS.values()), start, currencies)
        bench = pd.DataFrame({name: prices.eur[tk] for name, tk in BENCHMARKS.items() if tk in prices.eur})
        return cls(tx=tx_adj, tickers=tickers, meta=meta, prices=prices, benchmark_prices=bench, rf=rf)

    # ------------------------------------------------------- reporting currency
    def in_currency(self, code: str) -> Portfolio:
        """The same portfolio reported in another currency, converted at each day's exchange rate.

        Every price, trade, dividend and benchmark is translated at the rate of its own day and all
        figures are recomputed, so returns are those of an investor measuring in ``code`` (a euro
        investor's +10% can be a dollar investor's +4% when the euro fell). Cash held in euros is
        revalued daily. Taxes stay a euro matter and should use the EUR portfolio.
        """
        if code == self.base:
            return self
        if self.base != "EUR":  # always convert from the euro original
            return self.__dict__["_eur_origin"].in_currency(code)
        if code not in self.prices.fx or self.prices.fx[code].dropna().empty:
            raise ValueError(f"no EUR/{code} exchange rates available")
        fx = self.prices.fx[code].ffill().bfill()   # units of `code` per EUR, daily
        tx = self.tx.copy()
        rate = fx.reindex(_roll_to_business_day(tx["date"])).ffill().bfill().fillna(fx.iloc[-1]).to_numpy()
        for col in ("amount", "fee", "tax", "net_cash", "price"):
            tx[col] = tx[col] * rate
        prices = PriceData(eur=self.prices.eur.mul(fx, axis=0), local=self.prices.local,
                           fx=self.prices.fx.div(fx, axis=0), currency=self.prices.currency)
        bench_fx = fx.reindex(self.benchmark_prices.index).ffill()
        out = Portfolio(tx=tx, tickers=self.tickers, meta=self.meta, prices=prices,
                        benchmark_prices=self.benchmark_prices.mul(bench_fx, axis=0), rf=self.rf, base=code)
        # cash sits in euros: revalue the euro balance every day instead of summing converted flows
        out.__dict__["cash_balance"] = self.cash_balance * fx.reindex(self.index).ffill().bfill()
        out.__dict__["_eur_origin"] = self
        return out

    # --------------------------------------------------------------- base grid
    @cached_property
    def index(self) -> pd.DatetimeIndex:
        first = pd.offsets.BDay().rollforward(trades(self.tx)["date"].min())
        last = self.prices.eur.dropna(how="all").index.max()
        return pd.bdate_range(first, max(last, self.tx["date"].max()))

    @cached_property
    def _trades(self) -> pd.DataFrame:
        t = trades(self.tx).copy()
        t["bday"] = _roll_to_business_day(t["date"])
        return t

    @cached_property
    def shares(self) -> pd.DataFrame:
        """Shares held per ISIN at each day's close."""
        changes = self._trades.pivot_table(index="bday", columns="isin", values="shares", aggfunc="sum")
        held = changes.reindex(self.index, fill_value=0).fillna(0).cumsum()
        return held.where(held.abs() > SHARE_EPSILON, 0.0)

    @cached_property
    def price_eur(self) -> pd.DataFrame:
        """Daily price per ISIN in the reporting currency; falls back to the last Trade Republic execution price."""
        t = self._trades
        fallback = (t.pivot_table(index="bday", columns="isin", values="price", aggfunc="last")
                    .reindex(self.index).ffill())
        out = pd.DataFrame(index=self.index)
        for isin in self.shares.columns:
            tk = self.tickers.get(isin)
            yahoo = self.prices.eur[tk].reindex(self.index) if tk in self.prices.eur else pd.Series(np.nan, index=self.index)
            out[isin] = yahoo.ffill().fillna(fallback.get(isin))
        return out

    @cached_property
    def values(self) -> pd.DataFrame:
        """Market value per ISIN in the reporting currency."""
        return (self.shares * self.price_eur).where(self.shares != 0, 0.0).fillna(0.0)

    @cached_property
    def inflows(self) -> pd.DataFrame:
        """Money into each position per day (buy cost incl. fees)."""
        t = self._trades[self._trades["event"] == "buy"]
        cost = -(t["amount"] + t["fee"])
        return self._pivot_flows(t.assign(flow=cost))

    @cached_property
    def outflows(self) -> pd.DataFrame:
        """Money out of each position per day (sell proceeds after fees + gross dividends)."""
        t = self._trades[self._trades["event"] == "sell"]
        sells = t.assign(flow=t["amount"] + t["fee"])
        d = self.tx[(self.tx["event"] == "dividend") & self.tx["isin"].notna()].copy()
        d["bday"] = _roll_to_business_day(d["date"])
        divs = d.assign(flow=d["amount"])
        return self._pivot_flows(pd.concat([sells, divs]))

    def _pivot_flows(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(0.0, index=self.index, columns=self.shares.columns)
        p = df.pivot_table(index="bday", columns="isin", values="flow", aggfunc="sum")
        return p.reindex(index=self.index, columns=self.shares.columns).fillna(0.0)

    @cached_property
    def position_pnl(self) -> pd.DataFrame:
        """Cumulative pre-tax P&L per ISIN over time."""
        return self.values + self.outflows.cumsum() - self.inflows.cumsum()

    @cached_property
    def daily(self) -> pd.DataFrame:
        """Portfolio-level daily table: value, flows, net invested, P&L, TWR return."""
        value = self.values.sum(axis=1)
        inflow = self.inflows.sum(axis=1)
        outflow = self.outflows.sum(axis=1)
        prev = value.shift(1).fillna(0.0)
        denom = prev + inflow
        ret = ((value + outflow) / denom - 1).where(denom > SHARE_EPSILON, 0.0)
        net_invested = (inflow - outflow).cumsum()
        return pd.DataFrame({
            "value": value, "inflow": inflow, "outflow": outflow,
            "net_invested": net_invested, "pnl": value - net_invested, "return": ret,
        })

    @cached_property
    def benchmark_returns(self) -> pd.DataFrame:
        return self.benchmark_prices.reindex(self.index).ffill().pct_change().fillna(0.0)

    @property
    def last_date(self) -> pd.Timestamp:
        return self.index[-1]

    # ----------------------------------------------------------------- periods
    def period_start(self, period: str) -> pd.Timestamp:
        """First day of a named period: 'all', 'ytd', '1m', '3m', '6m', '1y'."""
        end = self.last_date
        offsets = {"1m": pd.DateOffset(months=1), "3m": pd.DateOffset(months=3),
                   "6m": pd.DateOffset(months=6), "1y": pd.DateOffset(years=1)}
        if period == "ytd":
            start = pd.Timestamp(year=end.year, month=1, day=1)
        elif period in offsets:
            start = end - offsets[period]
        else:
            start = self.index[0]
        return max(start, self.index[0])

    def returns(self, start: pd.Timestamp | None = None) -> pd.Series:
        r = self.daily["return"]
        return r[r.index > start] if start is not None and start > self.index[0] else r

    def period_summary(self, start: pd.Timestamp, benchmark: str = "MSCI World") -> dict:
        """Headline KPIs for the period after ``start`` (start = valuation base date)."""
        d = self.daily
        r = self.returns(start)
        base = d.loc[:start].iloc[-1] if start > self.index[0] else None
        pnl_start = base["pnl"] if base is not None else 0.0
        b = self.benchmark_returns[benchmark].reindex(r.index) if benchmark in self.benchmark_returns else None
        days = (self.last_date - (start if base is not None else self.index[0])).days
        mwr = self.xirr(start)
        return {
            "value": d["value"].iloc[-1],
            "pnl": d["pnl"].iloc[-1] - pnl_start,
            "twr": m.total_return(r),
            "twr_annualized": m.annualized_return(r),
            "mwr_annualized": mwr,
            "mwr": (1 + mwr) ** (days / 365) - 1 if pd.notna(mwr) else float("nan"),
            "benchmark_twr": m.total_return(b) if b is not None else float("nan"),
            "volatility": m.annualized_volatility(r),
            "sharpe": m.sharpe_ratio(r, self.rf),
            "sortino": m.sortino_ratio(r, self.rf),
            "max_drawdown": m.max_drawdown_info(r)["depth"],
            "days": days,
            "annualize": days >= 365,  # GIPS: no annualized figures for periods under one year
        }

    def relative_metrics(self, start: pd.Timestamp, benchmark: str) -> dict:
        """Benchmark-relative statistics on weekly returns (see metrics.to_weekly)."""
        r = self.returns(start)
        b = self.benchmark_returns[benchmark].reindex(r.index)
        rw, bw = m.to_weekly(r), m.to_weekly(b)
        beta, alpha = m.beta_alpha(rw, bw, self.rf, periods=m.WEEKS)
        up, down = m.capture_ratios(rw, bw)
        return {
            "beta": beta, "alpha": alpha,
            "correlation": float(rw.corr(bw)),
            "tracking_error": m.tracking_error(rw, bw, periods=m.WEEKS),
            "information_ratio": m.information_ratio(rw, bw, periods=m.WEEKS),
            "up_capture": up, "down_capture": down,
            "excess_return": m.total_return(r) - m.total_return(b),
        }

    def xirr(self, start: pd.Timestamp | None = None) -> float:
        """Money-weighted return p.a.; the start value counts as an initial investment."""
        d = self.daily
        flows = d["outflow"] - d["inflow"]
        if start is not None and start > self.index[0]:
            flows = flows[flows.index > start]
            initial = pd.Series([-d.loc[:start, "value"].iloc[-1]], index=[start])
            flows = pd.concat([initial, flows])
        flows = flows.copy()
        flows.iloc[-1] += d["value"].iloc[-1]
        flows = flows[flows != 0]
        return m.xirr(flows.index, flows.values)

    # ------------------------------------------------------------- benchmarks
    def shadow_portfolio(self, benchmark: str, start: pd.Timestamp | None = None) -> pd.DataFrame:
        """What if every buy/sell/dividend had gone into the benchmark instead?

        Long-Nickels PME: each inflow buys benchmark units, each outflow sells
        units of the same EUR amount. Compared to the real value over time.
        """
        d = self.daily
        px = self.benchmark_prices[benchmark].reindex(self.index).ffill().bfill()
        flows = d["inflow"] - d["outflow"]
        if start is not None and start > self.index[0]:
            d, px, flows = d[d.index >= start], px[px.index >= start], flows[flows.index >= start].copy()
            flows.iloc[0] = d["value"].iloc[0]  # the period starts with today's depot in the benchmark
        shadow = (flows / px).cumsum() * px
        return pd.DataFrame({"actual": d["value"], "shadow": shadow})

    def ks_pme(self, benchmark: str) -> float:
        """Kaplan-Schoar PME: > 1 means the portfolio beat the benchmark on a money-weighted basis."""
        d = self.daily
        px = self.benchmark_prices[benchmark].reindex(self.index).ffill().bfill()
        growth = px.iloc[-1] / px
        fv_out = (d["outflow"] * growth).sum() + d["value"].iloc[-1]
        fv_in = (d["inflow"] * growth).sum()
        return fv_out / fv_in if fv_in > 0 else float("nan")

    # -------------------------------------------------------------- positions
    @cached_property
    def lots(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        return fifo(self.tx)

    @property
    def open_lots(self) -> pd.DataFrame:
        return self.lots[0]

    @property
    def realized(self) -> pd.DataFrame:
        return self.lots[1]

    @cached_property
    def current_prices(self) -> pd.Series:
        return self.price_eur.iloc[-1]

    def _position_irr(self, isin: str) -> float:
        flows = self.outflows[isin] - self.inflows[isin]
        flows = flows.copy()
        flows.iloc[-1] += self.values[isin].iloc[-1]
        flows = flows[flows != 0]
        return m.xirr(flows.index, flows.values)

    @cached_property
    def positions(self) -> pd.DataFrame:
        """Open positions with cost basis, P&L, returns, risk and fundamentals."""
        lots = self.open_lots
        if lots.empty:
            return pd.DataFrame()
        g = lots.groupby("isin").agg(shares=("shares", "sum"), cost=("cost", "sum"),
                                     open_since=("buy_date", "min"))
        g = g.join(self.meta)
        price = self.current_prices
        g["price"] = price.reindex(g.index)
        g["value"] = g["shares"] * g["price"]
        g["weight"] = g["value"] / g["value"].sum()
        g["avg_cost"] = g["cost"] / g["shares"]
        g["unrealized"] = g["value"] - g["cost"]
        g["unrealized_pct"] = g["value"] / g["cost"] - 1
        realized = self.realized.groupby("isin")["gain"].sum()
        g["realized"] = realized.reindex(g.index).fillna(0.0)
        divs = self.tx[self.tx["event"] == "dividend"].groupby("isin")["amount"].sum()
        g["dividends"] = divs.reindex(g.index).fillna(0.0)
        fees = trades(self.tx).groupby("isin")["fee"].sum()
        g["fees"] = fees.reindex(g.index).fillna(0.0)
        g["total_pnl"] = self.position_pnl.iloc[-1].reindex(g.index)
        g["first_buy"] = trades(self.tx).groupby("isin")["date"].min().reindex(g.index)
        g["holding_days"] = (self.last_date - g["open_since"]).dt.days
        g["irr"] = [self._position_irr(i) for i in g.index]
        g["irr"] = g["irr"].where((self.last_date - g["first_buy"]).dt.days >= 365)

        px = self.price_eur
        last, prev = px.iloc[-1], px.iloc[-2] if len(px) > 1 else px.iloc[-1]
        g["day_change"] = (last / prev - 1).reindex(g.index)
        g["day_change_eur"] = g["shares"] * (last - prev).reindex(g.index)
        for label, offset in {"ret_1m": pd.DateOffset(months=1), "ret_ytd": None}.items():
            ref_date = (pd.Timestamp(year=self.last_date.year, month=1, day=1) - pd.Timedelta(days=1)
                        if offset is None else self.last_date - offset)
            ref = self._price_on(ref_date)
            g[label] = (last / ref - 1).reindex(g.index)
        g["off_52w_high"] = [self._off_high(i) for i in g.index]
        risk = self.holding_risk
        g = g.join(risk[["volatility_1y", "beta_1y"]])
        fx = self.currency_effect
        g = g.join(fx[["local_return", "fx_return", "fx_effect_eur"]])
        return g.sort_values("value", ascending=False)

    def _price_on(self, when: pd.Timestamp) -> pd.Series:
        """Best available EUR prices on or before ``when`` (full history from Yahoo)."""
        full = self.prices.eur.loc[:when]
        out = {}
        for isin in self.shares.columns:
            tk = self.tickers.get(isin)
            s = full[tk].dropna() if tk in full else pd.Series(dtype=float)
            out[isin] = s.iloc[-1] if len(s) else np.nan
        return pd.Series(out)

    def _off_high(self, isin: str) -> float:
        tk = self.tickers.get(isin)
        if tk not in self.prices.eur:
            return np.nan
        s = self.prices.eur[tk].dropna()
        s = s[s.index > self.last_date - pd.DateOffset(years=1)]
        return float(s.iloc[-1] / s.max() - 1) if len(s) else np.nan

    @cached_property
    def currency_effect(self) -> pd.DataFrame:
        """Split each open position's EUR return into local price move and currency move.

        For a lot bought at day d: EUR return = (P_local_now / P_local_d) * (FX_d / FX_now) - 1,
        where FX = units of the listing currency per EUR. ``fx_effect_eur`` is today's
        value minus the value it would have at the exchange rate of the purchase day.
        """
        rows = {}
        local, fx = self.prices.local, self.prices.fx
        for isin, lots in self.open_lots.groupby("isin"):
            tk = self.tickers.get(isin)
            if tk not in local:
                continue
            code = "GBP" if self.meta.loc[isin, "currency"] == "GBp" else self.meta.loc[isin, "currency"]
            fx_series = fx[code] if code in fx else pd.Series(1.0, index=fx.index)
            loc_now, fx_now = local[tk].dropna().iloc[-1], fx_series.dropna().iloc[-1]
            loc_buy = lots["buy_date"].map(lambda d: local[tk].loc[:d].dropna().iloc[-1])
            fx_buy = lots["buy_date"].map(lambda d: fx_series.loc[:d].dropna().iloc[-1])
            w = lots["cost"] / lots["cost"].sum()
            value_now = (lots["shares"] * loc_now / fx_now).sum()
            value_at_buy_fx = (lots["shares"] * loc_now / fx_buy).sum()
            rows[isin] = {
                "local_return": float((w * (loc_now / loc_buy - 1)).sum()),
                "fx_return": float((w * (fx_buy / fx_now - 1)).sum()),
                "fx_effect_eur": float(value_now - value_at_buy_fx),
            }
        return pd.DataFrame.from_dict(rows, orient="index",
                                      columns=["local_return", "fx_return", "fx_effect_eur"])

    @cached_property
    def holding_returns(self) -> pd.DataFrame:
        """Daily EUR returns of every ever-held ISIN over the last year (for risk analysis)."""
        start = self.last_date - pd.DateOffset(days=int(RISK_LOOKBACK_DAYS * 1.45))
        cols = {}
        for isin in self.shares.columns:
            tk = self.tickers.get(isin)
            if tk in self.prices.eur:
                cols[isin] = self.prices.eur[tk]
        px = pd.DataFrame(cols)
        px = px[px.index > start].ffill()
        return px.pct_change().iloc[1:].tail(RISK_LOOKBACK_DAYS)

    @cached_property
    def holding_risk(self) -> pd.DataFrame:
        """1-year volatility and beta vs. MSCI World per ISIN."""
        r = self.holding_returns
        bench = self.prices.eur[BENCHMARKS["MSCI World"]].pct_change().reindex(r.index)
        rw, bw = m.to_weekly(r), m.to_weekly(bench)
        out = {}
        for isin in r.columns:
            beta, _ = m.beta_alpha(rw[isin], bw, periods=m.WEEKS)
            out[isin] = {"volatility_1y": m.annualized_volatility(r[isin]), "beta_1y": beta}
        return pd.DataFrame.from_dict(out, orient="index")

    # --------------------------------------------------------- closed / sells
    @cached_property
    def closed_positions(self) -> pd.DataFrame:
        held = self.shares.iloc[-1]
        closed = [i for i in self.shares.columns if held[i] == 0]
        if not closed:
            return pd.DataFrame()
        t = self._trades
        rows = {}
        for isin in closed:
            ti = t[t["isin"] == isin]
            invested = self.inflows[isin].sum()
            sells = ti[ti["event"] == "sell"]
            sold_shares = -sells["shares"].sum()
            proceeds = (sells["amount"] + sells["fee"]).sum()
            rows[isin] = {
                "name": self.meta.loc[isin, "name"], "first_buy": ti["date"].min(),
                "last_sell": sells["date"].max(), "invested": invested,
                "pnl": self.position_pnl[isin].iloc[-1],
                "return_on_invested": self.position_pnl[isin].iloc[-1] / invested if invested else np.nan,
                "irr": self._position_irr(isin) if (sells["date"].max() - ti["date"].min()).days >= 365 else np.nan,
                "value_if_held": sold_shares * self.current_prices.get(isin, np.nan),
                "proceeds": proceeds,
            }
        df = pd.DataFrame.from_dict(rows, orient="index")
        df["hindsight"] = df["value_if_held"] - df["proceeds"]
        return df.sort_values("pnl", ascending=False)

    @cached_property
    def sell_analysis(self) -> pd.DataFrame:
        """Every sell: realized FIFO gain, and what the sold shares are worth today."""
        t = self._trades[self._trades["event"] == "sell"]
        if t.empty:
            return pd.DataFrame()
        gain = self.realized.groupby("sell_id").agg(gain=("gain", "sum"), cost=("cost", "sum"),
                                                     holding_days=("holding_days", "mean"))
        df = t.set_index("transaction_id")[["date", "isin", "name", "shares", "price", "amount", "fee", "tax"]]
        df = df.join(gain)
        df["shares"] = -df["shares"]
        df["proceeds"] = df["amount"] + df["fee"]
        df["price_now"] = df["isin"].map(self.current_prices)
        df["since_sale"] = df["price_now"] / df["price"] - 1
        df["hindsight"] = df["shares"] * df["price_now"] - df["proceeds"]
        df["return_pct"] = df["gain"] / df["cost"]
        return df.sort_values("date", ascending=False)

    def trade_statistics(self) -> dict:
        """Hit rate, payoff and disposition effect over all sell decisions."""
        s = self.sell_analysis
        if s.empty:
            return {}
        wins, losses = s[s["gain"] > 0], s[s["gain"] <= 0]
        return {
            "sells": len(s),
            "hit_rate": len(wins) / len(s),
            "avg_win": wins["gain"].mean() if len(wins) else 0.0,
            "avg_loss": losses["gain"].mean() if len(losses) else 0.0,
            "profit_factor": wins["gain"].sum() / -losses["gain"].sum() if losses["gain"].sum() < 0 else np.inf,
            "realized_total": s["gain"].sum(),
            "best": s.loc[s["gain"].idxmax()],
            "worst": s.loc[s["gain"].idxmin()],
            "avg_days_winners": wins["holding_days"].mean() if len(wins) else np.nan,
            "avg_days_losers": losses["holding_days"].mean() if len(losses) else np.nan,
            "hindsight_total": s["hindsight"].sum(),
        }

    # ------------------------------------------------------------------- risk
    def ex_ante_risk(self) -> dict:
        """Forward-looking risk of today's holdings using one year of daily returns."""
        pos = self.positions
        if pos.empty:
            return {}
        w = pos["value"] / pos["value"].sum()
        r = self.holding_returns[[i for i in w.index if i in self.holding_returns]].fillna(0.0)
        contrib = m.risk_contributions(w, r)
        port_daily = r @ w.reindex(r.columns).fillna(0.0)
        value = pos["value"].sum()
        sigma_daily = contrib["portfolio_volatility"].iloc[0] / np.sqrt(m.TRADING_DAYS)
        bench = self.prices.eur[BENCHMARKS["MSCI World"]].pct_change().reindex(r.index)
        beta, _ = m.beta_alpha(m.to_weekly(port_daily), m.to_weekly(bench), periods=m.WEEKS)
        avg_single_vol = float((w.reindex(contrib.index) * contrib["volatility"]).sum())
        return {
            "contributions": contrib,
            "volatility": float(contrib["portfolio_volatility"].iloc[0]),
            "diversification_ratio": avg_single_vol / contrib["portfolio_volatility"].iloc[0],
            "var95_param": 1.645 * sigma_daily * value,
            "var95_hist": m.historical_var(port_daily) * value,
            "es95_hist": m.expected_shortfall(port_daily) * value,
            "beta": beta,
            "correlation": m.to_weekly(r).corr(),
            "effective_positions": m.effective_positions(w),
            "simulated_returns": port_daily,
            "value": value,
        }

    def stress_tests(self) -> pd.DataFrame:
        """Instant shocks on today's holdings: market moves via beta, FX moves via exposure."""
        pos = self.positions
        if pos.empty:
            return pd.DataFrame()
        value = pos["value"]
        beta = pos["beta_1y"].fillna(1.0)
        foreign = value[pos["currency"].ne(self.base)]
        other = "USD" if self.base == "EUR" else "EUR"   # the main foreign currency from the reporting view
        exposed = value[pos["currency"].eq(other)]
        scenarios = {
            "MSCI World −10%": (value * beta * -0.10).sum(),
            "MSCI World −20%": (value * beta * -0.20).sum(),
            "MSCI World −35% (crash like 2020)": (value * beta * -0.35).sum(),
            f"{other} −10% vs. {self.base}": -0.10 * exposed.sum(),
            "All foreign currencies −10%": -0.10 * foreign.sum(),
            "Largest position −30%": -0.30 * value.max(),
        }
        total = value.sum()
        return pd.DataFrame({"impact_eur": scenarios}).assign(impact_pct=lambda d: d["impact_eur"] / total)

    # ------------------------------------------------------------- allocation
    def allocation(self, by: str) -> pd.Series:
        pos = self.positions
        if pos.empty:
            return pd.Series(dtype=float)
        return pos.groupby(by)["value"].sum().sort_values(ascending=False)

    # -------------------------------------------------------------- cashflows
    @cached_property
    def monthly_cashflows(self) -> pd.DataFrame:
        """Cash account and trading activity per calendar month."""
        tx = self.tx
        month = tx["date"].dt.to_period("M")
        pick = {
            "Deposits": ("deposit", "amount"), "Withdrawals": ("withdrawal", "amount"),
            "Card payments": ("card", "net_cash"), "Buys": ("buy", "amount"),
            "Sells": ("sell", "amount"), "Dividends": ("dividend", "net_cash"),
            "Interest": ("interest", "net_cash"), "Saveback": ("saveback", "net_cash"),
        }
        out = {label: tx[tx["event"] == ev].groupby(month[tx["event"] == ev])[col].sum()
               for label, (ev, col) in pick.items()}
        df = pd.DataFrame(out).fillna(0.0).sort_index()
        df["Order fees"] = trades(tx).groupby(month)["fee"].sum().reindex(df.index).fillna(0.0)
        df["Orders"] = trades(tx).groupby(month).size().reindex(df.index).fillna(0).astype(int)
        df["Savings plan executions"] = trades(tx)[trades(tx)["savings_plan"]].groupby(month).size() \
            .reindex(df.index).fillna(0).astype(int)
        return df

    @cached_property
    def cash_balance(self) -> pd.Series:
        tx = self.tx.assign(bday=_roll_to_business_day(self.tx["date"]))
        daily = tx.groupby("bday")["net_cash"].sum()
        return daily.cumsum().reindex(self.index).ffill().fillna(0.0)

    def cost_summary(self) -> dict:
        t = trades(self.tx)
        volume = t["amount"].abs().sum()
        avg_value = self.daily["value"].mean()
        years = max((self.last_date - self.index[0]).days / 365.25, 1 / 12)
        return {
            "fees": -t["fee"].sum(),
            "orders": len(t),
            "orders_with_fee": int((t["fee"] < 0).sum()),
            "savings_plan_orders": int(t["savings_plan"].sum()),
            "volume": volume,
            "fee_ratio": -t["fee"].sum() / volume if volume else np.nan,
            "fees_vs_pnl": -t["fee"].sum() / self.daily["pnl"].iloc[-1] if self.daily["pnl"].iloc[-1] else np.nan,
            "turnover": min(t.loc[t["event"] == "buy", "amount"].abs().sum(),
                            t.loc[t["event"] == "sell", "amount"].sum()) / avg_value / years if avg_value else np.nan,
            "taxes_paid": -self.tx["tax"].sum(),
        }


def _fund_region(name: str) -> str:
    n = name.upper()
    if "EM" in n.split() or "EMERGING" in n:
        return "Emerging markets"
    if "WORLD" in n or "ACWI" in n:
        return "Global"
    return "Fund"
