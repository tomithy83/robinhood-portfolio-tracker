"""Stock split events, applied during reconstruction.

Robinhood's historical price series (get_stock_historicals) is fully
back-adjusted: pre-split dates are reported on the current, post-split price
basis. To value a past month-end correctly, the reconstructed SHARE count
must be on that same post-split basis. We therefore scale each trade's
quantity by the product of the split factors for splits dated AFTER the
trade.

The API did not reliably expose these splits (get_splits, the instrument
splits feed, and get_events all came back empty for the known MSTY reverse
split), so this table is maintained by hand. It is validated against real
current holdings: the split-adjusted lifetime share count per ticker must
equal the actual current share count.

Each entry: (ticker, effective_date, factor). factor multiplies the
pre-split share count to get post-split shares. A 1-for-5 REVERSE split is
0.2 (5 old -> 1 new). A 2-for-1 FORWARD split is 2.0. This module is
foundational library data: it imports nothing from the package.
"""

from __future__ import annotations

from datetime import date

# (ticker, effective_date, factor)
SPLITS: list[tuple[str, date, float]] = [
    # MSTY 1-for-5 reverse split, 2025-12-08 (validated: adjusted lifetime
    # shares reproduce the real current holding of 431).
    ("MSTY", date(2025, 12, 8), 0.2),
]


def adjustment_factor(ticker: str, trade_date: date) -> float:
    """Factor converting a trade quantity to the current post-split basis:
    the product of factors for splits on this ticker dated strictly after the
    trade date. Trades on or after a split already sit on its basis.
    """
    factor = 1.0
    for sym, eff, f in SPLITS:
        if sym == ticker and trade_date < eff:
            factor *= f
    return factor
