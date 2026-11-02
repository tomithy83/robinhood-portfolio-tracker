# TODO — deferred workbook features

Tracked follow-ups, deferred while we build phases 1-3 (Overall Summary, Expense
split, Dividend Payments detail) and then the Tracking margin calibration.

## 1. Option Details tab
A detailed tab (companion to the existing "Options" summary) listing every
option ORDER, not just per-underlying premium totals.

Source: get_all_option_orders (filled only, in the backfill window). Shape is
documented in docs/robinhood-api.md section 5.

Proposed columns (one row per order, or per leg if multi-leg):
- Date, Underlying (chain_symbol), Direction (debit/credit),
  Strategy (opening_strategy/closing_strategy), Option Type (put/call),
  Side (buy/sell), Position Effect (open/close), Strike, Expiration,
  Quantity, Premium (net_amount), Net Direction, State.

Open questions:
- One row per order vs. one row per leg (multi-leg spreads have 2+ legs).
- Whether to resolve each leg's option-instrument URL for extra detail
  (get_option_instrument_data_by_id) or keep what's already on the order.

## 2. Holdings mega-tab (merge Dividends + Stock Trades + Positions)
A single per-ticker holdings tab with the full column set the user specified:

  Ticker, Shares, Average Purchase Price, Dividend Payout Frequency, Account,
  Sector, Maint Ratio, Name, Price, Market Value, Cost Basis, Day's Change $,
  Day's Change %, Growth in $, Growth in %, 1 yr Trend, Total Dividends,
  Total Return, Maint Requirement, % of Total Maint Req, % of Portfolio

Data-source notes (needs a probe before promising each column):
- Shares / Cost Basis / Avg Purchase Price -> from trade log + build_holdings
  (build_holdings gives average_buy_price, quantity, equity, price).
- Name / Price / Market Value / Day's Change -> build_holdings + quotes.
- Maint Ratio / Maint Requirement -> instrument record (maintenance_ratio),
  times market value; blended rate feeds the Overall Summary too.
- Sector -> get_fundamentals(symbol) (sector/industry fields) — verify.
- Dividend Payout Frequency -> NOT in API cleanly; likely a small manual table
  (like splits.py), or infer from dividend cadence in the ledger.
- 1 yr Trend -> get_stock_historicals (sparkline/▲▼ or % change) — verify.
- Total Dividends -> sum from the ledger per ticker.
- Total Return -> (market value + total dividends - cost basis) / cost basis.
- % of Portfolio / % of Total Maint Req -> computed from the set.

This is the largest tab; do the column-availability probe first, then build.
