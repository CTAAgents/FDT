"""金十数据 MCP 适配器 — 替代已退役的 futures_data_core.f10.jin10_mcp。

自包含实现，仅依赖 httpx。通过标准 MCP 协议接入金十财经数据服务。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_MCP_PROTOCOL_VERSION = "2025-11-25"
_JIN10_DEFAULT_URL = "https://mcp.jin10.com/mcp"


class _McpError(RuntimeError):
    """MCP 协议错误。"""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.data = data
        super().__init__(f"MCP error {code}: {message}")


class _McpHttpClient:
    """通用 MCP HTTP 客户端（精简版）。"""

    def __init__(self, server_url: str, headers: dict | None = None, timeout: float = 30):
        self.server_url = server_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self._initialized = False

    async def initialize(self) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "fdt-jin10-adapter", "version": "1.0.0"},
            },
        }
        result = await self._post(payload)
        self._initialized = True
        await self._notify_initialized()
        return result

    async def _notify_initialized(self):
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        try:
            await self._post(payload)
        except Exception:
            pass

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        if not self._initialized:
            await self.initialize()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        return await self._post(payload)

    async def get_data(self, tool_name: str, **kwargs) -> Any:
        result = await self.call_tool(tool_name, kwargs)
        content = result.get("content", [])
        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "")
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
        return result.get("result") or result

    async def read_resource(self, uri: str) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "resources/read",
            "params": {"uri": uri},
        }
        return await self._post(payload)

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.server_url}/",
                json=payload,
                headers={**self.headers, "Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                raise _McpError(resp.status_code, f"HTTP {resp.status_code}")
            data = resp.json()
            if "error" in data and data["error"] is not None:
                err = data["error"]
                raise _McpError(err.get("code", -1), err.get("message", "Unknown"), err.get("data"))
            return data.get("result", data)

    async def close(self):
        self._initialized = False


class Jin10McpFetcher:
    """金十数据 MCP 采集器。"""

    def __init__(
        self,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.server_url = server_url or os.environ.get("JIN10_MCP_URL", _JIN10_DEFAULT_URL)
        self.token = token or os.environ.get("JIN10_MCP_TOKEN", "")
        self.timeout = timeout or float(os.environ.get("FDT_MCP_TIMEOUT", "30"))
        self._client: Optional[_McpHttpClient] = None
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        if self._available is not None:
            return self._available
        self._available = bool(self.token)
        if not self._available:
            logger.debug("[Jin10MCP] 未设置 JIN10_MCP_TOKEN，金十 MCP 不可用")
        return self._available

    def _ensure_client(self) -> _McpHttpClient:
        if self._client is None:
            if not self.available:
                raise RuntimeError("金十 MCP 不可用：未设置 JIN10_MCP_TOKEN")
            self._client = _McpHttpClient(
                server_url=self.server_url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def _call(self, tool_name: str, **kwargs) -> dict:
        client = self._ensure_client()
        try:
            return await client.get_data(tool_name, **kwargs)
        except _McpError as e:
            logger.warning("[Jin10MCP] %s 调用失败: %s", tool_name, e)
            raise

    async def list_codes(self) -> list[dict]:
        client = self._ensure_client()
        try:
            result = await client.read_resource("quote://codes")
            content = result.get("content", [])
            for item in content:
                if item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, list):
                            return parsed
                        if isinstance(parsed, dict) and "data" in parsed:
                            data = parsed["data"]
                            if isinstance(data, list):
                                return data
                    except (json.JSONDecodeError, TypeError):
                        pass
            return []
        except _McpError as e:
            logger.warning("[Jin10MCP] list_codes 失败: %s", e)
            return []

    async def get_quote(self, code: str) -> dict:
        data = await self._call("get_quote", code=code)
        result = dict(data) if isinstance(data, dict) else {}
        result["source"] = "jin10_mcp"
        result["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result

    async def get_kline(self, code: str, time: str = "1day", count: int = 100) -> dict:
        data = await self._call("get_kline", code=code, time=time, count=count)
        result = dict(data) if isinstance(data, dict) else {}
        result["source"] = "jin10_mcp"
        result["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result

    async def list_flash(self, cursor: Optional[str] = None) -> dict:
        kwargs: dict = {}
        if cursor:
            kwargs["cursor"] = cursor
        data = await self._call("list_flash", **kwargs)
        return self._wrap_list_result(data, "flash")

    async def search_flash(self, keyword: str, cursor: Optional[str] = None) -> dict:
        kwargs: dict = {"keyword": keyword}
        if cursor:
            kwargs["cursor"] = cursor
        data = await self._call("search_flash", **kwargs)
        return self._wrap_list_result(data, "flash")

    async def list_news(self, cursor: Optional[str] = None) -> dict:
        kwargs: dict = {}
        if cursor:
            kwargs["cursor"] = cursor
        data = await self._call("list_news", **kwargs)
        return self._wrap_list_result(data, "news")

    async def search_news(self, keyword: str, cursor: Optional[str] = None) -> dict:
        kwargs: dict = {"keyword": keyword}
        if cursor:
            kwargs["cursor"] = cursor
        data = await self._call("search_news", **kwargs)
        return self._wrap_list_result(data, "news")

    async def get_news(self, news_id: str) -> dict:
        data = await self._call("get_news", id=news_id)
        result = dict(data) if isinstance(data, dict) else {}
        result["source"] = "jin10_mcp"
        result["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result

    async def list_calendar(self) -> dict:
        data = await self._call("list_calendar")
        items = data if isinstance(data, list) else []
        return {
            "items": items,
            "source": "jin10_mcp",
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _wrap_list_result(self, data: Any, category: str) -> dict:
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
        if self._client:
            await self._client.close()
            self._client = None


# ── 单例 + 模块级函数（与 data_source_adapter 兼容） ──

_jin10_fetcher: Optional[Jin10McpFetcher] = None


def _get_jin10() -> Jin10McpFetcher:
    global _jin10_fetcher
    if _jin10_fetcher is None:
        _jin10_fetcher = Jin10McpFetcher()
    return _jin10_fetcher


def jin10_available() -> bool:
    try:
        return _get_jin10().available
    except Exception as e:
        logger.debug("[Jin10Adapter] 不可用: %s", e)
        return False


async def jin10_list_flash(cursor: Optional[str] = None) -> dict:
    return await _get_jin10().list_flash(cursor=cursor)


async def jin10_search_flash(keyword: str, cursor: Optional[str] = None) -> dict:
    return await _get_jin10().search_flash(keyword, cursor=cursor)


async def jin10_list_news(cursor: Optional[str] = None) -> dict:
    return await _get_jin10().list_news(cursor=cursor)


async def jin10_search_news(keyword: str, cursor: Optional[str] = None) -> dict:
    return await _get_jin10().search_news(keyword, cursor=cursor)


async def jin10_get_news(news_id: str) -> dict:
    return await _get_jin10().get_news(news_id)


async def jin10_list_calendar() -> dict:
    return await _get_jin10().list_calendar()


async def jin10_get_quote(code: str) -> dict:
    return await _get_jin10().get_quote(code)


async def jin10_get_kline(code: str, time: str = "1day", count: int = 100) -> dict:
    return await _get_jin10().get_kline(code, time=time, count=count)
