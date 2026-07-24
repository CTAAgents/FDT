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


# ═══════════════════════════════════════════════════════════════
#  清洗对接（Phase 3.3）
# ═══════════════════════════════════════════════════════════════

def apply_fundamental_cleaning(
    data: dict,
    data_type: str,
    symbol: str = "",
) -> tuple[dict, Optional[dict]]:
    """对基本面数据应用清洗管线。

    将 query_* 返回的数据包装为 ``clean_fundamental_snapshot()`` 可消费的格式，
    执行清洗后返回清洗后的数据和清洗报告。

    Args:
        data: query_* 返回的原始数据（含 ``_meta``）。
        data_type: 数据类型（\"inventory\" / \"supply\" / \"demand\" / \"margin\"）。
        symbol: 品种代码。

    Returns:
        (cleaned_data, cleaning_summary) — 清洗后的数据和清洗摘要。
        清洗不可用时返回 (data, None)。
    """
    try:
        from data_adapter.cleaning.fundamental import clean_fundamental_snapshot

        # 包装为标准格式
        wrapper = {
            "data": {
                "_meta": data.get("_meta", {}),
                "source": data.get("_source", ""),
            },
            "data_grade": "PRIMARY",
        }

        cleaned, report = clean_fundamental_snapshot(wrapper, data_type, symbol=symbol)

        if report.total_actions > 0:
            summary = {
                "total_actions": report.total_actions,
                "actions": [
                    {"action": a.action, "field": a.field, "reason": a.reason}
                    for a in report.actions[:5]  # 最多 5 条
                ],
            }
            data["_cleaning"] = summary
            if "_caliber_warnings" in cleaned:
                data["_caliber_warnings"] = cleaned["_caliber_warnings"]
            return data, summary

    except ImportError:
        pass  # cleaning module not available
    except Exception:
        pass  # cleaning failed

    return data, None


# ═══════════════════════════════════════════════════════════════
#  时间对齐层（Phase 3.4）
# ═══════════════════════════════════════════════════════════════

def align_to_timeline(
    data: dict,
    target_dates: Optional[list[str]] = None,
    method: str = "ffill",
) -> dict:
    """将低频率基本面数据对齐到日 K 线时间轴。

    由于当前数据为硬编码快照（单期），此函数返回包含对齐元信息的包装，
    后续接入 DuckDB 多期时序数据后可启用真实对齐。

    Args:
        data: query_* 返回的数据（含 ``_meta`` / ``_updated``）。
        target_dates: 目标 K 线日期序列（当前未使用，预留）。
        method: 对齐方法（\"ffill\" 前向填充 / \"interp\" 线性插值）。

    Returns:
        添加 ``_timeline`` 元信息后的数据。
    """
    updated = str(data.get("_updated", ""))
    data["_timeline"] = {
        "aligned": False,
        "method": method,
        "data_date": updated,
        "target_count": len(target_dates) if target_dates else 0,
        "note": "single snapshot - multi-period data required for true alignment",
    }
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
