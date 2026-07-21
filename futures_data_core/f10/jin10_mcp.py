"""金十数据 MCP 采集器 [INDEPENDENT]。

通过标准 MCP 协议接入金十财经数据服务，提供：
  - 实时报价（外盘品种：黄金/白银/原油/铜/外汇等）
  - K线数据
  - 7×24h 快讯列表 & 搜索
  - 财经资讯列表 & 搜索 & 详情
  - 财经日历

运行模式: ``[INDEPENDENT]``，无 LLM 依赖，纯 HTTP MCP 调用。

环境变量：
    JIN10_MCP_URL    - MCP 服务地址，默认 https://mcp.jin10.com/mcp
    JIN10_MCP_TOKEN  - Bearer Token（必须设置，否则不可用）

使用示例：
    from futures_data_core.f10.jin10_mcp import Jin10McpFetcher
    fetcher = Jin10McpFetcher()
    if fetcher.available:
        flash = await fetcher.list_flash()
        quote = await fetcher.get_quote("XAUUSD")
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional

from futures_data_core.mcp_client import McpHttpClient, McpError

logger = logging.getLogger(__name__)

_JIN10_DEFAULT_URL = "https://mcp.jin10.com/mcp"


class Jin10McpFetcher:
    """金十数据 MCP 采集器。

    运行模式: ``[INDEPENDENT]``。
    """

    def __init__(
        self,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.server_url = server_url or os.environ.get("JIN10_MCP_URL", _JIN10_DEFAULT_URL)
        self.token = token or os.environ.get("JIN10_MCP_TOKEN", "")
        self.timeout = timeout or float(os.environ.get("FDT_MCP_TIMEOUT", "30"))
        self._client: Optional[McpHttpClient] = None
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        """是否可用（已设置 token）。"""
        if self._available is not None:
            return self._available
        self._available = bool(self.token)
        if not self._available:
            logger.debug("[Jin10MCP] 未设置 JIN10_MCP_TOKEN，金十 MCP 不可用")
        return self._available

    def _ensure_client(self) -> McpHttpClient:
        """获取或创建 MCP 客户端。"""
        if self._client is None:
            if not self.available:
                raise RuntimeError("金十 MCP 不可用：未设置 JIN10_MCP_TOKEN")
            self._client = McpHttpClient(
                server_url=self.server_url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def _call(self, tool_name: str, **kwargs) -> dict:
        """调用 MCP 工具并返回结构化数据。"""
        client = self._ensure_client()
        try:
            return await client.get_data(tool_name, **kwargs)
        except McpError as e:
            logger.warning("[Jin10MCP] %s 调用失败: %s", tool_name, e)
            raise

    # ════════════════════════════════════════════════════════════
    # 报价 & K线
    # ════════════════════════════════════════════════════════════

    async def list_codes(self) -> list[dict]:
        """获取支持的报价品种代码列表（通过 quote://codes 资源）。"""
        client = self._ensure_client()
        try:
            result = await client.read_resource("quote://codes")
            content = result.get("content", [])
            for item in content:
                if item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        import json as _json
                        parsed = _json.loads(text)
                        if isinstance(parsed, list):
                            return parsed
                        if isinstance(parsed, dict) and "data" in parsed:
                            data = parsed["data"]
                            if isinstance(data, list):
                                return data
                    except (_json.JSONDecodeError, TypeError):
                        pass
            return []
        except McpError as e:
            logger.warning("[Jin10MCP] list_codes 失败: %s", e)
            return []

    async def get_quote(self, code: str) -> dict:
        """获取指定品种实时行情。

        Args:
            code: 品种代码，如 XAUUSD / USOIL / COPPER / USDCNH

        Returns:
            行情字典：
            {
                "code": "XAUUSD",
                "name": "现货黄金",
                "time": "2026-07-22 15:30:00",
                "open": 2395.50,
                "close": 2401.20,
                "high": 2405.80,
                "low": 2392.10,
                "volume": 123456,
                "ups_price": 5.70,
                "ups_percent": 0.24,
                "source": "jin10_mcp",
                "fetched_at": "2026-07-22 15:30:05",
            }
        """
        data = await self._call("get_quote", code=code)
        result = dict(data) if isinstance(data, dict) else {}
        result["source"] = "jin10_mcp"
        result["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result

    async def get_kline(self, code: str, time: str = "1day", count: int = 100) -> dict:
        """获取指定品种K线数据。

        Args:
            code: 品种代码
            time: 周期，如 1min / 5min / 15min / 30min / 1hour / 1day
            count: K线数量

        Returns:
            {
                "code": "XAUUSD",
                "name": "现货黄金",
                "klines": [
                    {"time": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...},
                    ...
                ],
                "source": "jin10_mcp",
                "fetched_at": "...",
            }
        """
        data = await self._call("get_kline", code=code, time=time, count=count)
        result = dict(data) if isinstance(data, dict) else {}
        result["source"] = "jin10_mcp"
        result["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result

    # ════════════════════════════════════════════════════════════
    # 快讯 (Flash)
    # ════════════════════════════════════════════════════════════

    async def list_flash(self, cursor: Optional[str] = None) -> dict:
        """获取最新快讯列表。

        Args:
            cursor: 分页游标，首次传 None

        Returns:
            {
                "items": [{"id": ..., "title": ..., "content": ..., "time": ..., ...}],
                "next_cursor": "...",
                "has_more": true,
                "source": "jin10_mcp",
                "fetched_at": "...",
            }
        """
        kwargs: dict = {}
        if cursor:
            kwargs["cursor"] = cursor
        data = await self._call("list_flash", **kwargs)
        result = self._wrap_list_result(data, "flash")
        return result

    async def search_flash(self, keyword: str, cursor: Optional[str] = None) -> dict:
        """按关键词搜索快讯。

        Args:
            keyword: 搜索关键词，如 "黄金"、"美联储"、"非农"
            cursor: 分页游标

        Returns:
            同 list_flash
        """
        kwargs: dict = {"keyword": keyword}
        if cursor:
            kwargs["cursor"] = cursor
        data = await self._call("search_flash", **kwargs)
        result = self._wrap_list_result(data, "flash")
        return result

    # ════════════════════════════════════════════════════════════
    # 资讯 (News)
    # ════════════════════════════════════════════════════════════

    async def list_news(self, cursor: Optional[str] = None) -> dict:
        """获取最新资讯列表。

        Args:
            cursor: 分页游标

        Returns:
            {
                "items": [{"id": ..., "title": ..., "introduction": ..., "time": ..., "url": ..., ...}],
                "next_cursor": "...",
                "has_more": true,
                "source": "jin10_mcp",
                "fetched_at": "...",
            }
        """
        kwargs: dict = {}
        if cursor:
            kwargs["cursor"] = cursor
        data = await self._call("list_news", **kwargs)
        result = self._wrap_list_result(data, "news")
        return result

    async def search_news(self, keyword: str, cursor: Optional[str] = None) -> dict:
        """按关键词搜索资讯。

        Args:
            keyword: 搜索关键词
            cursor: 分页游标

        Returns:
            同 list_news
        """
        kwargs: dict = {"keyword": keyword}
        if cursor:
            kwargs["cursor"] = cursor
        data = await self._call("search_news", **kwargs)
        result = self._wrap_list_result(data, "news")
        return result

    async def get_news(self, news_id: str) -> dict:
        """获取单篇资讯详情。

        Args:
            news_id: 资讯 ID

        Returns:
            {
                "id": "...",
                "title": "...",
                "introduction": "...",
                "time": "...",
                "url": "...",
                "content": "...",
                "source": "jin10_mcp",
                "fetched_at": "...",
            }
        """
        data = await self._call("get_news", id=news_id)
        result = dict(data) if isinstance(data, dict) else {}
        result["source"] = "jin10_mcp"
        result["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result

    # ════════════════════════════════════════════════════════════
    # 财经日历
    # ════════════════════════════════════════════════════════════

    async def list_calendar(self) -> dict:
        """获取财经日历数据。

        Returns:
            {
                "items": [
                    {
                        "pub_time": "2026-07-23 20:30:00",
                        "star": 3,
                        "title": "美国至7月18日当周初请失业金人数",
                        "previous": "23.5万",
                        "consensus": "23.0万",
                        "actual": None,
                        "revised": None,
                        "affect_txt": "影响较小",
                    },
                    ...
                ],
                "source": "jin10_mcp",
                "fetched_at": "...",
            }
        """
        data = await self._call("list_calendar")
        items = data if isinstance(data, list) else []
        return {
            "items": items,
            "source": "jin10_mcp",
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ════════════════════════════════════════════════════════════
    # 辅助方法
    # ════════════════════════════════════════════════════════════

    def _wrap_list_result(self, data: Any, category: str) -> dict:
        """包装列表型返回结果，统一 items / next_cursor / has_more 结构。"""
        items: list = []
        next_cursor: Optional[str] = None
        has_more: bool = False

        if isinstance(data, dict):
            items = data.get("items", [])
            if not isinstance(items, list):
                items = []
            next_cursor = data.get("next_cursor") or data.get("nextCursor")
            has_more = bool(data.get("has_more", data.get("hasMore", False)))
        elif isinstance(data, list):
            items = data

        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "category": category,
            "source": "jin10_mcp",
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def close(self) -> None:
        """关闭 MCP 客户端连接。"""
        if self._client:
            await self._client.close()
            self._client = None
