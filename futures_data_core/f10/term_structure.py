"""期限结构分析 [INDEPENDENT]。

数据来源优先级：
  1. QMT/xtquant 全合约链（遍历六所，取结算价+昨持仓量）
  2. 注入的 TDX 等自定义 provider

实现采用**可注入合约链 provider** 设计：``get_term_structure`` 接受一个
``fetch_contracts`` 可调用对象（同步或异步），测试与真实环境均通过它供给
合约链，避免硬编码网络。计算内核 ``analyze_term_structure`` 为纯函数，便于
单元测试覆盖。

A2A 输出：``type=fdc.term_structure``。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Union

from futures_data_core._a2a import A2APayload, DATA_TYPES
from futures_data_core.core._datacore_bridge import (
    dc_result_to_a2apayload,
    try_datacore_first,
)



# 合约链 provider：``fetch_contracts(symbol) -> list[dict] | None``
# 每个 dict: {"contract": "CU2408", "month": "2408", "price": 72300,
#             "oi": 125000, "volume": 35200}
ContractsProvider = Callable[[str], Union[list[dict], Awaitable[Optional[list[dict]]]]]


def analyze_term_structure(contracts: Optional[list[dict]]) -> Optional[dict]:
    """从合约链计算期限结构（纯函数，无 IO）。

    算法（与 TDX ``get_term_structure`` 一致）：
      - 按合约月份升序排序，取首/尾为近/远月
      - ``slope_pct = (远月价 - 近月价) / 近月价 * 100``
      - 结构判定：``slope_pct < -0.1`` -> BACK；``> 0.1`` -> CONTANGO；否则 FLAT
      - 跨期价差（近月 - 次近月）

    Returns:
        结构化 dict；合约数 < 2 或无有效价格时返回 ``None``。
    """
    if not contracts or len(contracts) < 2:
        return None

    def _key(c: dict) -> str:
        return str(c.get("month") or c.get("contract") or "")

    sorted_c = sorted(contracts, key=_key)
    near = sorted_c[0]
    far = sorted_c[-1]
    try:
        near_price = float(near["price"])
        far_price = float(far["price"])
    except (KeyError, TypeError, ValueError):
        return None
    if near_price <= 0:
        return None

    slope_pct = (far_price - near_price) / near_price * 100.0
    if slope_pct < -0.1:
        structure = "BACK"
    elif slope_pct > 0.1:
        structure = "CONTANGO"
    else:
        structure = "FLAT"

    result: dict[str, Any] = {
        "structure": structure,
        "slope_pct": round(slope_pct, 4),
        "near_contract": near.get("contract"),
        "near_price": near_price,
        "far_contract": far.get("contract"),
        "far_price": far_price,
        "contracts": [
            {
                "contract": c.get("contract"),
                "month": c.get("month"),
                "price": _to_float(c.get("price")),
                "oi": c.get("oi"),
                "volume": c.get("volume"),
            }
            for c in sorted_c
        ],
    }
    # 跨期价差：近月 - 次近月（已保证 len >= 2）
    try:
        next_price = float(sorted_c[1]["price"])
        result["spread"] = round(near_price - next_price, 2)
    except (KeyError, TypeError, ValueError):
        pass
    return result


async def _resolve_contracts(
    symbol: str, fetch_contracts: Optional[ContractsProvider]
) -> Optional[list[dict]]:
    """解析合约链：优先使用注入 provider；否则走 QMT 降级。"""
    if fetch_contracts is not None:
        out = fetch_contracts(symbol)
        if hasattr(out, "__await__"):
            out = await out  # type: ignore[assignment]
        return out  # type: ignore[return-value]
    return await _qmt_contracts(symbol)


async def _qmt_contracts(symbol: str) -> Optional[list[dict]]:
    """通过 QMT/xtquant 获取品种全合约链。

    遍历国内六家期货交易所板块，匹配品种前缀后取全部合约的
    结算价/昨持仓量，按月份排序返回。
    """
    try:
        from xtquant import xtdata
    except ImportError:
        return None
    try:
        sym = symbol.upper()
        sectors = [
            "上海期货交易所", "大连商品交易所", "郑州商品交易所",
            "中国金融期货交易所", "上海国际能源交易中心", "广州期货交易所",
        ]
        candidates: list[str] = []
        for sector in sectors:
            try:
                codes = xtdata.get_stock_list_in_sector(sector) or []
            except Exception:
                codes = []
            matches = [
                c for c in codes
                if c.lstrip("0123456789").upper().startswith(sym)
            ]
            if matches:
                candidates.extend(matches)
        if not candidates:
            return None

        contracts: list[dict] = []
        for code in candidates:
            detail = xtdata.get_instrument_detail(code)
            if detail is None:
                continue
            settle = detail.get("SettlementPrice", 0)
            if not settle or settle <= 0:
                continue
            contracts.append({
                "contract": code,
                "month": "".join(ch for ch in code if ch.isdigit())[-4:],
                "price": float(settle),
                "oi": detail.get("LastVolume", 0),
            })
        return sorted(contracts, key=lambda c: c["month"]) if contracts else None
    except Exception:
        return None


def _month_from(contract: Any) -> Optional[str]:
    """从合约代码（如 CU2408 / rb2507）提取 4 位月份字符串。"""
    s = str(contract)
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def _to_float(value: Any) -> Optional[float]:
    """安全浮点转换（纯函数）：非数值返回 ``None``。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def get_term_structure(
    symbol: str, *, fetch_contracts: Optional[ContractsProvider] = None
) -> A2APayload:
    """获取品种期限结构（自动降级）。无 LLM 依赖。

    Args:
        symbol: 品种代码（如 ``"CU"``）。
        fetch_contracts: 可注入的合约链 provider；缺省使用 QMT 降级。

    Returns:
        :class:`A2APayload`，``data`` 含 ``structure`` / ``slope_pct`` /
        ``near_contract`` / ``far_contract`` / ``spread`` / ``contracts``。
    """
    # v9.4.0: Data-Core 优先检查
    dc_result, dc_used = await try_datacore_first("get_term_structure", symbol)
    if dc_used:
        return dc_result_to_a2apayload(
            dc_result, symbol, DATA_TYPES["TERM_STRUCTURE"],
            f"{symbol} 期限结构（Data-Core）",
        )

    contracts = await _resolve_contracts(symbol, fetch_contracts)
    result = analyze_term_structure(contracts) if contracts else None

    if result is None:
        payload = A2APayload(
            type=DATA_TYPES["TERM_STRUCTURE"],
            runtime_mode="independent",
            data={"symbol": symbol, "structure": "UNKNOWN", "contracts": []},
        )
        payload.set_grade("UNAVAILABLE")
        payload.add_warning("无法获取合约链，期限结构不可用")
        return payload

    result["symbol"] = symbol
    payload = A2APayload(
        type=DATA_TYPES["TERM_STRUCTURE"],
        runtime_mode="independent",
        data=result,
    )
    payload.set_grade("PRIMARY")
    payload.meta["sources"] = ["qmt_xtquant" if fetch_contracts is not None else "default"]
    payload.summary = (
        f"{symbol} 期限结构 {result['structure']}，斜率 {result['slope_pct']:.2f}%"
    )
    return payload
