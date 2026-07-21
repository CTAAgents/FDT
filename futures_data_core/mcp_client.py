"""通用 MCP (Model Context Protocol) HTTP 客户端 [INDEPENDENT]。

实现标准 MCP 协议流程：
    initialize -> notifications/initialized -> tools/list / resources/list -> tools/call

协议版本: 2025-11-25
传输方式: HTTP POST (JSON-RPC 2.0)

使用示例：
    client = McpHttpClient(
        server_url="https://mcp.example.com/mcp",
        headers={"Authorization": "Bearer sk-xxx"},
    )
    await client.initialize()
    tools = await client.list_tools()
    result = await client.call_tool("get_quote", {"code": "XAUUSD"})
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-11-25"


class McpError(RuntimeError):
    """MCP 协议错误。"""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.data = data
        super().__init__(f"MCP error {code}: {message}")


class McpHttpClient:
    """MCP HTTP 客户端（JSON-RPC 2.0 over HTTP）。

    运行模式: ``[INDEPENDENT]``。
    """

    def __init__(
        self,
        server_url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.headers = dict(headers or {})
        self.headers.setdefault("Content-Type", "application/json")
        self.headers.setdefault("Accept", "application/json, text/event-stream")
        self.timeout = timeout or float(os.environ.get("FDT_MCP_TIMEOUT", "30"))
        self._initialized = False
        self._session_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "McpHttpClient":
        self._client = httpx.AsyncClient(timeout=self.timeout, headers=self.headers)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=self.headers)
        return self._client

    # ════════════════════════════════════════════════════════════
    # JSON-RPC 基础
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _parse_sse(text: str) -> list[dict]:
        """解析 SSE (Server-Sent Events) 文本，提取 JSON-RPC 消息。

        MCP Streamable HTTP 使用 SSE 格式返回响应：
            event: message
            data: {"jsonrpc":"2.0", ...}

        Args:
            text: SSE 格式文本

        Returns:
            解析出的 JSON-RPC 消息字典列表
        """
        messages: list[dict] = []
        data_lines: list[str] = []

        for line in text.split("\n"):
            line = line.rstrip("\r")
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line == "" and data_lines:
                data_str = "\n".join(data_lines)
                data_lines = []
                if data_str:
                    try:
                        msg = json.loads(data_str)
                        messages.append(msg)
                    except json.JSONDecodeError:
                        pass

        if data_lines:
            data_str = "\n".join(data_lines)
            try:
                msg = json.loads(data_str)
                messages.append(msg)
            except json.JSONDecodeError:
                pass

        return messages

    async def _rpc(self, method: str, params: Optional[dict] = None) -> dict:
        """发送 JSON-RPC 请求并返回 result。

        支持两种响应格式：
        1. 普通 JSON 响应（直接返回 JSON-RPC 消息）
        2. SSE 响应（text/event-stream，从 data: 行提取 JSON）
        """
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        request_id = payload["id"]
        client = self._get_client()

        extra_headers = {}
        if self._session_id:
            extra_headers["mcp-session-id"] = self._session_id

        try:
            resp = await client.post(self.server_url, json=payload, headers=extra_headers)
            resp.raise_for_status()

            if not self._session_id:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self._session_id = sid

            if resp.status_code == 202:
                return {}

            text = resp.text

            content_type = resp.headers.get("content-type", "")
            if "text/event-stream" in content_type or text.startswith("event:") or text.startswith("data:"):
                messages = self._parse_sse(text)
                body = None
                for msg in messages:
                    if msg.get("id") == request_id:
                        body = msg
                        break
                if body is None and messages:
                    body = messages[-1]
                if body is None:
                    raise json.JSONDecodeError("No JSON-RPC message found in SSE stream", text, 0)
            else:
                body = json.loads(text)

        except httpx.HTTPStatusError as e:
            raise McpError(
                code=e.response.status_code,
                message=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            ) from e
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            raise McpError(code=-32000, message=f"Transport error: {e}") from e

        if "error" in body:
            err = body["error"]
            raise McpError(
                code=err.get("code", -32000),
                message=err.get("message", "Unknown error"),
                data=err.get("data"),
            )

        return body.get("result", {})

    # ════════════════════════════════════════════════════════════
    # MCP 生命周期
    # ════════════════════════════════════════════════════════════

    async def initialize(self, client_name: str = "fdt", client_version: str = "1.0.0") -> dict:
        """发送 initialize 请求，建立 MCP 会话。"""
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                    "resources": {},
                },
                "clientInfo": {
                    "name": client_name,
                    "version": client_version,
                },
            },
        )
        if not self._session_id:
            self._session_id = result.get("sessionId")
        self._initialized = True
        logger.info("[MCP] 初始化成功: server=%s, session=%s", self.server_url, self._session_id)
        return result

    async def notify_initialized(self) -> None:
        """发送 notifications/initialized 通知（无响应）。"""
        if not self._initialized:
            await self.initialize()
        try:
            await self._rpc("notifications/initialized", {})
        except McpError:
            pass

    # ════════════════════════════════════════════════════════════
    # Tools
    # ════════════════════════════════════════════════════════════

    async def list_tools(self, cursor: Optional[str] = None) -> dict:
        """列出可用工具。"""
        if not self._initialized:
            await self.initialize()
            await self.notify_initialized()
        params = {}
        if cursor:
            params["cursor"] = cursor
        return await self._rpc("tools/list", params if params else None)

    async def call_tool(self, name: str, arguments: Optional[dict] = None) -> dict:
        """调用工具，优先返回 structuredContent。

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            标准化结果字典：
            {
                "content": [...],           // 原始 content 数组
                "structured_content": {},   // 结构化内容（优先使用）
                "is_error": bool,           // 是否业务错误
            }
        """
        if not self._initialized:
            await self.initialize()
            await self.notify_initialized()

        result = await self._rpc(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )

        structured_content: dict = {}
        is_error = result.get("isError", False)

        for item in result.get("content", []):
            if item.get("type") == "text" and "structuredContent" in item:
                sc = item["structuredContent"]
                if isinstance(sc, dict):
                    structured_content = sc
                    break
            elif item.get("type") == "json":
                json_data = item.get("json", {})
                if isinstance(json_data, dict):
                    structured_content = json_data
                    break

        if not structured_content and result.get("content"):
            for item in result["content"]:
                if item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict):
                            structured_content = parsed
                    except (json.JSONDecodeError, TypeError):
                        pass
                    break

        return {
            "content": result.get("content", []),
            "structured_content": structured_content,
            "is_error": is_error,
        }

    # ════════════════════════════════════════════════════════════
    # Resources
    # ════════════════════════════════════════════════════════════

    async def list_resources(self, cursor: Optional[str] = None) -> dict:
        """列出可用资源。"""
        if not self._initialized:
            await self.initialize()
            await self.notify_initialized()
        params = {}
        if cursor:
            params["cursor"] = cursor
        return await self._rpc("resources/list", params if params else None)

    async def read_resource(self, uri: str) -> dict:
        """读取资源内容。"""
        if not self._initialized:
            await self.initialize()
            await self.notify_initialized()
        return await self._rpc("resources/read", {"uri": uri})

    # ════════════════════════════════════════════════════════════
    # 便捷方法
    # ════════════════════════════════════════════════════════════

    async def get_data(self, tool_name: str, **kwargs) -> dict:
        """调用工具并提取 data 字段（structured_content.data）。

        优先使用 structured_content，失败则回退到解析 content 文本。
        """
        result = await self.call_tool(tool_name, kwargs)
        if result["is_error"]:
            raise McpError(
                code=-32001,
                message=f"Tool {tool_name} returned isError=true",
                data=result,
            )
        sc = result["structured_content"]
        if "data" in sc:
            return sc["data"]
        if sc:
            return sc
        return {"_raw": result["content"]}

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        if self._client:
            await self._client.aclose()
            self._client = None
