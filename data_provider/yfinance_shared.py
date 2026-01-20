"""
Shared utilities for yfinance usage.

yfinance maintains some global/shared state internally; calling into it concurrently
(e.g., via ThreadPoolExecutor) can produce corrupted results. We serialize access
to yfinance to keep multi-stock runs stable.
"""

from threading import RLock
from typing import Any
from datetime import datetime, timedelta

YFINANCE_LOCK = RLock()


def yfinance_end_date_inclusive(end_date: Any) -> Any:
    """
    Convert an inclusive end date into yfinance's exclusive `end` parameter.

    yfinance treats `end` as exclusive for `download()`. Our fetchers typically pass an inclusive
    YYYY-MM-DD string, so we add 1 day when the value looks like a plain date.
    """
    if end_date is None:
        return None

    if isinstance(end_date, str):
        try:
            return (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            return end_date

    if isinstance(end_date, datetime):
        return end_date + timedelta(days=1)

    return end_date


def yfinance_download(*args: Any, **kwargs: Any):
    import yfinance as yf

    with YFINANCE_LOCK:
        return yf.download(*args, **kwargs)
