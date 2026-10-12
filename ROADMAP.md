# Roadmap

Prioritized by value for a long-term investor vs. effort. "Now" is being worked on, "Next" is planned, "Later"
needs a decision or more data.

## Now

- [ ] **Live demo** on Streamlit Community Cloud – demo mode only (`PORTFOLIO_DEMO=1`), server binding overridden for that deployment, never with real data.

## Next

- [ ] **Vorabpauschale** for accumulating funds and crediting of foreign withholding tax in the tax estimate.
- [ ] Price alerts on a schedule (GitHub Actions or launchd) with e-mail/push instead of manual checks.
- [ ] **Interactive Brokers via Flex Query** – the one broker with an official, read-only, token-based interface.
- [ ] Fair-value backtest: once the watchlist holds a few years of saved valuations, test buying below *your* fair value instead of the 52-week-high proxy.
- [ ] AppTest-based UI smoke test in CI (the headless sweep currently runs locally because it needs market data).
- [ ] Rebalancing helper: given a monthly budget, which positions bring the portfolio closest to target weights.

## Later

- [ ] Full ETF holdings (all positions and countries) from the fund providers' files, where they publish them – today the look-through uses the top ten.
- [ ] Withdrawal phase in the planner: how long does the portfolio last at a given monthly withdrawal?

- [ ] Quarterly fundamentals from SEC XBRL for longer, cleaner histories than the data provider offers.
- [ ] Factor exposure (size, value, momentum, quality) via regression on public factor returns.
- [ ] Multi-portfolio support (e.g. a partner's account) with consolidated view.

## Done

See the [CHANGELOG](CHANGELOG.md): import → analytics → monthly routine → long-term entry discipline → guided
valuation → reverse DCF and guidance → UX → public release → planning and look-through → entry backtest,
German UI and more brokers.
