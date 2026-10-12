# 0001 – Beta and correlations on weekly returns

**Status:** accepted · 2026-10-10

## Context
Most holdings are US stocks priced in EUR; the benchmark is a Xetra-listed MSCI World ETF. Xetra closes at 17:30 CET,
US markets at 22:00 CET. A US stock's daily close therefore contains news the benchmark's close of the same day
does not, and vice versa. On daily data this asynchronicity biased the betas of US stocks noticeably downwards and
made correlations look lower than they are – the portfolio looked better diversified than it was.

## Decision
Estimate beta, correlations, tracking error, information ratio and capture ratios on **weekly** (Friday-to-Friday)
compounded returns. Volatility and VaR stay on daily data, where the timing offset averages out.

## Consequences
- Betas and correlations are in line with published figures; risk contributions and stress tests (which use beta)
  are no longer understated.
- Fewer observations (52 per year): estimates over short periods are noisier, so the app shows them over one year
  or more.
