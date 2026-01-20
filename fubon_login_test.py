# -*- coding: utf-8 -*-
"""
Fubon Neo SDK 登入測試
請先填入您的帳號資訊後執行
"""

from fubon_neo.sdk import FubonSDK

sdk = FubonSDK()

# ===== 請填入您的帳號資訊 =====
ID_NUMBER = "S125161019"           # 身分證字號
LOGIN_PASSWORD = "Eggegg061026"         # 富邦網銀密碼
CERT_PATH = r"C:\CAFubon\S125161019\S125161019.pfx"  # 憑證路徑
CERT_PASSWORD = "s339423"          # 憑證密碼
# ==============================

try:
    print("正在登入 Fubon Neo...")
    accounts = sdk.login(ID_NUMBER, LOGIN_PASSWORD, CERT_PATH, CERT_PASSWORD)
    
    if accounts.is_success:
        print("✅ 登入成功！")
        print(f"帳戶數量: {len(accounts.data)}")
        for i, acc in enumerate(accounts.data):
            print(f"  帳戶 {i+1}: {acc.account}")
    else:
        print(f"❌ 登入失敗: {accounts.message}")
        
except Exception as e:
    print(f"❌ 發生錯誤: {e}")
