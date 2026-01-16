# -*- coding: utf-8 -*-
"""
===================================
策略模組 - 包含多種交易策略與技術指標
===================================

提供可插拔的策略系統：
1. TrendStrategy: 趨勢追蹤（原有的 MA5>MA10>MA20）
2. MeanReversionStrategy: 均值回歸（RSI + Bollinger Bands）

技術指標計算：
- RSI, MACD, KD(Stochastic), Bollinger Bands
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from enum import Enum

logger = logging.getLogger(__name__)

# 为了兼容 StockTrendAnalyzer 的枚举，保留原来的定义或在此重新定义并映射
# 这里我们重用 stock_analyzer 中定义的 Enums 或者重新定义它们
# 为了解耦，我们在 strategies 中定义通用的 Enum，stock_analyzer 可以引用这里的

class SignalType(Enum):
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    HOLD = "持有"
    WAIT = "观望"
    SELL = "卖出"
    STRONG_SELL = "强烈卖出"

@dataclass
class StrategyResult:
    """策略分析結果"""
    code: str
    signal: SignalType = SignalType.WAIT
    score: int = 0
    reasons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    indicators: Dict[str, Any] = field(default_factory=dict)
    
class TechnicalIndicators:
    """技術指標計算器"""
    
    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """計算相對強弱指標 (RSI)"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
        """計算 MACD (DIF, DEA, Histogram)"""
        exp1 = series.ewm(span=fast, adjust=False).mean()
        exp2 = series.ewm(span=slow, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=signal, adjust=False).mean()
        macd = (dif - dea) * 2
        return dif, dea, macd

    @staticmethod
    def calculate_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3) -> tuple:
        """計算 KDJ (Stochastic Oscillator)"""
        low_min = low.rolling(window=n).min()
        high_max = high.rolling(window=n).max()
        
        rsv = (close - low_min) / (high_max - low_min) * 100
        # 填充 NaN
        rsv = rsv.fillna(50)
        
        k = rsv.ewm(alpha=1/m1, adjust=False).mean()
        d = k.ewm(alpha=1/m2, adjust=False).mean()
        j = 3 * k - 2 * d
        return k, d, j
        
    @staticmethod
    def calculate_bollinger_bands(series: pd.Series, window: int = 20, num_std: float = 2.0) -> tuple:
        """計算布林通道 (Upper, Middle, Lower)"""
        middle = series.rolling(window=window).mean()
        std = series.rolling(window=window).std()
        upper = middle + (std * num_std)
        lower = middle - (std * num_std)
        return upper, middle, lower

class BaseStrategy(ABC):
    """策略基類"""
    
    def __init__(self, name: str):
        self.name = name
        
    @abstractmethod
    def analyze(self, df: pd.DataFrame, code: str) -> StrategyResult:
        """執行分析"""
        pass

class TrendFollowingStrategy(BaseStrategy):
    """
    趨勢追蹤策略 (原有的硬邏輯)
    核心：MA5 > MA10 > MA20 多頭排列
    """
    def __init__(self):
        super().__init__("TrendFollowing")
        
    def analyze(self, df: pd.DataFrame, code: str) -> StrategyResult:
        result = StrategyResult(code=code)
        
        if len(df) < 20:
            result.risks.append("數據不足 20 天，無法進行趨勢分析")
            return result
            
        latest = df.iloc[-1]
        close = latest['close']
        ma5 = latest.get('MA5', df['close'].rolling(5).mean().iloc[-1])
        ma10 = latest.get('MA10', df['close'].rolling(10).mean().iloc[-1])
        ma20 = latest.get('MA20', df['close'].rolling(20).mean().iloc[-1])
        
        # 記錄指標
        result.indicators = {
            'MA5': ma5, 'MA10': ma10, 'MA20': ma20, 'Close': close
        }
        
        score = 0
        
        # 1. 均線排列 (40分)
        if ma5 > ma10 > ma20:
            score += 40
            result.reasons.append("✅ 均線呈現多頭排列 (MA5>MA10>MA20)")
        elif ma5 > ma10:
            score += 20
            result.reasons.append("✅ 短期均線向上 (MA5>MA10)")
        elif ma5 < ma10 < ma20:
            result.risks.append("⚠️ 均線呈現空頭排列")
            
        # 2. 乖離率 (30分)
        bias = (close - ma5) / ma5 * 100
        if 0 > bias > -5:
            score += 30
            result.reasons.append(f"✅ 回踩 MA5 支撐 (乖離 {bias:.1f}%)")
        elif 0 < bias < 5:
            score += 20
            result.reasons.append(f"✅ 股價貼近 MA5 (乖離 {bias:.1f}%)")
        elif bias >= 5:
            result.risks.append(f"⚠️ 乖離率過高 ({bias:.1f}%)，嚴禁追高")
        
        # 3. 量能 (20分) - 簡單版
        vol_5d = df['volume'].iloc[-6:-1].mean()
        if vol_5d > 0:
            vol_ratio = latest['volume'] / vol_5d
            if vol_ratio < 0.8 and close > df.iloc[-2]['close']:
                score += 20
                result.reasons.append("✅ 縮量上漲 (籌碼鎖定)")
            elif vol_ratio > 1.5 and close > df.iloc[-2]['close']:
                score += 15
                result.reasons.append("✅ 放量突破")
                
        result.score = score
        
        # 判斷信號
        if score >= 80:
            result.signal = SignalType.STRONG_BUY
        elif score >= 60:
            result.signal = SignalType.BUY
        elif score >= 40:
            result.signal = SignalType.HOLD
        elif score >= 20:
            result.signal = SignalType.WAIT
        else:
            result.signal = SignalType.SELL
            
        return result

class MeanReversionStrategy(BaseStrategy):
    """
    均值回歸策略 (新增)
    核心：RSI 超賣 (<30) + 布林通道下軌支撐 + KD 黃金交叉
    適合：震盪盤或跌深反彈
    """
    def __init__(self):
        super().__init__("MeanReversion")
        
    def analyze(self, df: pd.DataFrame, code: str) -> StrategyResult:
        result = StrategyResult(code=code)
        
        if len(df) < 30:
            result.risks.append("數據不足，無法計算技術指標")
            return result
            
        # 計算指標
        df = df.copy()
        df['RSI'] = TechnicalIndicators.calculate_rsi(df['close'])
        upper, middle, lower = TechnicalIndicators.calculate_bollinger_bands(df['close'])
        k, d, j = TechnicalIndicators.calculate_kdj(df['high'], df['low'], df['close'])
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        close = latest['close']
        rsi = latest['RSI']
        k_val, d_val = k.iloc[-1], d.iloc[-1]
        prev_k, prev_d = k.iloc[-2], d.iloc[-2]
        b_lower = lower.iloc[-1]
        
        result.indicators = {
            'RSI': rsi, 'K': k_val, 'D': d_val, 'Bollinger_Lower': b_lower
        }
        
        score = 0
        
        # 1. RSI 超賣 (40分)
        if rsi < 30:
            score += 40
            result.reasons.append(f"✅ RSI 超賣 ({rsi:.1f})，隨時反彈")
        elif rsi < 40:
            score += 20
            result.reasons.append(f"✅ RSI 處於低檔區 ({rsi:.1f})")
        elif rsi > 70:
            result.risks.append(f"⚠️ RSI 超買 ({rsi:.1f})，注意回調")
            
        # 2. 布林通道 (30分)
        if close <= b_lower * 1.02: # 接近下軌 2%
            score += 30
            result.reasons.append("✅ 股價觸及布林下軌，有支撐")
            
        # 3. KD 黃金交叉 (30分)
        if prev_k < prev_d and k_val > d_val and k_val < 50:
            score += 30
            result.reasons.append("✅ KD 低檔黃金交叉")
            
        result.score = score
        
        # 判斷信號 (反彈策略要求較高分數)
        if score >= 80:
            result.signal = SignalType.STRONG_BUY
        elif score >= 60:
            result.signal = SignalType.BUY
        elif score >= 40:
            result.signal = SignalType.WAIT # 分數不高建議觀望
        else:
            result.signal = SignalType.SELL
            
        return result

class StrategyFactory:
    """策略工廠"""
    
    @staticmethod
    def get_strategy(strategy_name: str) -> BaseStrategy:
        if strategy_name.lower() == "reversion":
            return MeanReversionStrategy()
        else:
            return TrendFollowingStrategy() # 默認
