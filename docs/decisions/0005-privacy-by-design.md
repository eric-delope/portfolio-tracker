# 0005 – Privacy by design

**Status:** accepted · 2026-10-10 · extended 2026-10-11 (v1.1)

## Context
A broker export contains names, IBANs, card merchants and the complete financial history of a person. Hosted
portfolio trackers typically ask users to upload exactly that. This project takes the opposite position and makes
privacy its first design constraint – the project is public (GitHub, CV) and screenshots will be shared, so the
guarantees must be verifiable, not just promised.

## Decision
1. **Local processing only.** No backend, no account, no upload. Uploaded files stay in memory.
2. **Data minimisation on import.** Counterparty name, IBAN, payment reference and free text are dropped before any
   analysis; card merchant names never leave the importer.
3. **One gate for all network traffic** (`privacy.network`). Every request is logged with the identifiers it carries;
   `PORTFOLIO_OFFLINE=1` blocks them all and the app falls back to its cache.
4. **No third parties in the browser.** Font self-hosted (SIL OFL), Streamlit telemetry off, dashboard bound to
   `localhost` so other devices on the same network cannot open it.
5. **Transparency in the product.** A *Privacy & data* page shows what left the machine, what never does and what is
   stored where; privacy mode hides all euro amounts (and the requested tickers) for screenshots.
6. **Nothing personal in the repository.** Real data folders are git-ignored; a test scans every publishable file for
   exports, IBANs and e-mail addresses; the public demo is synthetic.
7. **Executable guarantees.** Privacy properties are unit tests that run in CI.

## Alternatives considered
- *Hosted multi-user app* – rejected: would require storing third parties' financial data.
- *Bundled market data instead of Yahoo* – rejected for now: no free redistributable source; offline mode covers the
  "nothing leaves" case after a fetch.
- *Encrypting files at rest in the app* – deferred: operating-system disk encryption is the stronger and simpler
  control for a single-user local tool.

## Consequences
- When online, Yahoo Finance learns which ticker symbols are requested (plus the IP address) – stated openly in the
  app and in `docs/PRIVACY.md`.
- The demo must be realistic enough to exercise every feature – hence a generator instead of a hand-written sample.
- Hosting a public live demo needs the server binding overridden for the demo deployment only.
