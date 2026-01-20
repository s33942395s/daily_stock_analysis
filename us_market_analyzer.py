from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

from data_provider.yfinance_shared import yfinance_download

logger = logging.getLogger(__name__)


FRED_GRAPH_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def _fred_latest(series_id: str, timeout_s: float = 10.0) -> Optional[Dict[str, Any]]:
    """
    Fetch latest value from FRED's fredgraph CSV endpoint (no API key required).
    """
    try:
        resp = requests.get(FRED_GRAPH_CSV, params={"id": series_id}, timeout=timeout_s)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        date_col = "DATE" if "DATE" in df.columns else ("observation_date" if "observation_date" in df.columns else None)
        if df.empty or date_col is None or series_id not in df.columns:
            return None

        # Keep last non-missing numeric value
        s = df[[date_col, series_id]].copy()
        s = s[s[series_id].astype(str) != "."]
        if s.empty:
            return None
        last = s.iloc[-1]
        return {"series": series_id, "date": str(last[date_col]), "value": float(last[series_id])}
    except Exception as e:
        logger.warning(f"[USMarket] FRED fetch failed ({series_id}): {e}")
        return None


def _as_list(tickers: Iterable[str]) -> List[str]:
    out: List[str] = []
    for t in tickers:
        t = (t or "").strip().upper()
        if t:
            out.append(t)
    return out


def _to_yahoo_ticker(symbol: str) -> str:
    """
    Convert symbols like BRK.B -> BRK-B for Yahoo Finance.
    """
    s = (symbol or "").strip().upper()
    return s.replace(".", "-")


def _fetch_history(
    tickers: List[str],
    period: str = "1y",
    timeout_s: float = 30.0,
) -> pd.DataFrame:
    tickers = _as_list(tickers)
    if not tickers:
        return pd.DataFrame()

    # yfinance sometimes struggles with huge lists; caller should keep it small.
    try:
        # use auto_adjust to work consistently across tickers (splits/dividends)
        df = yfinance_download(
            tickers=" ".join(tickers),
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception as e:
        logger.warning(f"[USMarket] yfinance history failed: {e}")
        return pd.DataFrame()


def _get_close_series(hist: pd.DataFrame, ticker: str) -> Optional[pd.Series]:
    """
    Extract close series from yfinance download output (handles single/multi ticker).
    """
    if hist is None or hist.empty:
        return None

    # Single ticker
    if "Close" in hist.columns and not isinstance(hist.columns, pd.MultiIndex):
        s = hist["Close"]
        return s.dropna()

    # MultiIndex: first level should be OHLCV, second level tickers (or vice versa)
    if isinstance(hist.columns, pd.MultiIndex):
        t = ticker.upper()
        t_alt = _to_yahoo_ticker(t)
        for candidate in (t, t_alt):
            try:
                if ("Close", candidate) in hist.columns:
                    return hist[("Close", candidate)].dropna()
            except Exception:
                pass

        # Fallback: try to slice by ticker then take Close
        try:
            if t in set(hist.columns.get_level_values(-1)):
                xs = hist.xs(t, axis=1, level=-1, drop_level=True)
                if "Close" in xs.columns:
                    return xs["Close"].dropna()
        except Exception:
            pass

    return None


def _ma(series: pd.Series, window: int) -> Optional[float]:
    if series is None or series.empty or len(series) < window:
        return None
    return float(series.rolling(window=window).mean().iloc[-1])


def _trend_regime(close: float, ma50: Optional[float], ma200: Optional[float]) -> str:
    if ma200 is None or ma50 is None:
        return "未知"
    if close > ma200 and ma50 > ma200:
        return "多頭結構"
    if close < ma200 and ma50 < ma200:
        return "空頭結構"
    return "區間/轉折"


def _pct_above_200dma(universe: List[str], period: str = "1y") -> Optional[Dict[str, Any]]:
    """
    Breadth proxy: % of tickers above their 200DMA (universe should be <= ~120).
    """
    tickers = [_to_yahoo_ticker(t) for t in _as_list(universe)]
    hist = _fetch_history(tickers, period=period)
    if hist.empty:
        return None

    above = 0
    valid = 0
    for t in tickers:
        s = _get_close_series(hist, t)
        if s is None or len(s) < 210:
            continue
        ma200 = s.rolling(200).mean().iloc[-1]
        close = float(s.iloc[-1])
        if pd.isna(ma200):
            continue
        valid += 1
        if close > float(ma200):
            above += 1

    if valid == 0:
        return None

    return {
        "universe": "SP100",
        "valid": valid,
        "above_200dma": above,
        "pct_above_200dma": round(above / valid * 100, 1),
    }


def _sp100_tickers(timeout_s: float = 10.0) -> List[str]:
    """
    Pull S&P 100 constituents from Wikipedia without requiring optional HTML parsers.
    """
    url = "https://en.wikipedia.org/wiki/S%26P_100"
    try:
        html = requests.get(
            url,
            timeout=timeout_s,
            headers={"User-Agent": "daily_stock_analysis/1.0 (+https://example.invalid)"},
        ).text

        # Find a wikitable that contains a "Symbol" header.
        tables = re.findall(r"(<table[^>]*class=\"[^\"]*wikitable[^\"]*\"[^>]*>.*?</table>)", html, flags=re.S)
        for table_html in tables:
            if "Symbol" not in table_html:
                continue

            # Header: find column index of "Symbol"
            header_match = re.search(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.S)
            if not header_match:
                continue
            header_html = header_match.group(1)
            headers = re.findall(r"<th[^>]*>(.*?)</th>", header_html, flags=re.S)
            headers_text = [re.sub(r"<.*?>", "", h, flags=re.S).strip() for h in headers]
            try:
                symbol_idx = headers_text.index("Symbol")
            except ValueError:
                continue

            # Rows: extract <td> cells and take symbol column
            symbols: List[str] = []
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.S)[1:]:
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
                if len(cells) <= symbol_idx:
                    continue
                cell = cells[symbol_idx]
                text = re.sub(r"<.*?>", "", cell, flags=re.S)
                text = re.sub(r"\[.*?\]", "", text).strip()  # remove footnotes like [1]
                text = text.replace("\xa0", "").strip()
                if text:
                    symbols.append(text)

            if symbols:
                return symbols
    except Exception as e:
        logger.warning(f"[USMarket] Failed to load SP100 tickers: {e}")
    return []


def get_us_market_indicators(
    breadth_limit: int = 100,
) -> Dict[str, Any]:
    """
    Build a US macro/market snapshot to be injected into the LLM context.

    Includes:
    - Trend: SPX/SPY regime (close vs 50/200MA)
    - Breadth: RSP vs SPY ratio
    - Breadth2: % above 200DMA (SP100 proxy)
    - Vol: VIX
    - Rates: 10Y/2Y (FRED), plus 2s10s
    - Credit: HY OAS (FRED)
    - Dollar: DXY
    """
    started = time.time()
    snapshot: Dict[str, Any] = {"asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    # --- Price-based indicators (Yahoo Finance) ---
    tickers = ["^GSPC", "SPY", "RSP", "^VIX", "DX-Y.NYB"]
    hist = _fetch_history(tickers, period="1y")

    # SPY / SPX trend regime
    for sym in ("^GSPC", "SPY"):
        s = _get_close_series(hist, sym)
        if s is None or s.empty:
            continue
        close = float(s.iloc[-1])
        ma50 = _ma(s, 50)
        ma200 = _ma(s, 200)
        snapshot["trend"] = {
            "symbol": sym,
            "close": round(close, 2),
            "ma50": None if ma50 is None else round(ma50, 2),
            "ma200": None if ma200 is None else round(ma200, 2),
            "regime": _trend_regime(close, ma50, ma200),
        }
        break

    # Breadth: equal weight vs cap weight
    rsp = _get_close_series(hist, "RSP")
    spy = _get_close_series(hist, "SPY")
    if rsp is not None and spy is not None and not rsp.empty and not spy.empty:
        ratio = (rsp / spy).dropna()
        snapshot["breadth_rsp_vs_spy"] = {
            "ratio": round(float(ratio.iloc[-1]), 4),
            "ratio_ma50": None if len(ratio) < 50 else round(float(ratio.rolling(50).mean().iloc[-1]), 4),
            "interpretation": "等權重相對強勢" if len(ratio) >= 50 and ratio.iloc[-1] > ratio.rolling(50).mean().iloc[-1] else "權值股相對更強/廣度偏弱",
        }

    # VIX
    vix = _get_close_series(hist, "^VIX")
    if vix is not None and not vix.empty:
        snapshot["volatility_vix"] = {
            "close": round(float(vix.iloc[-1]), 2),
            "ma20": None if len(vix) < 20 else round(float(vix.rolling(20).mean().iloc[-1]), 2),
        }

    # DXY
    dxy = _get_close_series(hist, "DX-Y.NYB")
    if dxy is not None and not dxy.empty:
        snapshot["usd_dxy"] = {
            "close": round(float(dxy.iloc[-1]), 2),
            "ma20": None if len(dxy) < 20 else round(float(dxy.rolling(20).mean().iloc[-1]), 2),
        }

    # --- Rates/Credit (FRED) ---
    y10 = _fred_latest("DGS10")
    y2 = _fred_latest("DGS2")
    if y10:
        snapshot["rates_10y"] = y10
    if y2:
        snapshot["rates_2y"] = y2
    if y10 and y2:
        snapshot["rates_2s10s"] = {
            "date": max(y10["date"], y2["date"]),
            "value": round(float(y10["value"]) - float(y2["value"]), 3),
            "unit": "pct",
        }

    hy = _fred_latest("BAMLH0A0HYM2")
    if hy:
        snapshot["credit_hy_oas"] = hy

    # --- Breadth2: % above 200DMA (SP100 proxy) ---
    sp100 = _sp100_tickers()
    if sp100:
        if breadth_limit and len(sp100) > breadth_limit:
            sp100 = sp100[:breadth_limit]
        breadth = _pct_above_200dma(sp100, period="1y")
        if breadth:
            snapshot["breadth_pct_above_200dma"] = breadth

    snapshot["elapsed_s"] = round(time.time() - started, 2)

    # INFO log when we successfully got anything meaningful
    summary_parts: List[str] = []
    trend = snapshot.get("trend")
    if isinstance(trend, dict) and trend.get("close") is not None:
        summary_parts.append(f"trend={trend.get('symbol')} {trend.get('regime')}")
    breadth = snapshot.get("breadth_rsp_vs_spy")
    if isinstance(breadth, dict) and breadth.get("ratio") is not None:
        summary_parts.append(f"RSP/SPY={breadth.get('ratio')}")
    breadth2 = snapshot.get("breadth_pct_above_200dma")
    if isinstance(breadth2, dict) and breadth2.get("pct_above_200dma") is not None:
        summary_parts.append(f">%200DMA={breadth2.get('pct_above_200dma')}% (n={breadth2.get('valid')})")
    vix = snapshot.get("volatility_vix")
    if isinstance(vix, dict) and vix.get("close") is not None:
        summary_parts.append(f"VIX={vix.get('close')}")
    y10 = snapshot.get("rates_10y")
    if isinstance(y10, dict) and y10.get("value") is not None:
        summary_parts.append(f"10Y={y10.get('value')}%")
    y2 = snapshot.get("rates_2y")
    if isinstance(y2, dict) and y2.get("value") is not None:
        summary_parts.append(f"2Y={y2.get('value')}%")
    hy = snapshot.get("credit_hy_oas")
    if isinstance(hy, dict) and hy.get("value") is not None:
        summary_parts.append(f"HY_OAS={hy.get('value')}%")
    dxy = snapshot.get("usd_dxy")
    if isinstance(dxy, dict) and dxy.get("close") is not None:
        summary_parts.append(f"DXY={dxy.get('close')}")

    if summary_parts:
        logger.info(f"[USMarket] Indicators OK ({snapshot.get('elapsed_s')}s): " + ", ".join(summary_parts))

    return snapshot


def format_us_market_indicators_for_prompt(indicators: Dict[str, Any]) -> str:
    """
    Human-readable summary for LLM prompt (keeps JSON small elsewhere if needed).
    """
    if not indicators:
        return ""
    return json.dumps(indicators, ensure_ascii=False, indent=2)
