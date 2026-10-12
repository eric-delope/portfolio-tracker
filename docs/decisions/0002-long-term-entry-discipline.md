# 0002 – Long-term focus: entry discipline instead of trading signals

**Status:** accepted · 2026-10-10

## Context
The user invests for the long term. Generic tracker features (daily P&L, momentum, price targets) encourage
short-term reactions. What determines long-term returns that the investor controls is mainly *what price* is paid
and *whether the original reason for owning* still holds.

## Decision
- Every company gets an own valuation (fair value, required return, margin of safety) that **rolls forward** with
  the required return, so entry levels do not go stale.
- Buying is planned as a savings-plan part plus limit tranches below fair value; each tranche shows its historical
  probability of being reached.
- No price targets. Selling is triggered only by a **broken thesis** (KPIs re-checked after each report) or by
  **valuation** (expected return from today's price below a floor, default 4% p.a.).
- The investor's own decisions are measured against the benchmark (scorecard, entry quality) with a significance
  verdict.

## Consequences
- Fewer, more deliberate actions; the monthly report becomes a short to-do list.
- The tool depends on the user maintaining valuations – stale valuations are therefore flagged as to-dos.
