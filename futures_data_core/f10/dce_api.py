"""大商所（DCE）官方 API 适配器 — 会员持仓排名。

官方文档：dceapiv1.0。鉴权流程：
    1. ``POST /cms/auth/accessToken``
       Header: ``apikey: <KEY>``
       Body:   ``{"secret": "<SECRET>"}``
       → ``data.token``（Bearer JWT，约 1h 有效）
    2. 其余接口 Header 必须同时携带：
       ``apikey: <KEY>`` 与 ``Authorization: Bearer <token>``

重要：``apikey`` 是**全局公共 Header 参数**，登录与登录后的所有请求都必须携带，
否则返回 ``code=402 验证token失败``。

凭证通过环境变量注入（不入库、不入源码、不进入版本控制）：
    DCE_API_KEY, DCE_API_SECRET

端点：
    - 合约解析  ``POST /forward/publicweb/tradepara/contractInfo``
                 Body: {"varietyId","tradeType":"1","lang":"zh"}
                 → data[]: [{contractId, variety, varietyOrder, ...}, ...]
    - 持仓排名  ``POST /forward/publicweb/dailystat/memberDealPosi``
                 Body: {"varietyId","tradeDate","contractId","tradeType":"1"}
                 → data.buyFutureList[] / data.sellFutureList[]
                    buyFutureList[].{rank, buyAbbr, todayBuyQty, buySub}
                    sellFutureList[].{rank, sellAbbr, todaySellQty, sellSub}

与 ``position.py`` 中既有的 ``portal.dce.com.cn`` 网页抓取路径互为备份：
本模块（官方 API）优先；当未配置凭证或 API 异常时，回退到 portal 抓取。
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional

import httpx

DCE_API_BASE = "http://www.dce.com.cn/dceapi"

# 进程内 token 缓存（单进程共享，约 1h 有效；保守缓存 55min）。
_TOKEN_CACHE: dict = {"token": None, "expires_at": 0.0}


def dce_api_configured() -> bool:
    """是否已配置 DCE 官方 API 凭证。"""
    return bool(os.environ.get("DCE_API_KEY") and os.environ.get("DCE_API_SECRET"))


def _split_symbol(symbol: str):
    """拆分品种/合约。

    返回 (variety, contract_id_or_None)。
    - 'm2609' / 'M2609' → ('m', 'm2609')  已是合约
    - 'm' / 'M'         → ('m', None)     需经 contractInfo 解析
    """
    s = symbol.lower()
    m = re.match(r"^([a-z]+?)(\d{3,4})$", s)
    if m:
        return m.group(1), s
    return s, None


def _to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


async def _login(apikey: str, secret: str, transport=None) -> str:
    """登录获取 Bearer token（带进程内缓存）。"""
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"]:
        return _TOKEN_CACHE["token"]
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, transport=transport) as c:
        r = await c.post(
            f"{DCE_API_BASE}/cms/auth/accessToken",
            headers={"apikey": apikey},
            json={"secret": secret},
        )
        r.raise_for_status()
        j = r.json()
    if not j.get("success"):
        raise RuntimeError(f"DCE API 登录失败：{j.get('msg')} (code={j.get('code')})")
    token = (j.get("data") or {}).get("token")
    if not token:
        raise RuntimeError("DCE API 登录响应缺少 token 字段")
    # 官方未显式下发 expiresIn；按 1h 保守缓存，留 5min 余量。
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + 55 * 60
    return token


async def _resolve_contract(
    variety: str, token: str, apikey: str, transport=None
) -> Optional[str]:
    """通过 contractInfo 解析品种的首个合约（近月/活跃）。"""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, transport=transport) as c:
        r = await c.post(
            f"{DCE_API_BASE}/forward/publicweb/tradepara/contractInfo",
            headers={
                "apikey": apikey,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"varietyId": variety, "tradeType": "1", "lang": "zh"},
        )
        r.raise_for_status()
        j = r.json()
    if not j.get("success"):
        raise RuntimeError(f"DCE contractInfo 失败：{j.get('msg')} (code={j.get('code')})")
    rows = j.get("data") or []
    if not rows:
        return None
    return rows[0].get("contractId")


async def fetch_dce_api_position_ranking(
    symbol: str, trade_date: str, *, transport=None
) -> dict:
    """大商所官方 API 持仓排名。

    Args:
        symbol: 品种或合约（如 'm' 或 'm2609'）
        trade_date: 交易日 YYYYMMDD
        transport: httpx transport（测试可注入 MockTransport）

    Returns:
        {long:[{rank,member,lots}], short:[...], contract} 或 {}（无数据/异常交由调用方处理）
    """
    apikey = os.environ.get("DCE_API_KEY")
    secret = os.environ.get("DCE_API_SECRET")
    if not apikey or not secret:
        raise RuntimeError("DCE_API_KEY / DCE_API_SECRET 未设置，无法使用大商所官方API")

    variety, contract_id = _split_symbol(symbol)
    token = await _login(apikey, secret, transport=transport)
    if contract_id is None:
        contract_id = await _resolve_contract(variety, token, apikey, transport=transport)
    if not contract_id:
        return {}

    headers = {
        "apikey": apikey,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "varietyId": variety,
        "tradeDate": trade_date,
        "contractId": contract_id,
        "tradeType": "1",
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, transport=transport) as c:
        r = await c.post(
            f"{DCE_API_BASE}/forward/publicweb/dailystat/memberDealPosi",
            headers=headers,
            json=body,
        )
        r.raise_for_status()
        j = r.json()
    if not j.get("success"):
        raise RuntimeError(
            f"DCE memberDealPosi 失败：{j.get('msg')} (code={j.get('code')})"
        )

    data = j.get("data") or {}
    long_list, short_list = [], []
    for it in data.get("buyFutureList") or []:
        long_list.append(
            {
                "rank": _to_int(it.get("rank")),
                "member": it.get("buyAbbr") or it.get("abbr") or "",
                "lots": _to_int(it.get("todayBuyQty")),
            }
        )
    for it in data.get("sellFutureList") or []:
        short_list.append(
            {
                "rank": _to_int(it.get("rank")),
                "member": it.get("sellAbbr") or it.get("abbr") or "",
                "lots": _to_int(it.get("todaySellQty")),
            }
        )
    if not long_list and not short_list:
        return {}
    return {"long": long_list, "short": short_list, "contract": contract_id.upper()}
