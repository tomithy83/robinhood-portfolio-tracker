# Robinhood Portfolio Tracker

A self-contained tool that pulls your Robinhood history, stores it in SQLite,
reconstructs a **month-end tracking ledger** back to **Oct 2025**, and exports a
multi-sheet workbook (Excel now, Google Sheets later). Built around a clean
three-layer package so adding data sources, output formats, or report tabs is
low-friction.

Everything is **computed values, not formulas**, so an exported Excel file and a
future Google Sheet are byte-for-byte identical in content.

## Quick start

```
pip install -r requirements.txt          # runtime deps
pip install -r requirements-dev.txt      # + pytest/hypothesis for the test suite
```

Put your credentials in a `.env` file at the repo root (copy `.env.example`):

```
ROBINHOOD_USERNAME=you@example.com
ROBINHOOD_PASSWORD=your_password
```

Run from source with `src/` on the path:

```
cd src
python -m rhtracker pull --since 2025-10-01   # log in (interactive MFA), pull, reconstruct
python -m rhtracker export                    # write a timestamped .xlsx under output/
python -m rhtracker report                    # print the month-end grid + summaries
python -m rhtracker reconstruct               # rebuild rows from stored data (no network)
python -m rhtracker categories                # print category tables
```

First `pull` prompts for an MFA code and caches a session under `~/.tokens`, so
later runs are non-interactive until the token expires.

### Refreshing for a new month

The backfill is a full rebuild. To refresh, delete the DB and re-pull:

```
rm robinhood.db           # (Windows: Remove-Item robinhood.db)
cd src && python -m rhtracker pull --since 2025-10-01 && python -m rhtracker export
```

A fresh rebuild is required because dedup would otherwise keep stale rows (e.g.
a ticker symbol or split factor that changed). It is cheap — the whole history
is a few hundred transactions.

## Commands

| Command | What it does | Network? |
|---------|--------------|----------|
| `pull [--since DATE]` | authenticate, harvest all transactions, fetch historical prices, capture a real account snapshot, reconstruct, store | yes |
| `reconstruct` | rebuild the month-end rows from already-stored data | no |
| `report` | print the overall summary, month-end grid, and transaction summary | no |
| `categories` | print dividend / expense / fee / stock / option tables | no |
| `export [--format xlsx|gsheets] [--out PATH]` | build the workbook and write it (default: timestamped `.xlsx` in `output/`) | no |


## Architecture

A `src/rhtracker` package in three layers, dependencies pointing **downward only**:

```
cli/            pull · reconstruct · report · categories · export   (parse args, print)
  |  imports
  v
services.py     pull() / reconstruct() / report() / category_report() / export_workbook()
  |  imports                                        (orchestration; no argparse, no print)
  v
library         model · sources · storage · reconstruct · reporting
                categories · export · writers · splits
```

- **CLI layer** (`cli/`, one file per command) only parses arguments and prints.
- **Services layer** wires the library together; returns values, never prints.
  Both the data `source` and the `store` are injectable (tests pass fakes).
- **Library layer** does the work and never imports upward. `model` and
  `splits` are the foundational data modules.

The downward-only rule is enforced by `tests/test_layers.py`, which statically
parses every module's imports.

```
src/rhtracker/
  __main__.py            # enables `python -m rhtracker`
  model.py               # Transaction, Position, Price, MonthlySnapshot, PortfolioSnapshot
  storage.py             # SqliteStore (bronze/silver/gold + real snapshot)
  reconstruct.py         # flows -> positions -> month-end MonthlySnapshot rows
  reporting.py           # snapshots/categories -> formatted strings
  categories.py          # dividend / expense / fee / stock / option groupings
  splits.py              # manual stock-split table (see below)
  export.py              # writer-agnostic ExportWorkbook builder (the sheets)
  services.py            # orchestration recipes
  sources/
    base.py              # Source protocol (authenticate / fetch_transactions / fetch_prices / fetch_portfolio_snapshot)
    robinhood.py         # RobinhoodSource — the only module that talks to the API
  writers/
    base.py              # WorkbookWriter protocol (the export seam)
    xlsx.py              # XlsxWriter (openpyxl)
    sheets.py            # SheetsWriter stub (Google Sheets, future)
  cli/
    main.py pull.py reconstruct.py report.py categories.py export.py
```

### Extending it

- **New data source** (another brokerage): implement the `Source` protocol in
  `sources/<name>.py` and pass an instance to `services.pull(source=...)`. No
  other layer changes.
- **New output format** (Google Sheets): implement `WorkbookWriter.write` in
  `writers/sheets.py` against the same `ExportWorkbook`; the CLI already accepts
  `--format gsheets`. The sheet-building code in `export.py` does not change.

## Workbook sheets

| Sheet | Contents |
|-------|----------|
| Overall Summary | **real** broker figures as of the last pull (gross, equity, margin borrowed, total margin, buying power, maintenance, buffer, interest) |
| Tracking | the month-end grid (gross, growth, dividends, interest, expenses, margin, W2 contributions, net value) |
| Transactions | the full normalized ledger |
| Dividends | dividend income by ticker |
| Dividend Payments | every individual dividend row |
| Expense Summary | expenses + fees by payee |
| Expense Details | every expense/fee transaction |
| Stock Trades | buy/sell totals per ticker |
| Options | option premium bought/sold per underlying |
| Positions | holdings at the latest month-end |
| Definitions | a cheat sheet explaining every column and the known approximations |


## Data accuracy notes

Read these before trusting the numbers — they are the hard-won lessons behind
this tool.

### Margin / cash is a true cash ledger
Margin debt changes **only** when cash moves; `equity = market_value - margin_debt`
(equity is the derived quantity that floats with the market, not margin). The
reconstructed month-end margin is a running sum of every signed cash movement
and reconciles to the broker's real `portfolio_cash` within settlement noise
(a few hundred dollars from `unsettled_debit` — after-hours trades not yet
settled). It is **not** calibrated or fudged; it is a genuine ledger.

### The two-ledger gotcha (why this was hard)
Robinhood splits money across the **brokerage** (`rhs_account`) and the
**Robinhood banking/checking** (`rhy_banking_checking`) sides. Transfers between
them — and credit-card cashback — appear in **no** standard feed; only in the
undocumented `unified_transfers` endpoint. Missing these understated the ledger
by ~$17k. They are now captured as `rhy_transfer` (withdrawal out) and
`cashback` (income). See `docs/robinhood-api.md` section 7 for the full story.

### Splits are manual
Robinhood does not reliably expose stock splits via the API (`get_splits`, the
instrument splits feed, and `get_events` all came back empty for a known MSTY
1-for-5 reverse split). Splits live in a small hand-maintained table,
`src/rhtracker/splits.py`, and are validated against real current share counts.
If a holding splits, add one line there and re-pull.

### Historical prices are back-adjusted
`get_stock_historicals` reports pre-split dates on the current post-split price
basis, so reconstructed share counts are expressed on that same basis.

### Known limitations
- **Gold credit card** transactions are not retrievable via this API.
- **Options** are summarized by premium only; they do not contribute to
  `gross_value` (stocks/funds only).
- Historical month-end margin is reconstructed (the API exposes only the
  current real balance), so past month-ends are accurate-but-reconstructed; the
  current month ties to the real snapshot.

## Storage (`robinhood.db`)

| Layer | Tables |
|-------|--------|
| bronze | `raw_events` (raw API payloads) |
| silver | `transactions`, `positions_daily`, `price_cache` |
| gold | `monthly_tracking` |
| snapshot | `portfolio_snapshot` (real point-in-time broker figures) |

Dedup is on `reference_id` then the `transaction_hash` primary key; every query
is parameterized.

## Testing

```
python -m pytest tests/
```

Runs offline against a `FakeSource` (no live Robinhood needed). Includes the
36-assertion reconstruction oracle, split handling, category/export logic, the
services cohesion test, and the layer-dependency property tests.

## API reference

`docs/robinhood-api.md` documents the (unofficial) Robinhood API: how to
discover endpoints, the full URL map, real captured response shapes, the options
schema, and the unified_transfers / two-ledger findings.

## Files not in git

`.env` (credentials), `robinhood.db`, and `output/` (exported workbooks) are
gitignored. `.env.example` is the committed template.
