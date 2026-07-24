"""基本面数据结构化工具 — 解析 + 附加元数据 + 清洗对接。

将 ``query_*`` 函数返回的硬编码字典升级为带 ``_meta`` 的结构化格式，
同时保持文本字段的 LLM 可读性。

使用方法：:

    from structured_data import enrich_with_meta, DEFAULT_META

    # 在 query_* 函数末尾：
    base = {"利润": "80元/吨", "趋势": "低位"}
    result = enrich_with_meta(base, "利润", value=80, unit="元/吨", direction="下降")
    result["_source"] = "Mysteel"
    result["_updated"] = "2026-07-04"
    return result
"""

from __future__ import annotations

import re
from typing import Any, Optional

from data_adapter.types import StructuredFundamentalMeta

# ── 默认元数据模板（数据采集日期 / 来源） ──
DEFAULT_META = {
    "data_date": "2026-07-04",
    "revision": "v1",
}


def parse_numeric(text: str) -> Optional[float]:
    """从文本中提取首个数值。

    ``"80元/吨"`` → ``80.0``
    ``"亏损加深"`` → ``None``
    """
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if m:
        return float(m.group())
    return None


def parse_unit(text: str, default: str = "") -> str:
    """从文本中提取单位（元/吨 / % / 万吨 等）。"""
    m = re.search(r"(元/吨|元/斤|元/只?|%|万吨|万吨/天|天|亿只|亿|万|点|美元/吨)", text)
    return m.group(1) if m else default


def detect_direction(text: str) -> str:
    """从文本中判断趋势方向。"""
    up_words = {"上升", "上涨", "增加", "高位", "加速", "+", "增", "盈利"}
    down_words = {"下降", "下跌", "减少", "低位", "亏损", "压缩", "放缓", "-", "减", "亏损"}
    for w in up_words:
        if w in text:
            return "上升"
    for w in down_words:
        if w in text:
            return "下降"
    return "持平"


def enrich_with_meta(
    data: dict,
    field_name: str,
    *,
    value: Optional[float] = None,
    unit: str = "",
    direction: str = "",
    data_date: str = "",
    source: str = "",
) -> dict:
    """为字典中的单个字段附加结构化元数据。

    Args:
        data: 原始字典（会被修改）。
        field_name: 字段名。
        value: 数值。不传则从文本自动提取。
        unit: 单位。不传则从文本自动提取。
        direction: 方向。不传则从文本自动检测。
        data_date: 数据日期。
        source: 数据来源。

    Returns:
        修改后的 data 字典（附加 ``_meta`` 键）。
    """
    text = str(data.get(field_name, ""))

    meta = StructuredFundamentalMeta(
        value=value if value is not None else parse_numeric(text),
        unit=unit if unit else parse_unit(text),
        direction=direction if direction else detect_direction(text),
        data_date=data_date or DEFAULT_META["data_date"],
        source=source,
        revision=DEFAULT_META["revision"],
    )

    if "_meta" not in data:
        data["_meta"] = {}
    data["_meta"][field_name] = meta

    return data


def enrich_all_fields(
    data: dict,
    default_date: str = "2026-07-04",
    default_source: str = "",
) -> dict:
    """为字典中所有非元字段附加结构化元数据。

    自动解析每个文本字段的数值、单位、方向。

    Args:
        data: 原始字典（包含 ``_source`` / ``_updated`` / ``seasonal`` 等元字段）。
        default_date: 默认数据日期。
        default_source: 默认数据来源（从 ``_source`` 自动提取）。

    Returns:
        修改后的 data 字典。
    """
    source = default_source or str(data.get("_source", ""))
    meta_keys = {"_source", "_updated", "_meta", "_cleaning", "seasonal", "info", "seasonal"}

    for key in list(data.keys()):
        if key in meta_keys:
            continue
        text = str(data.get(key, ""))
        if not text or text.startswith("无"):
            continue

        value = parse_numeric(text)
        if value is not None:
            meta = StructuredFundamentalMeta(
                value=value,
                unit=parse_unit(text),
                direction=detect_direction(text),
                data_date=default_date,
                source=source,
            )
            if "_meta" not in data:
                data["_meta"] = {}
            data["_meta"][key] = meta

    return data
