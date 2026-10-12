"""Does waiting pay? Backtest of buying on pullbacks vs. a plain monthly savings plan."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import charts as ch
import common as c
from common import pct, plot
from portfolio_tracker.backtest import DipRule, simulate, verdict

LADDERS = {"5 / 10 / 15%": (0.05, 0.10, 0.15), "10 / 20 / 30%": (0.10, 0.20, 0.30), "15 / 30 / 45%": (0.15, 0.30, 0.45)}
WAITS = {"3 months": 3, "6 months": 6, "12 months": 12, "never": None}


def candidates(p, wl) -> dict[str, str]:
    """Ticker -> name: the watchlist first, then everything in the portfolio."""
    out = {e.ticker: e.name for e in wl}
    for isin, row in p.positions.iterrows():
        tk = p.tickers.get(isin)
        if tk and tk not in out:
            out[tk] = row["name"]
    return out


def render(p, wl) -> None:
    st.subheader("Does waiting pay?")
    c.lead("Limit orders wait for a cheaper price – meanwhile the money sits on the side. **Would waiting for "
           "pullbacks have beaten simply buying every month?** Tested on every start month of the last ten years.")
    names = candidates(p, wl)
    if not names:
        st.caption("Add a company to the watchlist or hold a position to run the backtest.")
        return
    with c.card():
        c.card_title("Rules", "the same money every month for both strategies")
        i1, i2 = st.columns([1.6, 1])
        tk = i1.selectbox("Company", list(names), format_func=names.get, key="bt_ticker")
        wait = i2.selectbox("Invest anyway after", list(WAITS), index=2, key="bt_wait",
                            help="Cash that has waited this long is invested even without a pullback – like a "
                                 "limit order you finally replace with a market order.")
        i3, i4 = st.columns([1.6, 1])
        ladder = i3.segmented_control("Buy at … below the 52-week high", list(LADDERS), default="10 / 20 / 30%",
                                      required=True, key="bt_ladder",
                                      help="Three tranches: the first spends a third of the cash saved up, the "
                                           "second half of the rest, the third everything.")
        years = i4.segmented_control("Window", [3, 5, 7], default=5, required=True, key="bt_years",
                                     format_func=lambda y: f"{y} years")
    rf = c.settings()["rf"]
    windows = c.backtest_windows(tk, LADDERS[ladder], WAITS[wait], years, rf)
    if windows.empty:
        st.caption(f"Not enough price history for {names[tk]} – the backtest needs at least {years + 1} years.")
        return
    v = verdict(windows)
    c.stats([
        c.stat("Waiting won", pct(v["win_rate"], 0, False), f"in {v['windows']} windows of {years} years"),
        c.stat("Typical difference", pct(v["median"], 1), "final wealth vs. savings plan", c.tone(v["median"])),
        c.stat("Range", f"{pct(v['worst'], 1)} … {pct(v['best'], 1)}", "worst and best window"),
        c.stat("Cash on the side", pct(v["idle_cash"], 0, False), "on average, earning the risk-free rate",
               help=f"Cash earns {pct(rf, 1, False)} p.a. – the rate from Settings."),
    ])
    who = names[tk]
    if v["win_rate"] >= 0.5:
        c.callout(f"For **{who}**, waiting for pullbacks paid off in **{pct(v['win_rate'], 0, False)}** of all "
                  f"{years}-year windows – the cheaper entries outweighed the time on the side.", "good")
    else:
        c.callout(f"For **{who}**, the plain savings plan won in **{pct(1 - v['win_rate'], 0, False)}** of all "
                  f"{years}-year windows: the cheaper entries did not make up for the money sitting on the side "
                  f"(typically {pct(v['median'], 1)}).", "info")

    left, right = st.columns(2, gap="medium")
    with left:
        plot(ch.titled(ch.window_bars(windows, years), "Every window",
                       "final wealth, waiting for pullbacks vs. savings plan · blue = waiting won"))
    with right:
        tr = c.total_return_prices(tk)
        start = windows["start"].iloc[-1]
        run = simulate(tr, 100.0, DipRule(LADDERS[ladder], WAITS[wait]), rf, start)
        high = tr.rolling(252, min_periods=1).max().loc[run.index]
        plot(ch.titled(ch.backtest_buys(tr.loc[run.index], high, run["buy"], ""), f"The latest {years} years",
                       "when waiting bought · price incl. dividends, dotted: 52-week high, dot size = amount"))

    if st.toggle("Compare all companies", key="bt_all",
                 help="Runs the same rules for every company on the watchlist and in the portfolio."):
        rows = []
        for t_, n_ in names.items():
            w_ = c.backtest_windows(t_, LADDERS[ladder], WAITS[wait], years, rf)
            if w_.empty:
                continue
            vv = verdict(w_)
            rows.append({"Company": n_, "Waiting won": vv["win_rate"], "Typical difference": vv["median"],
                         "Worst": vv["worst"], "Best": vv["best"], "Cash on the side": vv["idle_cash"]})
        if rows:
            df = pd.DataFrame(rows).sort_values("Typical difference", ascending=False)
            c.table(df, {"Waiting won": "pct:0", "Typical difference": "spct", "Worst": "spct", "Best": "spct",
                         "Cash on the side": "pct:0"}, compact=True)

    with st.expander("How the backtest works"):
        st.markdown(
            f"- **Same money, same days.** Both strategies receive {c.symbol(None)}100 on the first trading day of "
            "every month. The savings plan buys at once.\n"
            "- **Waiting for pullbacks** keeps the money in cash (earning the risk-free rate) and buys when the price "
            "is the chosen distance below its 52-week high: the first level spends a third of the cash, the second "
            "half of the rest, the third everything. While the price stays in the deepest zone, new money goes "
            "straight in; after a recovery the ladder starts again.\n"
            "- **Every start month** of the last ten years is tested as its own window, so the result does not depend "
            "on one lucky or unlucky start. Prices include reinvested dividends; the trading currency is used.\n"
            "- **Not modelled:** taxes, fees and spreads. The history is that of a company that is still listed and "
            "on your list today (survivorship) – exactly the kind of stock that rarely gets cheap.\n"
            "- **Why the 52-week high and not your fair value?** Your valuations of past years do not exist, so a "
            "fair-value rule cannot be tested without hindsight. Pullbacks from the high are the honest stand-in.\n"
            "- Full write-up in `docs/METHODOLOGY.md`."
        )
