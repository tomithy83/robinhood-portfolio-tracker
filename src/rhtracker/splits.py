"""Stock split adjustment, applied during reconstruction.

Robinhood's historical price series (get_stock_historicals) is fully
back-adjusted: pre-split dates are reported on the current, post-split price
basis. To value a past month-end correctly, the reconstructed SHARE count
must be on that same post-split basis. We therefore scale each trade's
quantity by the product of the split factors for splits dated AFTER the
trade.

The API does not reliably expose these splits (get_splits, the instrument
splits feed, and get_events can all come back empty), so the split table is
maintained by hand in ``settings.json`` (see ``settings.example.json``) and
validated against real current holdings: the split-adjusted lifetime share
count per ticker should equal the actual current share count.

Each configured entry is ``{"ticker", "date", "factor"}``; ``factor``
multiplies the pre-split share count to get post-split shares. A 1-for-5
REVERSE split is 0.2 (5 old -> 1 new); a 2-for-1 FORWARD split is 2.0. This
module reads only the settings library module (plus stdlib).
"""

from __future__ import annotations

from datetime import date

from rhtracker import settings


def adjustment_factor(ticker: str, trade_date: date) -> float:
    """Factor converting a trade quantity to the current post-split basis:
    the product of factors for splits on this ticker dated strictly after the
    trade date. Trades on or after a split already sit on its basis.
    """
    factor = 1.0
    for entry in settings.splits():
        if entry.ticker == ticker and trade_date < entry.effective_date:
            factor *= entry.factor
    return factor
