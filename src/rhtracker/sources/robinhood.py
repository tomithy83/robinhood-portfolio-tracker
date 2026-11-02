"""RobinhoodSource — the only module that talks to the Robinhood API.

Ports ``pull.py`` (interactive auth reusing the ``~/.tokens`` session pickle and
the harvest plan) and ``normalize.py`` (the per-type normalizers with their sign
conventions). Normalization is private to this module: the harvest plan runs the
per-type normalizers and returns already-normalized :class:`rhtracker.model.Transaction`
objects, so no raw API shape escapes.

``robin_stocks`` is imported lazily inside the methods that need it, so importing
this module never requires the dependency to be installed — which keeps the
source unit-testable (its private normalizers) with no live API.

Sign conventions (preserved verbatim from ``normalize.py``):

====================  =================  ==================
transaction           amount             quantity
====================  =================  ==================
buy                   negative (out)     positive (in)
sell                  positive (in)      negative (out)
dividend / interest   positive           --
/ deposit / credit
expense / withdrawal  negative           --
/ margin_interest
/ fee
====================  =================  ==================

Amounts from the API may be a flat value or a nested dict
``{"amount": ..., "currency_code": ...}``; :func:`_amount` handles both. The
dedup identity is a SHA256 hash over ``date|type|asset|amount|reference_id``.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import date

from rhtracker import settings
from rhtracker.model import PortfolioSnapshot, Price, Transaction

log = logging.getLogger("rhtracker.sources.robinhood")

PICKLE_DIR = os.path.expanduser("~/.tokens")


# --------------------------------------------------------------------------
# Normalization helpers (private to this module)
# --------------------------------------------------------------------------
def _compute_hash(txn_date, txn_type, asset, amount, reference_id) -> str:
    raw = f"{txn_date}|{txn_type}|{asset}|{amount}|{reference_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _amount(raw) -> float:
    """Robinhood amounts are sometimes a flat string/number, sometimes a dict
    ``{'amount': '546.42', 'currency_code': 'USD'}``. Handle both."""
    if isinstance(raw, dict):
        return float(raw.get("amount", 0) or 0)
    return float(raw or 0)


def _first_date(*candidates):
    """Return the first candidate that parses to an ISO date (first 10 chars)."""
    for c in candidates:
        if not c:
            continue
        s = str(c)[:10]
        try:
            return date.fromisoformat(s)
        except ValueError:
            continue
    return None


def _ticker_from_instrument(url):
    """Last-resort fallback: pull the uuid segment out of an instrument URL.
    Callers should prefer an explicit ``symbol``/``ticker`` field."""
    if not url:
        return None
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else None


# --------------------------------------------------------------------------
# Per-type normalizers — each returns a model.Transaction, or None to skip
# --------------------------------------------------------------------------
def _normalize_stock_order(order):
    try:
        state = order.get("state", "unknown")
        # Only filled orders move shares/cash.
        if state != "filled":
            return None

        side = order.get("side", "")  # 'buy' or 'sell'
        ticker = (
            order.get("symbol")
            or order.get("ticker")
            or _ticker_from_instrument(order.get("instrument"))
            or "UNKNOWN"
        )
        qty = float(order.get("cumulative_quantity") or order.get("quantity") or 0)
        price = float(order.get("average_price") or 0)
        gross = qty * price

        # Signed cash + signed share delta
        if side == "buy":
            amount = -gross          # cash out
            share_delta = qty        # shares in
        elif side == "sell":
            amount = gross           # cash in
            share_delta = -qty       # shares out
        else:
            return None

        txn_date = _first_date(order.get("last_transaction_at"), order.get("created_at"))
        if not txn_date:
            return None
        ref_id = order.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, side, ticker, amount, ref_id),
            transaction_date=txn_date,
            transaction_type=side,  # 'buy' / 'sell'
            asset=ticker,
            amount=amount,
            quantity=share_delta,   # SIGNED share delta for reconstruction
            price=price,
            status=state,
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"stock order normalize failed: {e}")
        return None


def _normalize_dividend(dividend):
    try:
        state = dividend.get("state", "")
        if state in ("reversed", "voided"):
            return None
        amount = _amount(dividend.get("amount", 0))
        txn_date = _first_date(dividend.get("paid_at"), dividend.get("payable_date"),
                               dividend.get("record_date"))
        if not txn_date:
            return None
        ticker = dividend.get("symbol") or _ticker_from_instrument(dividend.get("instrument")) or "UNKNOWN"
        ref_id = dividend.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, "dividend", ticker, amount, ref_id),
            transaction_date=txn_date,
            transaction_type="dividend",
            asset=ticker,
            amount=abs(amount),     # money in
            quantity=None,
            price=None,
            status=state or "paid",
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"dividend normalize failed: {e}")
        return None


def _normalize_bank_transfer(transfer):
    try:
        amount = _amount(transfer.get("amount", 0))
        direction = transfer.get("direction", "")
        if direction == "deposit":
            txn_type, signed = "deposit", abs(amount)
        elif direction == "withdraw":
            txn_type, signed = "withdrawal", -abs(amount)
        else:
            log.warning(f"unknown bank transfer direction '{direction}' — skipping")
            return None
        txn_date = _first_date(transfer.get("created_at"))
        if not txn_date:
            return None
        ref_id = transfer.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, txn_type, "BANK", amount, ref_id),
            transaction_date=txn_date,
            transaction_type=txn_type,
            asset="BANK_TRANSFER",
            amount=signed,
            quantity=None,
            price=None,
            status=transfer.get("state", "unknown"),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"bank transfer normalize failed: {e}")
        return None


def _normalize_received_transfer(transfer):
    try:
        amount = _amount(transfer.get("amount", {}))
        direction = transfer.get("direction", "")
        originator = (transfer.get("originator_name") or transfer.get("description")
                      or "UNKNOWN")
        o = originator.lower()
        if direction == "credit":
            txn_type, signed = "direct_deposit", abs(amount)
            if "payroll" in o:
                txn_type = "payroll_deposit"
            elif "refund" in o:
                txn_type = "refund"
            # User-configured payee rules may override the generic label.
            txn_type = settings.classify("received", "credit", originator) or txn_type
        elif direction == "debit":
            txn_type, signed = "bill_payment", -abs(amount)
            # Payee-specific labels (auto loan, student loan, ...) come from
            # settings.json so no personal payee names live in the source.
            txn_type = settings.classify("received", "debit", originator) or txn_type
        else:
            log.warning(f"unknown received direction '{direction}' ({originator}) — skipping")
            return None
        txn_date = _first_date(transfer.get("created_at"), transfer.get("settled_at"),
                               transfer.get("settlement_date"))
        if not txn_date:
            return None
        ref_id = transfer.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, txn_type, originator, amount, ref_id),
            transaction_date=txn_date,
            transaction_type=txn_type,
            asset=originator[:50],
            amount=signed,
            quantity=None,
            price=None,
            status=transfer.get("state", "completed"),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"received transfer normalize failed: {e}")
        return None


def _normalize_card_transaction(ct):
    try:
        amount = _amount(ct.get("amount", 0))
        description = (ct.get("description") or ct.get("merchant_description")
                       or ct.get("nickname") or ct.get("merchant") or "CARD_TRANSACTION")
        direction = ct.get("direction", "") or ct.get("type", "")
        txn_date = _first_date(ct.get("created_at"), ct.get("transaction_date"),
                               ct.get("settled_at"))
        if not txn_date:
            return None
        d = description.lower()
        if direction == "credit":
            txn_type, signed = "direct_deposit", abs(amount)
            if "cashback" in d or "reward" in d:
                txn_type = "cashback"
            elif "refund" in d:
                txn_type = "refund"
            elif "interest" in d:
                txn_type = "interest_payment"
            txn_type = settings.classify("card", "credit", description) or txn_type
        elif direction == "debit":
            signed = -abs(amount)
            if "atm" in d:
                txn_type = "atm_withdrawal"
            elif "payment" in d:
                txn_type = "bill_payment"
            else:
                txn_type = "card_purchase"
            # User rules can refine a debit into a more specific payee label.
            txn_type = settings.classify("card", "debit", description) or txn_type
        else:
            log.warning(f"unknown card direction '{direction}' ({description}) — default card_purchase")
            txn_type, signed = "card_purchase", -abs(amount)
        ref_id = ct.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, txn_type, description, amount, ref_id),
            transaction_date=txn_date,
            transaction_type=txn_type,
            asset=description[:50],
            amount=signed,
            quantity=None,
            price=None,
            status=ct.get("state", "completed"),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"card transaction normalize failed: {e}")
        return None


def _normalize_margin_interest(mi):
    try:
        amount = _amount(mi.get("amount", 0))
        txn_date = _first_date(mi.get("created_at"), mi.get("charged_at"))
        if not txn_date:
            return None
        ref_id = mi.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, "margin_interest", "MARGIN", amount, ref_id),
            transaction_date=txn_date,
            transaction_type="margin_interest",
            asset="MARGIN",
            amount=-abs(amount),
            quantity=None,
            price=None,
            status=mi.get("state", "completed"),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"margin interest normalize failed: {e}")
        return None


def _normalize_interest_payment(ip):
    try:
        amount = _amount(ip.get("amount", 0))
        txn_date = _first_date(ip.get("pay_date"), ip.get("paid_at"), ip.get("created_at"))
        if not txn_date:
            return None
        ref_id = ip.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, "interest_payment", "CASH_SWEEP", amount, ref_id),
            transaction_date=txn_date,
            transaction_type="interest_payment",
            asset="CASH_SWEEP",
            amount=abs(amount),
            quantity=None,
            price=None,
            status=ip.get("state", "completed"),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"interest payment normalize failed: {e}")
        return None


def _normalize_subscription_fee(sf):
    try:
        amount = _amount(sf.get("amount", 0))
        txn_date = _first_date(sf.get("created_at"), sf.get("charged_at"))
        if not txn_date:
            return None
        ref_id = sf.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, "subscription_fee", "RH_GOLD", amount, ref_id),
            transaction_date=txn_date,
            transaction_type="subscription_fee",
            asset="RH_GOLD",
            amount=-abs(amount),
            quantity=None,
            price=None,
            status=sf.get("state", "completed"),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"subscription fee normalize failed: {e}")
        return None


def _normalize_wire_transfer(wt):
    try:
        amount = _amount(wt.get("amount", 0))
        direction = wt.get("direction", "")
        if direction == "incoming":
            txn_type, signed = "wire_deposit", abs(amount)
        elif direction == "outgoing":
            txn_type, signed = "wire_withdrawal", -abs(amount)
        else:
            log.warning(f"unknown wire direction '{direction}' — skipping")
            return None
        txn_date = _first_date(wt.get("created_at"))
        if not txn_date:
            return None
        ref_id = wt.get("id", "")
        return Transaction(
            hash=_compute_hash(txn_date, txn_type, "WIRE", amount, ref_id),
            transaction_date=txn_date,
            transaction_type=txn_type,
            asset="WIRE_TRANSFER",
            amount=signed,
            quantity=None,
            price=None,
            status=wt.get("state", "completed"),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f"wire transfer normalize failed: {e}")
        return None


def _normalize_internal_transfer(t):
    """Normalize a unified_transfers ``internal`` row.

    These move cash between the brokerage (rhs_account) and the Robinhood
    banking/checking side (rhy_banking_checking) or reflect card cashback
    landing in the brokerage. They appear in NO other feed, so without them
    the cash/margin reconstruction is understated.

    Classification uses the account-type fields (reliable), NOT direction:
      * brokerage (rhs_account) is the ORIGINATOR -> cash OUT (rhy_transfer).
      * brokerage (rhs_account) is the RECEIVER   -> cash IN  (cashback).
    Only completed transfers that actually touch the brokerage count.
    """
    try:
        if t.get('state') != 'completed':
            return None
        orig = t.get('originating_account_type') or ''
        recv = t.get('receiving_account_type') or ''
        amount = _amount(t.get('amount', 0))
        if amount == 0:
            return None
        BROK = 'rhs_account'
        if orig == BROK and recv != BROK:
            # cash leaving the brokerage (e.g. -> rhy_banking_checking)
            txn_type, signed, label = 'rhy_transfer', -abs(amount), (recv or 'rhy_banking')
        elif recv == BROK and orig != BROK:
            # cash entering the brokerage (card cashback, rhy top-up)
            txn_type, signed, label = 'cashback', abs(amount), (orig or 'internal_credit')
        else:
            # both sides brokerage or neither -> no net brokerage cash effect
            return None
        txn_date = _first_date(t.get('created_at'), t.get('record_date'), t.get('completed_at'))
        if not txn_date:
            return None
        ref_id = t.get('id', '') or t.get('ref_id', '')
        return Transaction(
            hash=_compute_hash(txn_date, txn_type, label, signed, ref_id),
            transaction_date=txn_date,
            transaction_type=txn_type,
            asset=label[:50],
            amount=signed,
            quantity=None,
            price=None,
            status=t.get('state', 'completed'),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f'internal transfer normalize failed: {e}')
        return None


def _normalize_option_order(order):
    """Normalize a filled option order into a Transaction.

    Shape: multi-leg, but the realized cash figure is ``net_amount`` with
    ``net_amount_direction`` giving the sign.
    direction/net_amount_direction: ``debit`` = premium paid (cash out),
    ``credit`` = premium received (cash in). ``chain_symbol`` is the clean
    underlying ticker (no instrument-URL resolution needed). Only filled
    orders move cash.
    """
    try:
        if order.get('state') != 'filled':
            return None
        direction = order.get('net_amount_direction') or order.get('direction') or ''
        net = _amount(order.get('net_amount', 0))
        if direction == 'debit':
            txn_type, signed = 'option_buy', -abs(net)
        elif direction == 'credit':
            txn_type, signed = 'option_sell', abs(net)
        else:
            log.warning(f"unknown option direction '{direction}' — skipping")
            return None
        symbol = order.get('chain_symbol') or 'OPTION'
        txn_date = _first_date(order.get('created_at'), order.get('updated_at'))
        if not txn_date:
            return None
        ref_id = order.get('id', '')
        return Transaction(
            hash=_compute_hash(txn_date, txn_type, symbol, signed, ref_id),
            transaction_date=txn_date,
            transaction_type=txn_type,
            asset=symbol,
            amount=signed,
            quantity=None,
            price=None,
            status=order.get('state', 'filled'),
            reference_id=ref_id,
        )
    except Exception as e:
        log.warning(f'option order normalize failed: {e}')
        return None


# (api_method_name, normalizer, event_type, call_kwargs) — ported from pull.py
_HARVEST_PLAN = [
    ("get_all_stock_orders",  _normalize_stock_order,       "stock_orders",       {}),
    ("get_dividends",         _normalize_dividend,          "dividends",          {}),
    ("get_bank_transfers",    _normalize_bank_transfer,     "bank_transfers",     {}),
    ("get_bank_transfers",    _normalize_received_transfer, "received_transfers", {"direction": "received"}),
    ("get_card_transactions", _normalize_card_transaction,  "card_transactions",  {}),
    ("get_margin_interest",   _normalize_margin_interest,   "margin_interest",    {}),
    ("get_interest_payments", _normalize_interest_payment,  "interest_payments",  {}),
    ("get_subscription_fees", _normalize_subscription_fee,  "subscription_fees",  {}),
    ("get_wire_transfers",    _normalize_wire_transfer,     "wire_transfers",     {}),
    ("get_all_option_orders", _normalize_option_order,     "option_orders",      {}),
]


class RobinhoodSource:
    """Concrete :class:`~rhtracker.sources.base.Source` backed by the Robinhood API."""

    def __init__(self, pickle_dir: str = PICKLE_DIR):
        self._pickle_dir = pickle_dir
        self._rh = None  # the authenticated robin_stocks.robinhood module

    # ------------------------------------------------------------------
    # Source protocol
    # ------------------------------------------------------------------
    def authenticate(self) -> None:
        """Interactive login. Reuses the ``~/.tokens`` pickle if valid, else prompts.

        Credentials come from the environment
        (``ROBINHOOD_USERNAME`` / ``ROBINHOOD_PASSWORD``) or an interactive
        prompt. MFA is handled interactively by ``robin_stocks`` when needed.
        """
        # Load credentials from the project .env (repo root) if present, so
        # ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD can live there instead of
        # the shell environment. dotenv is optional; fall back to real env.
        try:
            from pathlib import Path as _Path
            from dotenv import load_dotenv as _load_dotenv
            _load_dotenv(dotenv_path=_Path(__file__).resolve().parents[3] / ".env")
        except ImportError:
            pass

        try:
            import robin_stocks.robinhood as rh
        except ImportError:
            log.error("robin_stocks not installed. Run: pip install robin-stocks")
            raise SystemExit(1)

        os.makedirs(self._pickle_dir, exist_ok=True)
        username = os.getenv("ROBINHOOD_USERNAME")
        password = os.getenv("ROBINHOOD_PASSWORD")

        # robin_stocks.login prompts for anything missing (incl. MFA code) and
        # stores a session pickle so later runs are non-interactive until expiry.
        login = rh.login(
            username=username,
            password=password,
            expiresIn=86400,
            store_session=True,
            pickle_path=self._pickle_dir,
        )
        if not login:
            log.error("Login failed.")
            raise SystemExit(1)
        log.info("Authenticated with Robinhood.")
        self._rh = rh

    def fetch_transactions(self, since: date) -> list[Transaction]:
        """Run the harvest plan, normalize each raw record, and return the
        transactions on or after ``since`` (already normalized to model types)."""
        rh = self._require_rh()
        out: list[Transaction] = []
        for method_name, normalizer, event_type, kwargs in _HARVEST_PLAN:
            raw = self._call(rh, method_name, kwargs)
            kept = 0
            for item in raw:
                txn = normalizer(item)
                if txn is None:
                    continue
                if txn.transaction_date < since:
                    continue
                out.append(txn)
                kept += 1
            log.info(f"{event_type}: {len(raw)} raw, {kept} kept")
        # Unified transfers: capture the 'internal' rows (brokerage <-> RHY
        # banking, and card cashback) that no other feed reports. The ACH
        # rows here duplicate get_bank_transfers, so we take internal only.
        try:
            from robin_stocks.robinhood.helper import request_get
            unified = request_get(
                'https://bonfire.robinhood.com/paymenthub/unified_transfers/',
                dataType='pagination') or []
            kept = 0
            for t in unified:
                if t.get('transfer_type') != 'internal':
                    continue
                txn = _normalize_internal_transfer(t)
                if txn is None or txn.transaction_date < since:
                    continue
                out.append(txn)
                kept += 1
            log.info(f'unified_transfers(internal): {kept} kept')
        except Exception as e:
            log.error(f'unified_transfers fetch failed: {e}')

        out = self._resolve_symbols(rh, out)
        return out

    def fetch_prices(self, tickers: list[str], dates: list[date]) -> list[Price]:
        """For each ticker, fetch daily closes and select, for each requested
        date, the last close on or before it. Returns a flat list of prices."""
        rh = self._require_rh()
        if not tickers or not dates:
            return []

        prices: list[Price] = []
        for ticker in tickers:
            try:
                hist = rh.get_stock_historicals(
                    ticker, interval="day", span="year", bounds="regular"
                )
            except Exception as e:
                log.warning(f"historicals failed for {ticker}: {e}")
                continue
            if not hist:
                continue
            # hist is a list of {begins_at, close_price, ...}; live data can
            # include None / non-dict entries, so guard each point.
            series = []
            for pt in hist:
                if not isinstance(pt, dict):
                    continue
                d = (pt.get("begins_at") or "")[:10]
                close = pt.get("close_price")
                if d and close:
                    series.append((d, float(close)))
            series.sort()
            if not series:
                continue
            # for each requested date, pick the last close on or before it
            for target in dates:
                target_iso = target.isoformat()
                chosen = None
                for d, close in series:
                    if d <= target_iso:
                        chosen = close
                    else:
                        break
                if chosen is not None:
                    prices.append(Price(ticker=ticker, price_date=target, close=chosen))
        return prices

    def fetch_portfolio_snapshot(self) -> PortfolioSnapshot | None:
        """Capture the broker's real account + portfolio profile (as-of-now)."""
        from datetime import datetime, timezone
        rh = self._require_rh()
        def f(d, k):
            try:
                v = d.get(k)
                return float(v) if v is not None and v != '' else None
            except (TypeError, ValueError):
                return None
        try:
            acct = rh.load_account_profile()
        except Exception as e:
            log.warning(f'account profile fetch failed: {e}'); acct = {}
        try:
            pf = rh.load_portfolio_profile()
        except Exception as e:
            log.warning(f'portfolio profile fetch failed: {e}'); pf = {}
        mb = acct.get('margin_balances', {}) if isinstance(acct, dict) else {}
        return PortfolioSnapshot(
            captured_at=datetime.now(timezone.utc).isoformat(),
            gross_value=f(pf, 'market_value'),
            equity=f(pf, 'equity'),
            cash=f(acct, 'cash'),
            margin_borrowed=f(mb, 'settled_amount_borrowed'),
            outstanding_interest=f(mb, 'outstanding_interest'),
            buying_power=f(acct, 'buying_power'),
            excess_maintenance=f(pf, 'excess_maintenance'),
            withdrawable=f(pf, 'withdrawable_amount'),
            equity_previous_close=f(pf, 'equity_previous_close'),
            market_value_previous_close=f(pf, 'last_core_market_value'),
            portfolio_cash=f(acct, 'portfolio_cash'),
            overnight_buying_power=f(mb, 'overnight_buying_power'),
            overnight_ratio=f(mb, 'overnight_ratio'),
            ext_gross_value=f(pf, 'extended_hours_market_value'),
            ext_equity=f(pf, 'extended_hours_equity'),
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _require_rh(self):
        if self._rh is None:
            raise RuntimeError("authenticate() must be called before fetching data")
        return self._rh

    def _resolve_symbols(self, rh, txns):
        """Replace UUID-looking buy/sell assets with real ticker symbols.

        get_all_stock_orders returns an instrument URL but no symbol, so the
        normalizer falls back to the instrument UUID. Resolve those to real
        tickers via get_symbol_by_url (cached) so price lookups work.
        """
        import re as _re
        from dataclasses import replace as _replace
        uuid_re = _re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-", )
        cache = {}
        resolved = []
        for t in txns:
            if t.transaction_type in ("buy", "sell", "dividend") and t.asset and uuid_re.match(t.asset):
                uid = t.asset
                if uid not in cache:
                    url = f"https://api.robinhood.com/instruments/{uid.lower()}/"
                    try:
                        sym = rh.get_symbol_by_url(url)
                    except Exception as e:
                        log.warning(f"symbol resolution failed for {uid}: {e}")
                        sym = None
                    cache[uid] = sym or uid
                resolved.append(_replace(t, asset=cache[uid]))
            else:
                resolved.append(t)
        return resolved

    @staticmethod
    def _call(rh, method_name, kwargs):
        """Invoke a robin_stocks method, logging and swallowing failures so one
        bad harvest step never aborts the rest (ported from pull._call)."""
        fn = getattr(rh, method_name, None)
        if fn is None:
            log.warning(f"robin_stocks has no method {method_name} — skipping")
            return []
        try:
            result = fn(**kwargs) if kwargs else fn()
            return result or []
        except Exception as e:
            log.error(f"{method_name}({kwargs}) failed: {e}")
            return []
