# -*- coding: utf-8 -*-
"""
===================================
台股自選股智能分析系統 - 主調度程序
===================================

職責：
1. 協調各模組完成股票分析流程
2. 實現低併發的線程池調度
3. 全局異常處理，確保單股失敗不影響整體
4. 提供命令行入口

使用方式：
    python main.py              # 正常執行
    python main.py --debug      # 調試模式
    python main.py --dry-run    # 僅獲取數據不分析

交易理念（已融入分析）：
- 嚴進策略：不追高，乖離率 > 5% 不買入
- 趨勢交易：只做 MA5>MA10>MA20 多頭排列
- 效率優先：關注籌碼集中度好的股票
- 買點偏好：縮量回踩 MA5/MA10 支撐
"""
import os

# 代理配置 - 僅在本地環境使用，GitHub Actions 不需要
if os.getenv("GITHUB_ACTIONS") != "true":
    # 本地開發環境，如需代理請取消註釋或修改端口
    # os.environ["http_proxy"] = "http://127.0.0.1:10809"
    # os.environ["https_proxy"] = "http://127.0.0.1:10809"
    pass

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timezone, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from tqdm import tqdm
from feishu_doc import FeishuDocManager

from config import get_config, Config
from storage import get_db, DatabaseManager
from data_provider import DataFetcherManager
# Removed: AkShare (A-stock only)
from analyzer import GeminiAnalyzer, AnalysisResult, STOCK_NAME_MAP
from notification import NotificationService, NotificationChannel, send_daily_report
from search_service import SearchService, SearchResponse
from stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult
from market_analyzer import MarketAnalyzer

# 配置日誌格式
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup_logging(debug: bool = False, log_dir: str = "./logs") -> None:
    """
    配置日誌系統（同時輸出到控制台和文件）
    
    Args:
        debug: 是否啟用調試模式
        log_dir: 日誌文件目錄
    """
    level = logging.DEBUG if debug else logging.INFO
    
    # 創建日誌目錄
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # 日誌文件路徑（按日期分文件）
    today_str = datetime.now().strftime('%Y%m%d')
    log_file = log_path / f"stock_analysis_{today_str}.log"
    debug_log_file = log_path / f"stock_analysis_debug_{today_str}.log"
    
    # 創建根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # 根 logger 設為 DEBUG，由 handler 控制輸出級別
    
    # Handler 1: 控制台輸出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(console_handler)
    
    # Handler 2: 常規日誌文件（INFO 級別，10MB 輪轉）
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(file_handler)
    
    # Handler 3: 調試日誌文件（DEBUG 級別，包含所有詳細信息）
    debug_handler = RotatingFileHandler(
        debug_log_file,
        maxBytes=50 * 1024 * 1024,  # 50MB
        backupCount=3,
        encoding='utf-8'
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(debug_handler)
    
    # 降低第三方庫的日誌級別
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    logging.getLogger('google').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    
    logging.info(f"日誌系統初始化完成，日誌目錄: {log_path.absolute()}")
    logging.info(f"常規日誌: {log_file}")
    logging.info(f"調試日誌: {debug_log_file}")


logger = logging.getLogger(__name__)


class StockAnalysisPipeline:
    """
    股票分析主流程調度器
    
    職責：
    1. 管理整個分析流程
    2. 協調數據獲取、存儲、搜索、分析、通知等模組
    3. 實現併發控制和異常處理
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        max_workers: Optional[int] = None
    ):
        """
        初始化調度器
        
        Args:
            config: 配置對象（可選，默認使用全局配置）
            max_workers: 最大併發線程數（可選，默認從配置讀取）
        """
        self.config = config or get_config()
        self.max_workers = max_workers or self.config.max_workers
        
        # 初始化各模組
        self.db = get_db()
        self.fetcher_manager = DataFetcherManager()
        # Note: Using YFinance for Taiwan stocks, no separate realtime fetcher needed
        self.trend_analyzer = StockTrendAnalyzer()  # 趨勢分析器
        self.analyzer = GeminiAnalyzer()
        self.notifier = NotificationService()
        
        # 初始化搜索服務
        self.search_service = SearchService(
            tavily_keys=self.config.tavily_api_keys,
            serpapi_keys=self.config.serpapi_keys,
        )
        
        logger.info(f"調度器初始化完成，最大併發數: {self.max_workers}")
        if hasattr(self.trend_analyzer, 'strategy'):
             logger.info(f"已啟用趨勢分析器 (策略: {self.trend_analyzer.strategy.name})")
        else:
             logger.info("已啟用趨勢分析器")
        if self.search_service.is_available:
            logger.info("搜索服務已啟用 (Tavily/SerpAPI)")
        else:
            logger.warning("搜索服務未啟用（未配置 API Key）")
    
    def fetch_and_save_stock_data(
        self, 
        code: str,
        force_refresh: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        獲取並保存單家股票數據
        
        斷點續傳邏輯：
        1. 檢查數據庫是否已有今日數據
        2. 如果有且不強制刷新，則跳過網絡請求
        3. 否則從數據源獲取並保存
        
        Args:
            code: 股票代碼
            force_refresh: 是否強制刷新（忽略本地緩存）
            
        Returns:
            Tuple[是否成功, 錯誤信息]
        """
        try:
            today = date.today()
            
            # 斷點續傳檢查：如果今日數據已存在，跳過
            if not force_refresh and self.db.has_today_data(code, today):
                logger.info(f"[{code}] 今日數據已存在，跳過獲取（斷點續傳）")
                return True, None
            
            # 從數據源獲取數據
            logger.info(f"[{code}] 開始從數據源獲取數據...")
            df, source_name = self.fetcher_manager.get_daily_data(code, days=30)
            
            if df is None or df.empty:
                return False, "獲取數據為空"
            
            # 保存到數據庫
            saved_count = self.db.save_daily_data(df, code, source_name)
            logger.info(f"[{code}] 數據保存成功（來源: {source_name}，新增 {saved_count} 條）")
            
            return True, None
            
        except Exception as e:
            error_msg = f"獲取/保存數據失敗: {str(e)}"
            logger.error(f"[{code}] {error_msg}")
            return False, error_msg
    
    def analyze_stock(self, code: str) -> Optional[AnalysisResult]:
        """
        分析單家股票（增強版：量比、換手率、籌碼分析、多維度情報）
        
        流程：
        1. 獲取實時行情（量比、換手率）
        2. 獲取籌碼分佈
        3. 進行趨勢分析（基於交易理念）
        4. 多維度情報搜索（最新消息+風險排查+業績預期）
        5. 從數據庫獲取分析上下文
        6. 調用 AI 進行綜合分析
        
        Args:
            code: 股票代碼
            
        Returns:
            AnalysisResult 或 None（如果分析失敗）
        """
        try:
            # 獲取股票名稱
            # 優先順序: 1. STOCK_NAME_MAP 映射表  2. API 自動獲取  3. 股票代碼
            stock_name = STOCK_NAME_MAP.get(code, '')
            
            if not stock_name:
                # 嘗試從數據源自動獲取股票名稱
                stock_name = self.fetcher_manager.get_stock_name(code) or code
            
            logger.info(f"[{code}] {stock_name} - Using Taiwan stock analysis")

            
            # Step 2: Skip chip distribution (not available for Taiwan stocks via YFinance)
            # Taiwan uses institutional investor data instead, which requires different API
            
            # Step 3: 趨勢分析（基於交易理念）
            trend_result: Optional[TrendAnalysisResult] = None
            try:
                # 獲取歷史數據進行趨勢分析
                context = self.db.get_analysis_context(code)
                if context and 'raw_data' in context:
                    import pandas as pd
                    raw_data = context['raw_data']
                    if isinstance(raw_data, list) and len(raw_data) > 0:
                        df = pd.DataFrame(raw_data)
                        trend_result = self.trend_analyzer.analyze(df, code)
                        logger.info(f"[{code}] 趨勢分析: {trend_result.trend_status.value}, "
                                  f"買入信號={trend_result.buy_signal.value}, 評分={trend_result.signal_score}")
            except Exception as e:
                logger.warning(f"[{code}] 趨勢分析失敗: {e}")
            
            # Step 3.5: 獲取三大法人買賣超數據（籌碼面）
            institutional_data = None
            try:
                institutional_data = self.fetcher_manager.get_institutional_data(code)
                if institutional_data:
                    logger.info(f"[{code}] 三大法人: 外資 {institutional_data['foreign_net']:+,}張, "
                               f"投信 {institutional_data['trust_net']:+,}張, "
                               f"自營商 {institutional_data['dealer_net']:+,}張")
            except Exception as e:
                logger.warning(f"[{code}] 獲取三大法人數據失敗: {e}")
            
            # Step 4: 多維度情報搜索（最新消息+風險排查+業績預期）
            news_context = None
            if self.search_service.is_available:
                logger.info(f"[{code}] 開始多維度情報搜索...")
                
                # 使用多維度搜索（最多3次搜索）
                intel_results = self.search_service.search_comprehensive_intel(
                    stock_code=code,
                    stock_name=stock_name,
                    max_searches=3
                )
                
                # 格式化情報報告
                if intel_results:
                    news_context = self.search_service.format_intel_report(intel_results, stock_name)
                    total_results = sum(
                        len(r.results) for r in intel_results.values() if r.success
                    )
                    logger.info(f"[{code}] 情報搜索完成: 共 {total_results} 條結果")
                    logger.debug(f"[{code}] 情報搜索結果:\n{news_context}")
            else:
                logger.info(f"[{code}] 搜索服務不可用，跳過情報搜索")
            
            # Step 5: 獲取分析上下文（技術面數據）
            context = self.db.get_analysis_context(code)
            
            if context is None:
                logger.warning(f"[{code}] 無法獲取分析上下文，跳過分析")
                return None
            
            # Step 6: Enhance context (add trend analysis, stock name, institutional data)
            enhanced_context = self._enhance_context(
                context, 
                trend_result,
                stock_name,
                institutional_data
            )
            
            # Step 7: 調用 AI 分析（傳入增強的上下文和新聞）
            result = self.analyzer.analyze(enhanced_context, news_context=news_context)
            
            return result
            
        except Exception as e:
            logger.error(f"[{code}] 分析失敗: {e}")
            logger.exception(f"[{code}] 詳細錯誤信息:")
            return None
    
    def _enhance_context(
        self,
        context: Dict[str, Any],
        trend_result: Optional[TrendAnalysisResult],
        stock_name: str = "",
        institutional_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        增強分析上下文（台股版）
        
        將趨勢分析結果、股票名稱、三大法人數據添加到上下文中
        
        Args:
            context: 原始上下文
            trend_result: 趨勢分析結果
            stock_name: 股票名稱
            institutional_data: 三大法人買賣超數據
            
        Returns:
            增強後的上下文
        """
        enhanced = context.copy()
        
        # 添加股票名稱
        if stock_name:
            enhanced['stock_name'] = stock_name
        
        # 添加趨勢分析結果
        if trend_result:
            enhanced['trend_analysis'] = {
                'trend_status': trend_result.trend_status.value,
                'ma_alignment': trend_result.ma_alignment,
                'trend_strength': trend_result.trend_strength,
                'bias_ma5': trend_result.bias_ma5,
                'bias_ma10': trend_result.bias_ma10,
                'volume_status': trend_result.volume_status.value,
                'volume_trend': trend_result.volume_trend,
                'buy_signal': trend_result.buy_signal.value,
                'signal_score': trend_result.signal_score,
                'signal_reasons': trend_result.signal_reasons,
                'risk_factors': trend_result.risk_factors,
            }
        
        # 添加三大法人買賣超數據（籌碼面）
        if institutional_data:
            enhanced['institutional_investors'] = {
                'foreign_net': institutional_data.get('foreign_net', 0),
                'trust_net': institutional_data.get('trust_net', 0),
                'dealer_net': institutional_data.get('dealer_net', 0),
                'total_net': institutional_data.get('total_net', 0),
                'date': institutional_data.get('date', ''),
            }
        
        return enhanced

    
    def _describe_volume_ratio(self, volume_ratio: float) -> str:
        """
        量比描述
        
        量比 = 當前成交量 / 過去5日平均成交量
        """
        if volume_ratio < 0.5:
            return "極度萎縮"
        elif volume_ratio < 0.8:
            return "明顯萎縮"
        elif volume_ratio < 1.2:
            return "正常"
        elif volume_ratio < 2.0:
            return "溫和放量"
        elif volume_ratio < 3.0:
            return "明顯放量"
        else:
            return "巨量"
    
    def process_single_stock(
        self, 
        code: str,
        skip_analysis: bool = False
    ) -> Optional[AnalysisResult]:
        """
        處理單家股票的完整流程
        
        包括：
        1. 獲取數據
        2. 保存數據
        3. AI 分析
        
        此方法會被線程池調用，需要處理好異常
        
        Args:
            code: 股票代碼
            skip_analysis: 是否跳過 AI 分析
            
        Returns:
            AnalysisResult 或 None
        """
        logger.info(f"========== 開始處理 {code} ==========")
        
        try:
            # Step 1: 獲取並保存數據
            success, error = self.fetch_and_save_stock_data(code)
            
            if not success:
                logger.warning(f"[{code}] 數據獲取失敗: {error}")
                # 即使獲取失敗，也嘗試用已有數據分析
            
            # Step 2: AI 分析
            if skip_analysis:
                logger.info(f"[{code}] 跳過 AI 分析（dry-run 模式）")
                return None
            
            result = self.analyze_stock(code)
            
            if result:
                logger.info(
                    f"[{code}] 分析完成: {result.operation_advice}, "
                    f"評分 {result.sentiment_score}"
                )
            
            return result
            
        except Exception as e:
            # 捕獲所有異常，確保單股失敗不影響整體
            logger.exception(f"[{code}] 處理過程發生未知異常: {e}")
            return None
    
    def run(
        self, 
        stock_codes: Optional[List[str]] = None,
        dry_run: bool = False,
        send_notification: bool = True
    ) -> List[AnalysisResult]:
        """
        執行完整的分析流程
        
        流程：
        1. 獲取待分析的股票列表
        2. 使用線程池併發處理
        3. 收集分析結果
        4. 發送通知
        
        Args:
            stock_codes: 股票代碼列表（可選，默認使用配置中的自選股）
            dry_run: 是否僅獲取數據不分析
            send_notification: 是否發送推送通知
            
        Returns:
            分析結果列表
        """
        start_time = time.time()
        
        # 使用配置中的股票列表
        if stock_codes is None:
            self.config.refresh_stock_list()
            stock_codes = self.config.stock_list
        
        if not stock_codes:
            logger.error("未配置自選股列表，請在 .env 文件中設置 STOCK_LIST")
            return []
        
        logger.info(f"===== 開始分析 {len(stock_codes)} 只股票 =====")
        logger.info(f"股票列表: {', '.join(stock_codes)}")
        logger.info(f"併發數: {self.max_workers}, 模式: {'僅獲取數據' if dry_run else '完整分析'}")
        
        results: List[AnalysisResult] = []
        
        # 使用線程池併發處理
        # 注意：max_workers 設置較低（默認3）以避免觸發反爬
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交任務
            future_to_code = {
                executor.submit(
                    self.process_single_stock, 
                    code, 
                    skip_analysis=dry_run
                ): code
                for code in stock_codes
            }
            
            # 使用 tqdm 進度條收集結果
            with tqdm(
                total=len(stock_codes),
                desc="🤖 AI 分析進度",
                unit="股",
                ncols=80,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
            ) as pbar:
                for future in as_completed(future_to_code):
                    code = future_to_code[future]
                    try:
                        result = future.result()
                        if result:
                            results.append(result)
                            pbar.set_postfix_str(f"✅ {code}")
                        else:
                            pbar.set_postfix_str(f"⚠️ {code}")
                    except Exception as e:
                        logger.error(f"[{code}] 任務執行失敗: {e}")
                        pbar.set_postfix_str(f"❌ {code}")
                    pbar.update(1)
        
        # 統計
        elapsed_time = time.time() - start_time
        
        # dry-run 模式下，數據獲取成功即視為成功
        if dry_run:
            # 檢查哪些股票的數據今天已存在
            success_count = sum(1 for code in stock_codes if self.db.has_today_data(code))
            fail_count = len(stock_codes) - success_count
        else:
            success_count = len(results)
            fail_count = len(stock_codes) - success_count
        
        logger.info(f"===== 分析完成 =====")
        logger.info(f"成功: {success_count}, 失敗: {fail_count}, 耗時: {elapsed_time:.2f} 秒")
        
        # 發送通知
        if results and send_notification and not dry_run:
            self._send_notifications(results)
        
        return results
    
    def _send_notifications(self, results: List[AnalysisResult]) -> None:
        """
        發送分析結果通知
        
        生成決策儀表板格式的報告
        
        Args:
            results: 分析結果列表
        """
        try:
            logger.info("生成決策儀表板日報...")
            
            # 生成決策儀表板格式的詳細日報
            report = self.notifier.generate_dashboard_report(results)
            
            # 保存到本地
            filepath = self.notifier.save_report_to_file(report)
            logger.info(f"決策儀表板日報已保存: {filepath}")
            
            # 推送通知
            if self.notifier.is_available():
                channels = self.notifier.get_available_channels()

                # 企業微信：只發精簡版（平台限制）
                wechat_success = False
                if NotificationChannel.WECHAT in channels:
                    dashboard_content = self.notifier.generate_wechat_dashboard(results)
                    logger.info(f"企業微信儀表板長度: {len(dashboard_content)} 字符")
                    logger.debug(f"企業微信推送內容:\n{dashboard_content}")
                    wechat_success = self.notifier.send_to_wechat(dashboard_content)

                # 其他渠道：發完整報告（避免自定義 Webhook 被 wechat 截斷邏輯污染）
                non_wechat_success = False
                for channel in channels:
                    if channel == NotificationChannel.WECHAT:
                        continue
                    if channel == NotificationChannel.FEISHU:
                        non_wechat_success = self.notifier.send_to_feishu(report) or non_wechat_success
                    elif channel == NotificationChannel.TELEGRAM:
                        non_wechat_success = self.notifier.send_to_telegram(report) or non_wechat_success
                    elif channel == NotificationChannel.EMAIL:
                        non_wechat_success = self.notifier.send_to_email(report) or non_wechat_success
                    elif channel == NotificationChannel.CUSTOM:
                        non_wechat_success = self.notifier.send_to_custom(report) or non_wechat_success
                    else:
                        logger.warning(f"未知通知渠道: {channel}")

                success = wechat_success or non_wechat_success
                if success:
                    logger.info("決策儀表板推送成功")
                else:
                    logger.warning("決策儀表板推送失敗")
            else:
                logger.info("通知渠道未配置，跳過推送")
                
        except Exception as e:
            logger.error(f"發送通知失敗: {e}")


def parse_arguments() -> argparse.Namespace:
    """解析命令行參數"""
    parser = argparse.ArgumentParser(
        description='台股自選股智能分析系統',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python main.py                    # 正常執行
  python main.py --debug            # 調試模式
  python main.py --dry-run          # 僅獲取數據，不進行 AI 分析
  python main.py --stocks 2330,2317  # 指定分析特定股票
  python main.py --no-notify        # 不發送推送通知
  python main.py --schedule         # 啟用定時任務模式
  python main.py --market-review    # 僅執行大盤復盤
        '''
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='啟用調試模式，輸出詳細日誌'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='僅獲取數據，不進行 AI 分析'
    )
    
    parser.add_argument(
        '--stocks',
        type=str,
        help='指定要分析的股票代碼，逗號分隔（覆蓋配置文件）'
    )
    
    parser.add_argument(
        '--no-notify',
        action='store_true',
        help='不發送推送通知'
    )
    
    parser.add_argument(
        '--workers',
        type=int,
        default=None,
        help='併發線程數（默認使用配置值）'
    )
    
    parser.add_argument(
        '--schedule',
        action='store_true',
        help='啟用定時任務模式，每日定時執行'
    )
    
    parser.add_argument(
        '--market-review',
        action='store_true',
        help='僅執行大盤復盤分析'
    )
    
    parser.add_argument(
        '--no-market-review',
        action='store_true',
        help='跳過大盤復盤分析'
    )
    
    parser.add_argument(
        '--scan-tw50',
        action='store_true',
        help='掃描台股 50 成分股，篩選買入信號'
    )
    
    return parser.parse_args()


def run_market_review(notifier: NotificationService, analyzer=None, search_service=None) -> Optional[str]:
    """
    執行大盤復盤分析
    
    Args:
        notifier: 通知服務
        analyzer: AI分析器（可選）
        search_service: 搜索服務（可選）
    
    Returns:
        復盤報告文本
    """
    logger.info("開始執行大盤復盤分析...")
    
    try:
        market_analyzer = MarketAnalyzer(
            search_service=search_service,
            analyzer=analyzer
        )
        
        # 執行復盤
        review_report = market_analyzer.run_daily_review()
        
        if review_report:
            # 保存報告到文件
            date_str = datetime.now().strftime('%Y%m%d')
            report_filename = f"market_review_{date_str}.md"
            filepath = notifier.save_report_to_file(
                f"# 🎯 大盤復盤\n\n{review_report}", 
                report_filename
            )
            logger.info(f"大盤復盤報告已保存: {filepath}")
            
            # 推送通知
            if notifier.is_available():
                # 添加標題
                report_content = f"🎯 大盤復盤\n\n{review_report}"
                
                success = notifier.send(report_content)
                if success:
                    logger.info("大盤復盤推送成功")
                else:
                    logger.warning("大盤復盤推送失敗")
            
            return review_report
        
    except Exception as e:
        logger.error(f"大盤復盤分析失敗: {e}")
    
    return None


def run_full_analysis(
    config: Config,
    args: argparse.Namespace,
    stock_codes: Optional[List[str]] = None
):
    """
    執行完整的分析流程（個股 + 大盤復盤）
    
    這是定時任務調用的主函數
    """
    try:
        # 創建調度器
        pipeline = StockAnalysisPipeline(
            config=config,
            max_workers=args.workers
        )
        
        # 1. 運行個股分析
        results = pipeline.run(
            stock_codes=stock_codes,
            dry_run=args.dry_run,
            send_notification=not args.no_notify
        )
        
        # 2. 運行大盤復盤（如果啟用且不是僅個股模式）
        market_report = ""
        if config.market_review_enabled and not args.no_market_review:
            # 只調用一次，並獲取結果
            review_result = run_market_review(
                notifier=pipeline.notifier,
                analyzer=pipeline.analyzer,
                search_service=pipeline.search_service
            )
            # 如果有結果，賦值給 market_report 用於後續飛書文檔生成
            if review_result:
                market_report = review_result
        
        # 輸出摘要
        if results:
            logger.info("\n===== 分析結果摘要 =====")
            for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
                emoji = r.get_emoji()
                logger.info(
                    f"{emoji} {r.name}({r.code}): {r.operation_advice} | "
                    f"評分 {r.sentiment_score} | {r.trend_prediction}"
                )
        
        logger.info("\n任務執行完成")

        # === 新增：生成飛書雲文檔 ===
        try:
            feishu_doc = FeishuDocManager()
            if feishu_doc.is_configured() and (results or market_report):
                logger.info("正在創建飛書雲文檔...")

                # 1. 準備標題 "01-01 13:01大盤復盤"
                tz_cn = timezone(timedelta(hours=8))
                now = datetime.now(tz_cn)
                doc_title = f"{now.strftime('%Y-%m-%d %H:%M')} 大盤復盤"

                # 2. 準備內容 (拼接個股分析和大盤復盤)
                full_content = ""

                # 添加大盤復盤內容（如果有）
                if market_report:
                    full_content += f"# 📈 大盤復盤\n\n{market_report}\n\n---\n\n"

                # 添加個股決策儀表板（使用 NotificationService 生成）
                if results:
                    dashboard_content = pipeline.notifier.generate_dashboard_report(results)
                    full_content += f"# 🚀 個股決策儀表板\n\n{dashboard_content}"

                # 3. 創建文檔
                doc_url = feishu_doc.create_daily_doc(doc_title, full_content)
                if doc_url:
                    logger.info(f"飛書雲文檔創建成功: {doc_url}")
                    # 可選：將文檔鏈接也推送到群裡
                    pipeline.notifier.send(f"[{now.strftime('%Y-%m-%d %H:%M')}] 復盤文檔創建成功: {doc_url}")

        except Exception as e:
            logger.error(f"飛書文檔生成失敗: {e}")
        
    except Exception as e:
        logger.exception(f"分析流程執行失敗: {e}")


def main() -> int:
    """
    主入口函數
    
    Returns:
        退出碼（0 表示成功）
    """
    # 解析命令行參數
    args = parse_arguments()
    
    # 加載配置（在設置日誌前加載，以獲取日誌目錄）
    config = get_config()
    
    # 配置日誌（輸出到控制台和文件）
    setup_logging(debug=args.debug, log_dir=config.log_dir)
    
    logger.info("=" * 60)
    logger.info("台股自選股智能分析系統 啟動")
    logger.info(f"執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # 驗證配置
    warnings = config.validate()
    for warning in warnings:
        logger.warning(warning)
    
    # 解析股票列表
    stock_codes = None
    if args.stocks:
        stock_codes = [code.strip() for code in args.stocks.split(',') if code.strip()]
        logger.info(f"使用命令行指定的股票列表: {stock_codes}")
    elif args.scan_tw50:
        from tw50_stocks import get_tw50_stocks
        stock_codes = get_tw50_stocks()
        logger.info(f"使用台股 50 成分股清單: 共 {len(stock_codes)} 檔")
    
    try:
        # 模式1: 僅大盤復盤
        if args.market_review:
            logger.info("模式: 僅大盤復盤")
            notifier = NotificationService()
            
            # 初始化搜索服務和分析器（如果有配置）
            search_service = None
            analyzer = None
            
            if config.tavily_api_keys or config.serpapi_keys:
                search_service = SearchService(
                    tavily_keys=config.tavily_api_keys,
                    serpapi_keys=config.serpapi_keys
                )
            
            if config.gemini_api_key:
                analyzer = GeminiAnalyzer(api_key=config.gemini_api_key)
            
            run_market_review(notifier, analyzer, search_service)
            return 0
        
        # 模式2: 定時任務模式
        if args.schedule or config.schedule_enabled:
            logger.info("模式: 定時任務")
            logger.info(f"每日執行時間: {config.schedule_time}")
            
            from scheduler import run_with_schedule
            
            def scheduled_task():
                run_full_analysis(config, args, stock_codes)
            
            run_with_schedule(
                task=scheduled_task,
                schedule_time=config.schedule_time,
                run_immediately=True  # 啟動時先執行一次
            )
            return 0
        
        # 模式3: 正常單次運行
        run_full_analysis(config, args, stock_codes)
        
        logger.info("\n程序執行完成")
        return 0
        
    except KeyboardInterrupt:
        logger.info("\n用戶中斷，程序退出")
        return 130
        
    except Exception as e:
        logger.exception(f"程序執行失敗: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
