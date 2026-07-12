"""徽商 HS 基本面 [INDEPENDENT]。

数据来源：徽商期货 HS HTTP API（可选增强源）。该端点需鉴权，未配置时静默降级，
绝不假定任何未经验证的端点必然可用（避免幻觉）。

实现采用**可注入 transport** 设计；JSON 解析为纯函数。

A2A 输出：``type=fdc.fundamental``（hs 子源）。
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES

_HS_DEFAULT_ENDPOINT = "https://www.hsqh.com/api/futures/fundamental/{symbol}"


class HuishangFetcher:
    """徽商 HS 基本面抓取器 [INDEPENDENT, 可选]。"""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        token: Optional[str] = None,
        transport: Optional[Callable[[str], Awaitable[tuple[int, str]]]] = None,
    ) -> None:
        self.endpoint = endpoint or _HS_DEFAULT_ENDPOINT
        self.token = token
        self._transport = transport

    async def fetch(self, symbol: str) -> Optional[dict]:
        """抓取并解析 HS 基本面；不可用时返回 ``None``。"""
        url = self.endpoint.format(symbol=symbol.lower())
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            raw = self._transport(url) if self._transport is not None else await _httpx_get(url, headers)
            if hasattr(raw, "__await__"):
                raw = await raw
            status, body = raw
        except Exception:
            return None
        if status != 200:
            return None
        return self._parse(body)

    @staticmethod
    def _parse(body: str) -> Optional[dict]:
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            return None
        if isinstance(data, dict):
            return data.get("data", data)
        return None


async def _httpx_get(url: str, headers: dict) -> tuple[int, str]:
    """真实 httpx 抓取（抽离为模块级函数，便于测试桩替换）。"""
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
        return resp.status_code, resp.text


async def get_huishang_fundamental(
    symbol: str,
    *,
    fetcher: Optional[HuishangFetcher] = None,
    transport=None,
) -> A2APayload:
    """获取徽商 HS 基本面。无 LLM 依赖。

    Args:
        symbol: 品种代码。
        fetcher: 注入的 :class:`HuishangFetcher`；缺省新建（可用 ``transport`` 注入）。
        transport: 注入抓取器（仅在 ``fetcher`` 为 ``None`` 时生效）。

    Returns:
        :class:`A2APayload`，``data`` 为 HS 返回的基本面 dict。
    """
    f = fetcher or HuishangFetcher(transport=transport)
    raw = await f.fetch(symbol)

    if raw is None:
        payload = A2APayload(
            type=DATA_TYPES["FUNDAMENTAL"],
            runtime_mode="independent",
            data={"symbol": symbol, "huishang": None},
        )
        payload.set_grade("UNAVAILABLE")
        payload.add_warning("徽商HS基本面不可用（未配置或请求失败）")
        return payload

    data: dict[str, Any] = {"symbol": symbol, "huishang": raw}
    payload = A2APayload(
        type=DATA_TYPES["FUNDAMENTAL"], runtime_mode="independent", data=data
    )
    payload.set_grade("DAILY")
    payload.meta["sources"] = ["huishang_hs"]
    payload.summary = f"{symbol} 徽商HS基本面已获取"
    return payload
