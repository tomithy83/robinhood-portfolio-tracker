# Robinhood API Reference (via robin_stocks)

A working reference for the Robinhood HTTP API as accessed through the
`robin_stocks` Python library, focused on **how to discover more** rather than
just listing calls. Robinhood has **no official public API** — everything here
is the unofficial, reverse-engineered interface that `robin_stocks` wraps.
Treat it as living documentation: the empirical sections were captured from a
real authenticated session and are the most trustworthy part, because the
upstream docs are frequently stale (this project has already hit several
docs-vs-reality gaps, noted inline).

Captured: robin_stocks 3.4.0, Python 3.13, against a live account.

---

## 1. How to discover more API detail

This is the core skill. Four complementary techniques, in order of reliability:

### 1a. Enumerate the library surface (offline, always current for your install)
`robin_stocks.robinhood` is a package of submodules. List every public
function with its signature, grouped by the submodule that defines it:

```python
import robin_stocks.robinhood as rh
import inspect, types
for name in sorted(dir(rh)):
    obj = getattr(rh, name)
    if isinstance(obj, types.FunctionType) and not name.startswith("_"):
        print(obj.__module__.split(".")[-1], name, inspect.signature(obj))
```

Submodules: `authentication, account, orders, options, stocks, markets,
crypto, profiles, export, helper, urls, globals`.

### 1b. Read the URL map (the key to going beyond the wrapper)
Every wrapper ultimately builds a URL in `robin_stocks.robinhood.urls`. Dump it
to see the raw endpoints — this reveals the *actual* REST API, including
endpoints with no convenience wrapper:

```python
import robin_stocks.robinhood.urls as u, inspect
for n in sorted(dir(u)):
    o = getattr(u, n)
    if callable(o) and not n.startswith("_"):
        print(n, inspect.getsource(o))
```

See section 3 for the full captured URL map.

### 1c. Hit any endpoint directly with the request helpers
`robin_stocks` exposes generic authenticated request functions. Once logged in,
you can call *any* Robinhood URL, even ones without a wrapper:

```python
from robin_stocks.robinhood.helper import request_get
# dataType controls paging/filtering:
#   'regular'    -> raw response
#   'results'    -> response['results']
#   'pagination' -> response['results'] + follows 'next' across all pages
#   'indexzero'  -> response['results'][0]
data = request_get("https://api.robinhood.com/options/orders/",
                   dataType="pagination")
```
`request_post`, `request_delete`, `request_document` exist too. This is how you
prototype against an endpoint before writing a wrapper, and how you handle
paginated history (most `/orders/`, `/dividends/`, transfer endpoints paginate).

### 1d. Probe live response shapes (the ground truth)
The upstream docs rarely show real field names. Capture them from your own
account — keys, types, and a scrubbed sample — and keep the result (section 4):

```python
d = rh.get_all_option_orders()
print(type(d), len(d))
print(list(d[0].keys()))   # the real schema
```

### Discovery gotchas learned the hard way
- **Instrument URLs want lowercase UUIDs.** Orders return an `instrument` URL
  whose UUID is uppercase; `get_symbol_by_url(url)` returns `''` (a silent 404)
  unless the UUID is lowercased first.
- **`get_stock_historicals` is back-adjusted.** Pre-split dates are reported on
  the *current* post-split price basis (the series is smooth across a split).
  Reconstructed share counts must be on the same basis — see the splits note.
- **Splits are not reliably exposed.** `get_splits(sym)`, the instrument
  `splits` sub-resource, and `get_events(sym)` all returned empty for a known
  MSTY 1-for-5 reverse split. Corporate actions may require manual handling.
- **`psql`/empty-result truthiness** (legacy note): the old engine's bug.
- **Account type matters.** `get_wire_transfers` 404s on accounts with no wire
  feature; `get_open_option_positions` can be empty while order history is not.


---

## 2. Function surface (read / query functions by submodule)

Trading/order-placement functions (`order_*`, `cancel_*`) are omitted — this
project only reads. Full signatures are reproducible via technique 1a.

### account
- `build_holdings(with_dividends=False)` - current positions keyed by ticker (REAL current shares; the trustworthy anchor for split validation).
- `get_all_positions(info=None)` / `get_open_stock_positions(...)`
- `get_bank_transfers(direction=None)` - `direction='received'` for external-initiated ACH (payroll, autopay); default for RH-initiated.
- `get_card_transactions(cardType=None)` - debit card / spending (minerva host).
- `get_dividends()` / `get_dividends_by_instrument(...)` / `get_total_dividends()`
- `get_margin_interest()`, `get_interest_payments()` (cash sweep), `get_subscription_fees()` (Gold)
- `get_wire_transfers()` - 404s if the account has no wire feature.
- `get_stock_loan_payments()`, `get_day_trades()`, `get_documents()`
- `get_historical_portfolio(interval, span, bounds)` - portfolio value series.
- `load_phoenix_account()` - unified account snapshot (phoenix host).

### orders
- `get_all_stock_orders(info=None, account_number=None, start_date=None)` - full stock order history (paginated).
- `get_all_option_orders(info=None, account_number=None, start_date=None)` - full option order history (see section 4 for shape).
- `get_all_crypto_orders()`, `get_all_open_*_orders(...)`
- `get_stock_order_info(id)` / `get_option_order_info(id)` / `get_crypto_order_info(id)`
- `find_stock_orders(**filters)`

### options
- `get_open_option_positions(...)` - currently open contracts (can be empty).
- `get_all_option_positions(...)` - all option positions incl. closed.
- `get_aggregate_positions(...)` / `get_aggregate_open_positions(...)` - grouped by strategy/chain.
- `get_option_instrument_data_by_id(id)` - resolve a leg's option instrument.
- `get_chains(symbol)`, `find_tradable_options(...)`, `get_option_market_data_by_id(id)`
- `get_option_historicals(symbol, exp, strike, type, ...)`

### stocks
- `get_instruments_by_symbols(*syms)` / `get_instrument_by_url(url)` / `get_symbol_by_url(url)` - resolve instruments <-> tickers (lowercase the UUID!).
- `get_stock_historicals(symbols, interval, span, bounds)` - daily/intraday closes; BACK-ADJUSTED for splits.
- `get_quotes(...)`, `get_latest_price(...)`, `get_fundamentals(...)`
- `get_splits(symbol)` - often empty; do not rely on it.
- `get_events(symbol)` - option expirations etc.; did NOT contain equity splits in testing.
- `get_ratings`, `get_news`, `get_earnings`, `get_pricebook_by_symbol`

### profiles
- `load_account_profile()`, `load_portfolio_profile()`, `load_basic_profile()`, `load_investment_profile()`, `load_security_profile()`, `load_user_profile()`

### markets
- `get_markets()`, `get_market_hours(market, date)`, `get_top_movers()`, `get_top_100()`

### crypto (nummus host)
- `get_crypto_positions()`, `get_crypto_quote(sym)`, `get_crypto_historicals(sym, ...)`, `get_crypto_currency_pairs()`

### helper (the escape hatch)
- `request_get(url, dataType, payload, jsonify_data)`, `request_post`, `request_delete`, `request_document`

### authentication
- `login(username, password, expiresIn=86400, scope='internal', by_sms=True, store_session=True, mfa_code=None, pickle_path='', pickle_name='')`
- `logout()`


---

## 3. Endpoint URL map (hosts and raw endpoints)

From `robin_stocks.robinhood.urls`. Robinhood spans several hosts:
- `api.robinhood.com` - core (accounts, orders, instruments, dividends, options)
- `nummus.robinhood.com` - crypto
- `minerva.robinhood.com` - card / spending history
- `bonfire.robinhood.com` - unified transfers (`/paymenthub/unified_transfers/`)
- `phoenix.robinhood.com` - unified account snapshot (`/accounts/unified`)

Key endpoints (call with `request_get(url, dataType='pagination')`):

| Area | URL |
|------|-----|
| Accounts | `api/accounts/` |
| Portfolio | `api/portfolios/` ; historicals `api/portfolios/historicals/{acct}/` |
| Positions | `api/positions/` |
| Stock orders | `api/orders/` |
| Option orders | `api/options/orders/` |
| Option positions | `api/options/positions/` ; aggregate `api/options/aggregate_positions/` |
| Option instruments | `api/options/instruments/{id}/` |
| Option events | `api/options/events/` |
| Option chains | `api/options/chains/{id}/` |
| Instruments | `api/instruments/` ; splits `api/instruments/{id}/splits/` |
| Dividends | `api/dividends/` |
| ACH transfers | `api/ach/transfers/` ; received `api/ach/received/transfers/` |
| Wire transfers | `api/wire/transfers` (404 if unavailable) |
| Card transactions | `minerva/history/transactions/` |
| Margin interest | `api/cash_journal/margin_interest_charges/` |
| Interest (sweep) | `api/accounts/sweeps/` |
| Stock loan pmts | `api/accounts/stock_loan_payments/` |
| Subscription fees | `api/subscription/subscription_fees/` |
| Unified transfers | `bonfire/paymenthub/unified_transfers/` |
| Historicals | `api/quotes/historicals/` (back-adjusted) |
| Quotes | `api/quotes/` ; marketdata `api/marketdata/quotes/{id}/` |
| Instrument->chain | `api/instruments/` -> field `tradable_chain_id` |
| Login | `api/oauth2/token/` |


---

## 4. Empirical response shapes (captured live)

Real keys and a scrubbed sample per endpoint (account numbers and UUIDs redacted). This is ground truth for field names.

```
=== get_all_option_orders ===
  list[250]
  keys: ['account_number', 'account_number_rhs', 'cancel_url', 'canceled_quantity', 'created_at', 'direction', 'id', 'legs', 'pending_quantity', 'premium', 'processed_premium', 'processed_premium_direction', 'market_hours', 'net_amount', 'net_amount_direction', 'price', 'processed_quantity', 'quantity', 'ref_id', 'approval_id', 'regulatory_fees', 'contract_fees', 'pro_trader_fees', 'gold_savings', 'state', 'time_in_force', 'trigger', 'type', 'updated_at', 'chain_id', 'chain_symbol', 'trade_value_multiplier', 'response_category', 'opening_strategy', 'closing_strategy', 'stop_price', 'form_source', 'client_bid_at_submission', 'client_ask_at_submission', 'client_time_at_submission', 'average_net_premium_paid', 'estimated_total_net_amount', 'estimated_total_net_amount_direction', 'estimated_total_net_amount_v2', 'estimated_total_net_amount_direction_v2', 'is_replaceable', 'strategy', 'derived_state', 'sales_taxes', 'placed_agent', 'agent_display_name', 'agent_id', 'canceled_agent_name', 'canceled_agent_id']
  sample: {"account_number": "<acct>", "account_number_rhs": "<acct>", "cancel_url": null, "canceled_quantity": "2.00000", "created_at": "2026-10-22T18:24:37.582048Z", "direction": "credit", "id": "<uuid>", "legs": [{"executions": [], "id": "<uuid>", "option": "https://api.robinhood.com/options/instruments/<uuid>/", "position_effect": "open", "ratio_quantity": 1, "side": "buy", "expiration_date": "2026-11-20", "strike_price": "113.0000", "option_type": "put", "long_strategy_code": "<uuid>_L1", "short_strategy_code": "<uuid>_S1"}, {"executions": [], "id": "<uuid>", "option": "https://api.robinhood.com/options/instruments/<uuid>/", "position_effect": "open", "ratio_quantity": 1, "side": "sell", "expiration_date": "2026-11-20", "strike_price": "114.0000", "option_type": "put", "long_strategy_code": "<uuid>_L1", "short_strategy_code": "<uuid>_S1"}], "pending_quantity": "0.00000", "premium": "30.000000

=== get_open_option_positions ===
  list[0]

=== get_aggregate_positions ===
  list[7]
  keys: ['id', 'chain', 'account', 'account_number', 'account_number_rhs', 'symbol', 'strategy', 'average_open_price', 'legs', 'quantity', 'intraday_average_open_price', 'intraday_quantity', 'direction', 'intraday_direction', 'trade_value_multiplier', 'created_at', 'updated_at', 'strategy_code', 'clearing_running_quantity', 'clearing_cost_basis', 'clearing_intraday_running_quantity', 'clearing_intraday_cost_basis', 'clearing_direction', 'clearing_intraday_direction', 'underlying_type', 'detail_display_name']
  sample: {"id": "<uuid>", "chain": "https://api.robinhood.com/options/chains/<uuid>/", "account": "https://api.robinhood.com/accounts/<acct>/", "account_number": "<acct>", "account_number_rhs": "<acct>", "symbol": "SPY", "strategy": "long_put", "average_open_price": "0.0000", "legs": [{"id": "<uuid>", "ratio_quantity": 1, "position": "https://api.robinhood.com/options/positions/<uuid>/", "position_type": "long", "option": "https://api.robinhood.com/options/instruments/<uuid>/", "option_id": "<uuid>", "expiration_date": "2026-03-27", "strike_price": "617.0000", "option_type": "put", "settle_on_open": false, "clearing_cost_basis_in_strategy": "0.0000", "clearing_direction": "debit"}], "quantity": "0.0000", "intraday_average_open_price": "0.0000", "intraday_quantity": "0", "direction": "debit", "intraday_direction": "debit", "trade_value_multiplier": "100.0000", "created_at": "2026-03-20T13:30:16.36

=== get_all_stock_orders[0] ===
  list[342]
  keys: ['id', 'ref_id', 'approval_id', 'account', 'user_uuid', 'position', 'instrument', 'cumulative_quantity', 'average_price', 'fees', 'sec_fees', 'taf_fees', 'cat_fees', 'sales_taxes', 'state', 'derived_state', 'pending_cancel_open_agent', 'cancel', 'price', 'stop_price', 'quantity', 'last_transaction_at', 'last_update_version', 'executions', 'extended_hours', 'market_hours', 'override_dtbp_checks', 'override_day_trade_checks', 'last_trail_price_source', 'last_trail_price', 'last_trail_price_updated_at', 'dollar_based_amount', 'requested_notional_amount', 'drip_dividend_id', 'total_notional', 'executed_notional', 'investment_schedule_id', 'response_category', 'ipo_access_cancellation_reason', 'is_ipo_access_price_finalized', 'is_visible_to_user', 'is_primary_account', 'preset_percent_limit', 'order_form_version', 'is_editable', 'root_advanced_order_id', 'root_advanced_order_contingency_type', 'parent_advanced_order_id', 'parent_advanced_order_contingency_type', 'type', 'side', 'order_form_type', 'is_ipo_access_order', 'trigger', 'instrument_id', 'created_at', 'has_ipo_access_custom_price_limit', 'ipo_access_lower_collared_price', 'ipo_access_upper_collared_price', 'ipo_access_upper_price', 'ipo_access_lower_price', 'ipo_access_requested_quantity', 'url', 'time_in_force', 'reject_reason', 'updated_at', 'stop_triggered_at', 'placed_agent', 'position_effect', 'replaces', 'user_cancel_request_state', 'tax_lot_selection_type', 'agent_display_name', 'agent_id', 'canceled_agent_name', 'canceled_agent_id', 'account_number_rhs']
  sample: {"id": "<uuid>", "ref_id": "<uuid>", "approval_id": null, "account": "https://api.robinhood.com/accounts/<acct>/", "user_uuid": "<uuid>", "position": "https://api.robinhood.com/positions/<acct>/<uuid>/", "instrument": "https://api.robinhood.com/instruments/<uuid>/", "cumulative_quantity": "1.00000000", "average_price": "135.70000000", "fees": "0", "sec_fees": "0.00", "taf_fees": "0.00", "cat_fees": "0.00", "sales_taxes": [], "state": "filled", "derived_state": "filled", "pending_cancel_open_agent": null, "cancel": null, "price": "138.42000000", "stop_price": null, "quantity": "1.00000000", "last_transaction_at": "2026-10-30T21:05:05.758000Z", "last_update_version": 2, "executions": [{"price": "135.70000000", "quantity": "1.00000000", "rounded_notional": "135.70000000", "settlement_date": "2026-11-02", "timestamp": "2026-10-30T21:05:05.758000Z", "id": "<uuid>", "ipo_access_execution_rank"

=== get_dividends[0] ===
  list[331]
  keys: ['id', 'url', 'account', 'account_number_rhs', 'instrument', 'amount', 'gross_amount', 'fee', 'rate', 'position', 'withholding', 'record_date', 'payable_date', 'paid_at', 'state', 'cash_dividend_id', 'drip_enabled', 'fx_order_id', 'nra_withholding', 'is_primary_account', 'related_adjustments', 'is_early_dividend', 'days_early', 'ex_dividend_date', 'active_instrument_id']
  sample: {"id": "<uuid>", "url": "https://api.robinhood.com/dividends/<uuid>/", "account": "https://api.robinhood.com/accounts/<acct>/", "account_number_rhs": "<acct>", "instrument": "https://api.robinhood.com/instruments/<uuid>/", "amount": "70.25", "gross_amount": "70.25", "fee": "0.00", "rate": "0.<acct>", "position": "431.0000", "withholding": "0.00", "record_date": "2026-10-30", "payable_date": "2026-10-30", "paid_at": null, "state": "pending", "cash_dividend_id": "<uuid>", "drip_enabled": false, "fx_order_id": null, "nra_withholding": "0", "is_primary_account": true, "related_adjustments": [], "is_early_dividend": false, "days_early": null, "ex_dividend_date": "2026-10-29", "active_instrument_id": null}

=== get_events(MSTY) ===
  list[0]
```


---

## 5. Options schema notes (for the upcoming harvester)

From the live `get_all_option_orders` capture (250 orders on the test account):

An **option order** is multi-leg. Top-level fields that matter:
- `direction` - `debit` (you paid net premium) or `credit` (you received it).
- `premium`, `processed_premium`, `net_amount` + `net_amount_direction` - dollar
  amounts; `net_amount` with its direction is the realized cash effect.
- `price`, `processed_quantity`, `quantity`, `canceled_quantity`
- `state` (`filled`, `cancelled`, ...), `created_at`, `updated_at`
- `chain_symbol` - the UNDERLYING ticker (e.g. `SPY`) - no instrument-URL
  resolution needed, unlike stock orders.
- `opening_strategy` / `closing_strategy` (e.g. `long_put`, `put_credit_spread`)
- `trade_value_multiplier` (usually 100 - contract size)
- `legs[]` - each leg has: `side` (`buy`/`sell`), `position_effect`
  (`open`/`close`), `option_type` (`put`/`call`), `strike_price`,
  `expiration_date`, `ratio_quantity`, and `option` (an option-instrument URL).

**Signed-cash convention to mirror the stock rule:**
- `direction == 'debit'`  -> cash OUT -> amount negative (premium paid).
- `direction == 'credit'` -> cash IN  -> amount positive (premium received).
Use `net_amount` * sign(`net_amount_direction`) for the realized figure, and
only count `state == 'filled'` orders.

**Aggregate positions** (`get_aggregate_positions`, 7 on the test account)
describe current open strategies grouped by `chain`/`strategy` (e.g. a SPY
`long_put`), with `legs[]` carrying `strike_price`, `expiration_date`,
`option_type`, and `clearing_direction`. `get_open_option_positions` may be
empty even when aggregates exist.

**Expirations** show up in `get_events(symbol)` as `type: expiration` records
(`event_date`, `quantity`, `underlying_price`), NOT in the orders feed.

**Implication for valuation:** options are excluded from `gross_value` by design
(stocks/funds only). An options table would summarize premium flow (debit/credit
per underlying) rather than mark-to-market position value.

---

## 6. Project-specific mapping

How `rhtracker` currently uses these endpoints (see `src/rhtracker/sources/robinhood.py`):

| rhtracker need | endpoint used |
|----------------|---------------|
| stock buys/sells | `get_all_stock_orders` (filled only; symbol via `get_symbol_by_url`, lowercased) |
| dividends | `get_dividends` (symbol-resolved; `state=pending` rows exist) |
| deposits/withdrawals | `get_bank_transfers()` and `get_bank_transfers(direction='received')` |
| expenses | received transfers + `get_card_transactions` |
| margin interest | `get_margin_interest` |
| gold fee | `get_subscription_fees` |
| cash sweep interest | `get_interest_payments` |
| historical prices | `get_stock_historicals` (back-adjusted) |
| current shares (split validation) | `build_holdings` |
| NOT YET HARVESTED | `get_all_option_orders` (the next feature) |

Splits are handled manually in `src/rhtracker/splits.py` because the API does
not expose them reliably.


---

## 7. Cash-completeness audit & the unified_transfers gotcha

**The single biggest discovery of this project.** Reconstructing the cash /
margin balance by summing all transaction feeds came up ~$17k short of the real
`portfolio_cash`. Root cause: Robinhood splits money across TWO ledgers — the
brokerage (`rhs_account`) and the Robinhood banking/checking side
(`rhy_banking_checking`) — and transfers between them appear in NO legacy feed
(not orders, dividends, ACH, card, or interest). They only surface in:

    https://bonfire.robinhood.com/paymenthub/unified_transfers/   (134 rows)

### unified_transfers structure
`transfer_type` is one of:
- `originated_ach`     — duplicates `ach/transfers` (RH-initiated deposits/withdrawals)
- `non_originated_ach` — duplicates `ach/received/transfers/` (payroll in, autopay out)
- `internal`           — **brokerage <-> RHY banking, and card cashback. UNIQUE to this feed.**

To avoid double-counting, ingest ONLY `transfer_type == 'internal'` from here;
keep the ACH types coming from the dedicated wrappers.

### Classifying `internal` rows (direction is NOT reliable — use account types)
All internal rows report `direction = push`, so direction cannot classify them.
Use the account-type fields instead, with brokerage = `rhs_account`:
- `originating_account_type == 'rhs_account'` and receiver is not  -> cash OUT
  (e.g. `-> rhy_banking_checking`): a withdrawal to RH checking.
- `receiving_account_type == 'rhs_account'` and originator is not   -> cash IN
  (e.g. `rct_firm_account -> rhs_account`, desc `8493`): credit-card cashback.
- both/neither brokerage -> no brokerage cash effect; skip.

On the test account: 3 withdrawals to checking (-$13,513) + ~28 cashback
credits (+$497). Adding these closed the gap from ~$17k to ~$370 (0.9%), the
residual being `unsettled_debit` (pending trades) — i.e. the ledger is complete.

### Completeness audit method (repeatable)
Hit every cash-bearing endpoint and check for non-empty feeds you are not
harvesting. Result on the test account:

| endpoint | rows | status |
|----------|------|--------|
| orders, options/orders, dividends | 342 / 250 / 331 | captured |
| ach/transfers, ach/received | 10 / 90 | captured |
| margin_interest, sweeps(interest), subscription_fees | 11 / 8 / 1 | captured (sweeps all pre-window) |
| unified_transfers (internal) | 134 (33 internal) | **now captured** |
| wire/transfers | envelope only (null) | empty |
| stock_loan_payments, card(minerva) | 0 / 0 | empty |
| options/events | 5 | zero-cash expirations |
| referral | 1 | 2020 free share (COTY), no cash |

The strongest completeness check is not enumerating feeds but the residual:
`sum(all stored transaction amounts)` vs the real `portfolio_cash` from
`load_account_profile().margin_balances`. A small residual (here $370 /0.9%)
means the ledger is effectively complete; a large one means a feed is missing.

Two distinct "cash" numbers to keep straight:
- `account.cash` (−$45,853) includes unsettled funds/holds.
- `margin_balances.portfolio_cash` (−$41,544) = actual MARGIN BORROWED; this is
  what the reconstructed "Margin Debt" should reconcile to.
