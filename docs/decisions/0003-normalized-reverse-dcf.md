# 0003 – Reverse DCF on a normalized cash-flow basis

**Status:** accepted · 2026-10-11

## Context
The first reverse DCF used today's free-cash-flow margin. For companies in an investment cycle (e.g. data-centre
capex at Amazon, Meta, Microsoft) today's FCF margin is temporarily depressed, so the model claimed the market
priced in absurd growth (Amazon: > 35% p.a. for five years). Using a "normal" FCF margin instead ignores that
growth has to be financed.

## Decision
Default to the normalized basis used by Speedwell Research and Damodaran:
`cash flow = revenue × after-tax operating margin − Δrevenue / sales-to-capital`.
Sales-to-capital defaults to today's revenue ÷ invested capital (equity + debt − cash), clipped to 0.5–4.
The FCF basis (with stock-based compensation deducted) remains available as an alternative.

## Consequences
- Implied growth rates became plausible and comparable with consensus (e.g. Meta ≈ 16% vs. analysts ≈ 21%).
- One more assumption (sales-to-capital) – shown, explained and editable in the UI.
