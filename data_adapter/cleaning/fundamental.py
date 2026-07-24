"""基本面数据清洗 — 快照级校验 + 时间对齐 + 口径变更 + 修订追踪。

Phase 3 of the cleaning pipeline.

功能：
1. 快照值有效性校验（负值/空值/越界）
2. 新鲜度评分（data_date vs 当前日期）
3. 跨字段交叉一致性校验
4. 缺失值处理与数据等级降级
5. 统计口径变更检测（规则跳变点识别）
6. 修订版追踪（版本标注）
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from data_adapter.types import CleaningAction, CleaningReport

# ── 已知的统计口径变更事件（交易所规则调整） ──
# 格式：YYYY-MM-DD 字段名 描述
_KNOWN_CALIBER_CHANGES: list[dict] = [
    {"date": "2023-08-04", "field": "margin_rate", "symbol": "SA",
     "description": "纯碱保证金率从 9% 调至 12%"},
    {"date": "2023-09-08", "field": "margin_rate", "symbol": "SA",
     "description": "纯碱保证金率从 12% 调至 15%"},
    {"date": "2023-10-13", "field": "tick_size", "symbol": "LC",
     "description": "碳酸锂最小变动价位从 50→10 元/吨"},
    {"date": "2024-01-10", "field": "margin_rate", "symbol": "LC",
     "description": "碳酸锂保证金率从 12% 调至 15%"},
    {"date": "2024-04-17", "field": "trading_limit", "symbol": "SI",
     "description": "工业硅涨跌停板从 6% 调至 7%"},
]

# 数据分级阈值（天）
_FRESHNESS_THRESHOLDS = {
    "basis": {"fresh": 1, "stale": 5},              # 基差：1天内新鲜，5天以上过时
    "warrant": {"fresh": 3, "stale": 10},            # 仓单：3天内新鲜，10天以上过时
    "position_ranking": {"fresh": 3, "stale": 10},   # 持仓排名：3天
    "fund_flow": {"fresh": 3, "stale": 10},          # 资金流向：3天
    "inventory": {"fresh": 7, "stale": 30},          # 库存：周级发布
}

# 字段值合理性边界
_VALUE_BOUNDS: dict[str, dict] = {
    "spot_price": {"min": 0.001, "max": 1_000_000},
    "basis_pct": {"min": -1.0, "max": 1.0},
    "total_oi": {"min": 0, "max": 10_000_000},
}


# ═══════════════════════════════════════════════════════════════
#  内部工具
# ═══════════════════════════════════════════════════════════════

def _today_str() -> str:
    """获取 UTC 日期字符串 YYYYMMDD。"""
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _parse_date(date_val: Any) -> Optional[datetime]:
    """尝试多种格式解析日期。"""
    if not date_val:
        return None
    s = str(date_val).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%dT%H%M%S"):
        try:
            return datetime.strptime(s[:10], fmt.replace("T%H%M%S", "").strip())
        except (ValueError, IndexError):
            continue
    return None


def _days_since(date_val: Any) -> Optional[float]:
    """计算距今天数。"""
    dt = _parse_date(date_val)
    if dt is None:
        return None
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    return (today - dt).total_seconds() / 86400.0


# ═══════════════════════════════════════════════════════════════
#  清洗函数
# ═══════════════════════════════════════════════════════════════

def validate_snapshot_values(
    data: dict,
    data_type: str,
    symbol: str = "",
) -> tuple[dict, list[CleaningAction]]:
    """快照值有效性校验。

    检查负值、越界、空值，修复/标记异常数据。
    """
    actions: list[CleaningAction] = []
    result = dict(data)  # 浅拷贝
    inner = result.get("data", {})

    if not isinstance(inner, dict):
        return result, actions

    # ── 通用字段类型检查 ──
    numeric_fields = {"last_price", "spot_price", "total", "daily_change",
                      "net_long", "long_volume", "short_volume",
                      "total_oi", "long_short_ratio", "basis", "basis_pct",
                      "inventory", "change"}

    for key in list(inner.keys()):
        val = inner.get(key)
        if val is None:
            continue
        if key not in numeric_fields:
            continue
        try:
            v = float(val)
        except (ValueError, TypeError):
            actions.append(CleaningAction(
                action="fixed",
                field=key,
                index=0,
                reason=f"non-numeric value ({type(val).__name__}), set to None",
                original=str(val),
            ))
            inner[key] = None
            continue

        # 负值检查（仅对必须为正的字段）
        if v < 0 and key in ("total", "total_oi", "long_volume", "short_volume",
                             "spot_price", "inventory", "volume"):
            actions.append(CleaningAction(
                action="fixed",
                field=key,
                index=0,
                reason=f"negative value ({v}), absolved",
                original=str(v),
            ))
            inner[key] = abs(v)
            continue

        # 边界检查
        bounds = _VALUE_BOUNDS.get(key)
        if bounds:
            if v < bounds["min"]:
                actions.append(CleaningAction(
                    action="fixed",
                    field=key,
                    index=0,
                    reason=f"value {v} below min {bounds['min']}, clipped",
                    original=str(v),
                ))
                inner[key] = bounds["min"]
            elif v > bounds["max"]:
                actions.append(CleaningAction(
                    action="marked",
                    field=key,
                    index=0,
                    reason=f"value {v} exceeds max {bounds['max']}, flagged",
                    original=str(v),
                ))

    # ── 分级校验 ──
    if data_type == "warrant":
        total = inner.get("total")
        change = inner.get("daily_change")
        if total is not None and change is not None:
            try:
                if abs(float(change)) > abs(float(total)) * 0.5 and float(total) > 0:
                    actions.append(CleaningAction(
                        action="marked",
                        field="daily_change",
                        index=0,
                        reason=f"daily_change ({change}) > 50% of total ({total}), possible data error",
                        original=str(change),
                    ))
            except (ValueError, TypeError):
                pass

    elif data_type == "position_ranking":
        long_v = inner.get("long_volume")
        short_v = inner.get("short_volume")
        net = inner.get("net_long")
        if long_v is not None and short_v is not None and net is not None:
            try:
                expected_net = float(long_v) - float(short_v)
                actual_net = float(net)
                if abs(expected_net - actual_net) > 0.01 * max(abs(expected_net), 1000):
                    actions.append(CleaningAction(
                        action="fixed",
                        field="net_long",
                        index=0,
                        reason=f"net_long inconsistency: expected {expected_net:.0f}, got {actual_net:.0f}, recalculated",
                        original=str(net),
                    ))
                    inner["net_long"] = expected_net
            except (ValueError, TypeError):
                pass

    elif data_type == "fund_flow":
        ratio = inner.get("long_short_ratio")
        if ratio is not None:
            try:
                r = float(ratio)
                if r <= 0:
                    actions.append(CleaningAction(
                        action="fixed",
                        field="long_short_ratio",
                        index=0,
                        reason=f"non-positive ratio ({r}), set to 1.0",
                        original=str(ratio),
                    ))
                    inner["long_short_ratio"] = 1.0
            except (ValueError, TypeError):
                pass

    result["data"] = inner
    return result, actions


def rate_freshness(
    data: dict,
    data_type: str,
    symbol: str = "",
) -> tuple[dict, list[CleaningAction]]:
    """数据新鲜度评分。

    检查 ``data_date`` 或 ``date`` 字段与当前日期的差距，
    输出 ``freshness_days`` / ``freshness_level`` 标记。
    """
    actions: list[CleaningAction] = []
    result = dict(data)
    inner = result.get("data", {})
    if not isinstance(inner, dict):
        inner = {}

    # 尝试获取日期字段
    date_val = inner.get("data_date") or inner.get("date") or result.get("date")
    days = _days_since(date_val)

    thresholds = _FRESHNESS_THRESHOLDS.get(data_type, {"fresh": 3, "stale": 10})

    if days is not None:
        inner["freshness_days"] = round(days, 1)
        if days <= thresholds["fresh"]:
            inner["freshness_level"] = "FRESH"
        elif days <= thresholds["stale"]:
            inner["freshness_level"] = "STALE"
        else:
            inner["freshness_level"] = "STALE_WARNING"
            actions.append(CleaningAction(
                action="marked",
                field="data_date",
                index=0,
                reason=f"data stale: {days:.0f}d old (threshold: {thresholds['stale']}d)",
                original=str(date_val),
            ))
    else:
        inner["freshness_days"] = None
        inner["freshness_level"] = "UNKNOWN"

    # 新鲜度降级：过时数据标记 data_grade
    if inner.get("freshness_level") == "STALE_WARNING":
        grade = result.get("data_grade", "PRIMARY")
        if grade == "PRIMARY":
            result["data_grade"] = "STALE"
            actions.append(CleaningAction(
                action="marked",
                field="data_grade",
                index=0,
                reason="downgraded PRIMARY→STALE due to staleness",
                original=grade,
            ))

    result["data"] = inner
    return result, actions


def detect_caliber_change(
    data: dict,
    data_type: str,
    symbol: str = "",
) -> tuple[dict, list[CleaningAction]]:
    """检测已知的统计口径变更。

    检查当前品种是否有已知的规则调整事件。
    """
    actions: list[CleaningAction] = []
    result = dict(data)

    if not symbol:
        return result, actions

    bare = symbol.upper().rstrip("0123456789")

    for change in _KNOWN_CALIBER_CHANGES:
        sym_match = change.get("symbol", "")
        if bare in sym_match or sym_match in bare:
            actions.append(CleaningAction(
                action="marked",
                field=change["field"],
                index=0,
                reason=f"caliber change [{change['date']}]: {change['description']}",
                original="",
            ))

    if actions:
        result["_caliber_warnings"] = [a.reason for a in actions]

    return result, actions


def handle_missing_fields(
    data: dict,
    data_type: str,
    required_fields: Optional[list[str]] = None,
) -> tuple[dict, list[CleaningAction]]:
    """缺失值处理与数据等级降级。

    检查必需字段是否缺失，缺失严重时降级 data_grade。
    """
    actions: list[CleaningAction] = []
    result = dict(data)
    inner = result.get("data", {})
    if not isinstance(inner, dict):
        inner = {}

    _REQUIRED_BY_TYPE: dict[str, list[str]] = {
        "basis": ["spot_price"],
        "warrant": ["total"],
        "position_ranking": ["net_long", "long_volume", "short_volume"],
        "fund_flow": ["total_oi", "long_short_ratio"],
        "inventory": ["inventory"],
    }

    fields = required_fields or _REQUIRED_BY_TYPE.get(data_type, [])

    missing = [f for f in fields if f not in inner or inner.get(f) is None]
    for f in missing:
        actions.append(CleaningAction(
            action="marked",
            field=f,
            index=0,
            reason=f"missing required field '{f}' for {data_type}",
            original="",
        ))

    # 缺失超阈值自动降级
    if fields and len(missing) / len(fields) > 0.5:
        grade = result.get("data_grade", "")
        result["data_grade"] = "DEGRADED"
        if grade and grade not in ("DEGRADED", "UNAVAILABLE"):
            actions.append(CleaningAction(
                action="marked",
                field="data_grade",
                index=0,
                reason=f"downgraded due to {len(missing)}/{len(fields)} missing fields",
                original=grade,
            ))

    result["data"] = inner
    return result, actions


def track_revision(
    data: dict,
    data_type: str,
) -> tuple[dict, list[CleaningAction]]:
    """修订版追踪。

    为数据添加版本标记和修订追踪信息。
    """
    actions: list[CleaningAction] = []
    result = dict(data)
    inner = result.get("data", {})
    if not isinstance(inner, dict):
        inner = {}

    today = _today_str()
    inner["_revision"] = {
        "tracked_at": today,
        "version": "v1",
        "source": result.get("data_grade", "PRIMARY"),
    }

    result["data"] = inner
    return result, actions


# ═══════════════════════════════════════════════════════════════
#  统一入口
# ═══════════════════════════════════════════════════════════════

def clean_fundamental_snapshot(
    data: dict,
    data_type: str,
    symbol: str = "",
) -> tuple[dict, CleaningReport]:
    """统一基本面快照清洗入口。

    Args:
        data: 基本面数据 dict（含 ``data`` / ``summary`` / ``data_grade``）。
        data_type: 数据类型，如 ``"basis"``, ``"warrant"`` 等。
        symbol: 品种代码，用于口径检测。

    Returns:
        (cleaned_data, report)。
    """
    actions: list[CleaningAction] = []
    result = dict(data)

    # 1. 缺失字段检查
    result, ma_actions = handle_missing_fields(result, data_type)
    actions.extend(ma_actions)

    # 2. 值有效性校验
    result, vs_actions = validate_snapshot_values(result, data_type, symbol)
    actions.extend(vs_actions)

    # 3. 新鲜度评分
    result, fr_actions = rate_freshness(result, data_type, symbol)
    actions.extend(fr_actions)

    # 4. 口径变更检测
    result, cc_actions = detect_caliber_change(result, data_type, symbol)
    actions.extend(cc_actions)

    # 5. 修订追踪
    result, tr_actions = track_revision(result, data_type)
    actions.extend(tr_actions)

    report = CleaningReport(cleaning_id="", actions=actions)
    return result, report
