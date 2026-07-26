"""Web 数据降级获取器 — 当 primary source 返回 UNAVAILABLE 时自动保底。

架构:
  每个 fetch_*() 函数返回统一 dict 格式:
    {"data": {字段...}, "summary": "...", "data_grade": "DERIVED", "source_url": "..."}

  当 primary source 失败时，data_adapter/__init__.py 自动降级到此模块。
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 公开财经 API 端点 ─────────────────────────────────

_SINA_KLINE_URL = "https://stock.finance.sina.com.cn/futures/api/json_v2.php/IndexService.getInnerFuturesDailyKLine"
_EAST_MONEY_SEARCH = "https://searchadapter.eastmoney.com/api/suggest/get"
_EAST_MONEY_FUTURE = "https://datacenter.eastmoney.com/api/data/v1/get"

# 品种→东方财富品种代码映射
_SYMBOL_TO_EM: dict[str, str] = {
    "RB": "rb", "HC": "hc", "I": "i", "J": "j", "JM": "jm",
    "CU": "cu", "AL": "al", "ZN": "zn", "PB": "pb", "NI": "ni",
    "SN": "sn", "AU": "au", "AG": "ag", "RU": "ru", "BU": "bu",
    "MA": "ma", "TA": "ta", "EG": "eg", "PF": "pf",
    "SC": "sc", "FU": "fu", "LU": "lu",
    "M": "m", "RM": "rm", "Y": "y", "P": "p", "OI": "oi",
    "SR": "sr", "CF": "cf", "ZC": "zc", "FG": "fg",
    "SP": "sp", "SS": "ss", "UR": "ur", "SA": "sa",
}


def _derived_dict(data: dict, summary: str, source_url: str = "") -> dict:
    """构造带溯源标记的降级数据字典。"""
    result: dict = {
        "data": data,
        "summary": summary,
        "data_grade": "DERIVED",
    }
    if source_url:
        result["source_url"] = source_url
    else:
        result["source_note"] = "Web 搜索降级数据，精度可能低于 PRIMARY"
    return result


async def fetch_basis_from_web(symbol: str) -> dict:
    """从东方财富获取基差数据（现货价 + 期货价 → 基差）。"""
    bare = symbol.upper().replace(".SH", "").replace(".SZ", "")
    em_code = _SYMBOL_TO_EM.get(bare)
    if not em_code:
        return _derived_dict({"symbol": bare, "spot_price": None, "basis": None, "basis_pct": None},
                             f"暂不支持 {bare} 基差 Web 降级")
    try:
        import httpx
        # 通过东方财富接口获取现货价格
        url = f"https://pushhis.eastmoney.com/api/qt/stock/kline/get?secid=1.{em_code}&fields1=f1,f2,f3&fields2=f51,f52&klt=101&fqt=1"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise ConnectionError(f"HTTP {resp.status_code}")
            raw = resp.json()
            # 解析返回值
            data_raw = raw.get("data", {})
            spot_price = None
            klines = data_raw.get("klines", [])
            if klines:
                last = klines[-1].split(",")
                if len(last) >= 2:
                    spot_price = float(last[1]) if last[1] != "-" else None
            if spot_price:
                return _derived_dict(
                    {"symbol": bare, "spot_price": spot_price, "basis": None, "basis_pct": None},
                    f"{bare} 现货价 {spot_price}（Web 降级）",
                    source_url="https://pushhis.eastmoney.com",
                )
    except Exception as e:
        logger.warning("[WebFallback] fetch_basis(%s) 失败: %s", symbol, e)
    return _derived_dict({"symbol": bare, "spot_price": None, "basis": None, "basis_pct": None},
                         f"{bare} 基差 Web 降级不可用")


async def fetch_warrant_from_web(symbol: str, exchange: str = "SHFE") -> dict:
    """从东方财富获取仓单日报数据。"""
    bare = symbol.upper().replace(".SH", "").replace(".SZ", "")
    try:
        import httpx
        # 东方财富数据中心 - 仓单 API
        url = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get"
            f"?reportName=RPT_DCE_WARRANT&columns=ALL"
            f"&filter=(VARIETY=\"{bare}\")&pageNumber=1&pageSize=5"
            f"&sortTypes=-1&sortColumns=NOTICE_DATE"
        )
        # DCE/SHFE/CZCE 不同交易所可能有不同接口
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                result = resp.json()
                items = (result.get("result") or {}).get("data", [])
                if items:
                    latest = items[0]
                    total = latest.get("WARRANT_VOLUME") or latest.get("total")
                    change = latest.get("CHANGE") or latest.get("daily_change")
                    if total is not None:
                        return _derived_dict(
                            {"symbol": bare, "exchange": exchange, "total": float(total),
                             "daily_change": float(change) if change else None},
                            f"{bare} ({exchange}) 仓单 {total}（Web 降级）",
                            source_url="https://datacenter.eastmoney.com",
                        )
    except Exception as e:
        logger.warning("[WebFallback] fetch_warrant(%s) 失败: %s", symbol, e)
    return _derived_dict({"symbol": bare, "exchange": exchange, "total": None, "daily_change": None},
                         f"{bare} 仓单 Web 降级不可用")


async def fetch_spread_from_web(symbol: str) -> dict:
    """从东方财富获取跨期价差数据。"""
    bare = symbol.upper().replace(".SH", "").replace(".SZ", "")
    em_code = _SYMBOL_TO_EM.get(bare)
    if not em_code:
        return _derived_dict({"symbol": bare, "spreads": []}, f"暂不支持 {bare} 价差 Web 降级")
    try:
        import httpx
        # 获取主力合约和次主力合约价格
        url = f"https://hq.sinajs.cn/list={em_code.upper()}0"
        # 实际使用东方财富连续合约 API
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://pushhis.eastmoney.com/api/qt/stock/kline/get?secid=0,{bare}&fields1=f1,f2,f3&fields2=f51,f52&klt=101&fqt=1",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                return _derived_dict(
                    {"symbol": bare, "spreads": [], "note": "价差数据需额外合约计算"},
                    f"{bare} 跨期价差暂通过合约价差计算（Web 降级）",
                    source_url="https://pushhis.eastmoney.com",
                )
    except Exception as e:
        logger.warning("[WebFallback] fetch_spread(%s) 失败: %s", symbol, e)
    return _derived_dict({"symbol": bare, "spreads": []}, f"{bare} 跨期价差 Web 降级不可用")


async def fetch_money_flow_from_web(symbol: str) -> dict:
    """从东方财富获取个股资金流向。"""
    bare = symbol.upper().replace(".SH", "").replace(".SZ", "")
    # 确定市场代码 1=上海 0=深圳
    market = "1" if bare.startswith("6") else "0"
    try:
        import httpx
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{bare}&fields=f62,f64,f66,f69,f72,f75,f78,f84"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                raw = resp.json()
                d = raw.get("data", {})
                if d:
                    # f62=主力净流入, f64=超大单净流入, f66=大单净流入
                    # f69=中单净流入, f72=小单净流入, f78=散户净流入
                    main_in = d.get("f62", 0) or 0
                    retail = abs(d.get("f78", 0) or 0)
                    mid = abs(d.get("f69", 0) or 0)
                    return _derived_dict(
                        {"symbol": bare, "main_net_inflow": main_in,
                         "retail_net_inflow": retail, "mid_net_inflow": mid},
                        f"{bare} 主力净流入 {main_in}（Web 降级）",
                        source_url="https://push2.eastmoney.com",
                    )
    except Exception as e:
        logger.warning("[WebFallback] fetch_money_flow(%s) 失败: %s", symbol, e)
    return _derived_dict({"symbol": bare, "main_net_inflow": None},
                         f"{bare} 资金流向 Web 降级不可用")


async def fetch_north_flow_from_web(symbol: str) -> dict:
    """从东方财富获取北向资金数据。"""
    bare = symbol.upper().replace(".SH", "").replace(".SZ", "")
    market = "1" if bare.startswith("6") else "0"
    try:
        import httpx
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{bare}&fields=f162,f163,f164,f165"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                raw = resp.json()
                d = raw.get("data", {})
                if d:
                    net_buy = d.get("f162", 0) or 0  # 北向净买入
                    holding_pct = d.get("f164", 0) or 0  # 持股占比
                    return _derived_dict(
                        {"symbol": bare, "north_net_buy": net_buy,
                         "north_holding_pct": holding_pct},
                        f"{bare} 北向净买入 {net_buy}（Web 降级）",
                        source_url="https://push2.eastmoney.com",
                    )
    except Exception as e:
        logger.warning("[WebFallback] fetch_north_flow(%s) 失败: %s", symbol, e)
    return _derived_dict({"symbol": bare, "north_net_buy": None},
                         f"{bare} 北向资金 Web 降级不可用")


async def fetch_etf_premium_from_web(symbol: str) -> dict:
    """从东方财富获取 ETF 溢价率。"""
    bare = symbol.upper().replace(".SH", "").replace(".SZ", "")
    market = "1" if bare.startswith("5") else "0"
    try:
        import httpx
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={market}.{bare}&fields=f170,f171,f172,f173"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                raw = resp.json()
                d = raw.get("data", {})
                if d:
                    premium = d.get("f170", 0) or 0  # ETF 溢价率(%)
                    if premium != 0:
                        return _derived_dict(
                            {"symbol": bare, "premium_pct": premium},
                            f"{bare} ETF溢价 {premium}%（Web 降级）",
                            source_url="https://push2.eastmoney.com",
                        )
    except Exception as e:
        logger.warning("[WebFallback] fetch_etf_premium(%s) 失败: %s", symbol, e)
    return _derived_dict({"symbol": bare, "premium_pct": None},
                         f"{bare} ETF溢价 Web 降级不可用")


async def fetch_inventory_from_web(symbol: str) -> dict:
    """从东方财富获取库存数据（AKShare 主力降级）。"""
    bare = symbol.upper().replace(".SH", "").replace(".SZ", "")
    try:
        import httpx
        url = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get"
            f"?reportName=RPT_FUTURES_INVENTORY&columns=ALL"
            f"&filter=(VARIETY=\"{bare}\")&pageNumber=1&pageSize=5"
            f"&sortTypes=-1&sortColumns=NOTICE_DATE"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                result = resp.json()
                items = (result.get("result") or {}).get("data", [])
                if items:
                    latest = items[0]
                    inv = latest.get("INVENTORY") or latest.get("total")
                    change = latest.get("CHANGE") or latest.get("change")
                    unit = latest.get("UNIT") or "吨"
                    if inv is not None:
                        return _derived_dict(
                            {"symbol": bare, "inventory": float(inv),
                             "change": float(change) if change else None,
                             "unit": unit, "data_date": str(latest.get("NOTICE_DATE", ""))},
                            f"{bare} 库存 {inv} {unit}（Web 降级）",
                            source_url="https://datacenter.eastmoney.com",
                        )
    except Exception as e:
        logger.warning("[WebFallback] fetch_inventory(%s) 失败: %s", symbol, e)
    return _derived_dict({"symbol": bare, "inventory": None, "change": None},
                         f"{bare} 库存 Web 降级不可用")
