"""Data-Core F10 桥接器 [INDEPENDENT]。

为 FDT 的 F10 模块提供统一的 Data-Core 优先检查入口。每个 F10 模块的公开
入口函数只需调用 ``try_datacore_first()`` 即可实现 Data-Core → 原有实现的
两级降级链。

约定
====
- Data-Core ``fdc_compat`` 返回纯 ``dict``（而非 ``A2APayload``）。
- 桥接器负责将 dict 包装为 ``A2APayload``，确保下游消费者无感知。
- 当 Data-Core 不可用（未安装 / import 失败 / 返回空 / 抛异常）时，
  返回 ``(None, False)``，调用方继续走原有实现。

使用方式
========
.. code-block:: python

    from futures_data_core.core._datacore_bridge import try_datacore_first, dc_result_to_a2apayload
    from futures_data_core._a2a import DATA_TYPES

    async def get_basis(symbol, **kwargs):
        dc_result, dc_used = await try_datacore_first("get_basis", symbol)
        if dc_used:
            return dc_result_to_a2apayload(
                dc_result, symbol, DATA_TYPES["BASIS"],
                f"{symbol} 基差（Data-Core）"
            )
        # ... 原有实现
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from futures_data_core._a2a import A2APayload, DATA_GRADE, DATA_GRADE_NAME

logger = logging.getLogger("fdt_datacore_bridge")

# ── Data-Core F10 函数名映射 ──────────────────────────────────────
# key: try_datacore_first 的第一个参数 func_name
# value: datacore.fdc_compat 中的实际函数名
_DC_FUNC_MAP: dict[str, str] = {
    "get_term_structure": "get_term_structure",
    "get_spread": "get_spread",
    "get_basis": "get_basis",
    "get_warrant": "get_warrant",
    "get_fundamental": "get_fundamental",
    "get_f10": "get_f10",
    "get_position_ranking": "get_position_ranking",
    "compute_indicators": "compute_indicators",
}


async def try_datacore_first(
    func_name: str,
    symbol: str,
    **kwargs: Any,
) -> tuple[Optional[dict], bool]:
    """尝试从 Data-Core 获取数据。

    Args:
        func_name: 函数名（见 ``_DC_FUNC_MAP``）。
        symbol: 品种代码。
        **kwargs: 透传给 Data-Core 函数的额外参数。

    Returns:
        ``(data, used)``:
        - ``data``: Data-Core 返回的 dict（成功时）；失败时为 ``None``。
        - ``used``: ``True`` 表示 Data-Core 提供了有效数据，调用方应直接返回；
          ``False`` 表示 Data-Core 不可用/返回空，调用方应回退原有实现。
    """
    dc_func_name = _DC_FUNC_MAP.get(func_name)
    if dc_func_name is None:
        logger.debug("[DCBridge] 未知函数 %s，跳过", func_name)
        return None, False

    try:
        import datacore.fdc_compat as dc  # noqa: F401
    except ImportError:
        logger.debug("[DCBridge] datacore 模块未安装，跳过 %s", func_name)
        return None, False

    try:
        dc_func = getattr(dc, dc_func_name, None)
        if dc_func is None:
            logger.warning("[DCBridge] datacore.fdc_compat 无 %s 函数", dc_func_name)
            return None, False

        # 调用 Data-Core 函数
        result = dc_func(symbol)
        # 支持同步和异步两种调用方式
        if hasattr(result, "__await__"):
            result = await result

        # 判定有效
        if result and isinstance(result, dict) and _is_valid_dc_result(result):
            logger.info("[DCBridge] %s(%s) ← Data-Core", func_name, symbol)
            return result, True

        logger.debug("[DCBridge] %s(%s) Data-Core 返回空/无效", func_name, symbol)
        return None, False

    except Exception as exc:
        logger.warning("[DCBridge] %s(%s) Data-Core 异常: %s", func_name, symbol, exc)
        return None, False


def dc_result_to_a2apayload(
    dc_result: dict,
    symbol: str,
    data_type: str,
    summary: str = "",
) -> A2APayload:
    """将 Data-Core 返回的 dict 包装为 FDT ``A2APayload``。

    Args:
        dc_result: Data-Core 函数返回的 dict。
        symbol: 品种代码。
        data_type: ``DATA_TYPES`` 中的类型常量。
        summary: 可选的简短摘要。

    Returns:
        构造好的 ``A2APayload``，meta 中包含 ``"datacore"`` 来源标记。
    """
    # 提取 data_grade 级别
    grade_label = dc_result.get("data_grade", _infer_grade(dc_result))
    try:
        grade_index = DATA_GRADE[grade_label]
    except (KeyError, TypeError):
        grade_index = DATA_GRADE.get("STALE", 3)  # 默认降级

    payload = A2APayload(
        type=data_type,
        runtime_mode="independent",
        data=dc_result,
        summary=summary or f"{symbol} ({data_type}) — Data-Core",
    )
    payload.set_grade(DATA_GRADE_NAME[grade_index])
    payload.meta["source"] = "datacore"
    payload.meta["sources"] = ["datacore"]
    return payload


# ── 内部工具 ─────────────────────────────────────────────────────


def _is_valid_dc_result(result: dict) -> bool:
    """判定 Data-Core 返回的 dict 是否包含有效数据。"""
    if not result:
        return False

    # 检查是否有实质内容字段（而非仅 symbol/meta）
    data_keys = set(result.keys())
    # 排除元数据字段
    meta_fields = {"symbol", "data_grade", "source", "sources", "meta", "summary", "error"}
    content_keys = data_keys - meta_fields
    if not content_keys:
        return False

    # 至少有一个非空字段
    for key in content_keys:
        val = result[key]
        if val is not None and val != {} and val != [] and val != "":
            return True
    return False


def _infer_grade(result: dict) -> str:
    """从 Data-Core 返回中推断数据等级。"""
    if _is_valid_dc_result(result):
        return "STALE"
    return "UNAVAILABLE"


__all__ = [
    "try_datacore_first",
    "dc_result_to_a2apayload",
]
