"""Unit test for reporting (task 5.1).

Renders a known set of snapshots and asserts the formatted values appear, that
the missing-price flag line is present for a flagged row and absent otherwise,
and that a canned transaction summary renders readably.

Validates: Requirements 2.5, 6.4
"""

from datetime import date

from rhtracker import reporting
from rhtracker.model import MonthlySnapshot


def _snapshot(month_end, gross_value, value_flags=None):
    """Build a MonthlySnapshot with simple, distinct numbers."""
    return MonthlySnapshot(
        month_end=month_end,
        gross_value=gross_value,
        total_increase=100.0,
        asset_growth=50.0,
        dividends=5.0,
        interest_paid=2.0,
        cash_after_interest=3.0,
        monthly_expenses=10.0,
        margin_used=0.0,
        margin_paid_down=0.0,
        margin_debt=0.0,
        w2_contribution=200.0,
        total_w2_contribution=200.0,
        net_portfolio_value=gross_value,
        total_interest_paid=2.0,
        value_flags=value_flags,
    )


def test_render_monthly_header_and_values():
    flagged = _snapshot(
        date(2025, 10, 31), 1234.56, value_flags="missing price: AAPL"
    )
    clean = _snapshot(date(2025, 11, 30), 2000.00)
    out = reporting.render_monthly([flagged, clean])

    # Header labels present.
    assert "GrossVal" in out
    assert "NetPV" in out
    # Formatted gross values (thousands separator + 2 decimals) present.
    assert "1,234.56" in out
    assert "2,000.00" in out
    # Both month-ends rendered.
    assert "2025-10-31" in out
    assert "2025-11-30" in out


def test_render_monthly_flag_line_present_only_for_flagged_row():
    flagged = _snapshot(
        date(2025, 10, 31), 1234.56, value_flags="missing price: AAPL"
    )
    clean = _snapshot(date(2025, 11, 30), 2000.00)

    out = reporting.render_monthly([flagged, clean])
    assert "! missing price: AAPL" in out
    # Exactly one flag line — the clean row contributes none.
    assert out.count("! missing price") == 1

    out_clean_only = reporting.render_monthly([clean])
    assert "!" not in out_clean_only


def test_render_monthly_blanks_none_cells():
    snap = _snapshot(date(2025, 10, 31), None)
    out = reporting.render_monthly([snap])
    # Month still renders; gross value cell is blank (no stray "None").
    assert "2025-10-31" in out
    assert "None" not in out


def test_render_monthly_empty():
    assert "reconstruct" in reporting.render_monthly([]).lower()


def test_render_transaction_summary():
    summary = [
        {"transaction_type": "buy", "n": 3, "total_amount": -300.0},
        {"transaction_type": "dividend", "n": 2, "total_amount": 12.5},
    ]
    out = reporting.render_transaction_summary(summary)
    assert "buy" in out
    assert "dividend" in out
    assert "-300.00" in out
    assert "12.50" in out
    # Count column and overall total.
    assert "Total transactions: 5" in out


def test_render_transaction_summary_empty():
    assert reporting.render_transaction_summary([]) == "No transactions in DB."
