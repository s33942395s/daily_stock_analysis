# -*- coding: utf-8 -*-
"""
===================================
TaiwanStockFetcher - Taiwan Stock Data Source (Priority 1)
===================================

Data Source: Yahoo Finance (Taiwan stocks)
Features: Optimized for Taiwan stock market
Position: Primary data source for Taiwan stock analysis

Key Strategies:
1. Automatic Taiwan stock code format handling (XXXX.TW / XXXX.TWO)
2. Support both listed (.TW) and OTC (.TWO) stocks
3. Exponential backoff retry on failure
4. Data standardization

Taiwan Stock Market Hours:
- Open: 09:00
- Close: 13:30
- No T+1 restriction (can buy and sell same day)
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

logger = logging.getLogger(__name__)


class TaiwanStockFetcher(BaseFetcher):
    """
    Taiwan Stock Data Source Implementation
    
    Priority: 1 (Highest)
    Data Source: Yahoo Finance (Taiwan)
    
    Key Strategies:
    - Automatic stock code format conversion
    - Support listed/OTC stocks
    - Data standardization
    
    Code Format:
    - Listed: 2330.TW (TSMC)
    - OTC: 4956.TWO
    - Also accepts pure numbers: 2330 (auto-add .TW)
    """
    
    name = "TaiwanStockFetcher"
    priority = 1
    
    def __init__(self):
        """Initialize TaiwanStockFetcher"""
        logger.info("Taiwan stock data source initialized (using Yahoo Finance)")
    
    def _normalize_stock_code(self, stock_code: str) -> str:
        """
        Standardize Taiwan stock code format
        
        Accepted formats:
        1. Pure number: 2330 -> 2330.TW
        2. With suffix: 2330.TW -> 2330.TW
        3. OTC stock: 4956.TWO -> 4956.TWO
        
        Args:
            stock_code: Original code
            
        Returns:
            Standardized code
        """
        code = stock_code.strip().upper()
        
        # Already has correct suffix
        if code.endswith('.TW') or code.endswith('.TWO'):
            return code
        
        # Remove other potential suffixes
        code = re.sub(r'\.(SS|SZ|SH)$', '', code, flags=re.IGNORECASE)
        
        # Pure 4-digit number, add .TW (listed market)
        if code.isdigit() and len(code) == 4:
            return f"{code}.TW"
        
        # Other cases, try adding .TW
        logger.warning(f"Unusual stock code format: {stock_code}, trying to add .TW suffix")
        return f"{code}.TW"
    
    def _is_taiwan_stock(self, stock_code: str) -> bool:
        """
        Check if it's a Taiwan stock code
        
        Taiwan stock characteristics:
        - 4 digits
        - Suffix .TW or .TWO
        """
        code = stock_code.strip().upper()
        
        # Check suffix
        if code.endswith('.TW') or code.endswith('.TWO'):
            # Extract number part
            number_part = code.split('.')[0]
            return number_part.isdigit() and len(number_part) == 4
        
        # Pure 4-digit number
        return code.isdigit() and len(code) == 4
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw Taiwan stock data from Yahoo Finance
        
        Process:
        1. Standardize stock code
        2. Verify it's a Taiwan stock
        3. Call yfinance API
        4. Process returned data
        
        Args:
            stock_code: Stock code (e.g. 2330, 2330.TW)
            start_date: Start date
            end_date: End date
            
        Returns:
            Raw data DataFrame
        """
        import yfinance as yf
        
        # Standardize code
        normalized_code = self._normalize_stock_code(stock_code)
        
        # Verify Taiwan stock
        if not self._is_taiwan_stock(normalized_code):
            raise DataFetchError(f"Not a Taiwan stock code: {stock_code} (please use 4-digit or XXXX.TW format)")
        
        logger.debug(f"Calling yfinance.download({normalized_code}, {start_date}, {end_date})")
        
        try:
            # Use yfinance to download data
            df = yf.download(
                tickers=normalized_code,
                start=start_date,
                end=end_date,
                progress=False,  # Disable progress bar
                auto_adjust=True,  # Auto-adjust prices (handle ex-dividend)
            )
            
            if df.empty:
                raise DataFetchError(f"Yahoo Finance found no data for {normalized_code}")
            
            logger.info(f"Successfully fetched {normalized_code} data, total {len(df)} records")
            return df
            
        except Exception as e:
            if isinstance(e, DataFetchError):
                raise
            raise DataFetchError(f"Yahoo Finance Taiwan stock data fetch failed: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Standardize Taiwan stock data
        
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
        
        # Handle multi-level columns (yfinance sometimes returns multi-index)
        if isinstance(df.columns, pd.MultiIndex):
            # Flatten multi-index columns, keep only first level
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
        
        # Calculate percentage change (yfinance doesn't provide)
        if 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
        
        # Calculate trading amount (TWD)
        # Amount = Volume * Close Price
        if 'volume' in df.columns and 'close' in df.columns:
            df['amount'] = (df['volume'] * df['close']).round(0)
        else:
            df['amount'] = 0
        
        # Standardize stock code (remove suffix)
        normalized_code = self._normalize_stock_code(stock_code)
        code_only = normalized_code.split('.')[0]
        df['code'] = code_only
        
        # Keep only required columns
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        
        return df


if __name__ == "__main__":
    # Test code
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
    )
    
    fetcher = TaiwanStockFetcher()
    
    # Test cases
    test_codes = [
        '2330',       # TSMC (pure number)
        '2330.TW',    # TSMC (full format)
        '2317.TW',    # Hon Hai
        '2454.TW',    # MediaTek
    ]
    
    for code in test_codes:
        try:
            print(f"\n{'='*50}")
            print(f"Testing stock: {code}")
            print('='*50)
            
            df = fetcher.get_daily_data(code, days=5)
            print(f"Successfully fetched {len(df)} records")
            print(f"\nLast 3 days data:")
            print(df.tail(3)[['date', 'close', 'volume', 'pct_chg']])
            
        except Exception as e:
            print(f"Fetch failed: {e}")
