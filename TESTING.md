# 台股系統快速測試指令

## 1. 測試台股數據獲取（單一股票）

```bash
python -c "from data_provider.taiwan_stock_fetcher import TaiwanStockFetcher; f = TaiwanStockFetcher(); df = f.get_daily_data('2330.TW', days=5); print(f'\n✅ 成功獲取 {len(df)} 筆資料\n'); print(df[['date', 'close', 'volume', 'pct_chg']].tail(3))"
```

## 2. 測試完整分析流程（台積電，不推送）

```bash
python main.py --stocks 2330.TW --no-notify
```

## 3. 測試多隻股票分析

```bash
python main.py --stocks 2330.TW,2317.TW,2454.TW --no-notify
```

## 4. 運行完整流程（含推送，需先配置 .env）

```bash
python main.py
```

## 5. 僅運行大盤復盤

```bash
python main.py --market-review
```

## 測試範例股票

| 代碼 | 名稱 | 類型 |
|------|------|------|
| 2330.TW | 台積電 | 半導體龍頭 |
| 2317.TW | 鴻海 | 電子製造 |
| 2454.TW | 聯發科 | IC設計 |
| 2412.TW | 中華電 | 電信 |
| 2881.TW | 富邦金 | 金融 |
