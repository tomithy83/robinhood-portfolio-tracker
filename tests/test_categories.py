"""Tests for category breakdown builders and their rendering."""

from datetime import date

from rhtracker import categories, reporting
from rhtracker.model import Transaction


def _t(typ, asset, amount):
    return Transaction(hash=f"{typ}-{asset}-{amount}", transaction_date=date(2025, 11, 1),
                       transaction_type=typ, asset=asset, amount=amount,
                       quantity=None, price=None, status="ok", reference_id=f"{typ}-{asset}-{amount}")


TXNS = [
    _t("dividend", "MSTY", 10.0),
    _t("dividend", "MSTY", 5.0),
    _t("dividend", "YMAX", 3.0),
    _t("bill_payment", "Capital One", -100.0),
    _t("auto_loan_payment", "HONDA PMT", -546.42),
    _t("margin_interest", "MARGIN", -7.5),
    _t("subscription_fee", "RH_GOLD", -50.0),
    _t("buy", "MSTY", -200.0),
    _t("sell", "MSTY", 60.0),
]


def test_dividends_grouped_and_summed():
    rows = categories.dividends_by_ticker(TXNS)
    by = {r.label: r for r in rows}
    assert by["MSTY"].count == 2 and by["MSTY"].total == 15.0
    assert by["YMAX"].total == 3.0
    # sorted descending by total
    assert rows[0].label == "MSTY"


def test_expenses_shown_positive():
    rows = categories.expenses_by_payee(TXNS)
    by = {r.label: r.total for r in rows}
    assert by["Capital One"] == 100.0        # stored -100 -> shown positive
    assert by["HONDA PMT"] == 546.42


def test_fees_grouped_positive():
    rows = categories.fees_by_type(TXNS)
    by = {r.label: r.total for r in rows}
    assert by["margin_interest"] == 7.5
    assert by["subscription_fee"] == 50.0


def test_stock_trades_buy_and_sell():
    rows = categories.stock_trades_by_ticker(TXNS)
    msty = [r for r in rows if r.ticker == "MSTY"][0]
    assert msty.buy_count == 1 and msty.buy_total == 200.0
    assert msty.sell_count == 1 and msty.sell_total == 60.0


def test_renderers_produce_tables_with_totals():
    assert "Dividends by ticker" in reporting.render_dividends(categories.dividends_by_ticker(TXNS))
    assert "TOTAL" in reporting.render_expenses(categories.expenses_by_payee(TXNS))
    assert "margin_interest" in reporting.render_fees(categories.fees_by_type(TXNS))
    trades = reporting.render_stock_trades(categories.stock_trades_by_ticker(TXNS))
    assert "buy_amount" in trades and "sell_amount" in trades


def test_option_trades_by_underlying():
    txns = [
        _t("option_buy", "SPY", -100.0),
        _t("option_buy", "SPY", -50.0),
        _t("option_sell", "SPY", 40.0),
        _t("option_buy", "SPYM", -95.0),
    ]
    rows = categories.option_trades_by_underlying(txns)
    spy = [r for r in rows if r.ticker == 'SPY'][0]
    assert spy.buy_count == 2 and spy.buy_total == 150.0   # premium paid, positive
    assert spy.sell_count == 1 and spy.sell_total == 40.0  # premium received
    spym = [r for r in rows if r.ticker == 'SPYM'][0]
    assert spym.buy_total == 95.0
    # renderer produces a table
    out = reporting.render_option_trades(rows)
    assert "buy_premium" in out and "sell_premium" in out and "SPY" in out
