"""
模式蒸馏引擎 — Phase B2
=======================
从 Et 记录中自动蒸馏全局模式（Gt），形成可复用的 Harness 调优知识。

用法:
    from scripts.pattern_distiller import (
        distill_patterns, cluster_records, extract_config_delta,
    )
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from contracts.experience_schema import validate_distilled_pattern


# ── 常量 ──

MIN_SAMPLE_COUNT = 5       # 模式最少支撑案例数
CONFIDENCE_THRESHOLD = 0.3  # 最低置信度
MAX_PATTERNS = 50          # 模式库上限

# 聚类维度
CLUSTER_DIMS = ["adx_range", "volatility_regime", "data_freshness_level"]


def _load_records(records_dir: Path) -> list[dict]:
    """加载所有 Et 记录"""
    records = []
    if not records_dir.exists():
        return records
    for f in records_dir.glob("*.json"):
        if f.name == "INDEX.json":
            continue
        records.append(json.loads(f.read_text(encoding="utf-8")))
    return records


def _cluster_key(record: dict) -> tuple:
    """生成聚类键：基于三维条件组合"""
    tc = record.get("task_conditions", {})
    return tuple(tc.get(dim, "unknown") for dim in CLUSTER_DIMS)


def cluster_records(records: list[dict]) -> dict[tuple, list[dict]]:
    """按三维条件组合聚类

    Returns:
        { (adx_range, volatility_regime, freshness_level): [record, ...] }
    """
    clusters = defaultdict(list)
    for r in records:
        key = _cluster_key(r)
        clusters[key].append(r)
    return dict(clusters)


def _avg_config_field(records: list[dict], dimension: str, field: str) -> Optional[float]:
    """计算一组记录中某个配置字段的平均值"""
    values = []
    for r in records:
        val = r.get("harness_config", {}).get(dimension, {}).get(field)
        if val is not None and isinstance(val, (int, float)):
            values.append(float(val))
    if not values:
        return None
    return sum(values) / len(values)


def extract_config_delta(
    success_records: list[dict],
    failure_records: list[dict],
    min_delta_ratio: float = 0.15,
) -> dict:
    """对比成功/失败组的 Harness 配置差异

    只提取差异比 >= min_delta_ratio 的配置项。
    """
    if not success_records or not failure_records:
        return {}

    delta = {}
    dimensions = set()
    for r in success_records + failure_records:
        dimensions.update(r.get("harness_config", {}).keys())

    for dim in dimensions:
        dim_delta = {}
        fields = set()
        for r in success_records + failure_records:
            fields.update(r.get("harness_config", {}).get(dim, {}).keys())

        for field in fields:
            s_val = _avg_config_field(success_records, dim, field)
            f_val = _avg_config_field(failure_records, dim, field)

            if s_val is not None and f_val is not None:
                base = max(abs(s_val), abs(f_val), 0.01)
                diff = abs(s_val - f_val) / base
                if diff >= min_delta_ratio:
                    dim_delta[field] = round(s_val, 4)

        if dim_delta:
            delta[dim] = dim_delta

    return delta


def _compute_confidence(
    sample_count: int,
    success_rate: float,
    delta_magnitude: float,
) -> float:
    """计算模式置信度 (0.0-1.0)

    综合三个因子：
    - 样本充足度 (0.0-0.4)
    - 成功率 (0.0-0.35)
    - 差异显著度 (0.0-0.25)
    """
    sample_score = min(sample_count / 20.0, 1.0) * 0.4
    success_score = success_rate * 0.35
    delta_score = min(delta_magnitude, 1.0) * 0.25
    return round(sample_score + success_score + delta_score, 4)


def _count_delta_fields(config_delta: dict) -> float:
    """计算差异字段数量作为显著度代理"""
    count = 0
    for dim_fields in config_delta.values():
        count += len(dim_fields)
    return min(count / 5.0, 1.0)


def _next_pattern_id(patterns_dir: Path) -> str:
    """生成下一个 pattern_id"""
    if not patterns_dir.exists():
        return "P001"
    existing = [f.stem for f in patterns_dir.glob("*.json")]
    max_num = 0
    for name in existing:
        if name.startswith("P"):
            try:
                num = int(name[1:])
                max_num = max(max_num, num)
            except ValueError:
                continue
    return f"P{max_num + 1:03d}"


def distill_patterns(
    records_dir: Path,
    patterns_dir: Path,
    min_sample: int = MIN_SAMPLE_COUNT,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    max_patterns: int = MAX_PATTERNS,
) -> list[dict]:
    """从 Et 记录蒸馏全局模式

    Args:
        records_dir: Et 记录目录
        patterns_dir: Gt 模式存储目录
        min_sample: 每个模式最少支撑案例数
        confidence_threshold: 最低置信度阈值
        max_patterns: 模式库上限

    Returns:
        新生成的 DistilledPattern 列表（未持久化）
    """
    records = _load_records(records_dir)
    clusters = cluster_records(records)
    new_patterns = []

    for cluster_key, clustered_records in clusters.items():
        # 分离成功/失败
        success = [r for r in clustered_records if r.get("result", {}).get("signal_quality") == "actionable"]
        failure = [r for r in clustered_records if r.get("result", {}).get("signal_quality") != "actionable"]

        total = len(success) + len(failure)
        if total < min_sample:
            continue

        success_rate = len(success) / total if total > 0 else 0

        # 提取配置差异（以成功案例的配置为推荐）
        config_delta = extract_config_delta(success, failure)
        if not config_delta:
            continue

        confidence = _compute_confidence(
            sample_count=total,
            success_rate=success_rate,
            delta_magnitude=_count_delta_fields(config_delta),
        )

        if confidence < confidence_threshold:
            continue

        pattern = {
            "pattern_id": _next_pattern_id(patterns_dir),
            "pattern_type": "success" if success_rate > 0.5 else "failure",
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "conditions": {
                "adx_range": [cluster_key[0]],
                "volatility_regime": [cluster_key[1]],
                "data_freshness_level": [cluster_key[2]],
            },
            "config_delta": config_delta,
            "confidence": confidence,
            "sample_count": total,
            "success_rate": round(success_rate, 4),
            "source_trace_ids": [r.get("trace_id", "")[:4] for r in clustered_records],
            "status": "staging",
        }

        errors = validate_distilled_pattern(pattern)
        if errors:
            continue

        new_patterns.append(pattern)

    # 上限控制
    if len(new_patterns) > max_patterns:
        new_patterns.sort(key=lambda p: p["confidence"] * p["sample_count"], reverse=True)
        new_patterns = new_patterns[:max_patterns]

    return new_patterns


def save_pattern(pattern: dict, patterns_dir: Path) -> Path:
    """持久化单条 Gt 模式到 JSON 文件"""
    patterns_dir.mkdir(parents=True, exist_ok=True)
    filepath = patterns_dir / f"{pattern['pattern_id']}.json"
    filepath.write_text(
        json.dumps(pattern, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return filepath