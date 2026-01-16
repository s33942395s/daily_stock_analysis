# -*- coding: utf-8 -*-
"""
===================================
策略分析適配器 (Adapter)
===================================

這是一個適配層，用於兼容舊的 StockTrendAnalyzer 接口，
但底層邏輯已經轉發給新的 strategies.py 模組。
"""

import logging
import pandas as pd
from typing import Dict, Any, List
from dataclasses import asdict

from strategies import StrategyFactory, SignalType, StrategyResult
from config import get_config

logger = logging.getLogger(__name__)

# 保持 TrendAnalysisResult 結構，以便兼容 Notification 模塊
# 這裡我們動態構建它，或者重新定義一個兼容的類
class TrendAnalysisResult:
    """
    兼容舊版的分析結果對象
    """
    def __init__(self, code: str):
        self.code = code
        self.trend_status = None # 舊版枚舉，這裡可能需要 mock
        self.ma_alignment = ""
        self.trend_strength = 0
        self.buy_signal = None
        self.signal_score = 0
        self.signal_reasons = []
        self.risk_factors = []
        
        # 為了兼容性，添加舊版字段的默認值
        self.ma5 = 0
        self.ma10 = 0
        self.ma20 = 0
        self.volume_status = "N/A" # 簡化
        self.volume_trend = ""
        self.bias_ma5 = 0
        self.bias_ma10 = 0
        
        # 兼容 Notification 取值
        self.buy_signal_value = "观望"
        self.trend_status_value = "震荡"

    @property
    def buy_signal(self):
        # 為了兼容 .value 訪問
        class EnumLike:
            def __init__(self, val): self.value = val
        return EnumLike(self.buy_signal_value)
        
    @buy_signal.setter
    def buy_signal(self, val):
        self.buy_signal_value = val.value if hasattr(val, 'value') else str(val)

    @property
    def trend_status(self):
        class EnumLike:
            def __init__(self, val): self.value = val
        return EnumLike(self.trend_status_value)
    
    @trend_status.setter
    def trend_status(self, val):
        self.trend_status_value = val.value if hasattr(val, 'value') else str(val)

class StockTrendAnalyzer:
    """
    新版分析器 (Wrapper)
    從 Config 讀取策略名稱，並調用對應策略
    """
    
    def __init__(self):
        config = get_config()
        # 默認為趨勢策略，如果 config 中有定義則讀取
        self.strategy_name = getattr(config, 'strategy_name', 'trend')
        self.strategy = StrategyFactory.get_strategy(self.strategy_name)
        logger.info(f"StockTrendAnalyzer 初始化完成，使用策略: {self.strategy.name}")
        
    def analyze(self, df: pd.DataFrame, code: str) -> TrendAnalysisResult:
        """
        執行分析並轉換結果格式
        """
        # 1. 執行新策略分析
        strat_result = self.strategy.analyze(df, code)
        
        # 2. 轉換為舊版 TrendAnalysisResult 對象 (Adapter Pattern)
        result = TrendAnalysisResult(code=code)
        
        # 映射信號
        result.buy_signal_value = strat_result.signal.value
        result.signal_score = strat_result.score
        result.signal_reasons = strat_result.reasons
        result.risk_factors = strat_result.risks
        
        # 填充指標數據 (如果有)
        indicators = strat_result.indicators
        result.ma5 = indicators.get('MA5', 0)
        result.ma10 = indicators.get('MA10', 0)
        result.ma20 = indicators.get('MA20', 0)
        
        # 填充描述性字段 (基於策略類型)
        if self.strategy.name == "TrendFollowing":
            result.trend_status_value = "趋势跟踪"
            result.ma_alignment = "見買入理由"
            result.volume_trend = "見指標分析"
        elif self.strategy.name == "MeanReversion":
            result.trend_status_value = "均值回归"
            # 均值回歸策略可能關注 RSI
            result.ma_alignment = f"RSI: {indicators.get('RSI', 0):.1f}"
            
        return result

    def format_analysis(self, result: TrendAnalysisResult) -> str:
        """格式化輸出 (保持兼容)"""
        return f"""
=== {result.code} 分析報告 ===
策略: {self.strategy.name}
信號: {result.buy_signal.value}
評分: {result.signal_score}

✅ 理由:
{chr(10).join(['- ' + r for r in result.signal_reasons])}

⚠️ 風險:
{chr(10).join(['- ' + r for r in result.risk_factors])}
"""

def analyze_stock(df: pd.DataFrame, code: str):
    analyzer = StockTrendAnalyzer()
    return analyzer.analyze(df, code)
