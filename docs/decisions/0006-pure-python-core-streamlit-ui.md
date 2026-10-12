# 0006 – Pure-Python analytics core, Streamlit only as UI

**Status:** accepted · 2026-10-10

## Context
The analytics (returns, risk, taxes, valuation) must be correct and testable; the UI changed several times based on
feedback. Mixing both would make every UI change risky.

## Decision
- `src/portfolio_tracker/` contains all calculations as plain functions and dataclasses on pandas objects, without
  Streamlit imports, covered by unit tests (identities, round trips, edge cases).
- `app/` contains only presentation: page layout, formatting, charts, caching and session state.
- Streamlit was chosen over a web framework for speed of iteration and because the audience is one investor.

## Consequences
- 89 unit tests run in about two seconds and gate every change in CI.
- The same core powers the CLI alert check and the PDF memo, and could back another UI later.
