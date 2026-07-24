# -*- coding: utf-8 -*-
#
# Web 基本面数据采集工具 - LangChain @tool 封装层
# ==================================================
# 所有导入已改为惰性加载（函数内部），不再依赖已退役的 data_source_adapter/futures_data_core。
#

import asyncio
import json


def _run_async(coro):
    """同步函数中运行异步协程的辅助函数。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.ensure_future(coro)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _import_jin10():
    """惰性加载 Jin10 MCP 函数（替代已删除的 data_source_adapter）。"""
    from data_adapter.sources.jin10_adapter import (
        jin10_available,
        jin10_get_kline,
        jin10_get_news,
        jin10_get_quote,
        jin10_list_calendar,
        jin10_list_flash,
        jin10_list_news,
        jin10_search_flash,
        jin10_search_news,
    )
    return {
        "jin10_available": jin10_available,
        "jin10_get_kline": jin10_get_kline,
        "jin10_get_news": jin10_get_news,
        "jin10_get_quote": jin10_get_quote,
        "jin10_list_calendar": jin10_list_calendar,
        "jin10_list_flash": jin10_list_flash,
        "jin10_list_news": jin10_list_news,
        "jin10_search_flash": jin10_search_flash,
        "jin10_search_news": jin10_search_news,
    }


def _import_web_collector():
    """惰性加载 web_collector 工具（替代已删除的 futures_data_core.f10.web_collector）。"""
    import warnings
    warnings.warn("web_collector 已随 FDC 退役，返回空数据")

    def _empty(**kwargs):
        return {"data": {}, "summary": "web_collector 已退役", "available": False}

    return {
        "collect_fundamental_web": _empty,
        "fetch_kline": _empty,
        "fetch_quote": _empty,
        "search_news": _empty,
    }


# ── 模块级桩函数（保持 __all__ 兼容） ──

def jin10_available() -> bool:
    return _import_jin10()["jin10_available"]()


async def jin10_list_flash(cursor=None) -> dict:
    return await _import_jin10()["jin10_list_flash"](cursor=cursor)


async def jin10_search_flash(keyword: str, cursor=None) -> dict:
    return await _import_jin10()["jin10_search_flash"](keyword, cursor=cursor)


async def jin10_list_news(cursor=None) -> dict:
    return await _import_jin10()["jin10_list_news"](cursor=cursor)


async def jin10_search_news(keyword: str, cursor=None) -> dict:
    return await _import_jin10()["jin10_search_news"](keyword, cursor=cursor)


async def jin10_get_news(news_id: str) -> dict:
    return await _import_jin10()["jin10_get_news"](news_id)


async def jin10_list_calendar() -> dict:
    return await _import_jin10()["jin10_list_calendar"]()


async def jin10_get_quote(code: str) -> dict:
    return await _import_jin10()["jin10_get_quote"](code)


async def jin10_get_kline(code: str, time: str = "1day", count: int = 100) -> dict:
    return await _import_jin10()["jin10_get_kline"](code, time=time, count=count)


def fetch_quote(variety: str) -> dict:
    return _import_web_collector()["fetch_quote"](variety)


def fetch_kline(variety: str, days: int = 30) -> dict:
    return _import_web_collector()["fetch_kline"](variety, days)


def search_news(keyword: str) -> dict:
    return _import_web_collector()["search_news"](keyword)


def collect_fundamental_web(**kwargs) -> dict:
    return _import_web_collector()["collect_fundamental_web"](**kwargs)


__all__ = [
    "fetch_quote", "fetch_kline", "search_news", "collect_fundamental_web",
    "jin10_available",
    "jin10_list_flash", "jin10_search_flash",
    "jin10_list_news", "jin10_search_news", "jin10_get_news",
    "jin10_list_calendar",
    "jin10_get_quote", "jin10_get_kline",
]

# ── LangChain @tool 封装（可选依赖） ──

_LANGCHAIN_TOOLS = []
try:
    from langchain_core.tools import tool

    _jin10 = _import_jin10()

    @tool
    def langchain_fetch_quote(variety: str) -> str:
        """Get futures real-time quote data by variety code (e.g. RB, CU, I)."""
        return json.dumps(fetch_quote(variety), ensure_ascii=False)

    @tool
    def langchain_fetch_kline(variety: str, days: int = 30) -> str:
        """Get futures daily kline data by variety code and number of days."""
        return json.dumps(fetch_kline(variety, days), ensure_ascii=False)

    @tool
    def langchain_search_news(keyword: str) -> str:
        """Search latest futures industry news by keyword."""
        return json.dumps(search_news(keyword), ensure_ascii=False)

    @tool
    def langchain_jin10_list_flash(cursor: str = "") -> str:
        """Get latest flash news list from Jin10 MCP. Use cursor for pagination."""
        result = _run_async(_jin10["jin10_list_flash"](cursor=cursor or None))
        return json.dumps(result, ensure_ascii=False)

    @tool
    def langchain_jin10_search_flash(keyword: str, cursor: str = "") -> str:
        """Search flash news by keyword from Jin10 MCP (e.g. 黄金, 原油, 美联储, 非农)."""
        result = _run_async(_jin10["jin10_search_flash"](keyword, cursor=cursor or None))
        return json.dumps(result, ensure_ascii=False)

    @tool
    def langchain_jin10_list_news(cursor: str = "") -> str:
        """Get latest news article list from Jin10 MCP. Use cursor for pagination."""
        result = _run_async(_jin10["jin10_list_news"](cursor=cursor or None))
        return json.dumps(result, ensure_ascii=False)

    @tool
    def langchain_jin10_search_news(keyword: str, cursor: str = "") -> str:
        """Search news articles by keyword from Jin10 MCP."""
        result = _run_async(_jin10["jin10_search_news"](keyword, cursor=cursor or None))
        return json.dumps(result, ensure_ascii=False)

    @tool
    def langchain_jin10_get_news(news_id: str) -> str:
        """Get single news article detail by ID from Jin10 MCP."""
        result = _run_async(_jin10["jin10_get_news"](news_id))
        return json.dumps(result, ensure_ascii=False)

    @tool
    def langchain_jin10_list_calendar() -> str:
        """Get economic calendar data from Jin10 MCP."""
        result = _run_async(_jin10["jin10_list_calendar"]())
        return json.dumps(result, ensure_ascii=False)

    @tool
    def langchain_jin10_get_quote(code: str) -> str:
        """Get real-time quote by code from Jin10 MCP (e.g. XAUUSD, USOIL, COPPER, USDCNH)."""
        result = _run_async(_jin10["jin10_get_quote"](code))
        return json.dumps(result, ensure_ascii=False)

    @tool
    def langchain_jin10_get_kline(code: str, time: str = "1day", count: int = 100) -> str:
        """Get kline data by code from Jin10 MCP. time: 1min/5min/15min/30min/1hour/1day."""
        result = _run_async(_jin10["jin10_get_kline"](code, time=time, count=count))
        return json.dumps(result, ensure_ascii=False)

    _LANGCHAIN_TOOLS = [
        "langchain_fetch_quote", "langchain_fetch_kline", "langchain_search_news",
        "langchain_jin10_list_flash", "langchain_jin10_search_flash",
        "langchain_jin10_list_news", "langchain_jin10_search_news",
        "langchain_jin10_get_news", "langchain_jin10_list_calendar",
        "langchain_jin10_get_quote", "langchain_jin10_get_kline",
    ]
except ImportError:
    pass

__all__ += _LANGCHAIN_TOOLS
