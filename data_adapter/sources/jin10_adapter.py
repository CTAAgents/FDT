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
        self._client: Optional[httpx.AsyncClient] = None
        self._session_id: Optional[str] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

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
        client = self._get_client()
        resp = await client.post(
            self.server_url,
            json=payload,
            headers={**self.headers, "Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 202):
            raise _McpError(resp.status_code, f"HTTP {resp.status_code}")
        # 提取 mcp-session-id（jin10 MCP 使用会话 ID 追踪状态）
        session_id = resp.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        # 解析 SSE 响应
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                break
        else:
            data = {}
        if "error" in data and data["error"] is not None:
            err = data["error"]
            raise _McpError(err.get("code", -1), err.get("message", "Unknown"), err.get("data"))
        result = data.get("result", data)
        self._initialized = True
        await self._notify_initialized()
        import asyncio
        await asyncio.sleep(0.3)
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
        client = self._get_client()
        req_headers = {**self.headers, "Content-Type": "application/json"}
        if self._session_id:
            req_headers["mcp-session-id"] = self._session_id
        resp = await client.post(
            self.server_url,  # 无尾部斜杠 — jin10 MCP 使用 SSE 传输
            json=payload,
            headers=req_headers,
        )
        # 202 Accepted — MCP Streamable HTTP 协议，需读 SSE 响应体
        if resp.status_code not in (200, 202):
            raise _McpError(resp.status_code, f"HTTP {resp.status_code}")
        # jin10 MCP 使用 SSE (Server-Sent Events) 传输协议
        # 响应格式: event: message\ndata: {json}\n
        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type or resp.status_code == 202:
            for line in resp.text.split("\n"):
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    break
            else:
                data = {}
        else:
            data = resp.json()
        if "error" in data and data["error"] is not None:
            err = data["error"]
            raise _McpError(err.get("code", -1), err.get("message", "Unknown"), err.get("data"))
        return data.get("result", data)

    async def close(self):
        self._initialized = False
        if self._client:
            await self._client.aclose()
            self._client = None


class Jin10McpFetcher:
    """金十数据 MCP 采集器。"""

    def __init__(
        self,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        # 自动从 .env 加载环境变量（若存在）
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        self.server_url = server_url or os.environ.get("JIN10_MCP_URL", _JIN10_DEFAULT_URL)
        self.token = token or os.environ.get("JIN10_MCP_TOKEN", "")
        self.timeout = timeout or float(os.environ.get("FDT_MCP_TIMEOUT", "30"))
        self._client: Optional[_McpHttpClient] = None
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        if self._available is not None:
            return self._available
        if not bool(self.token):
            logger.warning("[Jin10MCP] 未设置 JIN10_MCP_TOKEN，金十 MCP 不可用 — "
                          "请在 .env 或系统环境变量中配置有效的 JIN10_MCP_TOKEN")
            self._available = False
            return False
        self._available = True
        return True

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

    async def test_connection(self) -> dict:
        """测试 MCP 服务器连接，返回详细诊断信息。"""
        result = {
            "server_url": self.server_url,
            "token_configured": bool(self.token),
            "reachable": False,
            "error": None,
            "details": {},
        }
        if not self.token:
            result["error"] = "JIN10_MCP_TOKEN 未配置（在 .env 中取消注释或设置环境变量）"
            return result
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self.server_url,  # 无尾部斜杠 — jin10 MCP 使用 SSE 传输
                    json={
                        "jsonrpc": "2.0",
                        "id": "test-conn",
                        "method": "initialize",
                        "params": {"protocolVersion": _MCP_PROTOCOL_VERSION, "capabilities": {}},
                    },
                    headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                )
                result["details"]["http_status"] = resp.status_code
                result["reachable"] = resp.status_code == 200
                if resp.status_code == 200:
                    # SSE 响应: event: message\ndata: {json}\n
                    content_type = resp.headers.get("content-type", "")
                    if "text/event-stream" in content_type:
                        for line in resp.text.split("\n"):
                            if line.startswith("data: "):
                                data = json.loads(line[6:])
                                break
                        else:
                            data = {}
                    else:
                        data = resp.json()
                    result["details"]["server_info"] = data.get("result", {}).get("serverInfo", {})
                    result["details"]["protocol_version"] = data.get("result", {}).get("protocolVersion", "")
                elif resp.status_code == 401:
                    result["error"] = "HTTP 401: Token 无效或被拒绝，请检查 JIN10_MCP_TOKEN 是否正确"
                elif resp.status_code == 403:
                    result["error"] = "HTTP 403: 无权限访问，请检查 Token 权限"
                else:
                    result["error"] = f"HTTP {resp.status_code}: 服务器返回异常状态码"
        except httpx.ConnectError as e:
            result["error"] = f"连接失败: {e} (server_url={self.server_url})"
        except httpx.TimeoutException:
            result["error"] = f"连接超时 (timeout=5s, server_url={self.server_url})"
        except Exception as e:
            result["error"] = f"连接异常: {type(e).__name__}: {e}"
        return result

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
        fetcher = _get_jin10()
        if not fetcher.available:
            logger.info("[Jin10Adapter] 不可用: JIN10_MCP_TOKEN 未配置")
            return False
        return True
    except Exception as e:
        logger.debug("[Jin10Adapter] 不可用: %s", e)
        return False


async def jin10_diagnose() -> dict:
    """返回金十 MCP 的详细连接诊断信息（用于调试和日志）。"""
    fetcher = _get_jin10()
    base = {
        "server_url": fetcher.server_url,
        "token_configured": bool(fetcher.token),
        "available": fetcher.available,
    }
    if fetcher.token:
        diag = await fetcher.test_connection()
        base.update(diag)
    else:
        base["reachable"] = False
        base["error"] = "JIN10_MCP_TOKEN 未配置（在 .env 中取消注释 JIN10_MCP_TOKEN 或设置环境变量）"
    return base


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
