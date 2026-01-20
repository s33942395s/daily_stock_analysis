# -*- coding: utf-8 -*-
"""
===================================
USStockFetcher - US Stock Data Source (Priority 2)
===================================

Data Source: Yahoo Finance (US stocks)
Features: Optimized for US stock market (NYSE, NASDAQ)
Position: Secondary data source after Taiwan stocks

Key Strategies:
1. Automatic US stock code format handling
2. Support NYSE and NASDAQ listed stocks
3. Support ETFs (SPY, QQQ, etc.)
4. Exponential backoff retry on failure
5. Data standardization

US Stock Market Hours (ET):
- Regular: 09:30 - 16:00
- Pre-market: 04:00 - 09:30
- After-hours: 16:00 - 20:00
"""

import logging
import re
from datetime import datetime
from typing import Optional

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS
from .yfinance_shared import YFINANCE_LOCK, yfinance_end_date_inclusive

logger = logging.getLogger(__name__)


class USStockFetcher(BaseFetcher):
    """
    US Stock Data Source Implementation
    
    Priority: 2 (After Taiwan stocks, before generic YFinance)
    Data Source: Yahoo Finance (US)
    
    Key Strategies:
    - Automatic stock code format validation
    - Support NYSE, NASDAQ stocks
    - Support ETFs and ADRs
    - Data standardization
    
    Code Format:
    - Stocks: AAPL, MSFT, GOOGL, TSLA
    - ETFs: SPY, QQQ, VTI, VOO
    - Class shares: BRK.A, BRK.B
    """
    
    name = "USStockFetcher"
    priority = 2  # Higher than generic YFinanceFetcher (5), lower than Taiwan (1)
    
    # Common US stock exchanges/indices for validation
    COMMON_US_TICKERS = {
        # Top tech stocks
        'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA',
        # Popular ETFs
        'SPY', 'QQQ', 'VTI', 'VOO', 'IWM', 'DIA', 'ARKK',
        # Other major stocks
        'JPM', 'V', 'MA', 'JNJ', 'WMT', 'PG', 'UNH', 'HD', 'BAC', 'XOM',
        'CVX', 'PFE', 'ABBV', 'KO', 'PEP', 'COST', 'MRK', 'TMO', 'AVGO',
        'ORCL', 'CSCO', 'ACN', 'ADBE', 'CRM', 'NKE', 'MCD', 'DIS', 'NFLX',
        'AMD', 'INTC', 'QCOM', 'TXN', 'IBM', 'GE', 'CAT', 'BA', 'UPS',
    }
    
    def __init__(self):
        """Initialize USStockFetcher"""
        logger.info("US stock data source initialized (using Yahoo Finance)")
    
    def _normalize_stock_code(self, stock_code: str) -> str:
        """
        Standardize US stock code format
        
        Args:
            stock_code: Original code
            
        Returns:
            Standardized code (uppercase)
        """
        code = stock_code.strip().upper()
        
        # Remove any accidental suffixes
        code = re.sub(r'\.(TW|TWO|SS|SZ|SH)$', '', code, flags=re.IGNORECASE)
        
        return code
    
    def _is_us_stock(self, stock_code: str) -> bool:
        """
        Check if it's a US stock code
        
        US stock characteristics:
        - 1-5 uppercase letters (AAPL, MSFT, BRK.B)
        - May contain a dot for class shares (BRK.A, BRK.B)
        - NOT a Taiwan stock format (4-6 digits)
        
        Args:
            stock_code: Stock code to check
            
        Returns:
            True if it appears to be a US stock
        """
        code = stock_code.strip().upper()
        
        # Remove known non-US suffixes
        code = re.sub(r'\.(TW|TWO|SS|SZ|SH)$', '', code, flags=re.IGNORECASE)
        
        # If it's all digits, it's likely Taiwan/China stock
        if code.isdigit():
            return False
        
        # Check for Taiwan stock format (4-6 digits with optional .TW/.TWO)
        if re.match(r'^\d{4,6}(\.TW|\.TWO)?$', stock_code, re.IGNORECASE):
            return False
        
        # US stock pattern: 1-5 letters, optionally followed by .A or .B
        # Examples: AAPL, MSFT, BRK.A, BRK.B
        if re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code):
            return True
        
        # Check against known US tickers
        base_code = code.split('.')[0]
        if base_code in self.COMMON_US_TICKERS:
            return True
        
        return False
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw US stock data from Yahoo Finance
        
        Process:
        1. Standardize stock code
        2. Verify it's a US stock
        3. Call yfinance API
        4. Process returned data
        
        Args:
            stock_code: Stock code (e.g. AAPL, MSFT)
            start_date: Start date
            end_date: End date
            
        Returns:
            Raw data DataFrame
        """
        import yfinance as yf
        
        # Standardize code
        normalized_code = self._normalize_stock_code(stock_code)
        
        # Verify US stock
        if not self._is_us_stock(normalized_code):
            raise DataFetchError(f"Not a US stock code: {stock_code}")
        
        logger.debug(f"Calling yfinance.download({normalized_code}, {start_date}, {end_date})")
        
        try:
            # yfinance `end` is exclusive; convert our inclusive end date
            yf_end_date = yfinance_end_date_inclusive(end_date)
            
            # Use yfinance to download data with lock for thread safety
            with YFINANCE_LOCK:
                df = yf.download(
                    tickers=normalized_code,
                    start=start_date,
                    end=yf_end_date,
                    progress=False,
                    auto_adjust=True,
                )
            
            if df.empty:
                raise DataFetchError(f"Yahoo Finance found no data for {normalized_code}")
            
            logger.info(f"Successfully fetched {normalized_code} data, total {len(df)} records")
            return df
            
        except Exception as e:
            if isinstance(e, DataFetchError):
                raise
            raise DataFetchError(f"Yahoo Finance US stock data fetch failed: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Standardize US stock data
        
        yfinance returns column names:
        Open, High, Low, Close, Volume (index is date)
        
        Need to map to standard column names:
        date, open, high, low, close, volume, amount, pct_chg
        
        Args:
            df: Raw data
            stock_code: Stock code
            
        Returns:
            Standardized DataFrame
        """
        df = df.copy()
        
        # Handle multi-level columns
        if isinstance(df.columns, pd.MultiIndex):
            normalized_code = self._normalize_stock_code(stock_code)
            try:
                selected = False
                for level in range(df.columns.nlevels):
                    level_values = df.columns.get_level_values(level)
                    if normalized_code in set(level_values):
                        df = df.xs(normalized_code, axis=1, level=level, drop_level=True)
                        selected = True
                        break
                
                if not selected:
                    last_level = df.columns.get_level_values(-1)
                    unique_last = list(pd.unique(last_level))
                    if len(unique_last) == 1:
                        df = df.xs(unique_last[0], axis=1, level=-1, drop_level=True)
                    else:
                        df.columns = df.columns.get_level_values(0)
            except Exception:
                df.columns = df.columns.get_level_values(0)
        
        # Reset index, convert date from index to column
        df = df.reset_index()
        
        # Column mapping (yfinance uses capitalized names)
        column_mapping = {
            'Date': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
        }
        
        df = df.rename(columns=column_mapping)
        
        # Remove duplicates if any
        if df.columns.has_duplicates:
            df = df.loc[:, ~df.columns.duplicated()]
        
        # Calculate percentage change
        if 'close' in df.columns:
            close_series = df['close']
            if isinstance(close_series, pd.DataFrame):
                close_series = close_series.iloc[:, 0]
            df['pct_chg'] = close_series.pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
        
        # Calculate trading amount (USD)
        if 'volume' in df.columns and 'close' in df.columns:
            volume_series = df['volume']
            if isinstance(volume_series, pd.DataFrame):
                volume_series = volume_series.iloc[:, 0]
            close_series = df['close']
            if isinstance(close_series, pd.DataFrame):
                close_series = close_series.iloc[:, 0]
            df['amount'] = (volume_series * close_series).round(0)
        else:
            df['amount'] = 0
        
        # Standardize stock code
        df['code'] = self._normalize_stock_code(stock_code)
        
        # Keep only required columns
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        
        return df
    
    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """
        Get US stock name
        
        Uses yfinance's info property to get stock name,
        prioritizing shortName or longName
        
        Args:
            stock_code: Stock code (e.g. AAPL, MSFT)
            
        Returns:
            Stock name, e.g. "Apple Inc."
            Returns None if fetch fails
        """
        import yfinance as yf
        
        normalized_code = self._normalize_stock_code(stock_code)
        
        if not self._is_us_stock(normalized_code):
            return None
        
        try:
            with YFINANCE_LOCK:
                ticker = yf.Ticker(normalized_code)
                info = ticker.info
            
            # Priority: shortName > longName
            name = info.get('shortName') or info.get('longName')
            if name:
                logger.info(f"[{stock_code}] Got stock name: {name}")
                return name
            return None
        except Exception as e:
            logger.warning(f"[{stock_code}] Failed to get stock name: {e}")
            return None


if __name__ == "__main__":
    # Test code
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
    )
    
    fetcher = USStockFetcher()
    
    # Test cases
    test_codes = [
        'AAPL',     # Apple
        'MSFT',     # Microsoft
        'GOOGL',    # Alphabet
        'TSLA',     # Tesla
        'SPY',      # S&P 500 ETF
    ]
    
    for code in test_codes:
        try:
            print(f"\n{'='*50}")
            print(f"Testing stock: {code}")
            print('='*50)
            
            # Test stock identification
            print(f"Is US stock: {fetcher._is_us_stock(code)}")
            
            # Get stock name
            name = fetcher.get_stock_name(code)
            print(f"Stock name: {name}")
            
            # Get daily data
            df = fetcher.get_daily_data(code, days=5)
            print(f"Successfully fetched {len(df)} records")
            print(f"\nLast 3 days data:")
            print(df.tail(3)[['date', 'close', 'volume', 'pct_chg']])
            
        except Exception as e:
            print(f"Fetch failed: {e}")
