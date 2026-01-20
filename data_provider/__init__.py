"""
===================================
Data Provider Module - Taiwan & US Stock
===================================

Strategy Pattern for data source management:
- TaiwanStockFetcher: Primary (Taiwan stocks via YFinance)
- USStockFetcher: US stocks (NYSE, NASDAQ via YFinance)
- YfinanceFetcher: Fallback (International markets)
"""

from .base import BaseFetcher, DataFetcherManager, DataFetchError
from .taiwan_stock_fetcher import TaiwanStockFetcher
from .us_stock_fetcher import USStockFetcher
from .yfinance_fetcher import YfinanceFetcher

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'DataFetchError',
    'TaiwanStockFetcher',
    'USStockFetcher',
    'YfinanceFetcher',
]

