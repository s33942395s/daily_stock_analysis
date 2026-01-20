# -*- coding: utf-8 -*-
"""
===================================
Data Source Base & Manager - Taiwan Stock Version
===================================

Design Pattern: Strategy Pattern
- BaseFetcher: Abstract base class, defines unified interface
- DataFetcherManager: Strategy manager, implements auto-switching

Anti-ban Strategy:
1. Built-in rate limiting in each Fetcher
2. Auto-switch to next data source on failure
3. Exponential backoff retry mechanism
"""

import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List, Tuple, Dict

import pandas as pd
import numpy as np
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# Configure logging
logger = logging.getLogger(__name__)


# Standard column names definition
STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']


class DataFetchError(Exception):
    """Data fetch exception base class"""
    pass


class RateLimitError(DataFetchError):
    """API rate limit exception"""
    pass


class DataSourceUnavailableError(DataFetchError):
    """Data source unavailable exception"""
    pass


class BaseFetcher(ABC):
    """
    Data source abstract base class
    
    Responsibilities:
    1. Define unified data fetching interface
    2. Provide data standardization methods
    3. Implement common technical indicator calculations
    
    Subclass implements:
    - _fetch_raw_data(): Fetch raw data from specific source
    - _normalize_data(): Convert raw data to standard format
    """
    
    name: str = "BaseFetcher"
    priority: int = 99  # Lower number = higher priority
    
    @abstractmethod
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw data from data source (subclass must implement)
        
        Args:
            stock_code: Stock code, e.g. '2330.TW'
            start_date: Start date, format 'YYYY-MM-DD'
            end_date: End date, format 'YYYY-MM-DD'
            
        Returns:
            Raw data DataFrame (column names vary by source)
        """
        pass
    
    @abstractmethod
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Standardize data column names (subclass must implement)
        
        Convert different data source column names to:
        ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        """
        pass
    
    def get_daily_data(
        self, 
        stock_code: str, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30
    ) -> pd.DataFrame:
        """
        Get daily data (unified entry point)
        
        Flow:
        1. Calculate date range
        2. Call subclass to get raw data
        3. Standardize column names
        4. Calculate technical indicators
        
        Args:
            stock_code: Stock code
            start_date: Start date (optional)
            end_date: End date (optional, default today)
            days: Number of days to fetch (used when start_date not specified)
            
        Returns:
            Standardized DataFrame with technical indicators
        """
        # Calculate date range
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        if start_date is None:
            from datetime import timedelta
            start_dt = datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days * 2)
            start_date = start_dt.strftime('%Y-%m-%d')
        
        logger.info(f"[{self.name}] Fetching {stock_code}: {start_date} ~ {end_date}")
        
        try:
            # Step 1: Get raw data
            raw_df = self._fetch_raw_data(stock_code, start_date, end_date)
            
            if raw_df is None or raw_df.empty:
                raise DataFetchError(f"[{self.name}] No data for {stock_code}")
            
            # Step 2: Standardize column names
            df = self._normalize_data(raw_df, stock_code)
            
            # Step 3: Clean data
            df = self._clean_data(df)
            
            # Step 4: Calculate technical indicators
            df = self._calculate_indicators(df)
            
            logger.info(f"[{self.name}] {stock_code} success, {len(df)} records")
            return df
            
        except Exception as e:
            logger.error(f"[{self.name}] {stock_code} failed: {str(e)}")
            raise DataFetchError(f"[{self.name}] {stock_code}: {str(e)}") from e
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean data
        
        Process:
        1. Ensure date column format correct
        2. Convert numeric types
        3. Remove rows with null values
        4. Sort by date
        """
        df = df.copy()
        
        # Ensure date column is datetime type
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        
        # Convert numeric columns
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Remove rows with null key columns
        df = df.dropna(subset=['close', 'volume'])
        
        # Sort by date ascending
        df = df.sort_values('date', ascending=True).reset_index(drop=True)
        
        return df
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators
        
        Indicators:
        - MA5, MA10, MA20: Moving averages
        - Volume_Ratio: Volume ratio (today volume / 5-day average)
        """
        df = df.copy()
        
        # Moving averages
        df['ma5'] = df['close'].rolling(window=5, min_periods=1).mean()
        df['ma10'] = df['close'].rolling(window=10, min_periods=1).mean()
        df['ma20'] = df['close'].rolling(window=20, min_periods=1).mean()
        
        # Volume ratio
        avg_volume_5 = df['volume'].rolling(window=5, min_periods=1).mean()
        df['volume_ratio'] = df['volume'] / avg_volume_5.shift(1)
        df['volume_ratio'] = df['volume_ratio'].fillna(1.0)
        
        # Round to 2 decimals
        for col in ['ma5', 'ma10', 'ma20', 'volume_ratio']:
            if col in df.columns:
                df[col] = df[col].round(2)
        
        return df
    
    @staticmethod
    def random_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """
        Smart random sleep (Jitter)
        
        Anti-ban strategy: Simulate human behavior with random delays
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        logger.debug(f"Random sleep {sleep_time:.2f}s...")
        time.sleep(sleep_time)


class DataFetcherManager:
    """
    Data source strategy manager
    
    Responsibilities:
    1. Manage multiple data sources (sorted by priority)
    2. Automatic failover
    3. Provide unified data fetching interface
    
    Switching strategy:
    - Prefer higher priority data sources
    - Auto-switch to next on failure
    - Raise exception when all sources fail
    """
    
    def __init__(self, fetchers: Optional[List[BaseFetcher]] = None):
        """
        Initialize manager
        
        Args:
            fetchers: Data source list (optional, auto-create by priority if not provided)
        """
        self._fetchers: List[BaseFetcher] = []
        
        if fetchers:
            self._fetchers = sorted(fetchers, key=lambda f: f.priority)
        else:
            self._init_default_fetchers()
    
    def _init_default_fetchers(self) -> None:
        """
        Initialize default data source list
        
        Priority:
        1. TaiwanStockFetcher (Priority 1) - Taiwan stocks via YFinance
        2. USStockFetcher (Priority 2) - US stocks via YFinance
        3. YfinanceFetcher (Priority 5) - Fallback for international
        """
        from .taiwan_stock_fetcher import TaiwanStockFetcher
        from .us_stock_fetcher import USStockFetcher
        from .yfinance_fetcher import YfinanceFetcher
        from .institutional_fetcher import InstitutionalFetcher
        
        self._fetchers = [
            TaiwanStockFetcher(),
            USStockFetcher(),
            YfinanceFetcher(),
        ]
        
        # 初始化籌碼數據獲取器
        self._institutional_fetcher = InstitutionalFetcher()
        
        # Sort by priority
        self._fetchers.sort(key=lambda f: f.priority)
        
        logger.info(f"Initialized {len(self._fetchers)} data sources: " + 
                   ", ".join([f.name for f in self._fetchers]))

    
    def add_fetcher(self, fetcher: BaseFetcher) -> None:
        """Add data source and re-sort"""
        self._fetchers.append(fetcher)
        self._fetchers.sort(key=lambda f: f.priority)
    
    def get_daily_data(
        self, 
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30
    ) -> Tuple[pd.DataFrame, str]:
        """
        Get daily data (auto-switch data source)
        
        Failover strategy:
        1. Start from highest priority source
        2. Catch exception and switch to next
        3. Record failure reason for each source
        4. Raise detailed exception when all fail
        
        Args:
            stock_code: Stock code
            start_date: Start date
            end_date: End date
            days: Days to fetch
            
        Returns:
            Tuple[DataFrame, str]: (data, successful source name)
            
        Raises:
            DataFetchError: When all sources fail
        """
        errors = []
        
        for fetcher in self._fetchers:
            try:
                logger.info(f"Trying [{fetcher.name}] for {stock_code}...")
                df = fetcher.get_daily_data(
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    days=days
                )
                
                if df is not None and not df.empty:
                    logger.info(f"[{fetcher.name}] success for {stock_code}")
                    return df, fetcher.name
                    
            except Exception as e:
                error_msg = f"[{fetcher.name}] failed: {str(e)}"
                logger.warning(error_msg)
                errors.append(error_msg)
                continue
        
        # All sources failed
        error_summary = f"All sources failed for {stock_code}:\n" + "\n".join(errors)
        logger.error(error_summary)
        raise DataFetchError(error_summary)
    
    @property
    def available_fetchers(self) -> List[str]:
        """Return list of available source names"""
        return [f.name for f in self._fetchers]
    
    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """
        獲取股票名稱
        
        依次嘗試各數據源的 get_stock_name 方法，返回第一個成功的結果
        
        Args:
            stock_code: 股票代碼
            
        Returns:
            股票名稱，如果所有數據源都失敗則返回 None
        """
        for fetcher in self._fetchers:
            if hasattr(fetcher, 'get_stock_name'):
                name = fetcher.get_stock_name(stock_code)
                if name:
                    return name
        return None
    
    def get_institutional_data(self, stock_code: str, date: Optional[str] = None) -> Optional[Dict]:
        """
        獲取個股三大法人買賣超數據
        
        Args:
            stock_code: 股票代碼
            date: 日期 (YYYY-MM-DD，預設為最近交易日)
            
        Returns:
            {
                'foreign_net': 外資淨買賣超（張）,
                'trust_net': 投信淨買賣超（張）,
                'dealer_net': 自營商淨買賣超（張）,
                'total_net': 三大法人合計,
            }
            如果獲取失敗則返回 None
        """
        if hasattr(self, '_institutional_fetcher') and self._institutional_fetcher:
            return self._institutional_fetcher.get_institutional_data(stock_code, date)
        return None
