"""跨期价差分析 [INDEPENDENT]。

数据来源：通达信 TQ-Local 合约链（近月 - 远月）。实现与 :mod:`term_structure`
一致的**可注入 provider** 设计；计算内核 ``compute_spread`` 为纯函数。

价差约定（与 TDX ``get_spread`` 一致）：
  - ``spread = 近月价 - 远月价``
  - ``spread_pct = spread / 远月价 * 100``
  - 类型：``spread > 0`` -> BACK（近高远低）；``< 0`` -> CONTANGO；``== 0`` -> FLAT

A2A 输出：``type=fdc.spread``。
"""

from __future__ import annotations

from typing import Any, Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES
from futures_data_core.core._datacore_bridge import (
    dc_result_to_a2apayload,
    try_datacore_first,
)
from futures_data_core.f10.term_structure import ContractsProvider, _month_from, _resolve_contracts


def compute_spread(near_price: float, far_price: float) -> dict:
    """计算近远月价差（纯函数）。

    Args:
        near_price: 近月合约价格。
        far_price: 远月合约价格。

    Returns:
        ``{"spread", "spread_pct", "type"}``；远月价非正时返回全 0 / FLAT。
    """
    if not far_price or far_price <= 0:
        return {"spread": 0.0, "spread_pct": 0.0, "type": "FLAT"}
    spread = near_price - far_price
    spread_pct = spread / far_price * 100.0
    if spread > 0:
        stype = "BACK"
    elif spread < 0:
        stype = "CONTANGO"
    else:
        stype = "FLAT"
    return {
        "spread": round(spread, 2),
        "spread_pct": round(spread_pct, 4),
        "type": stype,
    }


async def get_spread(
    symbol: str,
    month_near: Optional[str] = None,
    month_far: Optional[str] = None,
    *,
    fetch_contracts: Optional[ContractsProvider] = None,
) -> A2APayload:
    """获取跨期价差（自动降级）。无 LLM 依赖。

    Args:
        symbol: 品种代码。
        month_near: 指定近月（如 ``"2408"``）；缺省取合约链首月。
        month_far: 指定远月；缺省取次近月。
        fetch_contracts: 可注入合约链 provider。

    Returns:
        :class:`A2APayload`，``data`` 含近/远合约与价差。
    """
    # v9.4.0: Data-Core 优先检查
    dc_result, dc_used = await try_datacore_first("get_spread", symbol)
    if dc_used:
        return dc_result_to_a2apayload(
            dc_result, symbol, DATA_TYPES["SPREAD"],
            f"{symbol} 跨期价差（Data-Core）",
        )

    contracts = await _resolve_contracts(symbol, fetch_contracts)
    if not contracts or len(contracts) < 2:
        payload = A2APayload(
            type=DATA_TYPES["SPREAD"],
            runtime_mode="independent",
            data={"symbol": symbol, "spread": None},
        )
        payload.set_grade("UNAVAILABLE")
        payload.add_warning("合约链不足，无法计算跨期价差")
        return payload

    def _key(c: dict) -> str:
        return str(c.get("month") or c.get("contract") or "")

    sorted_c = sorted(contracts, key=_key)

    def _pick(target: Optional[str]):
        if target:
            hit = next((c for c in sorted_c if target in str(c.get("contract", ""))), None)
            return hit
        return None

    near = _pick(month_near) or sorted_c[0]
    far = _pick(month_far) or (sorted_c[1] if len(sorted_c) > 1 else sorted_c[-1])

    try:
        near_price = float(near["price"])
        far_price = float(far["price"])
    except (KeyError, TypeError, ValueError):
        payload = A2APayload(
            type=DATA_TYPES["SPREAD"],
            runtime_mode="independent",
            data={"symbol": symbol, "spread": None},
        )
        payload.set_grade("UNAVAILABLE")
        payload.add_warning("合约价格缺失，无法计算跨期价差")
        return payload

    spread = compute_spread(near_price, far_price)
    data: dict[str, Any] = {
        "symbol": symbol,
        "near_contract": near.get("contract"),
        "near_month": _month_from(near.get("contract")),
        "near_price": near_price,
        "far_contract": far.get("contract"),
        "far_month": _month_from(far.get("contract")),
        "far_price": far_price,
        **spread,
    }
    payload = A2APayload(
        type=DATA_TYPES["SPREAD"], runtime_mode="independent", data=data
    )
    payload.set_grade("PRIMARY")
    payload.meta["sources"] = ["qmt_xtquant" if fetch_contracts is not None else "default"]
    payload.summary = (
        f"{symbol} 跨期价差 {data['spread']:.2f}（{data['type']}）"
    )
    return payload
