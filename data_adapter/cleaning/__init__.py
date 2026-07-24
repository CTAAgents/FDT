"""数据清洗层 — K 线 + 基本面。

K 线清洗 ``clean_kline()`` 执行 5 道清洗：

1. OHLC 一致性校验（high≥low, close 在区间内, volume≥0）
2. 离群值检测（3σ 毛刺修复）
3. 复权处理（主力连续前复权）
4. 时间轴标准化（升序/去重/缺失标记）
5. 期货专项（交割月过滤 + 涨跌停封板标记）

基本面清洗 ``clean_fundamental()`` 执行 5 道清洗：

1. 缺失字段检查（必需字段完整性）
2. 值有效性校验（负值/越界/交叉一致性）
3. 新鲜度评分（data_date 时效性分级）
4. 统计口径变更检测（已知规则调整事件）
5. 修订版追踪（版本标注）

每道清洗产出一个清洗报告（CleaningReport），透传至下游。
"""

from __future__ import annotations

from data_adapter.cleaning.ohlc import clean_ohlc, OHLCCleaner
from data_adapter.cleaning.outlier import clean_outliers, OutlierDetector
from data_adapter.cleaning.adjustment import clean_adjustment, AdjustmentEngine
from data_adapter.cleaning.timeline import clean_timeline, TimelineCleaner
from data_adapter.cleaning.futures import clean_futures, FuturesCleaner
from data_adapter.cleaning.fundamental import (
    clean_fundamental_snapshot,
    validate_snapshot_values,
    rate_freshness,
    handle_missing_fields,
    detect_caliber_change,
    track_revision,
)
from data_adapter.types import CleaningReport, CleaningAction, KlineBar

__all__ = [
    "clean_kline",
    "clean_fundamental",
    "CleaningReport",
]

# ── 载入默认配置，各模块可独立开关 ──
_DEFAULT_CONFIG = {
    "enable_ohlc": True,
    "enable_outlier": True,
    "enable_adjustment": True,
    "enable_timeline": True,
    "enable_futures": True,
    "enable_fundamental": True,
    "outlier_z_threshold": 3.0,
    "adjust_method": "forward",  # "forward" | "none"
    "delivery_exclude_days": 15,
    # 传入下游需要的品种代码
    "symbol": "",
}

_FUNDAMENTAL_TYPES = {"basis", "warrant", "position_ranking", "fund_flow", "inventory"}


def clean_kline(
    bars: list[dict],
    config: dict | None = None,
) -> tuple[list[dict], CleaningReport]:
    """对原始 K 线执行全链路清洗。

    Args:
        bars: 原始 K 线列表（每项含 date/open/high/low/close/volume/open_interest）。
        config: 清洗配置，覆盖 ``_DEFAULT_CONFIG``。

    Returns:
        (cleaned_bars, report) — 清洗后的 K 线 + 清洗报告。
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    report = CleaningReport(cleaning_id="", actions=[])
    changed = list(bars)

    if cfg["enable_timeline"]:
        changed, tl_report = clean_timeline(changed)
        report.actions.extend(tl_report.actions)

    if cfg["enable_ohlc"]:
        changed, ohlc_report = clean_ohlc(changed)
        report.actions.extend(ohlc_report.actions)

    if cfg["enable_outlier"]:
        z = cfg["outlier_z_threshold"]
        changed, outlier_report = clean_outliers(changed, z_threshold=z)
        report.actions.extend(outlier_report.actions)

    if cfg["enable_adjustment"]:
        method = cfg["adjust_method"]
        changed, adj_report = clean_adjustment(changed, method=method)
        report.actions.extend(adj_report.actions)

    if cfg["enable_futures"]:
        sym = cfg.get("symbol", "")
        days = cfg.get("delivery_exclude_days", 15)
        changed, futures_report = clean_futures(changed, symbol=sym, delivery_exclude_days=days)
        report.actions.extend(futures_report.actions)

    # 清洗后再次确保升序
    changed.sort(key=lambda b: str(b.get("date", "")))

    report.cleaning_id = f"cln-{len(changed)}b-{len(report.actions)}a"
    return changed, report


def clean_fundamental(
    data: dict,
    data_type: str,
    symbol: str = "",
    enabled: bool = True,
) -> tuple[dict, CleaningReport]:
    """对基本面快照数据执行全链路清洗。

    Args:
        data: 基本面数据 dict（含 ``data`` / ``summary`` / ``data_grade``）。
        data_type: 数据类型，如 ``"basis"``, ``"warrant"`` 等。
        symbol: 品种代码，用于口径检测。
        enabled: 是否启用清洗（关闭时原样返回+空报告）。

    Returns:
        (cleaned_data, report)。
    """
    if not enabled:
        return dict(data), CleaningReport(cleaning_id="", actions=[])

    return clean_fundamental_snapshot(data, data_type=data_type, symbol=symbol)


def clean_fundamental_data(
    fdc_data: dict,
    cleaning_enabled: bool = True,
) -> dict:
    """对 ``DebateState.fdc_data`` 中所有基本面字段执行清洗。

    遍历每个品种的 ``fdc_data[symbol]``，对其中的
    ``basis`` / ``warrant`` / ``position_ranking`` / ``fund_flow`` 字段执行
    ``clean_fundamental()``，清洗报告附着在字段的 ``_cleaning`` 键中。

    Args:
        fdc_data: P2.5 预采集的 fdc_data dict。
        cleaning_enabled: 是否启用清洗。

    Returns:
        清洗后的 fdc_data。
    """
    if not cleaning_enabled:
        return dict(fdc_data)

    result = {}
    for sym, sym_data in fdc_data.items():
        cleaned_sym = dict(sym_data)
        for dtype in _FUNDAMENTAL_TYPES:
            raw = cleaned_sym.get(dtype)
            if isinstance(raw, dict) and raw.get("data_grade") != "UNAVAILABLE":
                cleaned, report = clean_fundamental(raw, data_type=dtype, symbol=sym, enabled=True)
                cleaned["_cleaning"] = {
                    "total_actions": report.total_actions,
                    "actions": [
                        {"action": a.action, "field": a.field, "reason": a.reason}
                        for a in report.actions
                    ],
                }
                cleaned_sym[dtype] = cleaned
        result[sym] = cleaned_sym
    return result
