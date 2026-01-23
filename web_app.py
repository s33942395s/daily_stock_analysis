# -*- coding: utf-8 -*-
"""
===================================
股票智能分析系統 - 網頁版分析工具
===================================

提供網頁介面進行台股/美股分析：
- 輸入股票代碼執行 AI 分析
- 支援台股 (2330.TW) 和美股 (AAPL)
- 即時顯示分析結果

啟動方式：
    python web_app.py
    
然後開啟瀏覽器訪問: http://localhost:5000
"""

import os
import sys
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from flask import Flask, render_template, request, jsonify

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化 Flask 應用
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # 支援中文 JSON

# 延遲導入以避免循環依賴
_pipeline = None
_fetcher_manager = None


def get_fetcher_manager():
    """獲取數據擷取器管理器（延遲初始化）"""
    global _fetcher_manager
    if _fetcher_manager is None:
        from data_provider import DataFetcherManager
        _fetcher_manager = DataFetcherManager()
    return _fetcher_manager


def get_pipeline():
    """獲取分析流水線（延遲初始化）"""
    global _pipeline
    if _pipeline is None:
        from main import StockAnalysisPipeline
        _pipeline = StockAnalysisPipeline()
    return _pipeline


def detect_market(code: str) -> str:
    """
    自動偵測股票市場
    
    Args:
        code: 股票代碼
        
    Returns:
        市場類型: 'TW', 'US', 或 'UNKNOWN'
    """
    code = code.strip().upper()
    
    # 台股格式
    if code.endswith('.TW') or code.endswith('.TWO'):
        return 'TW'
    
    # 純數字 4-6 位 = 台股
    if code.isdigit() and 4 <= len(code) <= 6:
        return 'TW'
    
    # 純英文 1-5 位 = 美股
    if code.replace('.', '').isalpha() and len(code.replace('.', '')) <= 5:
        return 'US'
    
    return 'UNKNOWN'


@app.route('/')
def index():
    """網頁主介面"""
    return render_template('index.html')


@app.route('/api/quote/<code>')
def get_quote(code: str):
    """
    獲取股票即時報價
    
    Args:
        code: 股票代碼
        
    Returns:
        JSON 格式的報價資訊
    """
    try:
        fetcher = get_fetcher_manager()
        
        # 獲取最近 5 天數據
        df, source = fetcher.get_daily_data(code, days=5)
        
        if df is None or df.empty:
            return jsonify({
                'success': False,
                'error': f'無法獲取 {code} 的數據'
            }), 404
        
        # 取最新一筆
        latest = df.iloc[-1]
        
        # 獲取股票名稱
        name = fetcher.get_stock_name(code) or code
        
        return jsonify({
            'success': True,
            'data': {
                'code': code,
                'name': name,
                'market': detect_market(code),
                'price': float(latest['close']),
                'change': float(latest['pct_chg']),
                'volume': int(latest['volume']),
                'date': latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else str(latest['date']),
                'source': source
            }
        })
        
    except Exception as e:
        logger.error(f"獲取報價失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/analyze', methods=['POST'])
def analyze_stock():
    """
    執行股票分析
    
    Request Body:
        {
            "code": "AAPL",
            "market": "US"  // 可選，自動偵測
        }
        
    Returns:
        JSON 格式的分析結果
    """
    try:
        data = request.get_json()
        code = data.get('code', '').strip().upper()
        
        if not code:
            return jsonify({
                'success': False,
                'error': '請輸入股票代碼'
            }), 400
        
        logger.info(f"開始分析股票: {code}")
        
        # 偵測市場
        market = data.get('market') or detect_market(code)
        
        # 獲取分析流水線
        pipeline = get_pipeline()
        
        # 先確保資料是最新的（強制刷新）
        logger.info(f"[{code}] 強制從數據源獲取最新資料...")
        success, error = pipeline.fetch_and_save_stock_data(code, force_refresh=True)
        if not success:
            logger.warning(f"[{code}] 資料更新失敗: {error}，嘗試使用現有資料分析")
        
        # 執行分析
        result = pipeline.analyze_stock(code)
        
        if result is None:
            return jsonify({
                'success': False,
                'error': f'無法分析 {code}，請確認代碼是否正確'
            }), 404
        
        # 轉換為 JSON 友善格式
        return jsonify({
            'success': True,
            'data': {
                'code': result.code,
                'name': result.name,
                'market': market,
                'sentiment_score': result.sentiment_score,
                'operation_advice': result.operation_advice,
                'trend_prediction': result.trend_prediction,
                'core_logic': result.core_logic,
                'key_signals': result.key_signals,
                'risk_warnings': result.risk_warnings,
                'sniper_strategy': result.sniper_strategy,
                'position_strategy': result.position_strategy,
                'position_advice': {
                    'no_position': result.get_position_advice(has_position=False),
                    'has_position': result.get_position_advice(has_position=True)
                },
                'checklist': result.checklist,
                'confidence': result.confidence,
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        })
        
    except Exception as e:
        logger.error(f"分析失敗: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/markets')
def get_markets():
    """獲取支援的市場列表"""
    return jsonify({
        'success': True,
        'data': [
            {
                'id': 'TW',
                'name': '台股',
                'description': '台灣證券交易所 (TWSE)',
                'examples': ['2330', '2317', '2454', '00923']
            },
            {
                'id': 'US',
                'name': '美股',
                'description': 'NYSE / NASDAQ',
                'examples': ['AAPL', 'MSFT', 'GOOGL', 'TSLA']
            }
        ]
    })


@app.route('/api/health')
def health_check():
    """健康檢查端點"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat()
    })


if __name__ == '__main__':
    print("\n" + "="*50)
    print("📈 股票智能分析系統 - 網頁版")
    print("="*50)
    print(f"\n🌐 請在瀏覽器開啟: http://localhost:5000")
    print("\n支援市場:")
    print("  • 台股: 2330, 2317, 00923.TW")
    print("  • 美股: AAPL, MSFT, GOOGL, TSLA")
    print("\n按 Ctrl+C 停止服務")
    print("="*50 + "\n")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        use_reloader=False  # 避免重複初始化
    )
