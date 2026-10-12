# Changelog

All notable changes, one version per iteration. Each iteration started from user feedback on the previous one;
the trigger is noted under *Why*. Format based on [Keep a Changelog](https://keepachangelog.com/).

## [1.6.0] – 2026-10-12 · Does waiting pay? · Deutsch · more brokers

*Why:* "do the backtest, then a German interface, then more broker formats – and could this work with an API?"

### Added
- **Entry backtest** ("Does waiting pay?", Watchlist & entries): waiting for pullbacks of 5/10/15, 10/20/30 or
  15/30/45% below the 52-week high (three tranches, optional "invest anyway after N months") vs. a plain monthly
  savings plan – same money on the same days, cash earning the risk-free rate, dividends reinvested. Tested on
  every start month of the last ten years; shows how often waiting won, the typical difference, the cash left on
  the side, a chart of every window and when the latest window bought. Optional comparison for every company.
- **German interface** (sidebar: English / Deutsch) with German number formats (1.234,56 € · 12,3 %) and dates.
  Texts stay English in the code and are translated where they are rendered; a catalog check
  (`scripts/i18n_catalog.py`, run in CI) fails when a new text has no translation.
- **More brokers:** automatic format detection; **Scalable Capital** CSV and a documented **generic layout** any
  broker export can be mapped to (`docs/IMPORT_FORMATS.md`, `data/sample/generic_template.csv`). ETFs are
  recognised by issuer or index in the name when the export does not say.
- 22 tests (backtest, broker formats, translation), 133 in total.

### Fixed
- Price cache: portfolios with different start dates (your export and the demo) no longer cut each other's
  history – the cache records from which date every symbol was loaded.

## [1.5.0] – 2026-10-12 · Planning and look-through

*Why:* "think about what would really help a private investor – also for portfolio and risk management."

### Added
- **Planning page:** Monte Carlo projection of the portfolio and saving plan (5,000 paths, log-normal monthly
  returns). Shows bad / typical / good case, the chance of reaching a goal, money paid in vs. growth, the monthly
  saving needed for a 75% chance, and a "what moves the needle" table (save more, invest longer, lower returns,
  growing savings). Pre-filled from the account; results in today's money by default.
- **Emergency-fund check** on the planning page: cash on the account in months of card spending.
- **Look-through** ("What you really own", Portfolio analysis → Positions): every ETF opened up into its top
  holdings and sector weights and combined with the direct positions – largest single company, top-10 concentration,
  real sector mix and overlaps between direct stocks and ETFs.
- 20 tests for planning and look-through, 2 for the fixes below (111 in total).

### Changed
- ETF-holdings requests go through the privacy gate like every other request (ticker only, shown in the log on
  the Privacy page, blocked in offline mode); `PRIVACY.md` updated.

### Fixed
- The dollar view could fail when the price provider briefly skipped the EUR/USD rate: a skipped symbol now keeps
  its last good history in the cache (and other portfolios' symbols are no longer overwritten). If no rates exist at
  all, the app shows euros with a notice instead of an error.

## [1.4.1] – 2026-10-12 · Dark-mode polish

*Why:* "hover numbers on the charts are unreadable in dark mode, the Sankey can't be read, scrolling stops."

### Fixed
- Hover boxes (single and unified) now take the card colour in dark mode instead of staying white with light text.
- Sankey: labels without the white glow, amounts next to each label, small streams grouped so nothing overlaps.
- Charts no longer zoom on drag or double-click, so they never capture scroll or drag gestures.
- Waterfall totals readable on dark backgrounds; treemap tiles pick black or white text automatically.

## [1.4.0] – 2026-10-12 · Dark mode and valuation charts

*Why:* "orient the charts on this screenshot (Qualtrim DCF view) – and I'd like a dark mode."

### Added
- **Dark mode:** native Streamlit light and dark themes (follows the system, switch under ⋮ → Settings). The custom
  design system switches with it through CSS variables; chart greys, grids and separators are re-coloured in the
  browser, series colours stay.
- **Valuation summary** on the "My price" step: verdict badge (buy zone / below fair value / overvalued), three plain
  sentences and a bar showing today's price against the maximum price and fair value, next to a key-value card with
  change pills.
- **Projections** card with three views: price history plus the path to each scenario's price in N years, P/E against
  its median and your exit P/E, and EPS history plus the scenario paths.
- Reference lines with boxed labels ("Median 39.1", "Your P/E 35.0") on all valuation-multiple charts.

### Changed
- Inline scripts (theme sync, step scrolling) moved from the deprecated `components.html` to `st.html`.

## [1.3.0] – 2026-10-11 · Euro or dollar

*Why:* "switch between euro and dollar".

### Added
- Reporting currency switch (EUR / USD) in the sidebar. Every price, trade, dividend and benchmark is converted at
  the exchange rate of its own day and all figures are recomputed – a true dollar view, not a relabelled euro view.
  Euro cash is revalued daily; the currency effect and FX stress test follow the chosen currency.
- Taxes, order checks and broker alert amounts stay in euros (account and tax currency).
- Three tests for the conversion (daily rates, constant-rate invariance of returns, stronger euro → higher dollar return).

## [1.2.0] – 2026-10-11 · Calm redesign

*Why:* "too crowded and cramped – I want simplicity and elegance", with Qualtrim as the reference.

### Changed
- New design system (`app/style.css`): off-white page, white cards, one accent colour, more whitespace, Inter
  everywhere (tables and key figures included), typographic minus signs.
- Key figures as one quiet strip per section instead of rows of boxed metrics; every chart in its own card with
  title and one-line subtitle; tables cut to the essential columns.
- Less text: long explanations moved into hover help or expanders, to-dos shortened to one line each, model
  assumptions of the reverse DCF and tranche editing folded away.
- Monthly charts on a real time axis instead of 36 rotated month labels.
- New screenshots in 2× resolution.

## [1.1.0] – 2026-10-11 · Privacy first

*Why:* "privacy and not sharing data should be front and centre" – and every claim must hold up technically.

### Added
- **Privacy gate** (`privacy.network`): every outbound request is logged with recipient, purpose and the identifiers
  it carries; **offline mode** (`PORTFOLIO_OFFLINE=1`) blocks all of them and the app runs from its cache
  (stale caches are used instead of failing; FX rates, filing indexes and US-listing lookups are now cached too).
- **Privacy & data page:** what left this computer, what never does, what is stored where, offline status, delete
  cached market data.
- **Privacy tests in CI:** personal details from an export never reach any output; the analytics core runs with all
  sockets blocked; offline mode makes zero requests; no export, IBAN or e-mail address in any publishable file.
- [docs/PRIVACY.md](docs/PRIVACY.md): data flow, enforcement, honest limits, GDPR context.

### Changed
- Font self-hosted (Inter, SIL OFL) instead of loading it from Google Fonts – the browser now contacts no host but
  `localhost` (verified with a headless browser audit).
- Dashboard bound to `localhost`: other devices on the same Wi-Fi can no longer open it.
- Privacy mode also hides the requested tickers on the privacy page.
- `PORTFOLIO_DEMO=1` forces the demo with its own watchlist, even when a real export exists.

## [1.0.0] – 2026-10-11 · Public release

*Why:* make the project usable and reviewable by others (GitHub, CV) without exposing personal data.

### Added
- Synthetic **demo portfolio** (three years, built from real historical prices) and demo watchlist; the app starts
  in demo mode when no export is present (`scripts/make_demo_data.py`).
- **Investment memo (PDF):** one-page export of a company valuation – verdict, quality, growth views, scenarios,
  valuation bridge, reverse DCF, entry plan with price chart, thesis KPIs.
- Documentation: README with screenshots and architecture, [METHODOLOGY](docs/METHODOLOGY.md) with validation,
  [ROADMAP](ROADMAP.md), [decision records](docs/decisions/).
- GitHub Actions CI (pytest + ruff on Python 3.12 and 3.14), MIT license, pinned requirements.

### Changed
- **Everything in English:** UI, number and date formats (1,234.56 · 11 Oct 2026), reports, verdicts, tests.
- Large page files split into one module per tab (`app/sections/analysis/`) and per research step
  (`app/sections/research/`); the analytics package stays free of Streamlit imports.
- Monthly notes are saved to `reports/`.

### Fixed
- Negative metric deltas could show an upward arrow (typographic minus not recognized as a sign).
- Sticky section bar let scrolled text show through on its right.
- Stress-test labels collided with long bars.

## [0.8.0] – 2026-10-11 · Calmer UX

*Why:* "simpler and more elegant – especially the tables and switching between tabs."

### Changed
- Custom HTML tables: no grid, right-aligned tabular numbers, colored signs, inline weight bars, pills for verdicts.
- Tabs restyled as a quiet segmented bar that stays visible while scrolling; tab state survives reruns and only the
  open tab is computed.
- Research steps get *Back / Next* buttons that switch the step and scroll back to the step bar.

## [0.7.0] – 2026-10-11 · Reverse DCF, company guidance, pro-grade research

*Why:* "add Drew Cohen's reverse DCF, show company guidance directly, learn from Finanzfluss, Fiscal.ai, Qualtrim."

### Added
- **Reverse DCF** after Speedwell Research: implied return grid (growth × margin), implied growth at the hurdle,
  draconian/conservative check, implied revenue path vs. consensus. Normalized basis with reinvestment.
- **Guidance extraction** from earnings releases (outlook section, ranges, boilerplate filter) and a **track
  record** of guidance vs. reported revenue.
- Financial tiles (annual/quarterly): revenue, operating income, SBC-adjusted FCF, EPS, margins, share count,
  net cash, dividends, valuation multiples over time, earnings surprises.
- Portfolio: dividend calendar and forecast, yield on cost, net worth (portfolio + cash), money-flow Sankey.

## [0.6.0] – 2026-10-10 · Guided valuation, professional charts

*Why:* "the right-hand panels are overloaded; guide me to the price I'm willing to pay; more professional charts;
show analyst and company expectations."

### Changed
- Research became an 8-step assistant; side panels removed.
- Quality check with own judgement (moat, predictability, management) → recommended margin of safety and hurdle.
- Charts rebuilt on a validated, colorblind-safe palette with page-level titles, subtitles and sources; a
  low-value "profit in period" chart removed.

### Added
- Analyst consensus (revenue, EPS with low–high range), recommendations, revisions, price targets.

## [0.5.0] – 2026-10-10 · Long-term focus on good entries

*Why:* "the tracker is for long-term portfolios and should focus on good entries."

### Added
- Entry ranking with verdicts (*Buy / Buy (small) / Savings plan / Watch / Avoid*).
- Rolling fair value; alerts grow with it; roll-forward reminder in the monthly report.
- Hit probability per tranche and expected return incl. waiting.
- Decision scorecard vs. benchmark (6/12/24 months) and entry-quality statistics.
- Thesis KPIs re-checked after every report; valuation-based sell line instead of price targets.

## [0.4.0] – 2026-10-10 · Monthly routine, watchlist, company research

*Why:* "once a month I want all key information, plus a watchlist with price alerts that I calculated myself."

### Added
- Monthly report with prioritized to-dos and Markdown export.
- Watchlist with price alerts (trading currency + EUR for the broker app), CLI alert check.
- Company research: fundamentals, own bear/base/bull forecasts, DCF cross-check, entry tranches, order check.

## [0.3.0] – 2026-10-10 · Deep portfolio analytics

*Why:* "much more than the broker's view – extract as much information as possible."

### Added
- Risk: volatility, Sharpe/Sortino, drawdowns, VaR/ES, risk contributions, correlations, stress tests.
- Attribution: price vs. currency effect per lot, contribution per position, P&L waterfall.
- Trading behaviour, closed positions, German tax estimate and latent tax, shadow portfolio and KS-PME.

## [0.2.0] – 2026-10-10 · Market data and performance

### Added
- ISIN → ticker resolution, EUR prices with FX, split handling, disk cache.
- Daily portfolio values, TWR, XIRR, FIFO lots, benchmarks; first Streamlit dashboard.

## [0.1.0] – 2026-10-10 · Import

### Added
- Trade Republic CSV import with normalized events, validation and removal of personal columns.
- Synthetic sample export and first unit tests.
