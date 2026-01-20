# -*- coding: utf-8 -*-
"""
===================================
台股大盤復盤分析模組
===================================

功能：
1. 獲取台股指數數據（加權指數、櫃買指數）
2. 搜索市場新聞以獲取復盤情報
3. 使用 LLM 生成每日大盤復盤報告

台股市場：
- TAIEX (加權指數)：主要上市股票指數
- TPEX (櫃買指數)：上櫃市場指數
- 交易時間：09:00 - 13:30
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
import yfinance as yf

from config import get_config
from search_service import SearchService
from data_provider.yfinance_shared import YFINANCE_LOCK

logger = logging.getLogger(__name__)


@dataclass
class MarketIndex:
    """大盤指數數據"""
    code: str                    # 指數代碼
    name: str                    # 指數名稱
    current: float = 0.0         # 當前價格
    change: float = 0.0          # 漲跌
    change_pct: float = 0.0      # 漲跌幅 (%)
    open: float = 0.0            # 開盤價
    high: float = 0.0            # 最高價
    low: float = 0.0             # 最低價
    prev_close: float = 0.0      # 昨收價
    volume: float = 0.0          # 成交量
    amount: float = 0.0          # 成交額
    amplitude: float = 0.0       # 振幅 (%)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'current': self.current,
            'change': self.change,
            'change_pct': self.change_pct,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'volume': self.volume,
            'amount': self.amount,
            'amplitude': self.amplitude,
        }


@dataclass
class MarketOverview:
    """市場概況數據"""
    date: str                           # 日期
    indices: List[MarketIndex] = field(default_factory=list)  # 主要指數
    up_count: int = 0                   # 上漲家數
    down_count: int = 0                 # 下跌家數
    flat_count: int = 0                 # 平盤家數
    limit_up_count: int = 0             # 漲停家數
    limit_down_count: int = 0           # 跌停家數
    total_amount: float = 0.0           # 總成交金額 (億台幣)
    foreign_flow: float = 0.0           # 外資買賣超 (億台幣)
    
    # 板塊排名
    top_sectors: List[Dict] = field(default_factory=list)     # 前 5 名板塊
    bottom_sectors: List[Dict] = field(default_factory=list)  # 後 5 名板塊


class MarketAnalyzer:
    """
    台股大盤復盤分析器
    
    功能：
    1. 獲取台股指數（加權指數、櫃買指數等）
    2. 獲取市場統計量
    3. 搜索市場新聞
    4. 生成大盤復盤報告
    """
    
    # 台股主要指數（Yahoo Finance 代碼）
    MAIN_INDICES = {
        '^TWII': '加權指數',
        '0050.TW': '元大台灣50',
        '0056.TW': '元大高股息',
        '2330.TW': '台積電',  # Reference stock
    }
    
    def __init__(self, search_service: Optional[SearchService] = None, analyzer=None):
        """
        初始化市場分析器
        
        Args:
            search_service: 搜索服務實例
            analyzer: AI 分析器實例（用於 LLM 調用）
        """
        self.config = get_config()
        self.search_service = search_service
        self.analyzer = analyzer
        
    def get_market_overview(self) -> MarketOverview:
        """
        獲取市場概況數據
        
        Returns:
            MarketOverview: 市場概況數據對象
        """
        today = datetime.now().strftime('%Y-%m-%d')
        overview = MarketOverview(date=today)
        
        # 1. 獲取主要指數
        overview.indices = self._get_main_indices()
        
        # 2. 獲取市場統計數據（從樣本股估算）
        self._get_market_statistics(overview)
        
        return overview
    
    def _get_main_indices(self) -> List[MarketIndex]:
        """使用 yfinance 獲取台股主要指數"""
        indices = []
        
        try:
            logger.info("[Market] 正在獲取台股主要指數...")
            
            for code, name in self.MAIN_INDICES.items():
                try:
                    with YFINANCE_LOCK:
                        ticker = yf.Ticker(code)
                        hist = ticker.history(period="2d")
                    
                    if hist is not None and len(hist) >= 1:
                        # 獲取最新數據
                        latest = hist.iloc[-1]
                        prev = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
                        
                        current = float(latest['Close'])
                        prev_close = float(prev['Close'])
                        change = current - prev_close
                        change_pct = (change / prev_close * 100) if prev_close > 0 else 0
                        
                        index = MarketIndex(
                            code=code,
                            name=name,
                            current=current,
                            change=change,
                            change_pct=change_pct,
                            open=float(latest['Open']),
                            high=float(latest['High']),
                            low=float(latest['Low']),
                            prev_close=prev_close,
                            volume=float(latest['Volume']),
                        )
                        
                        # 計算振幅
                        if index.prev_close > 0:
                            index.amplitude = (index.high - index.low) / index.prev_close * 100
                        
                        indices.append(index)
                        logger.info(f"[Market] {name}: {current:.2f} ({change_pct:+.2f}%)")
                        
                except Exception as e:
                    logger.warning(f"[Market] 獲取 {name} 失敗: {e}")
                    
            logger.info(f"[Market] 成功獲取 {len(indices)} 條指數數據")
                
        except Exception as e:
            logger.error(f"[Market] 獲取指數失敗: {e}")
        
        return indices
    
    def _get_market_statistics(self, overview: MarketOverview):
        """從台股樣本股獲取市場統計量"""
        try:
            logger.info("[Market] 正在從樣本股獲取市場統計數據...")
            
            # 用於估算市場情緒的台股樣本股
            sample_stocks = [
                '2330.TW', '2317.TW', '2454.TW', '2412.TW', '2881.TW',
                '2882.TW', '2303.TW', '1301.TW', '2891.TW', '3008.TW',
                '2308.TW', '1303.TW', '2886.TW', '2884.TW', '3711.TW',
                '2357.TW', '2382.TW', '2892.TW', '5880.TW', '2912.TW',
            ]
            
            up_count = 0
            down_count = 0
            flat_count = 0
            total_volume = 0
            
            for stock in sample_stocks:
                try:
                    with YFINANCE_LOCK:
                        ticker = yf.Ticker(stock)
                        hist = ticker.history(period="2d")
                    
                    if hist is not None and len(hist) >= 2:
                        current = hist.iloc[-1]['Close']
                        prev = hist.iloc[-2]['Close']
                        change_pct = (current - prev) / prev * 100 if prev > 0 else 0
                        
                        if change_pct > 0.1:
                            up_count += 1
                        elif change_pct < -0.1:
                            down_count += 1
                        else:
                            flat_count += 1
                            
                        total_volume += hist.iloc[-1]['Volume']
                        
                except Exception:
                    pass
            
            # 根據樣本股估算全市場數據
            scale_factor = 50  # 粗略估算：樣本股約佔市場的 2%
            overview.up_count = up_count * scale_factor
            overview.down_count = down_count * scale_factor
            overview.flat_count = flat_count * scale_factor
            
            # 估算總成交金額（單位：億台幣）
            overview.total_amount = total_volume * 500 / 1e9 * scale_factor  # 粗略估算
            
            logger.info(f"[Market] 樣本統計: 上漲 {up_count}, 下跌 {down_count}, 平盤 {flat_count}")
                
        except Exception as e:
            logger.error(f"[Market] 獲取統計量失敗: {e}")
    
    def search_market_news(self) -> List[Dict]:
        """
        搜索台股市場新聞
        
        Returns:
            新聞列表
        """
        if not self.search_service:
            logger.warning("[Market] 搜索服務未配置，跳過新聞搜索")
            return []
        
        all_news = []
        today = datetime.now()
        month_str = f"{today.year}年{today.month}月"
        
        # 多維度搜索 - 專注台股
        search_queries = [
            f"台股 大盤 行情 {month_str}",
            f"台灣股市 分析 今日 {month_str}",
            f"加權指數 分析 走勢 {month_str}",
        ]
        
        try:
            logger.info("[Market] 正在搜索台股市場新聞...")
            
            for query in search_queries:
                response = self.search_service.search_stock_news(
                    stock_code="market",
                    stock_name="台股",
                    max_results=3,
                    focus_keywords=query.split()
                )
                if response and response.results:
                    all_news.extend(response.results)
                    logger.info(f"[Market] 搜索 '{query}' 獲得 {len(response.results)} 條結果")
            
            logger.info(f"[Market] 共獲取 {len(all_news)} 條市場新聞")
            
        except Exception as e:
            logger.error(f"[Market] 搜索市場新聞失敗: {e}")
        
        return all_news
    
    def generate_market_review(self, overview: MarketOverview, news: List) -> str:
        """
        使用 LLM 生成台股市場復盤報告
        
        Args:
            overview: 市場概覽數據
            news: 市場新聞列表
            
        Returns:
            大盤復盤報告文本
        """
        if not self.analyzer or not self.analyzer.is_available():
            logger.warning("[Market] AI 分析器不可用，使用模板生成")
            return self._generate_template_review(overview, news)
        
        # 構建 Prompt
        prompt = self._build_review_prompt(overview, news)
        
        try:
            logger.info("[Market] 正在調用 LLM 生成復盤報告...")
            
            generation_config = {
                'temperature': 0.7,
                'max_output_tokens': 2048,
            }
            
            # 根據分析器類型調用 API
            if self.analyzer._use_openai:
                review = self.analyzer._call_openai_api(prompt, generation_config)
            else:
                response = self.analyzer._model.generate_content(
                    prompt,
                    generation_config=generation_config,
                )
                review = response.text.strip() if response and response.text else None
            
            if review:
                logger.info(f"[Market] 復盤報告生成成功，長度: {len(review)} 字符")
                return review
            else:
                logger.warning("[Market] LLM 返回內容為空")
                return self._generate_template_review(overview, news)
                
        except Exception as e:
            logger.error(f"[Market] LLM 生成失敗: {e}")
            return self._generate_template_review(overview, news)
    
    def _build_review_prompt(self, overview: MarketOverview, news: List) -> str:
        """構建台股大盤復盤 Prompt"""
        # 指數信息
        indices_text = ""
        for idx in overview.indices:
            direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
            indices_text += f"- {idx.name}: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"
        
        # 新聞信息
        news_text = ""
        for i, n in enumerate(news[:6], 1):
            if hasattr(n, 'title'):
                title = n.title[:50] if n.title else ''
                snippet = n.snippet[:100] if n.snippet else ''
            else:
                title = n.get('title', '')[:50]
                snippet = n.get('snippet', '')[:100]
            news_text += f"{i}. {title}\n   {snippet}\n"
        
        prompt = f"""你是一位專業的台灣股市分析師，請根據以下數據生成一份簡潔的大盤復盤報告。

【重要】輸出要求：
- 必須輸出純 Markdown 文本格式
- 禁止輸出 JSON 格式
- 禁止輸出代碼塊
- 使用繁體中文
- emoji 僅在標題處少量使用

---

# 今日市場數據

## 日期
{overview.date}

## 主要指數
{indices_text}

## 市場概況
- 上漲: {overview.up_count} 家 | 下跌: {overview.down_count} 家 | 平盤: {overview.flat_count} 家
- 估計成交金額: {overview.total_amount:.0f} 億台幣

## 市場新聞
{news_text if news_text else "暫無相關新聞"}

---

# 輸出格式模板（請嚴格按此格式輸出）

## 📊 {overview.date} 台股復盤

### 一、市場總結
（2-3句話概括今日市場整體表現，包括指數漲跌、成交量變化）

### 二、指數點評
（分析加權指數、櫃買指數等各指數走勢特點）

### 三、資金動向
（解讀成交量和外資動向的含義）

### 四、熱點解讀
（分析領漲領跌板塊背後的邏輯和驅動因素）

### 五、後市展望
（結合當前走勢和新聞，給出明日市場預判）

### 六、風險提示
（需要關注的風險點）

---

請直接輸出復盤報告內容，不要輸出其他說明文字。使用繁體中文。
"""
        return prompt
    
    def _generate_template_review(self, overview: MarketOverview, news: List) -> str:
        """生成模板復盤（無 LLM 時的兜底方案）"""
        
        # 判斷市場情緒
        taiex = next((idx for idx in overview.indices if '^TWII' in idx.code), None)
        if taiex:
            if taiex.change_pct > 1:
                market_mood = "強勢上漲"
            elif taiex.change_pct > 0:
                market_mood = "小幅上漲"
            elif taiex.change_pct > -1:
                market_mood = "小幅下跌"
            else:
                market_mood = "明顯下跌"
        else:
            market_mood = "震盪整理"
        
        # 指數信息
        indices_text = ""
        for idx in overview.indices[:4]:
            direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
            indices_text += f"- **{idx.name}**: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n"
        
        report = f"""## 📊 {overview.date} 台股復盤

### 一、市場總結
今日台股市場整體呈現**{market_mood}**態勢。

### 二、主要指數
{indices_text}

### 三、漲跌統計
| 指標 | 數值 |
|------|------|
| 上漲家數 | {overview.up_count} |
| 下跌家數 | {overview.down_count} |
| 平盤家數 | {overview.flat_count} |
| 估計成交額 | {overview.total_amount:.0f}億 |

### 四、風險提示
市場有風險，投資需謹慎。以上數據僅供參考，不構成投資建議。

---
*復盤時間: {datetime.now().strftime('%H:%M')}*
"""
        return report
    
    def run_daily_review(self) -> str:
        """
        執行每日大盤復盤流程
        
        Returns:
            復盤報告文本
        """
        logger.info("========== 開始執行台股大盤復盤分析 ==========")
        
        # 1. 獲取市場概況數據
        overview = self.get_market_overview()
        
        # 2. 搜索市場新聞
        news = self.search_market_news()
        
        # 3. 生成復盤報告
        report = self.generate_market_review(overview, news)
        
        logger.info("========== 台股大盤復盤分析執行完畢 ==========")
        
        return report


# 測試入口
if __name__ == "__main__":
    import sys
    sys.path.insert(0, '.')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    )
    
    analyzer = MarketAnalyzer()
    
    # 測試獲取市場概況
    overview = analyzer.get_market_overview()
    print(f"\n=== 市場概況 ===")
    print(f"日期: {overview.date}")
    print(f"指數數量: {len(overview.indices)}")
    for idx in overview.indices:
        print(f"  {idx.name}: {idx.current:.2f} ({idx.change_pct:+.2f}%)")
    print(f"上漲: {overview.up_count} | 下跌: {overview.down_count}")
    
    # 測試模板報告
    report = analyzer._generate_template_review(overview, [])
    print(f"\n=== 復盤報告 ===")
    print(report)
