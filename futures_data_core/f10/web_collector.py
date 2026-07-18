"""Web HTTP 行情/新闻采集 — FDC 独立数据源 [INDEPENDENT]。

======================================================
归属说明：本模块是 FDC (futures_data_core) 的一部分，
所有外部网页数据采集统一通过此模块接入，不散落其他目录。
======================================================

通过新浪财经和东方财富的公开 HTTP API 获取期货行情、
K线数据和行业新闻。无 LLM 依赖，纯 Python 标准库 + requests。

数据源（当前环境已验证可用）：
  - 新浪财经行情/K线 API  — 行情快照 + 日K线
  - 东方财富新闻搜索 API  — 行业新闻

使用示例：
    from futures_data_core.f10.web_collector import fetch_quote, fetch_kline, search_news
    quote = fetch_quote("RB")
    kline = fetch_kline("CU", days=30)
    news = search_news("螺纹钢 库存")
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

__all__ = [
    "fetch_quote",
    "fetch_kline",
    "search_news",
    "collect_fundamental_web",
]


# ════════════════════════════════════════════════════════════
# 1. 新浪财经期货实时行情
# ════════════════════════════════════════════════════════════
def fetch_quote(variety: str) -> dict:
    """获取期货品种实时行情快照（新浪财经）。

    通过新浪财经 hq.sinajs.cn 接口获取期货主力合约的实时行情，
    包含最新价、涨跌幅、成交量、持仓量等。

    运行模式: ``[INDEPENDENT]``。

    Args:
        variety: 品种代码，如 "RB"、"CU"、"I"

    Returns:
        行情字典，含 symbol / last_price / change_pct / volume / open_interest / 等。
    """
    sym = variety.upper()
    result: dict[str, Any] = {
        "symbol": sym,
        "source": "sina_finance",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        url = f"https://hq.sinajs.cn/list={sym}0"
        resp = requests.get(
            url,
            headers={"User-Agent": _UA, "Referer": "https://finance.sina.com.cn/"},
            timeout=10,
        )
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        text = resp.text
        match = re.search(r'var hq_str_\w+="([^"]+)"', text)
        if not match:
            result["error"] = "parse failed: no quote data"
            return result

        parts = match.group(1).split(",")
        if len(parts) < 20:
            result["error"] = f"parse failed: expected 20+ fields, got {len(parts)}"
            return result

        result["name"] = parts[0]
        result["open"] = float(parts[1]) if parts[1] else 0
        result["last_price"] = float(parts[2]) if parts[2] else 0
        result["high"] = float(parts[3]) if parts[3] else 0
        result["low"] = float(parts[4]) if parts[4] else 0
        result["pre_close"] = float(parts[5]) if parts[5] else 0
        result["volume"] = int(float(parts[8])) if parts[8] else 0
        result["open_interest"] = int(float(parts[9])) if parts[9] else 0
        result["date"] = parts[17] if len(parts) > 17 else ""
        result["time"] = parts[18] if len(parts) > 18 else ""

        if result["pre_close"] and result["last_price"]:
            result["change_pct"] = round(
                (result["last_price"] - result["pre_close"]) / result["pre_close"] * 100,
                2,
            )
        else:
            result["change_pct"] = 0

    except Exception as e:
        result["error"] = f"quote fetch failed: {str(e)[:80]}"

    return result


# ════════════════════════════════════════════════════════════
# 2. 新浪财经期货日K线
# ════════════════════════════════════════════════════════════
def fetch_kline(variety: str, days: int = 30) -> dict:
    """获取期货品种日K线数据（新浪财经）。

    获取主力连续合约的日线数据，包含开高低收、成交量、持仓量，
    以及均线趋势方向。

    运行模式: ``[INDEPENDENT]``。

    Args:
        variety: 品种代码，如 "RB"、"CU"
        days: 返回最近 N 根 K 线

    Returns:
        {symbol, bars: [{date, open, high, low, close, volume, oi}], ma5, ma20, ma_trend}
    """
    sym = variety.upper()
    result: dict[str, Any] = {
        "symbol": sym,
        "source": "sina_finance",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bars": [],
    }

    try:
        url = (
            f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php"
            f"/var%20_{sym}0=/InnerFuturesNewService.getDailyKLine"
            f"?symbol={sym}0"
        )
        resp = requests.get(
            url,
            headers={"User-Agent": _UA, "Referer": "https://finance.sina.com.cn/"},
            timeout=10,
        )
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}"
            return result

        text = resp.text
        match = re.search(r"=\((\[.+?\])\)", text, re.DOTALL)
        if not match:
            result["error"] = "parse failed: no kline data"
            return result

        klines = json.loads(match.group(1))
        if not klines:
            result["error"] = "empty kline data"
            return result

        bars = []
        for k in klines[-days:]:
            bars.append({
                "date": str(k.get("d", "")).replace("-", ""),
                "open": float(k.get("o", 0)),
                "high": float(k.get("h", 0)),
                "low": float(k.get("l", 0)),
                "close": float(k.get("c", 0)),
                "volume": int(float(k.get("v", 0))),
                "oi": int(float(k.get("p", 0))) if k.get("p") else 0,
            })
        result["bars"] = bars
        result["count"] = len(bars)

        if len(bars) >= 2:
            fc, lc = bars[0]["close"], bars[-1]["close"]
            result["change_pct"] = round((lc - fc) / fc * 100, 2) if fc else 0

        if len(bars) >= 5:
            ma5 = sum(b["close"] for b in bars[-5:]) / 5
            result["ma5"] = round(ma5, 2)
        if len(bars) >= 20:
            ma20 = sum(b["close"] for b in bars[-20:]) / 20
            result["ma20"] = round(ma20, 2)
            if "ma5" in result:
                result["ma_trend"] = (
                    "up" if result["ma5"] > ma20
                    else "down" if result["ma5"] < ma20
                    else "flat"
                )

    except Exception as e:
        result["error"] = f"kline fetch failed: {str(e)[:80]}"

    return result


# ════════════════════════════════════════════════════════════
# 3. 行业新闻搜索（东方财富新闻）
# ════════════════════════════════════════════════════════════
def search_news(keyword: str, max_results: int = 5) -> dict:
    """搜索期货相关最新行业新闻（东方财富）。

    运行模式: ``[INDEPENDENT]``。

    Args:
        keyword: 搜索关键词，如 "螺纹钢"、"铜 库存"
        max_results: 返回最多结果数

    Returns:
        {keyword, news: [{title, url, date}], source}
    """
    import urllib.parse

    result: dict[str, Any] = {
        "keyword": keyword,
        "source": "eastmoney_news",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "news": [],
    }

    try:
        encoded = urllib.parse.quote(f"{keyword} 期货")
        url = (
            "https://search-api-web.eastmoney.com/search/jsonp"
            f"?cb=jQuery&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{encoded}%22"
            f"%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D%2C%22client%22%3A%22web%22"
            f"%2C%22clientType%22%3A%22web%22%2C%22clientVersion%22%3A%22curr%22"
            f"%2C%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22"
            f"%2C%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A{max_results}%7D%7D%7D"
        )
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=10)
        if resp.status_code == 200:
            text = re.sub(r"^jQuery\(|\);?$", "", resp.text)
            data = json.loads(text)
            articles = data.get("data", {}).get("cmsArticleWebOld", {}).get("list", [])
            for article in articles[:max_results]:
                result["news"].append({
                    "title": article.get("title", "").strip(),
                    "url": article.get("url", ""),
                    "date": article.get("date", "")[:10],
                })
    except Exception as e:
        result["error"] = f"news search failed: {str(e)[:80]}"

    return result


# ════════════════════════════════════════════════════════════
# 4. 综合基本面采集（一键获取多源数据）
# ════════════════════════════════════════════════════════════
def collect_fundamental_web(variety: str, keyword: str = "") -> dict:
    """综合采集品种基本面数据（行情+K线+新闻）。

    同时获取行情快照、K线趋势、相关新闻，适合注入到大模型上下文。

    运行模式: ``[INDEPENDENT]``。

    Args:
        variety: 品种代码，如 "RB"
        keyword: 可选搜索关键词，为空时自动从品种代码推断中文名

    Returns:
        综合数据结构，含 quote / kline / news 三个子模块
    """
    sym_name_map = {
        "RB": "螺纹钢", "HC": "热卷", "I": "铁矿石", "CU": "铜",
        "AL": "铝", "ZN": "锌", "NI": "镍", "AU": "黄金", "AG": "白银",
        "SC": "原油", "MA": "甲醇", "TA": "PTA", "FG": "玻璃",
        "M": "豆粕", "Y": "豆油", "P": "棕榈油", "SR": "白糖",
        "CF": "棉花", "OI": "菜油", "RM": "菜粕", "RU": "橡胶",
        "J": "焦炭", "JM": "焦煤", "SA": "纯碱", "EC": "集运指数",
        "SI": "工业硅", "LC": "碳酸锂", "PK": "花生",
    }
    kw = keyword or sym_name_map.get(variety.upper(), variety)
    import concurrent.futures

    result: dict[str, Any] = {
        "symbol": variety.upper(),
        "source": "fdc_web_collector",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        qf = pool.submit(fetch_quote, variety)
        kf = pool.submit(fetch_kline, variety, 30)
        nf = pool.submit(search_news, kw, 3)

        result["quote"] = qf.result()
        result["kline"] = kf.result()
        result["news"] = nf.result()

        result["warnings"] = []
        for key in ["quote", "kline", "news"]:
            err = result[key].get("error")
            if err:
                result["warnings"].append(f"{key}: {err}")

    return result


# ── 保留旧接口（search_fundamental_llm 来自原 LLM-DRIVEN 模块）──
