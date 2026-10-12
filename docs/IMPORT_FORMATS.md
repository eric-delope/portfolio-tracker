# Import formats

The tracker reads a CSV export of your transactions. The format is recognised from the header line – put the
file into `data/raw/` (the newest file is used) or upload it in the sidebar under *Settings*.

| Broker | How to export | Recognised by |
|---|---|---|
| **Trade Republic** | App → Profile → Transactions → Export (CSV) | `datetime, date, category, type, asset_class, name, symbol, …` |
| **Scalable Capital** | Web app → Transactions → Export (CSV) | `date;time;status;reference;description;assetType;type;isin;…` |
| **Any other broker** | Copy your transactions into the generic layout below (spreadsheet) | `date, type, isin, name, shares, price, amount, fee, tax, currency` |

All formats end up in the same normalized table (`src/portfolio_tracker/brokers.py`), so every analysis works
the same way whatever the source. Columns that can hold personal data – names, IBANs, references, free-text
descriptions – are dropped inside the adapter, before anything else sees the data.

## Generic layout

One row per booking. **Numbers are positive** – the `type` gives the direction.

| Column | Content | Example |
|---|---|---|
| `date` | booking date, `2025-01-31` or `31.01.2025` | `2025-01-03` |
| `type` | `buy`, `sell`, `dividend`, `interest`, `deposit`, `withdrawal`, `fee`, `tax`, `tax refund` – or German: `Kauf`, `Verkauf`, `Dividende`, `Zinsen`, `Einzahlung`, `Auszahlung`, `Gebühr`, `Steuer` | `buy` |
| `isin` | ISIN of the security (empty for cash bookings) | `IE00B4L5Y983` |
| `name` | name of the security | `iShares Core MSCI World` |
| `shares` | number of shares (buy/sell) | `4` |
| `price` | price per share in `currency` (buy/sell) | `75.25` |
| `amount` | cash amount for deposits, withdrawals, dividends, interest, fees, taxes (for trades it is `shares × price` and may stay empty) | `1000` |
| `fee` | order fee | `1.00` |
| `tax` | tax withheld | `0.40` |
| `currency` | currency of the booking | `EUR` |

Optional columns: `time` (`14:30`), `asset_class` (`STOCK` / `FUND` – otherwise ETFs are recognised by issuer
or index in the name), `id` (a unique booking id). Comma or semicolon as separator, decimal point or comma –
both are detected. A ready-to-copy example: [`data/sample/generic_template.csv`](../data/sample/generic_template.csv).

**Savings plans:** use `savings plan` / `Sparplan` as the type – they count as buys and are marked as
savings-plan executions.

## Adding a broker

1. Write a function `my_broker(text: str) -> pd.DataFrame` in `brokers.py` that returns the normalized columns
   (`COLUMNS`) with the sign conventions documented at the top of the module.
2. Add it to `FORMATS` with the set of header columns that identifies the export.
3. Add a synthetic sample (no real data!) and tests to `tests/test_brokers.py`.

## Why CSV and not an API?

Short answer: for a monthly routine the export is three taps, and it keeps your broker login out of the tool.

- **Trade Republic** and **Scalable Capital** offer no official API. Unofficial tools (e.g. `pytr`) log in with
  your phone number and PIN by imitating the app. That works, but it means storing broker credentials on disk,
  can break with any app update and is not covered by the broker's terms – the opposite of this project's
  privacy promise. The tracker therefore never asks for a broker login.
- **Interactive Brokers** does offer an official, read-only interface: *Flex Queries* with a token. That would be
  the cleanest API connection and is on the roadmap.
- **comdirect** has an official REST API for private customers (OAuth with two-factor approval); possible, but
  more effort than a monthly export.

If you want the export to happen automatically, the low-effort route is: keep downloading the CSV, drop it into
`data/raw/` – the dashboard always picks the newest file.
