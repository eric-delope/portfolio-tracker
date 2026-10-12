# Methodology

How every number in the dashboard is computed, which assumptions sit behind it and how it was validated.
Module names refer to `src/portfolio_tracker/`.

## 1. Data

**Source.** The Trade Republic transaction export (CSV). `importer.py` maps every raw type (`BUY`, `SELL`,
`DIVIDEND`, `INTEREST_PAYMENT`, `TAX_OPTIMIZATION`, `BENEFITS_SAVEBACK`, transfers, card payments, …) to a
normalized event. Sign conventions verified against real exports: `shares` is signed (+ buy, − sell), `amount`
excludes fees and taxes, `fee` and `tax` are separate signed cash amounts. Personal columns (counterparty name, IBAN,
payment reference, free text) are dropped on import.

**Validation on import** (`importer.validate`): `|amount + shares × price| ≤ €0.05` for every trade, no negative
holdings (oversell), no negative cash balance, no duplicate transaction IDs, unknown types flagged.

**Market data** (`market.py`): ISIN → Yahoo ticker via search (cached; Xetra overrides for UCITS ETFs whose search
result is a USD London listing), daily closes in listing currency plus daily FX, converted to EUR. Prices are
split-adjusted but **not** dividend-adjusted, because dividends enter the analysis as cash flows. Splits are applied
to the transaction history (`lots.apply_splits`) so share counts and prices stay comparable.

## 2. Performance

**Perspective.** The securities account on its own. Money flows *into* it with every buy (incl. fee) and *out of*
it with every sale (after fee and tax) and every dividend (gross).

| Quantity | Definition |
|---|---|
| Profit | `P&L = V_t + Σ outflows − Σ inflows` |
| Time-weighted return | daily `r_t = (V_t + Out_t) / (V_{t−1} + In_t) − 1`, chained: `TWR = Π(1 + r_t) − 1` |
| Money-weighted return | XIRR of all flows plus the terminal value, solved with Brent's method |
| Annualization | only for periods ≥ 1 year (GIPS); shorter periods are shown as-is |
| Excess return | `TWR_portfolio − TWR_benchmark` over the same window |
| Alpha, beta | OLS of weekly portfolio on weekly benchmark returns; Jensen's alpha annualized with the risk-free rate |
| Information ratio | annualized excess return ÷ tracking error (weekly) |
| Up/down capture | mean portfolio return in benchmark-up (-down) weeks ÷ mean benchmark return in those weeks |

**Benchmarks.** Accumulating UCITS ETFs quoted in EUR on Xetra – MSCI World (EUNL), S&P 500 (SXR8), Nasdaq-100
(SXRV) – so dividends and currency effects are treated exactly as for a euro investor.

**Shadow portfolio & KS-PME.** Every portfolio cash flow is mirrored into the benchmark (public market equivalent).
The Kaplan-Schoar PME is `Σ FV(outflows) + V_T` divided by `Σ FV(inflows)`, both compounded with the benchmark;
> 1 means the portfolio beat the benchmark on a money-weighted basis.

**Attribution.** Per position: realized gains (FIFO), unrealized gains split into price effect (local currency) and
currency effect per lot, `EUR return = (P_t / P_buy) × (FX_buy / FX_t) − 1`, plus dividends.

**Reporting currency (EUR or USD).** `Portfolio.in_currency()` translates every price, trade, dividend and
benchmark close at the exchange rate of its own day and recomputes everything, so values and returns are those of
an investor measuring in that currency (if the euro gains 6% against the dollar, a +71% euro return becomes about
+82% in dollars). Cash held in euros is revalued daily. Taxes, order amounts and broker alerts stay in euros – the
account and tax currency. Verified by tests: converted values equal euro values × the daily rate, a constant rate
changes amounts but not returns, and a strengthening euro raises dollar returns.

## 3. Risk

- **Volatility, Sharpe, Sortino** on daily returns, annualized with √252.
- **Beta and correlations on weekly returns.** US markets close after Xetra, so daily EUR closes of US stocks and
  of a Xetra-listed benchmark are not simultaneous; daily betas are biased towards zero (see
  [decision 0001](decisions/0001-weekly-returns-for-beta.md)).
- **Drawdown** from the running peak of the TWR index, with duration and recovery date.
- **Value at Risk / Expected Shortfall:** historical simulation, today's weights × the last year of daily returns,
  95% level.
- **Risk contributions:** Euler decomposition `RC_i = w_i (Σw)_i / wᵀΣw` (sums to 100%); the
  **diversification ratio** is `Σ w_i σ_i / σ_p`; **effective positions** are `1 / Σ w_i²`.
- **Stress tests:** instant shocks to today's holdings – market moves via each position's beta, currency moves via
  the foreign-currency exposure.
- **Order check** (`ordercheck.py`): recomputes weight, sector, currency, volatility, beta, risk contribution and VaR
  *before vs. after* a planned buy and warns above 20% single-position or 35% sector weight.

### ETF look-through

`lookthrough.py` opens every ETF up. For each fund it takes the published **top-10 holdings and sector weights**
(Yahoo Finance fund data, cached for 14 days) and adds `position weight × weight in the fund` to each company and
sector. Direct holdings and fund holdings of the same company are matched by a loose company key (legal suffixes and
share classes removed: *Alphabet Inc Class A* = *Alphabet*). The rest of each fund beyond its top ten is reported as
"other holdings"; funds without data count as "Funds without data". Limits: only ten holdings per fund, and no
country split for ETFs from this source, so the country view keeps the fund's region label.

## 4. German taxes (simplified)

25% flat tax + 5.5% solidarity surcharge (26.375%, no church tax). Stock losses only offset stock gains (separate
loss pot), other losses go to the general pot; equity ETFs get the 30% partial exemption; the saver's allowance
(€1,000 / €2,000) is applied last. **Latent tax** = tax due if every open lot were sold today. Not modelled: the
*Vorabpauschale* on accumulating funds and the crediting of foreign withholding tax.

## 5. Decisions and entries

- **Decision scorecard** (`decisions.py`): every single-stock buy is scored as `stock return − benchmark return`
  over the following 6/12/24 months, every sell as `benchmark − sold stock`. Groups: buys, savings-plan executions,
  sells. Amount-weighted mean, hit rate and a t-statistic; the verdict stays *too little data* below 20 decisions
  and *not yet conclusive* while `|t| < 2`, because overlapping windows make observations dependent.
- **Entry quality:** where the buy price sat inside the price range of the next 6 months (0% = bought at the low),
  buy price vs. the average price over the next 3 months (what a savings plan would have paid), distance to the
  52-week high at purchase, and – once valuations exist – the share of buys below your own fair value at the time.

## 6. Valuation

**Scenario model** (`valuation.py`). For each of bear/base/bull with probability `p_s`:

```
EPS_t   = EPS_0 · (1 + g_s)^t          (year 1 optionally replaced by the analyst consensus)
Price_T = EPS_T · PE_exit,s
Value_s = Price_T / (1 + r)^T + Σ_t D_t / (1 + r)^t      (dividends grow with EPS)
Fair    = Σ_s p_s · Value_s
Max     = Fair · (1 − margin of safety)
```

*Consistency rule:* the expected price in T years is defined as `Fair · (1 + r)^T − FV(dividends)`, so buying exactly
at fair value earns exactly the required return `r` (tested). The expected return at any other price is the IRR of
`−price, dividends…, expected price`.

**Defaults** (all editable): growth suggestion = 60% median of the available views (history, analysts, company
guidance + 2 pp operating leverage on revenue-based views) + 40% long-run normal of 6%, clipped to −5…20%; exit P/E
from the stock's own P/E history (median, quartiles), ordered bear ≤ base ≤ bull. If analysts' EPS growth deviates
more than 15 pp from their revenue growth, the EPS base year is treated as distorted and revenue becomes the anchor.

**Quality → margin of safety and hurdle** (`quality.py`). Seven hard checks (revenue growth, operating margin, cash
conversion, leverage, ROE, share count, profitable every year) and three judgements (moat, predictability,
management: weak/medium/strong) are combined 50/50 into a score `s ∈ [0, 1]`:
`margin of safety = 30% − 20%·s` (10–30%), `required return = 12% − 3%·s` (9–12%).

**Rolling fair value.** Fair value compounds at the required return minus dividends paid:
`FV_t = FV_0 (1 + r)^t − Σ D_k (1 + r)^{t−k}`. Alerts store their distance to fair value and roll forward with it.

**Hit probability of an entry tranche.** Share of all start days in the last 10 years after which the stock fell at
least to the tranche level within 252 trading days. "Expected return incl. waiting" = `p · r_tranche + (1 − p) · r_f`.

**Verdicts** (`opportunities.py`): *Avoid* if the thesis is broken or the expected return < risk-free rate;
*Watch* if below the required return; *Savings plan* if attractive but no tranche reached or P/E in the top third of
its own history; *Buy (small)* for low quality or a position already ≥ 20%; otherwise *Buy*.

**Signals for holdings** (`watchlist.signal`): *Review* when a thesis KPI fails; *Consider trimming* when a sell line
is reached or the expected return from today's price falls below 4% p.a.; never on price moves alone.

## 7. Reverse DCF (Speedwell Research / Drew Cohen)

`reverse_dcf.py` starts from today's market cap and asks which annual return a buyer earns under given business
assumptions – the inverse of "what is it worth?".

- Explicit cash flows for 40 years, **no terminal value**.
- Revenue growth in buckets: years 1–5 `g`, years 6–10 `g/2`, years 11–20 `min(g/4, 4%)`, then a mature rate (2%).
- Margin moves linearly from today's level to the target margin over 5 years.
- **Normalized basis** (default): `cash flow = revenue × after-tax operating margin − Δrevenue / sales-to-capital`.
  Growth has to be funded; a temporary capex boom is not mistaken for a permanently low margin (see
  [decision 0003](decisions/0003-normalized-reverse-dcf.md)). Alternative basis: FCF margin with stock-based
  compensation deducted.
- **Implied return** = IRR that equates the present value of the cash flows with the market cap (Brent).
- **Implied growth** = growth `g` for which the implied return equals the hurdle (9%) at today's margin.
- Rule of thumb shown in the app: buy when *draconian* assumptions (no growth, margin −5 pp) avoid a loss and
  *conservative* ones (half the lowest growth forecast, margin unchanged) roughly earn the market return.

## 7b. Wealth planning (Monte Carlo)

`planning.py` simulates 5,000 paths month by month. Monthly growth is log-normal,
`exp(N(μ, σ_m))` with `σ_m = σ/√12` and `μ = ln(1+R)/12 − σ_m²/2`, so the **mean** compounds at the expected return
`R` while the **median** (shown as "typical") grows more slowly – the volatility drag. The monthly saving is added
at the end of each month and can grow yearly. With "today's money" every value is divided by `1.02^t`.

- **Bands** are the 10/25/50/75/90th percentiles across paths per month.
- **Chance of reaching a goal** = share of paths ending at or above it.
- **Saving needed for a 75% chance**: root search (Brent) on the monthly saving so that the 25th percentile of the
  final value equals the goal, using the same random draws for every try (common random numbers).
- **Defaults** come from the account: monthly saving = average net deposits of the last 12 months; volatility =
  the ex-ante volatility of today's holdings (clipped to 8–35%); expected return = 7% p.a. as a long-run equity
  assumption – the portfolio's own realised return covers too few years to extrapolate.
- **Emergency fund** = cash on the account ÷ average monthly card spending of the last 6 months (proxy for living
  costs): ≥ 6 months solid, 3–6 ok, < 3 thin.
- **Not modelled:** taxes, fees, fat tails, crisis clusters, changing risk. The bad case is therefore optimistic.

## 7c. Entry backtest – does waiting pay?

`backtest.py` compares two ways of investing the same monthly amount (paid on the first trading day of each
month) in one security:

- **Savings plan:** buys at once.
- **Waiting for pullbacks:** keeps the money in cash at the risk-free rate and buys in three tranches when the
  price is 10 / 20 / 30% (or the chosen levels) below its 52-week high. Tranche *t* of *k* spends 1/(k−t+1) of
  the cash pot, so the deepest level spends the rest; while the price stays in the deepest zone new money goes
  straight in; once the price recovers to within half the first level of its high, the ladder resets.
  Optionally, cash that has waited *N* months is invested anyway.

Prices are a total-return index (dividends reinvested on the ex-date, trading currency). Every start month with
a year of history before it opens a window of 3, 5 or 7 years; the result per window is the final wealth of
waiting ÷ savings plan − 1. Reported: share of windows waiting won, median, worst and best difference, average
cash share.

**Why the 52-week high and not the fair value?** The fair-value rule is what the watchlist actually uses, but the
valuations of past years do not exist – testing it would need hindsight. Pullbacks from the high are the
honest, testable proxy; a fair-value backtest is on the roadmap once saved valuations accumulate.

**Limits:** survivorship (the companies are those still listed and on your list today – exactly the stocks
that rarely got cheap), no taxes, fees or spreads, daily closes instead of intraday limit fills.

**Result on the author's list (10/20/30%, 12 months, 5-year windows):** waiting won in 0–12% of windows for
ASML, Microsoft, Costco and an MSCI World ETF (typically 2–7% less final wealth), around 40–50% for SAP, and in
89% for Adyen after its 2023 crash. In line with the literature on dollar-cost averaging vs. buying the dip.

## 8. Company guidance

`guidance.py` reads the latest earnings releases (exhibit 99.1 of 8-K/6-K filings, via Yahoo's mirror –
[decision 0004](decisions/0004-guidance-via-yahoo-mirror.md)), isolates the outlook section, filters legal
boilerplate and extracts ranges such as "revenue to be between $47.5 billion and $50.5 billion". The guided quarter
is the first quarter ending *after the release date* (robust when quarterly data lags). The **track record**
compares each guided range with the revenue later reported: above / within / below range.

## 9. Validation

| Check | How |
|---|---|
| Portfolio value = broker | Compared with the value shown in the Trade Republic app on the author's real export. |
| Accounting identities | `test_pnl_identity`, `test_unrealized_plus_realized_plus_dividends_equals_total`, `test_positions_match_holdings` |
| Monthly report adds up | monthly P&L sums to the total; monthly TWRs compound to the full-period TWR |
| TWR is flow-neutral | `test_twr_ignores_cash_flows`, `test_twr_matches_price_return_for_single_buy` |
| Shadow portfolio | equals the actual portfolio when only the benchmark is held |
| Solvers | XIRR of a known 10% case; reverse DCF recovers the growth it was given; `price_for_return` inverts the IRR |
| Valuation consistency | buying at fair value earns the required return, with and without dividends |
| Risk | risk contributions sum to 100%; beta of a scaled series equals the scale |
| Taxes | stock losses only offset stock gains; 30% partial exemption; latent tax |
| Planning | zero volatility reproduces compound interest; the simulated mean compounds at R; inflation deflation; the 75% saving really gives ≈ 75% |
| Backtest | flat prices tie, a steady rise punishes waiting, a crash and recovery rewards it; the ladder spends ⅓, ½, rest; dividends compound in the total-return index |
| Broker formats | Scalable Capital and generic layout: detection, signs, cancelled orders skipped, personal details dropped |
| Translations | every UI text has a German translation; placeholders match; German number formats |
| Look-through | direct + through-fund weights add up (MSFT 20% + 60% × 5%); totals sum to 100%; missing fund data is counted, not dropped |
| Guidance parser | real press-release wording (USD and EUR ranges), boilerplate ignored, lagging quarterly data |
| Data checks | oversell, amount mismatch, unknown types, foreign CSVs rejected |
| UI | headless sweep of every page, tab and research step (with and without privacy mode) via Streamlit's AppTest |
| Privacy | personal details never reach outputs; core runs with sockets blocked; offline mode makes no request; repository scan (see [PRIVACY.md](PRIVACY.md)) |

Run `pytest -q` for the 133 unit tests; CI runs them with `ruff` on every push.

## 10. Known limitations

- Yahoo Finance closes differ slightly from the Lang & Schwarz quotes Trade Republic executes at (median deviation
  shown in the app, usually < 2%). Fundamentals can be missing or late for non-US companies.
- Valuation outputs are only as good as the assumptions; the tool makes them explicit, it does not make them right.
- Taxes are a simplified model of German rules and not tax advice.
