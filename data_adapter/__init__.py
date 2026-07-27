"""数据适配层 — 数据源插座路由入口。

环境变量 FDT_DATA_SOURCE 控制当前使用的数据源：
  - "akshare" (默认): AKShareSource（期货 + A 股基本）
  - "tencent": TencentStockSource（腾讯自选股 — A 股/ETF 首选）

所有接口均为 async 函数，直接调用即可，不关心底层数据源实现。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from data_adapter.base import DataSource
from data_adapter.sources.akshare_source import AKShareSource
from data_adapter.types import KlineResult, QuoteResult

logger = logging.getLogger(__name__)

# ── 全局数据源单例 ──
_SOURCE_NAME = os.environ.get("FDT_DATA_SOURCE", "akshare").lower()

_DATA_SOURCE: Optional[DataSource] = None


def _get_source() -> DataSource:
    """获取当前数据源实例（懒加载单例）。"""
    global _DATA_SOURCE
    if _DATA_SOURCE is not None:
        return _DATA_SOURCE

    logger.info("[DataAdapter] 初始化数据源: %s", _SOURCE_NAME)

    if _SOURCE_NAME == "akshare":
        _DATA_SOURCE = AKShareSource()
    elif _SOURCE_NAME == "tencent":
        from data_adapter.sources.tencent_source import TencentStockSource
        _DATA_SOURCE = TencentStockSource()
    else:
        logger.warning("[DataAdapter] 未知数据源 %s，降级到 akshare", _SOURCE_NAME)
        _DATA_SOURCE = AKShareSource()

    return _DATA_SOURCE


# ── 通用接口 ──


async def get_kline(symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
    """获取 K 线数据。"""
    return await _get_source().get_kline(symbol, period, days)


async def get_quote(symbol: str) -> QuoteResult:
    """获取行情快照。"""
    return await _get_source().get_quote(symbol)


async def batch_get_quotes(symbols: list[str]) -> dict[str, QuoteResult]:
    """批量获取行情快照。"""
    return await _get_source().batch_get_quotes(symbols)


async def get_macro_pmi() -> dict:
    """获取 PMI 宏观数据。"""
    return await _get_source().get_macro_pmi()


async def get_macro_rate() -> dict:
    """获取利率宏观数据。"""
    return await _get_source().get_macro_rate()


# ── 权益专有接口（EquityDataSource 方法） ──


async def get_financials(symbol: str) -> dict:
    """获取财务报表核心指标。"""
    src = _get_source()
    if hasattr(src, "get_financials"):
        return await src.get_financials(symbol)  # type: ignore
    return {"symbol": symbol, "data_grade": "UNAVAILABLE", "note": "当前数据源不支持"}


async def get_dividend(symbol: str) -> dict:
    """获取分红记录。"""
    src = _get_source()
    if hasattr(src, "get_dividend"):
        return await src.get_dividend(symbol)  # type: ignore
    return {"symbol": symbol, "data_grade": "UNAVAILABLE"}


async def get_north_flow(symbol: str) -> dict:
    """获取北向资金流向。"""
    src = _get_source()
    if hasattr(src, "get_north_flow"):
        result = await src.get_north_flow(symbol)  # type: ignore
        if result.get("data_grade") != "UNAVAILABLE":
            return result
    from data_adapter.sources.web_data_fetcher import fetch_north_flow_from_web
    return await fetch_north_flow_from_web(symbol)


async def get_etf_nav(symbol: str) -> dict:
    """获取 ETF 净值。"""
    src = _get_source()
    if hasattr(src, "get_etf_nav"):
        return await src.get_etf_nav(symbol)  # type: ignore
    return {"symbol": symbol, "data_grade": "UNAVAILABLE"}


async def get_etf_constituents(symbol: str) -> dict:
    """获取 ETF 成分股。"""
    src = _get_source()
    if hasattr(src, "get_etf_constituents"):
        return await src.get_etf_constituents(symbol)  # type: ignore
    return {"symbol": symbol, "data_grade": "UNAVAILABLE"}


async def get_etf_premium(symbol: str) -> dict:
    """获取 ETF 溢价率。"""
    src = _get_source()
    if hasattr(src, "get_etf_premium"):
        result = await src.get_etf_premium(symbol)  # type: ignore
        if result.get("data_grade") != "UNAVAILABLE":
            return result
    from data_adapter.sources.web_data_fetcher import fetch_etf_premium_from_web
    return await fetch_etf_premium_from_web(symbol)


async def get_money_flow(symbol: str) -> dict:
    """获取个股资金流向（腾讯特有：主力/中户/散户净流入）。

    TencentStockSource 专有能力，AKShareSource 返回 UNAVAILABLE。
    """
    src = _get_source()
    if hasattr(src, "get_money_flow"):
        result = await src.get_money_flow(symbol)  # type: ignore
        if result.get("data_grade") != "UNAVAILABLE":
            return result
    from data_adapter.sources.web_data_fetcher import fetch_money_flow_from_web
    return await fetch_money_flow_from_web(symbol)


# ── 期货专有接口（FuturesDataSource 方法，仅 AKShareSource 支持） ──


async def get_contract_info(symbol: str) -> dict:
    """获取合约信息。"""
    return await _get_source().get_contract_info(symbol)  # type: ignore


async def get_warrant(symbol: str, exchange: str = "SHFE") -> dict:
    """获取仓单日报。"""
    result = await _get_source().get_warrant(symbol, exchange)  # type: ignore
    if result.get("data_grade") == "UNAVAILABLE":
        from data_adapter.sources.web_data_fetcher import fetch_warrant_from_web
        result = await fetch_warrant_from_web(symbol, exchange)
    return result


async def get_inventory(symbol: str) -> dict:
    """获取库存数据。"""
    result = await _get_source().get_inventory(symbol)  # type: ignore
    if result.get("data_grade") == "UNAVAILABLE":
        from data_adapter.sources.web_data_fetcher import fetch_inventory_from_web
        result = await fetch_inventory_from_web(symbol)
    return result


async def get_position_ranking(symbol: str) -> dict:
    """获取持仓排名。"""
    return await _get_source().get_position_ranking(symbol)  # type: ignore


async def get_fund_flow(symbol: str) -> dict:
    """获取资金流向。"""
    return await _get_source().get_fund_flow(symbol)  # type: ignore


async def get_foreign_hist(symbol: str) -> dict:
    """获取外盘历史数据。"""
    return await _get_source().get_foreign_hist(symbol)  # type: ignore


async def get_basis(symbol: str) -> dict:
    """获取基差数据。"""
    result = await _get_source().get_basis(symbol)  # type: ignore
    if result.get("data_grade") == "UNAVAILABLE":
        from data_adapter.sources.web_data_fetcher import fetch_basis_from_web
        result = await fetch_basis_from_web(symbol)
    return result


async def get_term_structure(symbol: str) -> dict:
    """获取期限结构数据（从合约序列计算）。"""
    return await _get_source().get_term_structure(symbol)  # type: ignore


async def get_spread(symbol: str) -> dict:
    """获取跨期价差数据。"""
    result = await _get_source().get_spread(symbol)  # type: ignore
    if result.get("data_grade") == "UNAVAILABLE":
        from data_adapter.sources.web_data_fetcher import fetch_spread_from_web
        result = await fetch_spread_from_web(symbol)
    return result


# ── Wind 数据源接口 ─────────────────────────────────────

_WIND_SOURCE: Optional["WindSource"] = None


def _get_wind_source():
    """获取 WindSource 实例（懒加载）。"""
    global _WIND_SOURCE
    if _WIND_SOURCE is None:
        from data_adapter.sources.wind_source import WindSource
        _WIND_SOURCE = WindSource()
    return _WIND_SOURCE


async def get_wind_edb(
    question: str,
    begin_date: str | None = None,
    end_date: str | None = None,
    observation: str | None = None,
) -> dict:
    """获取宏观 EDB 指标数据（12 小时缓存）。

    Args:
        question: 自然语言指标描述，如 "中国GDP"、"CPI同比"
        begin_date: 开始日期 yyyyMMdd（与 observation 互斥）
        end_date: 结束日期 yyyyMMdd
        observation: 近 N 期如 "10"，或 "all"（与 beginDate/endDate 互斥）

    Returns:
        {"data_grade": "PRIMARY"/"UNAVAILABLE", "data": ..., "source": "wind"}
    """
    return await _get_wind_source().get_edb(question, begin_date, end_date, observation)


async def get_wind_convertible_bond(code: str) -> dict:
    """获取可转债估值/条款数据。

    Args:
        code: 可转债代码，如 "110045.SH"

    Returns:
        {"data_grade": "PRIMARY"/"UNAVAILABLE", "data": ..., "source": "wind"}
    """
    return await _get_wind_source().get_convertible_bond(code)


async def get_wind_fund_holdings(code: str) -> dict:
    """获取 ETF/基金持仓数据。

    Args:
        code: 基金代码，如 "510050.SH"

    Returns:
        {"data_grade": "PRIMARY"/"UNAVAILABLE", "data": ..., "source": "wind"}
    """
    return await _get_wind_source().get_fund_holdings(code)


async def get_wind_fund_nav(code: str) -> dict:
    """获取 ETF 净值/行情快照。

    Args:
        code: 基金代码，如 "588200.SH"

    Returns:
        {"data_grade": "PRIMARY"/"UNAVAILABLE", "data": ..., "source": "wind"}
    """
    return await _get_wind_source().get_fund_nav(code)


async def get_wind_announcements(query: str, top_k: int = 5) -> dict:
    """搜索上市公司公告/财报。

    Args:
        query: 搜索关键词（不含空格）
        top_k: 返回文档数量

    Returns:
        {"data_grade": "PRIMARY"/"UNAVAILABLE", "announcements": [...], "source": "wind"}
    """
    return await _get_wind_source().get_announcements(query, top_k)


async def get_wind_financial_news(query: str, top_k: int = 5) -> dict:
    """搜索财经新闻。

    Args:
        query: 搜索关键词（不含空格）
        top_k: 返回文档数量

    Returns:
        {"data_grade": "PRIMARY"/"UNAVAILABLE", "news": [...], "source": "wind"}
    """
    return await _get_wind_source().get_financial_news(query, top_k)
