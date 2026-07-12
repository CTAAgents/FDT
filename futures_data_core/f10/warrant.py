"""仓单日报 [INDEPENDENT]。

数据来源：交易所官方日线数据（经 :mod:`exchange_scraper`）；解析出仓单相关列并汇总。

实现采用**可注入 transport** 设计：``get_warrant`` 接受 ``transport`` 可调用对象，
缺省走交易所官方端点（可能 404/WAF 拦截，自动降级）。解析与汇总逻辑为纯函数。

A2A 输出：``type=fdc.warrant``。
"""

from __future__ import annotations

from typing import Any, Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES
from futures_data_core.f10.exchange_scraper import (
    fetch_exchange_page,
    fmt_of,
    get_exchange_url,
    parse_daily_rows,
    today_yyyymmdd,
)

_WARRANT_KEYS = {"warrant", "receipt", "仓单", "仓单量", "仓单数量"}
_CHANGE_KEYS = {"change", "delta", "日变动", "增减", "仓单变动"}


def _match_key(headers: list[str], candidates: set[str]) -> Optional[str]:
    for h in headers:
        key = str(h).strip()
        if key.lower() in candidates or key in candidates:
            return h
    return None


def summarize_warrant(rows: list[dict]) -> dict:
    """从解析行汇总仓单总量与日变动（纯函数）。"""
    if not rows:
        return {"total": None, "daily_change": None, "rows": 0}

    headers = list(rows[0].keys())
    warrant_col = _match_key(headers, _WARRANT_KEYS)
    change_col = _match_key(headers, _CHANGE_KEYS)

    total = None
    if warrant_col:
        vals: list[float] = []
        for r in rows:
            try:
                vals.append(float(str(r.get(warrant_col, "")).replace(",", "")))
            except (TypeError, ValueError):
                pass
        if vals:
            total = sum(vals)

    daily_change = None
    if change_col:
        changes: list[float] = []
        for r in rows:
            try:
                changes.append(float(str(r.get(change_col, "")).replace(",", "")))
            except (TypeError, ValueError):
                pass
        if changes:
            daily_change = sum(changes)

    return {"total": total, "daily_change": daily_change, "rows": len(rows)}


async def get_warrant(
    symbol: str,
    exchange: str = "SHFE",
    trade_date: Optional[str] = None,
    *,
    transport=None,
) -> A2APayload:
    """获取品种仓单日报。无 LLM 依赖。

    Args:
        symbol: 品种代码。
        exchange: 交易所（SHFE/DCE/CZCE/CFFEX/GFEX）。
        trade_date: ``YYYYMMDD``；缺省今天。
        transport: 可注入抓取器（返回页面文本）；缺省走交易所官方端点。

    Returns:
        :class:`A2APayload`，``data`` 含 ``total`` / ``daily_change`` / ``source_rows``。
    """
    if trade_date is None:
        trade_date = today_yyyymmdd()

    url = get_exchange_url(exchange, trade_date)
    text = None
    if url:
        try:
            text = await fetch_exchange_page(url, transport=transport)
        except Exception:
            text = None

    fmt = fmt_of(exchange) or "html"
    rows = parse_daily_rows(text, fmt) if text else []
    summary = summarize_warrant(rows)

    if summary["total"] is None and not rows:
        payload = A2APayload(
            type=DATA_TYPES["WARRANT"],
            runtime_mode="independent",
            data={"symbol": symbol, "total": None},
        )
        payload.set_grade("UNAVAILABLE")
        payload.add_warning(f"{exchange} 仓单数据获取失败，已降级")
        return payload

    data: dict[str, Any] = {
        "symbol": symbol,
        "exchange": exchange,
        "trade_date": trade_date,
        "total": summary["total"],
        "daily_change": summary["daily_change"],
        "source_rows": summary["rows"],
    }
    payload = A2APayload(type=DATA_TYPES["WARRANT"], runtime_mode="independent", data=data)
    payload.set_grade("DAILY")
    payload.meta["sources"] = [exchange.lower()]
    payload.summary = (
        f"{symbol} ({exchange}) 仓单 {data['total']}"
        + (f"，日变动 {data['daily_change']}" if data["daily_change"] is not None else "")
    )
    return payload
