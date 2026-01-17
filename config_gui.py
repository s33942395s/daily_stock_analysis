# -*- coding: utf-8 -*-
"""
===================================
台股智能分析系統 - 圖形化設定工具
===================================

提供友善的圖形介面讓使用者設定：
- 自選股列表
- API Keys (Gemini, OpenAI, Tavily, SerpAPI)
- 通知設定 (Telegram)
- 其他系統設定
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
from typing import Dict, Any, Optional
import re


class ConfigGUI:
    """圖形化設定介面"""
    
    # .env 檔案路徑
    ENV_PATH = Path(__file__).parent / '.env'
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("台股智能分析系統 - 設定工具")
        self.root.geometry("750x700")
        self.root.resizable(True, True)
        
        # 設定視窗最小尺寸
        self.root.minsize(650, 500)
        
        # 設定主題風格
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # 自訂樣式
        self.style.configure('Title.TLabel', font=('Microsoft JhengHei UI', 14, 'bold'))
        self.style.configure('Section.TLabelframe.Label', font=('Microsoft JhengHei UI', 10, 'bold'))
        self.style.configure('TButton', font=('Microsoft JhengHei UI', 10))
        self.style.configure('TLabel', font=('Microsoft JhengHei UI', 9))
        self.style.configure('TEntry', font=('Consolas', 10))
        
        # 儲存所有輸入欄位的變數
        self.vars: Dict[str, tk.StringVar] = {}
        
        # 建立主框架
        self._create_main_frame()
        
        # 載入現有設定
        self._load_config()
        
    def _create_main_frame(self):
        """建立主框架"""
        # 主容器（使用 Canvas + Scrollbar 實現捲動）
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Canvas 和捲軸
        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        
        # 可捲動框架
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 滑鼠滾輪綁定
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # 佈局
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 內容區域
        content = ttk.Frame(self.scrollable_frame, padding=20)
        content.pack(fill=tk.BOTH, expand=True)
        
        # 標題
        title_label = ttk.Label(
            content, 
            text="📈 台股智能分析系統 - 設定",
            style='Title.TLabel'
        )
        title_label.pack(pady=(0, 15))
        
        # === 自選股設定 ===
        self._create_stock_section(content)
        
        # === AI API 設定 ===
        self._create_ai_section(content)
        
        # === 搜尋引擎設定 ===
        self._create_search_section(content)
        
        # === 通知設定 ===
        self._create_notification_section(content)
        
        # === 系統設定 ===
        self._create_system_section(content)
        
        # === 按鈕區 ===
        self._create_button_area(content)
        
    def _create_stock_section(self, parent):
        """建立自選股設定區"""
        frame = ttk.LabelFrame(parent, text="📊 自選股設定", style='Section.TLabelframe', padding=10)
        frame.pack(fill=tk.X, pady=5)
        
        # 說明文字
        ttk.Label(
            frame,
            text="輸入股票代碼（每行一個，或用逗號分隔）\n支援格式：2330、2330.TW、00923.TW",
            justify=tk.LEFT,
            foreground='gray'
        ).pack(anchor=tk.W)
        
        # 文字區域
        self.stock_text = scrolledtext.ScrolledText(
            frame, 
            height=4, 
            width=60,
            font=('Consolas', 11)
        )
        self.stock_text.pack(fill=tk.X, pady=(5, 0))
        
    def _create_ai_section(self, parent):
        """建立 AI API 設定區"""
        frame = ttk.LabelFrame(parent, text="🤖 AI 模型設定", style='Section.TLabelframe', padding=10)
        frame.pack(fill=tk.X, pady=5)
        
        # Gemini 設定
        gemini_frame = ttk.Frame(frame)
        gemini_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(gemini_frame, text="Gemini API Key：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['GEMINI_API_KEY'] = tk.StringVar()
        gemini_entry = ttk.Entry(gemini_frame, textvariable=self.vars['GEMINI_API_KEY'], width=50, show='*')
        gemini_entry.pack(side=tk.LEFT, padx=5)
        
        # 顯示/隱藏按鈕
        self.gemini_show_btn = ttk.Button(
            gemini_frame, text="👁", width=3,
            command=lambda: self._toggle_show(gemini_entry, self.gemini_show_btn)
        )
        self.gemini_show_btn.pack(side=tk.LEFT)
        
        # Gemini Model
        model_frame = ttk.Frame(frame)
        model_frame.pack(fill=tk.X, pady=2)
        ttk.Label(model_frame, text="Gemini Model：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['GEMINI_MODEL'] = tk.StringVar()
        ttk.Combobox(
            model_frame, 
            textvariable=self.vars['GEMINI_MODEL'],
            values=['gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-2.0-flash-exp'],
            width=47
        ).pack(side=tk.LEFT, padx=5)
        
        # 分隔線
        ttk.Separator(frame, orient='horizontal').pack(fill=tk.X, pady=8)
        
        # OpenAI 設定
        ttk.Label(frame, text="或使用 OpenAI 兼容 API（DeepSeek 等）", foreground='gray').pack(anchor=tk.W)
        
        openai_key_frame = ttk.Frame(frame)
        openai_key_frame.pack(fill=tk.X, pady=2)
        ttk.Label(openai_key_frame, text="OpenAI API Key：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['OPENAI_API_KEY'] = tk.StringVar()
        openai_entry = ttk.Entry(openai_key_frame, textvariable=self.vars['OPENAI_API_KEY'], width=50, show='*')
        openai_entry.pack(side=tk.LEFT, padx=5)
        self.openai_show_btn = ttk.Button(
            openai_key_frame, text="👁", width=3,
            command=lambda: self._toggle_show(openai_entry, self.openai_show_btn)
        )
        self.openai_show_btn.pack(side=tk.LEFT)
        
        openai_url_frame = ttk.Frame(frame)
        openai_url_frame.pack(fill=tk.X, pady=2)
        ttk.Label(openai_url_frame, text="Base URL：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['OPENAI_BASE_URL'] = tk.StringVar()
        ttk.Entry(openai_url_frame, textvariable=self.vars['OPENAI_BASE_URL'], width=50).pack(side=tk.LEFT, padx=5)
        
        openai_model_frame = ttk.Frame(frame)
        openai_model_frame.pack(fill=tk.X, pady=2)
        ttk.Label(openai_model_frame, text="Model：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['OPENAI_MODEL'] = tk.StringVar()
        ttk.Combobox(
            openai_model_frame,
            textvariable=self.vars['OPENAI_MODEL'],
            values=['deepseek-chat', 'gpt-4o-mini', 'gpt-4o', 'gpt-3.5-turbo'],
            width=47
        ).pack(side=tk.LEFT, padx=5)
        
    def _create_search_section(self, parent):
        """建立搜尋引擎設定區"""
        frame = ttk.LabelFrame(parent, text="🔍 搜尋引擎設定（新聞搜尋）", style='Section.TLabelframe', padding=10)
        frame.pack(fill=tk.X, pady=5)
        
        # Tavily
        tavily_frame = ttk.Frame(frame)
        tavily_frame.pack(fill=tk.X, pady=2)
        ttk.Label(tavily_frame, text="Tavily API Keys：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['TAVILY_API_KEYS'] = tk.StringVar()
        tavily_entry = ttk.Entry(tavily_frame, textvariable=self.vars['TAVILY_API_KEYS'], width=50, show='*')
        tavily_entry.pack(side=tk.LEFT, padx=5)
        self.tavily_show_btn = ttk.Button(
            tavily_frame, text="👁", width=3,
            command=lambda: self._toggle_show(tavily_entry, self.tavily_show_btn)
        )
        self.tavily_show_btn.pack(side=tk.LEFT)
        
        # SerpAPI
        serp_frame = ttk.Frame(frame)
        serp_frame.pack(fill=tk.X, pady=2)
        ttk.Label(serp_frame, text="SerpAPI Keys：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['SERPAPI_API_KEYS'] = tk.StringVar()
        serp_entry = ttk.Entry(serp_frame, textvariable=self.vars['SERPAPI_API_KEYS'], width=50, show='*')
        serp_entry.pack(side=tk.LEFT, padx=5)
        self.serp_show_btn = ttk.Button(
            serp_frame, text="👁", width=3,
            command=lambda: self._toggle_show(serp_entry, self.serp_show_btn)
        )
        self.serp_show_btn.pack(side=tk.LEFT)
        
        ttk.Label(frame, text="💡 可填入多個 Key，用逗號分隔", foreground='gray').pack(anchor=tk.W, pady=(5,0))
        
    def _create_notification_section(self, parent):
        """建立通知設定區"""
        frame = ttk.LabelFrame(parent, text="📬 通知設定", style='Section.TLabelframe', padding=10)
        frame.pack(fill=tk.X, pady=5)
        
        # Telegram
        ttk.Label(frame, text="Telegram 機器人", font=('Microsoft JhengHei UI', 9, 'bold')).pack(anchor=tk.W)
        
        tg_token_frame = ttk.Frame(frame)
        tg_token_frame.pack(fill=tk.X, pady=2)
        ttk.Label(tg_token_frame, text="Bot Token：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['TELEGRAM_BOT_TOKEN'] = tk.StringVar()
        tg_entry = ttk.Entry(tg_token_frame, textvariable=self.vars['TELEGRAM_BOT_TOKEN'], width=50, show='*')
        tg_entry.pack(side=tk.LEFT, padx=5)
        self.tg_show_btn = ttk.Button(
            tg_token_frame, text="👁", width=3,
            command=lambda: self._toggle_show(tg_entry, self.tg_show_btn)
        )
        self.tg_show_btn.pack(side=tk.LEFT)
        
        tg_chat_frame = ttk.Frame(frame)
        tg_chat_frame.pack(fill=tk.X, pady=2)
        ttk.Label(tg_chat_frame, text="Chat ID：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['TELEGRAM_CHAT_ID'] = tk.StringVar()
        ttk.Entry(tg_chat_frame, textvariable=self.vars['TELEGRAM_CHAT_ID'], width=50).pack(side=tk.LEFT, padx=5)
        
    def _create_system_section(self, parent):
        """建立系統設定區"""
        frame = ttk.LabelFrame(parent, text="⚙️ 系統設定", style='Section.TLabelframe', padding=10)
        frame.pack(fill=tk.X, pady=5)
        
        # 定時任務
        schedule_frame = ttk.Frame(frame)
        schedule_frame.pack(fill=tk.X, pady=2)
        
        self.vars['SCHEDULE_ENABLED'] = tk.StringVar()
        schedule_check = ttk.Checkbutton(
            schedule_frame, 
            text="啟用定時任務",
            variable=self.vars['SCHEDULE_ENABLED'],
            onvalue='true',
            offvalue='false'
        )
        schedule_check.pack(side=tk.LEFT)
        
        ttk.Label(schedule_frame, text="執行時間：").pack(side=tk.LEFT, padx=(20, 5))
        self.vars['SCHEDULE_TIME'] = tk.StringVar()
        ttk.Entry(schedule_frame, textvariable=self.vars['SCHEDULE_TIME'], width=8).pack(side=tk.LEFT)
        ttk.Label(schedule_frame, text="（HH:MM 格式）", foreground='gray').pack(side=tk.LEFT, padx=5)
        
        # 策略選擇
        strategy_frame = ttk.Frame(frame)
        strategy_frame.pack(fill=tk.X, pady=2)
        ttk.Label(strategy_frame, text="分析策略：", width=18, anchor='e').pack(side=tk.LEFT)
        self.vars['STRATEGY_NAME'] = tk.StringVar()
        ttk.Combobox(
            strategy_frame,
            textvariable=self.vars['STRATEGY_NAME'],
            values=['TrendFollowing', 'MeanReversion'],
            width=47,
            state='readonly'
        ).pack(side=tk.LEFT, padx=5)
        
    def _create_button_area(self, parent):
        """建立按鈕區"""
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, pady=20)
        
        # 儲存按鈕
        save_btn = ttk.Button(
            button_frame,
            text="💾 儲存設定",
            command=self._save_config,
            style='TButton'
        )
        save_btn.pack(side=tk.RIGHT, padx=5)
        
        # 重新載入按鈕
        reload_btn = ttk.Button(
            button_frame,
            text="🔄 重新載入",
            command=self._load_config,
            style='TButton'
        )
        reload_btn.pack(side=tk.RIGHT, padx=5)
        
        # 測試執行按鈕
        test_btn = ttk.Button(
            button_frame,
            text="▶️ 執行分析",
            command=self._run_analysis,
            style='TButton'
        )
        test_btn.pack(side=tk.LEFT, padx=5)
        
    def _toggle_show(self, entry: ttk.Entry, button: ttk.Button):
        """切換密碼顯示/隱藏"""
        if entry.cget('show') == '*':
            entry.configure(show='')
            button.configure(text='🙈')
        else:
            entry.configure(show='*')
            button.configure(text='👁')
            
    def _load_config(self):
        """從 .env 檔案載入設定"""
        if not self.ENV_PATH.exists():
            messagebox.showwarning("提示", ".env 檔案不存在，將使用預設值")
            return
            
        try:
            # 讀取 .env 檔案
            env_content = self.ENV_PATH.read_text(encoding='utf-8')
            
            # 解析設定
            config = {}
            for line in env_content.splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    # 找到第一個 = 的位置
                    eq_pos = line.index('=')
                    key = line[:eq_pos].strip()
                    value = line[eq_pos+1:].strip()
                    config[key] = value
            
            # 設定 UI 變數
            for key, var in self.vars.items():
                if key in config:
                    var.set(config[key])
                    
            # 設定股票列表（特殊處理）
            stock_list = config.get('STOCK_LIST', '')
            # 將逗號分隔轉為換行
            stocks = [s.strip() for s in stock_list.split(',') if s.strip()]
            self.stock_text.delete('1.0', tk.END)
            self.stock_text.insert('1.0', '\n'.join(stocks))
            
            # 設定預設值
            if not self.vars['GEMINI_MODEL'].get():
                self.vars['GEMINI_MODEL'].set('gemini-3-flash-preview')
            if not self.vars['OPENAI_MODEL'].get():
                self.vars['OPENAI_MODEL'].set('deepseek-chat')
            if not self.vars['STRATEGY_NAME'].get():
                self.vars['STRATEGY_NAME'].set('TrendFollowing')
            if not self.vars['SCHEDULE_TIME'].get():
                self.vars['SCHEDULE_TIME'].set('14:00')
                
        except Exception as e:
            messagebox.showerror("錯誤", f"載入設定失敗：{str(e)}")
            
    def _save_config(self):
        """儲存設定到 .env 檔案"""
        try:
            # 讀取現有 .env 檔案（保留註解和格式）
            if self.ENV_PATH.exists():
                original_content = self.ENV_PATH.read_text(encoding='utf-8')
            else:
                # 如果沒有 .env，嘗試從 .env.example 複製
                example_path = self.ENV_PATH.parent / '.env.example'
                if example_path.exists():
                    original_content = example_path.read_text(encoding='utf-8')
                else:
                    original_content = ""
            
            # 取得股票列表
            stock_text = self.stock_text.get('1.0', tk.END).strip()
            # 處理換行和逗號
            stocks = []
            for line in stock_text.replace(',', '\n').splitlines():
                stock = line.strip()
                if stock:
                    stocks.append(stock)
            stock_list = ','.join(stocks)
            
            # 建立要更新的設定
            updates = {
                'STOCK_LIST': stock_list,
            }
            
            # 加入其他設定
            for key, var in self.vars.items():
                value = var.get().strip()
                if value:  # 只儲存非空值
                    updates[key] = value
            
            # 更新 .env 內容
            new_lines = []
            updated_keys = set()
            
            for line in original_content.splitlines():
                stripped = line.strip()
                
                # 保留空行和註解
                if not stripped or stripped.startswith('#'):
                    new_lines.append(line)
                    continue
                
                # 檢查是否是設定行
                if '=' in stripped:
                    eq_pos = stripped.index('=')
                    key = stripped[:eq_pos].strip()
                    
                    if key in updates:
                        # 更新設定值
                        new_lines.append(f"{key}={updates[key]}")
                        updated_keys.add(key)
                    else:
                        # 保留原始行
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            
            # 將新的設定加到尾端
            for key, value in updates.items():
                if key not in updated_keys:
                    new_lines.append(f"{key}={value}")
            
            # 寫入檔案
            self.ENV_PATH.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
            
            messagebox.showinfo("成功", "設定已儲存！")
            
        except Exception as e:
            messagebox.showerror("錯誤", f"儲存設定失敗：{str(e)}")
            
    def _run_analysis(self):
        """執行股票分析"""
        # 先儲存設定
        self._save_config()
        
        # 確認執行
        if not messagebox.askyesno("確認", "是否立即執行股票分析？\n（這可能需要幾分鐘）"):
            return
            
        try:
            import subprocess
            
            # 取得 main.py 路徑
            main_py = Path(__file__).parent / 'main.py'
            
            # 開啟新的命令列視窗執行
            if sys.platform == 'win32':
                subprocess.Popen(
                    f'start cmd /k "cd /d {main_py.parent} && python main.py"',
                    shell=True
                )
            else:
                subprocess.Popen(
                    ['python', str(main_py)],
                    cwd=str(main_py.parent)
                )
                
            messagebox.showinfo("提示", "已在新視窗中開始執行分析")
            
        except Exception as e:
            messagebox.showerror("錯誤", f"執行失敗：{str(e)}")
            
    def run(self):
        """啟動 GUI"""
        # 置中視窗
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
        # 執行主迴圈
        self.root.mainloop()


def main():
    """主函式"""
    app = ConfigGUI()
    app.run()


if __name__ == "__main__":
    main()
