# -*- coding: utf-8 -*-
#
# Web 基本面数据采集工具 - FDC 薄封装层
# ==============================================
# 本模块是 futures_data_core.f10.web_collector 的 LangChain @tool 封装层。
#

import json

from futures_data_core.f10.web_collector import (
    fetch_quote,
    fetch_kline,
    search_news,
    collect_fundamental_web,
)

__all__ = [
    "fetch_quote", "fetch_kline", "search_news", "collect_fundamental_web",
]

_LANGCHAIN_TOOLS = []
try:
    from langchain_core.tools import tool

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

    _LANGCHAIN_TOOLS = ["langchain_fetch_quote", "langchain_fetch_kline", "langchain_search_news"]
except ImportError:
    pass

__all__ += _LANGCHAIN_TOOLS
