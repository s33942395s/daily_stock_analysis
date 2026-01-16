#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
簡繁轉換輔助腳本
使用 opencc 庫進行批量簡繁轉換
"""

def convert_file_to_traditional(file_path):
    """將檔案內容從簡體轉換為繁體"""
    try:
        from opencc import OpenCC
    except ImportError:
        print("需要安裝 opencc-python-reimplemented: pip install opencc-python-reimplemented")
        return False
    
    # 創建簡體到繁體轉換器
    cc = OpenCC('s2tw')  # 簡體到台灣繁體
    
    # 讀取檔案
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 轉換
    converted = cc.convert(content)
    
    # 寫回檔案
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(converted)
    
    print(f"已轉換: {file_path}")
    return True

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        convert_file_to_traditional(sys.argv[1])
    else:
        print("用法: python convert_s2t.py <檔案路徑>")
