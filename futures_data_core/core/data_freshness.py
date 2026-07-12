"""数据新鲜度评估 [INDEPENDENT]。

根据 ``config/data_sources.yaml`` 中的阈值，对一次扫描结果做质量断路器判定。
纯计算，无网络/LLM 依赖。
"""

from __future__ import annotations

import os

import yaml

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
_FRESHNESS_PATH = os.path.join(_CONFIG_DIR, "data_sources.yaml")

# 阈值默认值（配置加载失败时兜底）
_DEFAULT_THRESHOLDS = {
    "min_scan_success_rate": 0.90,
    "min_bars_per_symbol": 30,
    "max_daily_age_sessions": 5,
    "max_subdaily_age_days": 7,
    "min_positive_volume_ratio": 0.50,
    "max_scan_duration_seconds": 120,
    "max_output_json_mb": 5,
    "max_retries": 3,
    "retry_interval_minutes": 5,
}


def _load_thresholds() -> dict:
    """读取新鲜度阈值；失败返回默认值。"""
    try:
        with open(_FRESHNESS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("freshness", _DEFAULT_THRESHOLDS)
    except (OSError, yaml.YAMLError):
        return dict(_DEFAULT_THRESHOLDS)


def evaluate(scan_result: dict) -> dict:
    """评估扫描结果是否满足新鲜度断路器。

    Args:
        scan_result: 包含以下键的字典（缺失键按最宽松处理）：
            ``total_symbols``, ``success_count``, ``bars_per_symbol`` (dict),
            ``max_daily_age_sessions``, ``max_subdaily_age_days``,
            ``positive_volume_ratio``, ``scan_duration_seconds``,
            ``output_json_mb``, ``retries``.

    Returns:
        ``{"passed": bool, "violations": list[str], "thresholds": dict}``。
    """
    t = _load_thresholds()
    violations: list[str] = []

    total = scan_result.get("total_symbols", 0)
    success = scan_result.get("success_count", 0)
    if total > 0:
        rate = success / total
        if rate < t["min_scan_success_rate"]:
            violations.append(
                f"扫描成功率 {rate:.2%} < 阈值 {t['min_scan_success_rate']:.2%}"
            )

    bars = scan_result.get("bars_per_symbol", {})
    if bars:
        min_bars = min(bars.values()) if bars else 0
        if min_bars < t["min_bars_per_symbol"]:
            violations.append(
                f"最少 K 线条数 {min_bars} < 阈值 {t['min_bars_per_symbol']}"
            )

    age_s = scan_result.get("max_daily_age_sessions")
    if age_s is not None and age_s > t["max_daily_age_sessions"]:
        violations.append(
            f"日线时效性 {age_s} 交易日 > 阈值 {t['max_daily_age_sessions']}"
        )

    age_d = scan_result.get("max_subdaily_age_days")
    if age_d is not None and age_d > t["max_subdaily_age_days"]:
        violations.append(
            f"子周期时效性 {age_d} 天 > 阈值 {t['max_subdaily_age_days']}"
        )

    pvr = scan_result.get("positive_volume_ratio")
    if pvr is not None and pvr < t["min_positive_volume_ratio"]:
        violations.append(
            f"有效成交量占比 {pvr:.2%} < 阈值 {t['min_positive_volume_ratio']:.2%}"
        )

    dur = scan_result.get("scan_duration_seconds")
    if dur is not None and dur > t["max_scan_duration_seconds"]:
        violations.append(
            f"扫描耗时 {dur}s > 阈值 {t['max_scan_duration_seconds']}s"
        )

    size = scan_result.get("output_json_mb")
    if size is not None and size > t["max_output_json_mb"]:
        violations.append(
            f"输出 JSON {size}MB > 阈值 {t['max_output_json_mb']}MB"
        )

    retries = scan_result.get("retries")
    if retries is not None and retries > t["max_retries"]:
        violations.append(
            f"重试次数 {retries} > 阈值 {t['max_retries']}"
        )

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "thresholds": t,
    }


def data_grade_from_age(daily_age_sessions: int) -> str:
    """根据日线时效返回数据等级名称 (L0-L5)。"""
    if daily_age_sessions <= 0:
        return "PRIMARY"
    if daily_age_sessions <= 1:
        return "FRESH"
    if daily_age_sessions <= 5:
        return "DAILY"
    if daily_age_sessions <= 20:
        return "CACHED"
    return "REFERENCE"
