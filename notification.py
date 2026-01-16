# -*- coding: utf-8 -*-
"""
===================================
台股自選股智能分析系統 - 通知层
===================================

職責：
1. 彙總分析結果生成日報
2. 支持 Markdown 格式输出
3. 多渠道推送(自動識別)：
   - 企業微信 Webhook
   - 飛書 Webhook
   - Telegram Bot
   - 郵件 SMTP
"""

import logging
import json
import smtplib
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from enum import Enum

import requests

from config import get_config
from analyzer import AnalysisResult

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """通知渠道類型"""
    WECHAT = "wechat"      # 企業微信
    FEISHU = "feishu"      # 飛書
    TELEGRAM = "telegram"  # Telegram
    EMAIL = "email"        # 郵件
    CUSTOM = "custom"      # 自定義 Webhook
    UNKNOWN = "unknown"    # 未知


# SMTP 服務器配置(自動識別)
SMTP_CONFIGS = {
    # QQ郵箱
    "qq.com": {"server": "smtp.qq.com", "port": 465, "ssl": True},
    # 网易郵箱
    "163.com": {"server": "smtp.163.com", "port": 465, "ssl": True},
    "126.com": {"server": "smtp.126.com", "port": 465, "ssl": True},
    # Gmail
    "gmail.com": {"server": "smtp.gmail.com", "port": 587, "ssl": False},
    # Outlook
    "outlook.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    "hotmail.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    "live.com": {"server": "smtp-mail.outlook.com", "port": 587, "ssl": False},
    # 新浪
    "sina.com": {"server": "smtp.sina.com", "port": 465, "ssl": True},
    # 搜狐
    "sohu.com": {"server": "smtp.sohu.com", "port": 465, "ssl": True},
    # 阿里云
    "aliyun.com": {"server": "smtp.aliyun.com", "port": 465, "ssl": True},
    # 139郵箱
    "139.com": {"server": "smtp.139.com", "port": 465, "ssl": True},
}


class ChannelDetector:
    """
    渠道檢測器 - 簡化版
    
    根據配置直接判斷渠道類型(不再需要 URL 解析)
    """
    
    @staticmethod
    def get_channel_name(channel: NotificationChannel) -> str:
        """獲取渠道中文名稱"""
        names = {
            NotificationChannel.WECHAT: "企業微信",
            NotificationChannel.FEISHU: "飛書",
            NotificationChannel.TELEGRAM: "Telegram",
            NotificationChannel.EMAIL: "郵件",
            NotificationChannel.CUSTOM: "自定義Webhook",
            NotificationChannel.UNKNOWN: "未知渠道",
        }
        return names.get(channel, "未知渠道")


class NotificationService:
    """
    通知服務
    
    職責：
    1. 生成 Markdown 格式的分析日報
    2. 向所有已配置的渠道推送消息(多渠道併發)
    3. 支持本地保存日報
    
    支持的渠道：
    - 企業微信 Webhook
    - 飛書 Webhook
    - Telegram Bot
    - 郵件 SMTP
    
    注意：所有已配置的渠道都会收到推送
    """
    
    def __init__(self):
        """
        初始化通知服務
        
        檢測所有已配置的渠道，推送时会向所有渠道發送
        """
        config = get_config()
        
        # 各渠道的 Webhook URL
        self._wechat_url = config.wechat_webhook_url
        self._feishu_url = getattr(config, 'feishu_webhook_url', None)
        
        # Telegram 配置
        self._telegram_config = {
            'bot_token': getattr(config, 'telegram_bot_token', None),
            'chat_id': getattr(config, 'telegram_chat_id', None),
        }
        
        # 郵件配置
        self._email_config = {
            'sender': config.email_sender,
            'password': config.email_password,
            'receivers': config.email_receivers or ([config.email_sender] if config.email_sender else []),
        }
        
        # 自定義 Webhook 配置
        self._custom_webhook_urls = getattr(config, 'custom_webhook_urls', []) or []
        
        # 消息長度限制(字節)
        self._feishu_max_bytes = getattr(config, 'feishu_max_bytes', 20000)
        self._wechat_max_bytes = getattr(config, 'wechat_max_bytes', 4000)
        
        # 檢測所有已配置的渠道
        self._available_channels = self._detect_all_channels()
        
        if not self._available_channels:
            logger.warning("未配置有效的通知渠道，将不發送推送通知")
        else:
            channel_names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
            logger.info(f"已配置 {len(self._available_channels)} 個通知渠道：{', '.join(channel_names)}")
    
    def _detect_all_channels(self) -> List[NotificationChannel]:
        """
        檢測所有已配置的渠道
        
        Returns:
            已配置的渠道列表
        """
        channels = []
        
        # 企業微信
        if self._wechat_url:
            channels.append(NotificationChannel.WECHAT)
        
        # 飛書
        if self._feishu_url:
            channels.append(NotificationChannel.FEISHU)
        
        # Telegram
        if self._is_telegram_configured():
            channels.append(NotificationChannel.TELEGRAM)
        
        # 郵件
        if self._is_email_configured():
            channels.append(NotificationChannel.EMAIL)
        
        # 自定義 Webhook
        if self._custom_webhook_urls:
            channels.append(NotificationChannel.CUSTOM)
        
        return channels
    
    def _is_telegram_configured(self) -> bool:
        """檢查 Telegram 配置是否完整"""
        return bool(self._telegram_config['bot_token'] and self._telegram_config['chat_id'])
    
    def _is_email_configured(self) -> bool:
        """檢查郵件配置是否完整(只需郵箱和授權碼)"""
        return bool(self._email_config['sender'] and self._email_config['password'])
    
    def is_available(self) -> bool:
        """檢查通知服務是否可用(至少有一個渠道)"""
        return len(self._available_channels) > 0
    
    def get_available_channels(self) -> List[NotificationChannel]:
        """獲取所有已配置的渠道"""
        return self._available_channels
    
    def get_channel_names(self) -> str:
        """獲取所有已配置渠道的名称"""
        return ', '.join([ChannelDetector.get_channel_name(ch) for ch in self._available_channels])
    
    def generate_daily_report(
        self, 
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        生成 Markdown 格式的日報(詳細版)
        
        Args:
            results: 分析結果列表
            report_date: 報告日期(默認今天)
            
        Returns:
            Markdown 格式的日報內容
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')
        
        # 標題
        report_lines = [
            f"# 📅 {report_date} A股自選股智能分析報告",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 報告生成時間：{datetime.now().strftime('%H:%M:%S')}",
            "",
            "---",
            "",
        ]
        
        # 按評分排序(高分在前)
        sorted_results = sorted(
            results, 
            key=lambda x: x.sentiment_score, 
            reverse=True
        )
        
        # 統計信息
        buy_count = sum(1 for r in results if r.operation_advice in ['買入', '加倉', '強烈買入'])
        sell_count = sum(1 for r in results if r.operation_advice in ['賣出', '減倉', '強烈賣出'])
        hold_count = sum(1 for r in results if r.operation_advice in ['持有', '觀望'])
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0
        
        report_lines.extend([
            "## 📊 操作建議彙總",
            "",
            f"| 指標 | 數值 |",
            f"|------|------|",
            f"| 🟢 建議買入/加倉 | **{buy_count}** 只 |",
            f"| 🟡 建議持有/觀望 | **{hold_count}** 只 |",
            f"| 🔴 建議減倉/賣出 | **{sell_count}** 只 |",
            f"| 📈 平均看多評分 | **{avg_score:.1f}** 分 |",
            "",
            "---",
            "",
            "## 📈 個股詳細分析",
            "",
        ])
        
        # 逐個股票的詳細分析
        for result in sorted_results:
            emoji = result.get_emoji()
            confidence_stars = result.get_confidence_stars() if hasattr(result, 'get_confidence_stars') else '⭐⭐'
            
            report_lines.extend([
                f"### {emoji} {result.name} ({result.code})",
                "",
                f"**操作建議：{result.operation_advice}** | **綜合評分：{result.sentiment_score}分** | **趨勢預測：{result.trend_prediction}** | **置信度：{confidence_stars}**",
                "",
            ])
            
            # 核心看點
            if hasattr(result, 'key_points') and result.key_points:
                report_lines.extend([
                    f"**🎯 核心看點**：{result.key_points}",
                    "",
                ])
            
            # 買入/賣出理由
            if hasattr(result, 'buy_reason') and result.buy_reason:
                report_lines.extend([
                    f"**💡 操作理由**：{result.buy_reason}",
                    "",
                ])
            
            # 走勢分析
            if hasattr(result, 'trend_analysis') and result.trend_analysis:
                report_lines.extend([
                    "#### 📉 走勢分析",
                    f"{result.trend_analysis}",
                    "",
                ])
            
            # 短期/中期展望
            outlook_lines = []
            if hasattr(result, 'short_term_outlook') and result.short_term_outlook:
                outlook_lines.append(f"- **短期(1-3日)**：{result.short_term_outlook}")
            if hasattr(result, 'medium_term_outlook') and result.medium_term_outlook:
                outlook_lines.append(f"- **中期(1-2周)**：{result.medium_term_outlook}")
            if outlook_lines:
                report_lines.extend([
                    "#### 🔮 市場展望",
                    *outlook_lines,
                    "",
                ])
            
            # 技術面分析
            tech_lines = []
            if result.technical_analysis:
                tech_lines.append(f"**綜合**：{result.technical_analysis}")
            if hasattr(result, 'ma_analysis') and result.ma_analysis:
                tech_lines.append(f"**均線**：{result.ma_analysis}")
            if hasattr(result, 'volume_analysis') and result.volume_analysis:
                tech_lines.append(f"**量能**：{result.volume_analysis}")
            if hasattr(result, 'pattern_analysis') and result.pattern_analysis:
                tech_lines.append(f"**形態**：{result.pattern_analysis}")
            if tech_lines:
                report_lines.extend([
                    "#### 📊 技術面分析",
                    *tech_lines,
                    "",
                ])
            
            # 基本面分析
            fund_lines = []
            if hasattr(result, 'fundamental_analysis') and result.fundamental_analysis:
                fund_lines.append(result.fundamental_analysis)
            if hasattr(result, 'sector_position') and result.sector_position:
                fund_lines.append(f"**板塊地位**：{result.sector_position}")
            if hasattr(result, 'company_highlights') and result.company_highlights:
                fund_lines.append(f"**公司亮點**：{result.company_highlights}")
            if fund_lines:
                report_lines.extend([
                    "#### 🏢 基本面分析",
                    *fund_lines,
                    "",
                ])
            
            # 消息面/情緒面
            news_lines = []
            if result.news_summary:
                news_lines.append(f"**新聞摘要**：{result.news_summary}")
            if hasattr(result, 'market_sentiment') and result.market_sentiment:
                news_lines.append(f"**市場情緒**：{result.market_sentiment}")
            if hasattr(result, 'hot_topics') and result.hot_topics:
                news_lines.append(f"**相關熱點**：{result.hot_topics}")
            if news_lines:
                report_lines.extend([
                    "#### 📰 消息面/情緒面",
                    *news_lines,
                    "",
                ])
            
            # 綜合分析
            if result.analysis_summary:
                report_lines.extend([
                    "#### 📝 綜合分析",
                    result.analysis_summary,
                    "",
                ])
            
            # 風險提示
            if hasattr(result, 'risk_warning') and result.risk_warning:
                report_lines.extend([
                    f"⚠️ **風險提示**：{result.risk_warning}",
                    "",
                ])
            
            # 數據來源说明
            if hasattr(result, 'search_performed') and result.search_performed:
                report_lines.append(f"*🔍 已執行聯網搜索*")
            if hasattr(result, 'data_sources') and result.data_sources:
                report_lines.append(f"*📋 數據來源：{result.data_sources}*")
            
            # 錯誤信息(如果有)
            if not result.success and result.error_message:
                report_lines.extend([
                    "",
                    f"❌ **分析異常**：{result.error_message[:100]}",
                ])
            
            report_lines.extend([
                "",
                "---",
                "",
            ])
        
        # 底部信息(去除免责声明)
        report_lines.extend([
            "",
            f"*報告生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    def _get_signal_level(self, result: AnalysisResult) -> tuple:
        """
        根據操作建議獲取信号等级和颜色
        
        Returns:
            (信号文字, emoji, 颜色標記)
        """
        advice = result.operation_advice
        score = result.sentiment_score
        
        if advice in ['強烈買入'] or score >= 80:
            return ('強烈買入', '💚', '强买')
        elif advice in ['買入', '加倉'] or score >= 65:
            return ('買入', '🟢', '買入')
        elif advice in ['持有'] or 55 <= score < 65:
            return ('持有', '🟡', '持有')
        elif advice in ['觀望'] or 45 <= score < 55:
            return ('觀望', '⚪', '觀望')
        elif advice in ['減倉'] or 35 <= score < 45:
            return ('減倉', '🟠', '減倉')
        elif advice in ['賣出', '強烈賣出'] or score < 35:
            return ('賣出', '🔴', '賣出')
        else:
            return ('觀望', '⚪', '觀望')
    
    def generate_dashboard_report(
        self, 
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        生成決策儀表板格式的日報(詳細版)
        
        格式：市場概覽 + 重要信息 + 核心結論 + 數據透視 + 作戰計劃
        
        Args:
            results: 分析結果列表
            report_date: 報告日期(默認今天)
            
        Returns:
            Markdown 格式的決策儀表板日報
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')
        
        # 按評分排序(高分在前)
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        
        # 統計信息
        buy_count = sum(1 for r in results if r.operation_advice in ['買入', '加倉', '強烈買入'])
        sell_count = sum(1 for r in results if r.operation_advice in ['賣出', '減倉', '強烈賣出'])
        hold_count = sum(1 for r in results if r.operation_advice in ['持有', '觀望'])
        
        report_lines = [
            f"# 🎯 {report_date} 決策儀表板",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 🟢買入:{buy_count} 🟡觀望:{hold_count} 🔴賣出:{sell_count}",
            "",
            "---",
            "",
        ]
        
        # 逐個股票的決策儀表板
        for result in sorted_results:
            signal_text, signal_emoji, signal_tag = self._get_signal_level(result)
            dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
            
            # 股票名称(優先使用 dashboard 或 result 中的名称)
            stock_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
            
            report_lines.extend([
                f"## {signal_emoji} {stock_name} ({result.code})",
                "",
            ])
            
            # ========== 輿情与基本面概覽(放在最前面)==========
            intel = dashboard.get('intelligence', {}) if dashboard else {}
            if intel:
                report_lines.extend([
                    "### 📰 重要信息速覽",
                    "",
                ])
                
                # 輿情情緒總結
                if intel.get('sentiment_summary'):
                    report_lines.append(f"**💭 輿情情緒**: {intel['sentiment_summary']}")
                
                # 業績预期
                if intel.get('earnings_outlook'):
                    report_lines.append(f"**📊 業績预期**: {intel['earnings_outlook']}")
                
                # 風險警報(醒目显示)
                risk_alerts = intel.get('risk_alerts', [])
                if risk_alerts:
                    report_lines.append("")
                    report_lines.append("**🚨 風險警報**:")
                    for alert in risk_alerts:
                        report_lines.append(f"- {alert}")
                
                # 利好催化
                catalysts = intel.get('positive_catalysts', [])
                if catalysts:
                    report_lines.append("")
                    report_lines.append("**✨ 利好催化**:")
                    for cat in catalysts:
                        report_lines.append(f"- {cat}")
                
                # 最新消息
                if intel.get('latest_news'):
                    report_lines.append("")
                    report_lines.append(f"**📢 最新動態**: {intel['latest_news']}")
                
                report_lines.append("")
            
            # ========== 核心結論 ==========
            core = dashboard.get('core_conclusion', {}) if dashboard else {}
            one_sentence = core.get('one_sentence', result.analysis_summary)
            time_sense = core.get('time_sensitivity', '本週内')
            pos_advice = core.get('position_advice', {})
            
            report_lines.extend([
                "### 📌 核心結論",
                "",
                f"**{signal_emoji} {signal_text}** | {result.trend_prediction}",
                "",
                f"> **一句話決策**: {one_sentence}",
                "",
                f"⏰ **時效性**: {time_sense}",
                "",
            ])
            
            # 持倉分類建議
            if pos_advice:
                report_lines.extend([
                    "| 持倉情況 | 操作建議 |",
                    "|---------|---------|",
                    f"| 🆕 **空倉者** | {pos_advice.get('no_position', result.operation_advice)} |",
                    f"| 💼 **持倉者** | {pos_advice.get('has_position', '繼續持有')} |",
                    "",
                ])
            
            # ========== 數據透視 ==========
            data_persp = dashboard.get('data_perspective', {}) if dashboard else {}
            if data_persp:
                trend_data = data_persp.get('trend_status', {})
                price_data = data_persp.get('price_position', {})
                vol_data = data_persp.get('volume_analysis', {})
                chip_data = data_persp.get('chip_structure', {})
                
                report_lines.extend([
                    "### 📊 數據透視",
                    "",
                ])
                
                # 趨勢狀態
                if trend_data:
                    is_bullish = "✅ 是" if trend_data.get('is_bullish', False) else "❌ 否"
                    report_lines.extend([
                        f"**均線排列**: {trend_data.get('ma_alignment', 'N/A')} | 多頭排列: {is_bullish} | 趨勢強度: {trend_data.get('trend_score', 'N/A')}/100",
                        "",
                    ])
                
                # 價格位置
                if price_data:
                    bias_status = price_data.get('bias_status', 'N/A')
                    bias_emoji = "✅" if bias_status == "安全" else ("⚠️" if bias_status == "警戒" else "🚨")
                    report_lines.extend([
                        "| 價格指標 | 數值 |",
                        "|---------|------|",
                        f"| 當前價 | {price_data.get('current_price', 'N/A')} |",
                        f"| MA5 | {price_data.get('ma5', 'N/A')} |",
                        f"| MA10 | {price_data.get('ma10', 'N/A')} |",
                        f"| MA20 | {price_data.get('ma20', 'N/A')} |",
                        f"| 乖離率(MA5) | {price_data.get('bias_ma5', 'N/A')}% {bias_emoji}{bias_status} |",
                        f"| 支撐位 | {price_data.get('support_level', 'N/A')} |",
                        f"| 壓力位 | {price_data.get('resistance_level', 'N/A')} |",
                        "",
                    ])
                
                # 量能分析
                if vol_data:
                    report_lines.extend([
                        f"**量能**: 量比 {vol_data.get('volume_ratio', 'N/A')} ({vol_data.get('volume_status', '')}) | 換手率 {vol_data.get('turnover_rate', 'N/A')}%",
                        f"💡 *{vol_data.get('volume_meaning', '')}*",
                        "",
                    ])
                
                # 籌碼結構
                if chip_data:
                    chip_health = chip_data.get('chip_health', 'N/A')
                    chip_emoji = "✅" if chip_health == "健康" else ("⚠️" if chip_health == "一般" else "🚨")
                    report_lines.extend([
                        f"**籌碼**: 獲利比例 {chip_data.get('profit_ratio', 'N/A')} | 平均成本 {chip_data.get('avg_cost', 'N/A')} | 集中度 {chip_data.get('concentration', 'N/A')} {chip_emoji}{chip_health}",
                        "",
                    ])
            
            # 輿情情报已移至顶部显示
            
            # ========== 作戰計劃 ==========
            battle = dashboard.get('battle_plan', {}) if dashboard else {}
            if battle:
                report_lines.extend([
                    "### 🎯 作戰計劃",
                    "",
                ])
                
                # 狙擊點位
                sniper = battle.get('sniper_points', {})
                if sniper:
                    report_lines.extend([
                        "**📍 狙擊點位**",
                        "",
                        "| 點位類型 | 價格 |",
                        "|---------|------|",
                        f"| 🎯 理想買入点 | {sniper.get('ideal_buy', 'N/A')} |",
                        f"| 🔵 次優買入点 | {sniper.get('secondary_buy', 'N/A')} |",
                        f"| 🛑 止損位 | {sniper.get('stop_loss', 'N/A')} |",
                        f"| 🎊 目標位 | {sniper.get('take_profit', 'N/A')} |",
                        "",
                    ])
                
                # 倉位策略
                position = battle.get('position_strategy', {})
                if position:
                    report_lines.extend([
                        f"**💰 倉位建議**: {position.get('suggested_position', 'N/A')}",
                        f"- 建倉策略: {position.get('entry_plan', 'N/A')}",
                        f"- 風控策略: {position.get('risk_control', 'N/A')}",
                        "",
                    ])
                
                # 檢查清單
                checklist = battle.get('action_checklist', [])
                if checklist:
                    report_lines.extend([
                        "**✅ 檢查清單**",
                        "",
                    ])
                    for item in checklist:
                        report_lines.append(f"- {item}")
                    report_lines.append("")
            
            # 如果没有 dashboard，显示传统格式
            if not dashboard:
                # 操作理由
                if result.buy_reason:
                    report_lines.extend([
                        f"**💡 操作理由**: {result.buy_reason}",
                        "",
                    ])
                
                # 風險提示
                if result.risk_warning:
                    report_lines.extend([
                        f"**⚠️ 風險提示**: {result.risk_warning}",
                        "",
                    ])
                
                # 技術面分析
                if result.ma_analysis or result.volume_analysis:
                    report_lines.extend([
                        "### 📊 技術面",
                        "",
                    ])
                    if result.ma_analysis:
                        report_lines.append(f"**均線**: {result.ma_analysis}")
                    if result.volume_analysis:
                        report_lines.append(f"**量能**: {result.volume_analysis}")
                    report_lines.append("")
                
                # 消息面
                if result.news_summary:
                    report_lines.extend([
                        "### 📰 消息面",
                        f"{result.news_summary}",
                        "",
                    ])
            
            report_lines.extend([
                "---",
                "",
            ])
        
        # 底部(去除免责声明)
        report_lines.extend([
            "",
            f"*報告生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        return "\n".join(report_lines)
    
    def generate_wechat_dashboard(self, results: List[AnalysisResult]) -> str:
        """
        生成企業微信決策儀表板精簡版(控制在4000字符內)
        
        只保留核心結論和狙擊點位
        
        Args:
            results: 分析結果列表
            
        Returns:
            精簡版決策儀表板
        """
        report_date = datetime.now().strftime('%Y-%m-%d')
        
        # 按評分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        
        # 統計
        buy_count = sum(1 for r in results if r.operation_advice in ['買入', '加倉', '強烈買入'])
        sell_count = sum(1 for r in results if r.operation_advice in ['賣出', '減倉', '強烈賣出'])
        hold_count = sum(1 for r in results if r.operation_advice in ['持有', '觀望'])
        
        lines = [
            f"## 🎯 {report_date} 決策儀表板",
            "",
            f"> {len(results)}只股票 | 🟢買入:{buy_count} 🟡觀望:{hold_count} 🔴賣出:{sell_count}",
            "",
        ]
        
        for result in sorted_results:
            signal_text, signal_emoji, _ = self._get_signal_level(result)
            dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
            core = dashboard.get('core_conclusion', {}) if dashboard else {}
            battle = dashboard.get('battle_plan', {}) if dashboard else {}
            intel = dashboard.get('intelligence', {}) if dashboard else {}
            
            # 股票名称
            stock_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
            
            # 標題行：信号等级 + 股票名称
            lines.append(f"### {signal_emoji} **{signal_text}** | {stock_name}({result.code})")
            lines.append("")
            
            # 核心決策(一句話)
            one_sentence = core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
            if one_sentence:
                lines.append(f"📌 **{one_sentence[:80]}**")
                lines.append("")
            
            # 重要信息区(輿情+基本面)
            info_lines = []
            
            # 業績预期
            if intel.get('earnings_outlook'):
                outlook = intel['earnings_outlook'][:60]
                info_lines.append(f"📊 業績: {outlook}")
            
            # 輿情情緒
            if intel.get('sentiment_summary'):
                sentiment = intel['sentiment_summary'][:50]
                info_lines.append(f"💭 輿情: {sentiment}")
            
            if info_lines:
                lines.extend(info_lines)
                lines.append("")
            
            # 風險警報(最重要，醒目显示)
            risks = intel.get('risk_alerts', []) if intel else []
            if risks:
                lines.append("🚨 **風險**:")
                for risk in risks[:2]:  # 最多显示2条
                    risk_text = risk[:50] + "..." if len(risk) > 50 else risk
                    lines.append(f"   • {risk_text}")
                lines.append("")
            
            # 利好催化
            catalysts = intel.get('positive_catalysts', []) if intel else []
            if catalysts:
                lines.append("✨ **利好**:")
                for cat in catalysts[:2]:  # 最多显示2条
                    cat_text = cat[:50] + "..." if len(cat) > 50 else cat
                    lines.append(f"   • {cat_text}")
                lines.append("")
            
            # 狙擊點位
            sniper = battle.get('sniper_points', {}) if battle else {}
            if sniper:
                ideal_buy = sniper.get('ideal_buy', '')
                stop_loss = sniper.get('stop_loss', '')
                take_profit = sniper.get('take_profit', '')
                
                points = []
                if ideal_buy:
                    points.append(f"🎯买点:{ideal_buy[:15]}")
                if stop_loss:
                    points.append(f"🛑止損:{stop_loss[:15]}")
                if take_profit:
                    points.append(f"🎊目標:{take_profit[:15]}")
                
                if points:
                    lines.append(" | ".join(points))
                    lines.append("")
            
            # 持倉建議
            pos_advice = core.get('position_advice', {}) if core else {}
            if pos_advice:
                no_pos = pos_advice.get('no_position', '')
                has_pos = pos_advice.get('has_position', '')
                if no_pos:
                    lines.append(f"🆕 空倉者: {no_pos[:50]}")
                if has_pos:
                    lines.append(f"💼 持倉者: {has_pos[:50]}")
                lines.append("")
            
            # 檢查清單簡化版
            checklist = battle.get('action_checklist', []) if battle else []
            if checklist:
                # 只显示不通過的项目
                failed_checks = [c for c in checklist if c.startswith('❌') or c.startswith('⚠️')]
                if failed_checks:
                    lines.append("**檢查未通過项**:")
                    for check in failed_checks[:3]:
                        lines.append(f"   {check[:40]}")
                    lines.append("")
            
            lines.append("---")
            lines.append("")
        
        # 底部
        lines.append(f"*生成時間: {datetime.now().strftime('%H:%M')}*")
        
        content = "\n".join(lines)
        
        # 檢查長度
        if len(content) > 3800:
            logger.warning(f"儀表板超長({len(content)}字符)，截斷")
            content = content[:3800] + "\n...(已截斷)"
        
        return content
    
    def generate_wechat_summary(self, results: List[AnalysisResult]) -> str:
        """
        生成企業微信精簡版日報(控制在4000字符內)
        
        Args:
            results: 分析結果列表
            
        Returns:
            精簡版 Markdown 內容
        """
        report_date = datetime.now().strftime('%Y-%m-%d')
        
        # 按評分排序
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        
        # 統計
        buy_count = sum(1 for r in results if r.operation_advice in ['買入', '加倉', '強烈買入'])
        sell_count = sum(1 for r in results if r.operation_advice in ['賣出', '減倉', '強烈賣出'])
        hold_count = sum(1 for r in results if r.operation_advice in ['持有', '觀望'])
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0
        
        lines = [
            f"## 📅 {report_date} 台股分析報告",
            "",
            f"> 共 **{len(results)}** 只 | 🟢買入:{buy_count} 🟡持有:{hold_count} 🔴賣出:{sell_count} | 均分:{avg_score:.0f}",
            "",
        ]
        
        # 每只股票精简信息(控制長度)
        for result in sorted_results:
            emoji = result.get_emoji()
            
            # 核心信息行
            lines.append(f"### {emoji} {result.name}({result.code})")
            lines.append(f"**{result.operation_advice}** | 評分:{result.sentiment_score} | {result.trend_prediction}")
            
            # 操作理由(截斷)
            if hasattr(result, 'buy_reason') and result.buy_reason:
                reason = result.buy_reason[:80] + "..." if len(result.buy_reason) > 80 else result.buy_reason
                lines.append(f"💡 {reason}")
            
            # 核心看點
            if hasattr(result, 'key_points') and result.key_points:
                points = result.key_points[:60] + "..." if len(result.key_points) > 60 else result.key_points
                lines.append(f"🎯 {points}")
            
            # 風險提示(截斷)
            if hasattr(result, 'risk_warning') and result.risk_warning:
                risk = result.risk_warning[:50] + "..." if len(result.risk_warning) > 50 else result.risk_warning
                lines.append(f"⚠️ {risk}")
            
            lines.append("")
        
        # 底部
        lines.extend([
            "---",
            "*AI生成，僅供參考，不構成投資建議*",
            f"*詳細報告见 reports/report_{report_date.replace('-', '')}.md*"
        ])
        
        content = "\n".join(lines)
        
        # 最终檢查長度
        if len(content) > 3800:
            logger.warning(f"精简報告仍超長({len(content)}字符)，进行截斷")
            content = content[:3800] + "\n\n...(內容過長已截斷)"
        
        return content
    
    def send_to_wechat(self, content: str) -> bool:
        """
        推送消息到企業微信機器人
        
        企業微信 Webhook 消息格式：
        {
            "msgtype": "markdown",
            "markdown": {
                "content": "Markdown 內容"
            }
        }
        
        注意：企業微信 Markdown 限制 4096 字節(非字符)，超長內容会自动分批發送
        可通過环境变量 WECHAT_MAX_BYTES 调整限制值
        
        Args:
            content: Markdown 格式的消息內容
            
        Returns:
            是否發送成功
        """
        if not self._wechat_url:
            logger.warning("企業微信 Webhook 未配置，跳過推送")
            return False
        
        max_bytes = self._wechat_max_bytes  # 从配置讀取，默認 4000 字節
        
        # 檢查字節長度，超長则分批發送
        content_bytes = len(content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"消息內容超長({content_bytes}字節/{len(content)}字符)，将分批發送")
            return self._send_wechat_chunked(content, max_bytes)
        
        try:
            return self._send_wechat_message(content)
        except Exception as e:
            logger.error(f"發送企業微信消息失敗: {e}")
            return False
    
    def _send_wechat_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批發送长消息到企業微信
        
        按股票分析块(以 --- 或 ### 分隔)智能分割，確保每批不超過限制
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節数
            
        Returns:
            是否全部發送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            """獲取字符串的 UTF-8 字節数"""
            return len(s.encode('utf-8'))
        
        # 智能分割：優先按 "---" 分隔(股票之間的分隔線)
        # 如果没有分隔線，按 "### " 標題分割(每只股票的標題)
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            # 按 ### 分割，但保留 ### 前綴
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 無法智能分割，按字符強制分割
            return self._send_wechat_force_chunked(content, max_bytes)
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            # 如果单個 section 就超長，需要強制截斷
            if section_bytes > max_bytes:
                # 先發送當前积累的內容
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_bytes = 0
                
                # 強制截斷这個超長 section(按字節截斷)
                truncated = self._truncate_to_bytes(section, max_bytes - 200)
                truncated += "\n\n...(本段內容過長已截斷)"
                chunks.append(truncated)
                continue
            
            # 檢查加入後是否超長
            if current_bytes + section_bytes > max_bytes:
                # 保存當前块，開始新塊
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        # 添加最後一块
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 分批發送
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"企業微信分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # 添加分頁標記
            if total_chunks > 1:
                page_marker = f"\n\n📄 *({i+1}/{total_chunks})*"
                chunk_with_marker = chunk + page_marker
            else:
                chunk_with_marker = chunk
            
            try:
                if self._send_wechat_message(chunk_with_marker):
                    success_count += 1
                    logger.info(f"企業微信第 {i+1}/{total_chunks} 批發送成功")
                else:
                    logger.error(f"企業微信第 {i+1}/{total_chunks} 批發送失敗")
            except Exception as e:
                logger.error(f"企業微信第 {i+1}/{total_chunks} 批發送異常: {e}")
            
            # 批次間隔，避免觸發頻率限制
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _send_wechat_force_chunked(self, content: str, max_bytes: int) -> bool:
        """
        強制按字節分割發送(無法智能分割时的 fallback)
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節数
        """
        import time
        
        chunks = []
        current_chunk = ""
        
        # 按行分割，確保不会在多字節字符中間截斷
        lines = content.split('\n')
        
        for line in lines:
            test_chunk = current_chunk + ('\n' if current_chunk else '') + line
            if len(test_chunk.encode('utf-8')) > max_bytes - 100:  # 預留空間给分頁標記
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk = test_chunk
        
        if current_chunk:
            chunks.append(current_chunk)
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"企業微信強制分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            page_marker = f"\n\n📄 *({i+1}/{total_chunks})*" if total_chunks > 1 else ""
            
            try:
                if self._send_wechat_message(chunk + page_marker):
                    success_count += 1
            except Exception as e:
                logger.error(f"企業微信第 {i+1}/{total_chunks} 批發送異常: {e}")
            
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _truncate_to_bytes(self, text: str, max_bytes: int) -> str:
        """
        按字節数截斷字符串，確保不会在多字節字符中間截斷
        
        Args:
            text: 要截斷的字符串
            max_bytes: 最大字節数
            
        Returns:
            截斷后的字符串
        """
        encoded = text.encode('utf-8')
        if len(encoded) <= max_bytes:
            return text
        
        # 从 max_bytes 位置往前找，確保不截斷多字節字符
        truncated = encoded[:max_bytes]
        # 嘗試解碼，如果失敗则繼續往前
        while truncated:
            try:
                return truncated.decode('utf-8')
            except UnicodeDecodeError:
                truncated = truncated[:-1]
        return ""
    
    def _send_wechat_message(self, content: str) -> bool:
        """發送企業微信消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        
        response = requests.post(
            self._wechat_url,
            json=payload,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('errcode') == 0:
                logger.info("企業微信消息發送成功")
                return True
            else:
                logger.error(f"企業微信返回錯誤: {result}")
                return False
        else:
            logger.error(f"企業微信請求失敗: {response.status_code}")
            return False
    
    def send_to_feishu(self, content: str) -> bool:
        """
        推送消息到飛書機器人
        
        飛書自定義機器人 Webhook 消息格式：
        {
            "msg_type": "text",
            "content": {
                "text": "文本內容"
            }
        }
        
        说明：飛書文本消息不会渲染 Markdown，需使用交互卡片(lark_md)格式
        
        注意：飛書文本消息限制约 20KB，超長內容会自动分批發送
        可通過环境变量 FEISHU_MAX_BYTES 调整限制值
        
        Args:
            content: 消息內容(Markdown 会转为純文本)
            
        Returns:
            是否發送成功
        """
        if not self._feishu_url:
            logger.warning("飛書 Webhook 未配置，跳過推送")
            return False
        
        # 飛書 lark_md 支持有限，先做格式轉換
        formatted_content = self._format_feishu_markdown(content)

        max_bytes = self._feishu_max_bytes  # 从配置讀取，默認 20000 字節
        
        # 檢查字節長度，超長则分批發送
        content_bytes = len(formatted_content.encode('utf-8'))
        if content_bytes > max_bytes:
            logger.info(f"飛書消息內容超長({content_bytes}字節/{len(content)}字符)，将分批發送")
            return self._send_feishu_chunked(formatted_content, max_bytes)
        
        try:
            return self._send_feishu_message(formatted_content)
        except Exception as e:
            logger.error(f"發送飛書消息失敗: {e}")
            return False
    
    def _send_feishu_chunked(self, content: str, max_bytes: int) -> bool:
        """
        分批發送长消息到飛書
        
        按股票分析块(以 --- 或 ### 分隔)智能分割，確保每批不超過限制
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節数
            
        Returns:
            是否全部發送成功
        """
        import time
        
        def get_bytes(s: str) -> int:
            """獲取字符串的 UTF-8 字節数"""
            return len(s.encode('utf-8'))
        
        # 智能分割：優先按 "---" 分隔(股票之間的分隔線)
        # 如果没有分隔線，按 "### " 標題分割(每只股票的標題)
        if "\n---\n" in content:
            sections = content.split("\n---\n")
            separator = "\n---\n"
        elif "\n### " in content:
            # 按 ### 分割，但保留 ### 前綴
            parts = content.split("\n### ")
            sections = [parts[0]] + [f"### {p}" for p in parts[1:]]
            separator = "\n"
        else:
            # 無法智能分割，按行強制分割
            return self._send_feishu_force_chunked(content, max_bytes)
        
        chunks = []
        current_chunk = []
        current_bytes = 0
        separator_bytes = get_bytes(separator)
        
        for section in sections:
            section_bytes = get_bytes(section) + separator_bytes
            
            # 如果单個 section 就超長，需要強制截斷
            if section_bytes > max_bytes:
                # 先發送當前积累的內容
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                    current_chunk = []
                    current_bytes = 0
                
                # 強制截斷这個超長 section(按字節截斷)
                truncated = self._truncate_to_bytes(section, max_bytes - 200)
                truncated += "\n\n...(本段內容過長已截斷)"
                chunks.append(truncated)
                continue
            
            # 檢查加入後是否超長
            if current_bytes + section_bytes > max_bytes:
                # 保存當前块，開始新塊
                if current_chunk:
                    chunks.append(separator.join(current_chunk))
                current_chunk = [section]
                current_bytes = section_bytes
            else:
                current_chunk.append(section)
                current_bytes += section_bytes
        
        # 添加最後一块
        if current_chunk:
            chunks.append(separator.join(current_chunk))
        
        # 分批發送
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"飛書分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            # 添加分頁標記
            if total_chunks > 1:
                page_marker = f"\n\n📄 ({i+1}/{total_chunks})"
                chunk_with_marker = chunk + page_marker
            else:
                chunk_with_marker = chunk
            
            try:
                if self._send_feishu_message(chunk_with_marker):
                    success_count += 1
                    logger.info(f"飛書第 {i+1}/{total_chunks} 批發送成功")
                else:
                    logger.error(f"飛書第 {i+1}/{total_chunks} 批發送失敗")
            except Exception as e:
                logger.error(f"飛書第 {i+1}/{total_chunks} 批發送異常: {e}")
            
            # 批次間隔，避免觸發頻率限制
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _send_feishu_force_chunked(self, content: str, max_bytes: int) -> bool:
        """
        強制按字節分割發送(無法智能分割时的 fallback)
        
        Args:
            content: 完整消息內容
            max_bytes: 單條消息最大字節数
        """
        import time
        
        chunks = []
        current_chunk = ""
        
        # 按行分割，確保不会在多字節字符中間截斷
        lines = content.split('\n')
        
        for line in lines:
            test_chunk = current_chunk + ('\n' if current_chunk else '') + line
            if len(test_chunk.encode('utf-8')) > max_bytes - 100:  # 預留空間给分頁標記
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk = test_chunk
        
        if current_chunk:
            chunks.append(current_chunk)
        
        total_chunks = len(chunks)
        success_count = 0
        
        logger.info(f"飛書強制分批發送：共 {total_chunks} 批")
        
        for i, chunk in enumerate(chunks):
            page_marker = f"\n\n📄 ({i+1}/{total_chunks})" if total_chunks > 1 else ""
            
            try:
                if self._send_feishu_message(chunk + page_marker):
                    success_count += 1
            except Exception as e:
                logger.error(f"飛書第 {i+1}/{total_chunks} 批發送異常: {e}")
            
            if i < total_chunks - 1:
                time.sleep(1)
        
        return success_count == total_chunks
    
    def _send_feishu_message(self, content: str) -> bool:
        """發送單條飛書消息(優先使用 Markdown 卡片)"""
        def _post_payload(payload: Dict[str, Any]) -> bool:
            logger.debug(f"飛書請求 URL: {self._feishu_url}")
            logger.debug(f"飛書請求 payload 長度: {len(content)} 字符")

            response = requests.post(
                self._feishu_url,
                json=payload,
                timeout=30
            )

            logger.debug(f"飛書響應狀態码: {response.status_code}")
            logger.debug(f"飛書響應內容: {response.text}")

            if response.status_code == 200:
                result = response.json()
                code = result.get('code') if 'code' in result else result.get('StatusCode')
                if code == 0:
                    logger.info("飛書消息發送成功")
                    return True
                else:
                    error_msg = result.get('msg') or result.get('StatusMessage', '未知錯誤')
                    error_code = result.get('code') or result.get('StatusCode', 'N/A')
                    logger.error(f"飛書返回錯誤 [code={error_code}]: {error_msg}")
                    logger.error(f"完整響應: {result}")
                    return False
            else:
                logger.error(f"飛書請求失敗: HTTP {response.status_code}")
                logger.error(f"響應內容: {response.text}")
                return False

        # 1) 優先使用交互卡片(支持 Markdown 渲染)
        card_payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "台股智能分析報告"
                    }
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content
                        }
                    }
                ]
            }
        }

        if _post_payload(card_payload):
            return True

        # 2) 回退为普通文本消息
        text_payload = {
            "msg_type": "text",
            "content": {
                "text": content
            }
        }

        return _post_payload(text_payload)

    def _format_feishu_markdown(self, content: str) -> str:
        """
        将通用 Markdown 轉換为飛書 lark_md 更友好的格式
        - 飛書不支持 Markdown 標題(# / ## / ###)，用加粗代替
        - 引用塊使用前綴替代
        - 分隔線統一为細線
        - 表格轉換为條目列表
        """
        def _flush_table_rows(buffer: List[str], output: List[str]) -> None:
            if not buffer:
                return

            def _parse_row(row: str) -> List[str]:
                cells = [c.strip() for c in row.strip().strip('|').split('|')]
                return [c for c in cells if c]

            rows = []
            for raw in buffer:
                if re.match(r'^\s*\|?\s*[:-]+\s*(\|\s*[:-]+\s*)+\|?\s*$', raw):
                    continue
                parsed = _parse_row(raw)
                if parsed:
                    rows.append(parsed)

            if not rows:
                return

            header = rows[0]
            data_rows = rows[1:] if len(rows) > 1 else []
            for row in data_rows:
                pairs = []
                for idx, cell in enumerate(row):
                    key = header[idx] if idx < len(header) else f"列{idx + 1}"
                    pairs.append(f"{key}：{cell}")
                output.append(f"• {' | '.join(pairs)}")

        lines = []
        table_buffer: List[str] = []

        for raw_line in content.splitlines():
            line = raw_line.rstrip()

            if line.strip().startswith('|'):
                table_buffer.append(line)
                continue

            if table_buffer:
                _flush_table_rows(table_buffer, lines)
                table_buffer = []

            if re.match(r'^#{1,6}\s+', line):
                title = re.sub(r'^#{1,6}\s+', '', line).strip()
                line = f"**{title}**" if title else ""
            elif line.startswith('> '):
                quote = line[2:].strip()
                line = f"💬 {quote}" if quote else ""
            elif line.strip() == '---':
                line = '────────'
            elif line.startswith('- '):
                line = f"• {line[2:].strip()}"

            lines.append(line)

        if table_buffer:
            _flush_table_rows(table_buffer, lines)

        return "\n".join(lines).strip()
    
    def send_to_email(self, content: str, subject: Optional[str] = None) -> bool:
        """
        通過 SMTP 發送郵件(自動識別 SMTP 服務器)
        
        Args:
            content: 郵件內容(支持 Markdown，会轉換为 HTML)
            subject: 郵件主題(可選，默認自動生成)
            
        Returns:
            是否發送成功
        """
        if not self._is_email_configured():
            logger.warning("郵件配置不完整，跳過推送")
            return False
        
        sender = self._email_config['sender']
        password = self._email_config['password']
        receivers = self._email_config['receivers']
        
        try:
            # 生成主題
            if subject is None:
                date_str = datetime.now().strftime('%Y-%m-%d')
                subject = f"📈 台股智能分析報告 - {date_str}"
            
            # 将 Markdown 轉換为簡單 HTML
            html_content = self._markdown_to_html(content)
            
            # 構建郵件
            msg = MIMEMultipart('alternative')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = sender
            msg['To'] = ', '.join(receivers)
            
            # 添加純文本和 HTML 兩個版本
            text_part = MIMEText(content, 'plain', 'utf-8')
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(text_part)
            msg.attach(html_part)
            
            # 自動識別 SMTP 配置
            domain = sender.split('@')[-1].lower()
            smtp_config = SMTP_CONFIGS.get(domain)
            
            if smtp_config:
                smtp_server = smtp_config['server']
                smtp_port = smtp_config['port']
                use_ssl = smtp_config['ssl']
                logger.info(f"自動識別郵箱類型: {domain} -> {smtp_server}:{smtp_port}")
            else:
                # 未知郵箱，嘗試通用配置
                smtp_server = f"smtp.{domain}"
                smtp_port = 465
                use_ssl = True
                logger.warning(f"未知郵箱類型 {domain}，嘗試通用配置: {smtp_server}:{smtp_port}")
            
            # 根據配置選擇連接方式
            if use_ssl:
                # SSL 連接(端口 465)
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
            else:
                # TLS 連接(端口 587)
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                server.starttls()
            
            server.login(sender, password)
            server.send_message(msg)
            server.quit()
            
            logger.info(f"郵件發送成功，收件人: {receivers}")
            return True
            
        except smtplib.SMTPAuthenticationError:
            logger.error("郵件發送失敗：認證錯誤，请檢查郵箱和授權碼是否正確")
            return False
        except smtplib.SMTPConnectError as e:
            logger.error(f"郵件發送失敗：無法連接 SMTP 服務器 - {e}")
            return False
        except Exception as e:
            logger.error(f"發送郵件失敗: {e}")
            return False
    
    def _markdown_to_html(self, markdown_text: str) -> str:
        """
        将 Markdown 轉換为簡單的 HTML
        
        支持：標題、加粗、列表、分隔線
        """
        html = markdown_text
        
        # 轉義 HTML 特殊字符
        html = html.replace('&', '&amp;')
        html = html.replace('<', '&lt;')
        html = html.replace('>', '&gt;')
        
        # 標題 (# ## ###)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        
        # 加粗 **text**
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        
        # 斜體 *text*
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # 分隔線 ---
        html = re.sub(r'^---$', r'<hr>', html, flags=re.MULTILINE)
        
        # 列表項 - item
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        
        # 引用 > text
        html = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
        
        # 換行
        html = html.replace('\n', '<br>\n')
        
        # 包裝 HTML
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; padding: 20px; max-width: 800px; margin: 0 auto; }}
                h1, h2, h3 {{ color: #333; }}
                hr {{ border: none; border-top: 1px solid #ddd; margin: 20px 0; }}
                blockquote {{ border-left: 4px solid #ddd; padding-left: 16px; color: #666; }}
                li {{ margin: 4px 0; }}
            </style>
        </head>
        <body>
            {html}
        </body>
        </html>
        """
    
    def send_to_telegram(self, content: str) -> bool:
        """
        推送消息到 Telegram 機器人
        
        Telegram Bot API 格式：
        POST https://api.telegram.org/bot<token>/sendMessage
        {
            "chat_id": "xxx",
            "text": "消息內容",
            "parse_mode": "Markdown"
        }
        
        Args:
            content: 消息內容(Markdown 格式)
            
        Returns:
            是否發送成功
        """
        if not self._is_telegram_configured():
            logger.warning("Telegram 配置不完整，跳過推送")
            return False
        
        bot_token = self._telegram_config['bot_token']
        chat_id = self._telegram_config['chat_id']
        
        try:
            # Telegram API 端點
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            
            # Telegram 消息最大長度 4096 字符
            max_length = 4096
            
            if len(content) <= max_length:
                # 單條消息發送
                return self._send_telegram_message(api_url, chat_id, content)
            else:
                # 分段發送长消息
                return self._send_telegram_chunked(api_url, chat_id, content, max_length)
                
        except Exception as e:
            logger.error(f"發送 Telegram 消息失敗: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def _send_telegram_message(self, api_url: str, chat_id: str, text: str) -> bool:
        """發送單條 Telegram 消息"""
        # 轉換 Markdown 为 Telegram 支持的格式
        # Telegram 的 Markdown 格式稍有不同，做簡單处理
        telegram_text = self._convert_to_telegram_markdown(text)
        
        payload = {
            "chat_id": chat_id,
            "text": telegram_text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        
        response = requests.post(api_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                logger.info("Telegram 消息發送成功")
                return True
            else:
                error_desc = result.get('description', '未知錯誤')
                logger.error(f"Telegram 返回錯誤: {error_desc}")
                
                # 如果 Markdown 解析失敗，嘗試純文本發送
                if 'parse' in error_desc.lower() or 'markdown' in error_desc.lower():
                    logger.info("嘗試使用純文本格式重新發送...")
                    payload['parse_mode'] = None
                    payload['text'] = text  # 使用原始文本
                    del payload['parse_mode']
                    
                    response = requests.post(api_url, json=payload, timeout=10)
                    if response.status_code == 200 and response.json().get('ok'):
                        logger.info("Telegram 消息發送成功(純文本)")
                        return True
                
                return False
        else:
            logger.error(f"Telegram 請求失敗: HTTP {response.status_code}")
            logger.error(f"響應內容: {response.text}")
            return False
    
    def _send_telegram_chunked(self, api_url: str, chat_id: str, content: str, max_length: int) -> bool:
        """分段發送长 Telegram 消息"""
        # 按段落分割
        sections = content.split("\n---\n")
        
        current_chunk = []
        current_length = 0
        all_success = True
        chunk_index = 1
        
        for section in sections:
            section_length = len(section) + 5  # +5 for "\n---\n"
            
            if current_length + section_length > max_length:
                # 發送當前块
                if current_chunk:
                    chunk_content = "\n---\n".join(current_chunk)
                    logger.info(f"發送 Telegram 消息塊 {chunk_index}...")
                    if not self._send_telegram_message(api_url, chat_id, chunk_content):
                        all_success = False
                    chunk_index += 1
                
                # 重置
                current_chunk = [section]
                current_length = section_length
            else:
                current_chunk.append(section)
                current_length += section_length
        
        # 發送最後一块
        if current_chunk:
            chunk_content = "\n---\n".join(current_chunk)
            logger.info(f"發送 Telegram 消息塊 {chunk_index}(最後)...")
            if not self._send_telegram_message(api_url, chat_id, chunk_content):
                all_success = False
        
        return all_success
    
    def _convert_to_telegram_markdown(self, text: str) -> str:
        """
        將標準 Markdown 轉換为 Telegram 支持的格式
        
        Telegram Markdown 限制：
        - 不支持 # 標題
        - 使用 *bold* 而非 **bold**
        - 使用 _italic_ 
        """
        result = text
        
        # 移除 # 標題標記(Telegram 不支持)
        result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)
        
        # 轉換 **bold** 为 *bold*
        result = re.sub(r'\*\*(.+?)\*\*', r'*\1*', result)
        
        # 轉義特殊字符(Telegram Markdown 需要)
        # 注意：不轉義已經用於格式的 * _ `
        for char in ['[', ']', '(', ')']:
            result = result.replace(char, f'\\{char}')
        
        return result
    
    def send_to_custom(self, content: str) -> bool:
        """
        推送消息到自定義 Webhook
        
        支持任意接受 POST JSON 的 Webhook 端點
        默認發送格式：{"text": "消息內容", "content": "消息內容"}
        
        適用於：
        - 釘釘機器人
        - Discord Webhook
        - Slack Incoming Webhook
        - 自建通知服務
        - 其他支持 POST JSON 的服务
        
        Args:
            content: 消息內容(Markdown 格式)
            
        Returns:
            是否至少有一個 Webhook 發送成功
        """
        if not self._custom_webhook_urls:
            logger.warning("未配置自定義 Webhook，跳過推送")
            return False
        
        success_count = 0
        
        for i, url in enumerate(self._custom_webhook_urls):
            try:
                # 通用 JSON 格式，兼容大多數 Webhook
                # 釘釘格式: {"msgtype": "text", "text": {"content": "xxx"}}
                # Slack 格式: {"text": "xxx"}
                # Discord 格式: {"content": "xxx"}
                
                # 檢測 URL 類型并構造對應格式
                payload = self._build_custom_webhook_payload(url, content)
                
                headers = {
                    'Content-Type': 'application/json',
                    'User-Agent': 'StockAnalysis/1.0'
                }
                
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                headers_with_charset = dict(headers)
                headers_with_charset['Content-Type'] = 'application/json; charset=utf-8'
                response = requests.post(
                    url,
                    data=body,
                    headers=headers_with_charset,
                    timeout=30
                )
                
                if response.status_code == 200:
                    logger.info(f"自定義 Webhook {i+1} 推送成功")
                    success_count += 1
                else:
                    logger.error(f"自定義 Webhook {i+1} 推送失敗: HTTP {response.status_code}")
                    logger.debug(f"響應內容: {response.text[:200]}")
                    
            except Exception as e:
                logger.error(f"自定義 Webhook {i+1} 推送異常: {e}")
        
        logger.info(f"自定義 Webhook 推送完成：成功 {success_count}/{len(self._custom_webhook_urls)}")
        return success_count > 0
    
    def _build_custom_webhook_payload(self, url: str, content: str) -> dict:
        """
        根據 URL 構建對應的 Webhook payload
        
        自動識別常見服务并使用對應格式
        """
        url_lower = url.lower()
        
        # 釘釘機器人
        if 'dingtalk' in url_lower or 'oapi.dingtalk.com' in url_lower:
            return {
                "msgtype": "markdown",
                "markdown": {
                    "title": "股票分析報告",
                    "text": content
                }
            }
        
        # Discord Webhook
        if 'discord.com/api/webhooks' in url_lower or 'discordapp.com/api/webhooks' in url_lower:
            # Discord 限制 2000 字符
            truncated = content[:1900] + "..." if len(content) > 1900 else content
            return {
                "content": truncated
            }
        
        # Slack Incoming Webhook
        if 'hooks.slack.com' in url_lower:
            return {
                "text": content,
                "mrkdwn": True
            }
        
        # Bark (iOS 推送)
        if 'api.day.app' in url_lower:
            return {
                "title": "股票分析報告",
                "body": content[:4000],  # Bark 限制
                "group": "stock"
            }
        
        # 通用格式(兼容大多數服务)
        return {
            "text": content,
            "content": content,
            "message": content,
            "body": content
        }
    
    def send(self, content: str) -> bool:
        """
        統一發送接口 - 向所有已配置的渠道發送
        
        遍歷所有已配置的渠道，逐一發送消息
        
        Args:
            content: 消息內容(Markdown 格式)
            
        Returns:
            是否至少有一個渠道發送成功
        """
        if not self.is_available():
            logger.warning("通知服務不可用，跳過推送")
            return False
        
        channel_names = self.get_channel_names()
        logger.info(f"正在向 {len(self._available_channels)} 個渠道發送通知：{channel_names}")
        
        success_count = 0
        fail_count = 0
        
        for channel in self._available_channels:
            channel_name = ChannelDetector.get_channel_name(channel)
            try:
                if channel == NotificationChannel.WECHAT:
                    result = self.send_to_wechat(content)
                elif channel == NotificationChannel.FEISHU:
                    result = self.send_to_feishu(content)
                elif channel == NotificationChannel.TELEGRAM:
                    result = self.send_to_telegram(content)
                elif channel == NotificationChannel.EMAIL:
                    result = self.send_to_email(content)
                elif channel == NotificationChannel.CUSTOM:
                    result = self.send_to_custom(content)
                else:
                    logger.warning(f"不支持的通知渠道: {channel}")
                    result = False
                
                if result:
                    success_count += 1
                else:
                    fail_count += 1
                    
            except Exception as e:
                logger.error(f"{channel_name} 發送失敗: {e}")
                fail_count += 1
        
        logger.info(f"通知發送完成：成功 {success_count} 個，失敗 {fail_count} 個")
        return success_count > 0
    
    def _send_chunked_messages(self, content: str, max_length: int) -> bool:
        """
        分段發送长消息
        
        按段落(---)分割，確保每段不超過最大長度
        """
        # 按分隔線分割
        sections = content.split("\n---\n")
        
        current_chunk = []
        current_length = 0
        all_success = True
        chunk_index = 1
        
        for section in sections:
            section_with_divider = section + "\n---\n"
            section_length = len(section_with_divider)
            
            if current_length + section_length > max_length:
                # 發送當前块
                if current_chunk:
                    chunk_content = "\n---\n".join(current_chunk)
                    logger.info(f"發送消息塊 {chunk_index}...")
                    if not self.send(chunk_content):
                        all_success = False
                    chunk_index += 1
                
                # 重置
                current_chunk = [section]
                current_length = section_length
            else:
                current_chunk.append(section)
                current_length += section_length
        
        # 發送最後一块
        if current_chunk:
            chunk_content = "\n---\n".join(current_chunk)
            logger.info(f"發送消息塊 {chunk_index}(最後)...")
            if not self.send(chunk_content):
                all_success = False
        
        return all_success
    
    def save_report_to_file(
        self, 
        content: str, 
        filename: Optional[str] = None
    ) -> str:
        """
        保存日報到本地文件
        
        Args:
            content: 日報內容
            filename: 文件名(可選，默認按日期生成)
            
        Returns:
            保存的文件路徑
        """
        from pathlib import Path
        
        if filename is None:
            date_str = datetime.now().strftime('%Y%m%d')
            filename = f"report_{date_str}.md"
        
        # 確保 reports 目錄存在
        reports_dir = Path(__file__).parent / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = reports_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"日報已保存到: {filepath}")
        return str(filepath)


class NotificationBuilder:
    """
    通知消息構建器
    
    提供便捷的消息構建方法
    """
    
    @staticmethod
    def build_simple_alert(
        title: str,
        content: str,
        alert_type: str = "info"
    ) -> str:
        """
        構建簡單的提醒消息
        
        Args:
            title: 標題
            content: 內容
            alert_type: 類型(info, warning, error, success)
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        emoji = emoji_map.get(alert_type, "📢")
        
        return f"{emoji} **{title}**\n\n{content}"
    
    @staticmethod
    def build_stock_summary(results: List[AnalysisResult]) -> str:
        """
        構建股票摘要(簡短版)
        
        適用於快速通知
        """
        lines = ["📊 **今日自選股摘要**", ""]
        
        for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
            emoji = r.get_emoji()
            lines.append(f"{emoji} {r.name}({r.code}): {r.operation_advice} | 評分 {r.sentiment_score}")
        
        return "\n".join(lines)


# 便捷函数
def get_notification_service() -> NotificationService:
    """獲取通知服務實例"""
    return NotificationService()


def send_daily_report(results: List[AnalysisResult]) -> bool:
    """
    發送每日報告的快捷方式
    
    自動識別渠道並推送
    """
    service = get_notification_service()
    
    # 生成報告
    report = service.generate_daily_report(results)
    
    # 保存到本地
    service.save_report_to_file(report)
    
    # 推送到配置的渠道(自動識別)
    return service.send(report)


if __name__ == "__main__":
    # 測試代碼
    logging.basicConfig(level=logging.DEBUG)
    
    # 模擬分析結果
    test_results = [
        AnalysisResult(
            code='600519',
            name='贵州茅台',
            sentiment_score=75,
            trend_prediction='看多',
            analysis_summary='技術面强势，消息面利好',
            operation_advice='買入',
            technical_analysis='放量突破 MA20，MACD 金叉',
            news_summary='公司發佈分紅公告，業績超預期',
        ),
        AnalysisResult(
            code='000001',
            name='平安银行',
            sentiment_score=45,
            trend_prediction='震荡',
            analysis_summary='橫盤整理，等待方向',
            operation_advice='持有',
            technical_analysis='均線粘合，成交量萎縮',
            news_summary='近期無重大消息',
        ),
        AnalysisResult(
            code='300750',
            name='宁德时代',
            sentiment_score=35,
            trend_prediction='看空',
            analysis_summary='技術面走弱，注意風險',
            operation_advice='賣出',
            technical_analysis='跌破 MA10 支撐，量能不足',
            news_summary='行業競爭加劇，毛利率承壓',
        ),
    ]
    
    service = NotificationService()
    
    # 显示檢測到的渠道
    print(f"=== 通知渠道檢測 ===")
    print(f"當前渠道: {service.get_channel_names()}")
    print(f"渠道列表: {service.get_available_channels()}")
    print(f"服务可用: {service.is_available()}")
    
    # 生成日報
    print("\n=== 生成日報測試 ===")
    report = service.generate_daily_report(test_results)
    print(report)
    
    # 保存到文件
    print("\n=== 保存日報 ===")
    filepath = service.save_report_to_file(report)
    print(f"保存成功: {filepath}")
    
    # 推送测试
    if service.is_available():
        print(f"\n=== 推送測試({service.get_channel_names()})===")
        success = service.send(report)
        print(f"推送結果: {'成功' if success else '失敗'}")
    else:
        print("\n通知渠道未配置，跳過推送测试")
