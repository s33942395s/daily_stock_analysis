# -*- coding: utf-8 -*-
"""
===================================
InstitutionalFetcher - 三大法人買賣超數據獲取
===================================

數據來源：
- 上市股票 (TWSE): 證交所公開資訊
- 上櫃股票 (TPEx): 櫃買中心公開資訊

提供功能：
1. 獲取個股三大法人買賣超數據
2. 自動判斷上市/上櫃並選擇正確 API
3. 數據快取避免重複請求
"""

import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class InstitutionalFetcher:
    """
    三大法人買賣超數據獲取器
    
    數據來源：
    - TWSE (上市): https://www.twse.com.tw
    - TPEx (上櫃): https://www.tpex.org.tw
    """
    
    # API 端點
    TWSE_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
    TPEX_URL = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
    
    def __init__(self):
        """初始化"""
        self._cache: Dict[str, Dict] = {}  # {date_code: data}
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
        logger.info("三大法人數據獲取器初始化完成")
    
    def get_institutional_data(
        self, 
        stock_code: str, 
        date: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        獲取個股三大法人買賣超數據
        
        Args:
            stock_code: 股票代碼 (如 2330, 2330.TW)
            date: 日期 (YYYY-MM-DD 格式，預設為最近交易日)
            
        Returns:
            {
                'date': '2026-01-17',
                'stock_code': '2330',
                'stock_name': '台積電',
                'foreign_net': 5000,     # 外資淨買賣超（張）
                'trust_net': 200,        # 投信淨買賣超（張）
                'dealer_net': -100,      # 自營商淨買賣超（張）
                'total_net': 5100,       # 三大法人合計
            }
            如果獲取失敗則返回 None
        """
        # 標準化股票代碼
        code = self._normalize_code(stock_code)
        
        # 處理日期
        if date is None:
            date = self._get_latest_trading_date()
        
        # 檢查快取
        cache_key = f"{date}_{code}"
        if cache_key in self._cache:
            logger.debug(f"[{code}] 從快取獲取三大法人數據")
            return self._cache[cache_key]
        
        # 嘗試從 TWSE (上市) 獲取
        data = self._fetch_twse(code, date)
        
        # 如果上市找不到，嘗試上櫃
        if data is None:
            data = self._fetch_tpex(code, date)
        
        # 存入快取
        if data:
            self._cache[cache_key] = data
            logger.info(f"[{code}] 三大法人數據: 外資 {data['foreign_net']:+,}張, "
                       f"投信 {data['trust_net']:+,}張, 自營商 {data['dealer_net']:+,}張")
        
        return data
    
    def _normalize_code(self, stock_code: str) -> str:
        """標準化股票代碼（去除 .TW/.TWO 後綴）"""
        code = stock_code.strip().upper()
        if code.endswith('.TW') or code.endswith('.TWO'):
            code = code.split('.')[0]
        return code
    
    def _get_latest_trading_date(self) -> str:
        """獲取最近交易日（簡單處理：週末往前推）"""
        today = datetime.now()
        # 如果是週六或週日，往前推到週五
        while today.weekday() >= 5:  # 5=Saturday, 6=Sunday
            today -= timedelta(days=1)
        return today.strftime('%Y-%m-%d')
    
    def _fetch_twse(self, code: str, date: str) -> Optional[Dict[str, Any]]:
        """
        從證交所獲取上市股票三大法人數據
        
        API: https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALLBUT0999&response=json
        """
        try:
            # 轉換日期格式
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            date_str = date_obj.strftime('%Y%m%d')
            
            params = {
                'date': date_str,
                'selectType': 'ALLBUT0999',
                'response': 'json',
            }
            
            logger.debug(f"[TWSE] 請求三大法人數據: {date_str}")
            response = self._session.get(self.TWSE_URL, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # 檢查是否有數據
            if data.get('stat') != 'OK' or 'data' not in data:
                logger.debug(f"[TWSE] 無數據或請求失敗: {data.get('stat')}")
                return None
            
            # 在數據中查找指定股票
            for row in data['data']:
                # row 格式: [證券代號, 證券名稱, 外陸資買進股數, 外陸資賣出股數, 外陸資買賣超股數, 
                #           外資自營商買進股數, ..., 投信買進, 投信賣出, 投信買賣超, 
                #           自營商買賣超, 三大法人買賣超合計]
                if row[0].strip() == code:
                    return self._parse_twse_row(row, date)
            
            logger.debug(f"[TWSE] 未找到股票 {code}")
            return None
            
        except Exception as e:
            logger.warning(f"[TWSE] 獲取失敗: {e}")
            return None
    
    def _parse_twse_row(self, row: list, date: str) -> Dict[str, Any]:
        """解析 TWSE 三大法人數據行"""
        # TWSE T86 欄位順序 (2024年格式):
        # 0: 證券代號
        # 1: 證券名稱
        # 2: 外陸資買進股數(不含外資自營商)
        # 3: 外陸資賣出股數(不含外資自營商)
        # 4: 外陸資買賣超股數(不含外資自營商)
        # 5: 外資自營商買進股數
        # 6: 外資自營商賣出股數
        # 7: 外資自營商買賣超股數
        # 8: 投信買進股數
        # 9: 投信賣出股數
        # 10: 投信買賣超股數
        # 11: 自營商買賣超股數
        # 12: 自營商買進股數(自行買賣)
        # 13: 自營商賣出股數(自行買賣)
        # 14: 自營商買賣超股數(自行買賣)
        # 15: 自營商買進股數(避險)
        # 16: 自營商賣出股數(避險)
        # 17: 自營商買賣超股數(避險)
        # 18: 三大法人買賣超股數
        
        def parse_num(val):
            """解析數字（處理逗號和負號）"""
            if isinstance(val, (int, float)):
                return int(val)
            s = str(val).replace(',', '').replace(' ', '')
            try:
                return int(s)
            except ValueError:
                return 0
        
        # 外資 = 外陸資(不含自營商) + 外資自營商
        foreign_net = parse_num(row[4]) + parse_num(row[7])
        # 投信
        trust_net = parse_num(row[10])
        # 自營商合計
        dealer_net = parse_num(row[11])
        # 三大法人合計
        total_net = parse_num(row[18]) if len(row) > 18 else (foreign_net + trust_net + dealer_net)
        
        # 轉換為張 (股數 / 1000)
        return {
            'date': date,
            'stock_code': row[0].strip(),
            'stock_name': row[1].strip(),
            'foreign_net': foreign_net // 1000,
            'trust_net': trust_net // 1000,
            'dealer_net': dealer_net // 1000,
            'total_net': total_net // 1000,
        }
    
    def _fetch_tpex(self, code: str, date: str) -> Optional[Dict[str, Any]]:
        """
        從櫃買中心獲取上櫃股票三大法人數據
        
        API: https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php
        """
        try:
            # 轉換日期格式 (民國年/月/日)
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            roc_year = date_obj.year - 1911
            date_str = f"{roc_year}/{date_obj.month:02d}/{date_obj.day:02d}"
            
            params = {
                'l': 'zh-tw',
                'd': date_str,
                'se': 'EW',
                't': 'D', 
                'o': 'json',
            }
            
            logger.debug(f"[TPEx] 請求三大法人數據: {date_str}")
            response = self._session.get(self.TPEX_URL, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # 檢查是否有數據
            if 'aaData' not in data:
                logger.debug(f"[TPEx] 無數據")
                return None
            
            # 在數據中查找指定股票
            for row in data['aaData']:
                if row[0].strip() == code:
                    return self._parse_tpex_row(row, date)
            
            logger.debug(f"[TPEx] 未找到股票 {code}")
            return None
            
        except Exception as e:
            logger.warning(f"[TPEx] 獲取失敗: {e}")
            return None
    
    def _parse_tpex_row(self, row: list, date: str) -> Dict[str, Any]:
        """解析 TPEx 三大法人數據行"""
        # TPEx 欄位順序:
        # 0: 代號
        # 1: 名稱
        # 2: 外資及陸資買股數
        # 3: 外資及陸資賣股數
        # 4: 外資及陸資淨買股數
        # 5: 投信買進股數
        # 6: 投信賣出股數
        # 7: 投信淨買股數
        # 8: 自營商買賣超股數
        # 9: 三大法人買賣超股數
        
        def parse_num(val):
            if isinstance(val, (int, float)):
                return int(val)
            s = str(val).replace(',', '').replace(' ', '')
            try:
                return int(s)
            except ValueError:
                return 0
        
        foreign_net = parse_num(row[4])
        trust_net = parse_num(row[7])
        dealer_net = parse_num(row[8])
        total_net = parse_num(row[9]) if len(row) > 9 else (foreign_net + trust_net + dealer_net)
        
        # 轉換為張
        return {
            'date': date,
            'stock_code': row[0].strip(),
            'stock_name': row[1].strip(),
            'foreign_net': foreign_net // 1000,
            'trust_net': trust_net // 1000,
            'dealer_net': dealer_net // 1000,
            'total_net': total_net // 1000,
        }


# 測試入口
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
    )
    
    fetcher = InstitutionalFetcher()
    
    # 測試上市股票
    test_codes = ['2330', '2317', '2454']
    
    for code in test_codes:
        print(f"\n{'='*50}")
        print(f"測試股票: {code}")
        print('='*50)
        
        data = fetcher.get_institutional_data(code)
        if data:
            print(f"股票名稱: {data['stock_name']}")
            print(f"日期: {data['date']}")
            print(f"外資: {data['foreign_net']:+,} 張")
            print(f"投信: {data['trust_net']:+,} 張")
            print(f"自營商: {data['dealer_net']:+,} 張")
            print(f"合計: {data['total_net']:+,} 張")
        else:
            print("獲取失敗")
