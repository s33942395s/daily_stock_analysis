"""
===================================
Data Provider Module - Taiwan Stock
===================================

Strategy Pattern for data source management:
- TaiwanStockFetcher: Primary (Taiwan stocks via YFinance)
- YfinanceFetcher: Fallback (International markets)
"""

from .base import BaseFetcher, DataFetcherManager, DataFetchError
from .taiwan_stock_fetcher import TaiwanStockFetcher
from .yfinance_fetcher import YfinanceFetcher

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'DataFetchError',
    'TaiwanStockFetcher',
    'YfinanceFetcher',
]
