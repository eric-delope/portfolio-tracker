# 0004 – Company guidance from Yahoo's mirror of SEC exhibits

**Status:** accepted · 2026-10-11

## Context
Company guidance lives in the earnings press release (exhibit 99.1 of 8-K / 6-K filings). SEC EDGAR requires a
User-Agent with a contact e-mail address; sending the user's personal address with every request to a third party
was not acceptable without explicit consent. Paid data APIs were out of scope.

## Decision
Use the filing index that the market-data library already exposes and download exhibits from Yahoo's public mirror
(`cdn.yahoofinance.com`). Parse the outlook section locally: find ranges ("between $X and $Y billion"), drop legal
boilerplate, map the guided period to the first quarter ending after the release date.

## Consequences
- No personal data leaves the machine; no API key needed.
- Coverage limited to SEC filers (US listings, ADRs); companies that guide only on the call, or non-US filers,
  can be entered manually in the UI.
- Parser is heuristic – covered by tests on real release wording, and the original sentences are always shown
  next to the extracted numbers.
