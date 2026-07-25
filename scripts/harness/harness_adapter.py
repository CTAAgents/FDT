"""
案例适配引擎 — Phase C1
=======================
在辩论启动前，基于当前任务条件检索相似案例和全局模式，自动适配 Harness 配置。

用法:
    from scripts.harness_adapter import (
        adapt_harness, search_similar_cases, apply_config_delta,
        clamp_config,
    )
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 安全边界（支持嵌套路径 "dimension.field"）──

SAFETY_BOUNDS = {
    "d3_generation.debater_temp": (0.1, 0.8),
    "d3_generation.judge_temp": (0.1, 0.8),
    "d4_orchestration.debate_rounds": (2, 10),
    "d1_context.max_evidence_items": (3, 20),
    "d5_memory.history_turns": (1, 10),
}

# 默认配置
DEFAULT_CONFIG = {
    "d1_context": {"max_evidence_items": 5},
    "d3_generation": {"debater_temp": 0.4, "judge_temp": 0.2},
    "d4_orchestration": {"debate_rounds": 6},
    "d5_memory": {"history_turns": 3},
}


def _matches_conditions(
    task_conditions: dict,
    pattern_conditions: dict,
) -> bool:
    """检查任务条件是否匹配模式的匹配条件"""
    for dim, allowed_values in pattern_conditions.items():
        tc_value = task_conditions.get(dim)
        if tc_value is None:
            return False
        if tc_value not in allowed_values:
            return False
    return True


def _load_confirmed_patterns(patterns_dir: Path) -> list[dict]:
    """加载所有 confirmed 状态的 Gt 模式"""
    if not patterns_dir.exists():
        return []
    patterns = []
    for f in patterns_dir.glob("*.json"):
        pattern = json.loads(f.read_text(encoding="utf-8"))
        if pattern.get("status") == "confirmed":
            patterns.append(pattern)
    return patterns


def _load_recent_records(records_dir: Path, limit: int = 20) -> list[dict]:
    """加载最近 N 条 Et 记录（按时间戳降序）"""
    if not records_dir.exists():
        return []
    records = []
    for f in records_dir.glob("*.json"):
        if f.name == "INDEX.json":
            continue
        records.append(json.loads(f.read_text(encoding="utf-8")))
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records[:limit]


def _condition_similarity(tc1: dict, tc2: dict) -> float:
    """计算两个任务条件的相似度 (0.0-1.0)"""
    dims = ["adx_range", "volatility_regime", "data_freshness_level"]
    matches = sum(1 for d in dims if tc1.get(d) == tc2.get(d))
    return matches / len(dims)


def search_similar_cases(
    task_conditions: dict,
    records_dir: Path,
    threshold: float = 0.5,
) -> list[tuple[dict, float]]:
    """检索与当前任务条件相似的 Et 案例

    Returns:
        [(record, similarity_score), ...] 按 similarity 降序
    """
    records = _load_recent_records(records_dir)
    scored = []
    for r in records:
        sim = _condition_similarity(task_conditions, r.get("task_conditions", {}))
        if sim >= threshold:
            scored.append((r, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _deep_get(d: dict, keys: list[str], default=None):
    """深度获取嵌套字典值"""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


def _deep_set(d: dict, keys: list[str], value):
    """深度设置嵌套字典值"""
    for key in keys[:-1]:
        if key not in d:
            d[key] = {}
        d = d[key]
    d[keys[-1]] = value


def apply_config_delta(
    base_config: dict,
    delta: dict,
) -> dict:
    """将 config_delta 应用到基准配置上

    Args:
        base_config: 基准 Harness 配置（会被深拷贝）
        delta: 配置修正（如 {"d3_generation": {"debater_temp": 0.5}}）

    Returns:
        修改后的配置（新对象，不修改 base_config）
    """
    import copy
    result = copy.deepcopy(base_config)
    for dimension, fields in delta.items():
        for field, value in fields.items():
            _deep_set(result, [dimension, field], value)
    return result


def clamp_config(config: dict, bounds: dict = SAFETY_BOUNDS) -> list[dict]:
    """将配置值限制在安全边界内

    bounds 的 key 格式为 "dimension.field"（如 "d3_generation.debater_temp"）

    Returns:
        被修改的字段列表（每个元素包含 path, from, to）
    """
    clamped = []
    for path_key, (lo, hi) in bounds.items():
        parts = path_key.split(".", 1)
        if len(parts) != 2:
            continue
        dim, field = parts
        value = _deep_get(config, [dim, field])
        if value is None or not isinstance(value, (int, float)):
            continue
        if value < lo:
            _deep_set(config, [dim, field], lo)
            clamped.append({"path": path_key, "from": value, "to": lo})
        elif value > hi:
            _deep_set(config, [dim, field], hi)
            clamped.append({"path": path_key, "from": value, "to": hi})
    return clamped


def adapt_harness(
    task_conditions: dict,
    patterns_dir: Path,
    records_dir: Path,
    base_config: Optional[dict] = None,
    shadow_mode: bool = False,
) -> dict:
    """基于任务条件适配 Harness 配置

    Args:
        task_conditions: 当前辩论任务条件
        patterns_dir: Gt 模式目录
        records_dir: Et 记录目录
        base_config: 基准配置（默认使用 DEFAULT_CONFIG）
        shadow_mode: 影子模式 — 只记录不应用

    Returns:
        适配结果，包含：
        - adapted_config: 适配后配置
        - matched_patterns: 匹配的 pattern_id 列表
        - matched_cases: 匹配的相似案例数
        - adaptations: 适配变更列表
        - clamped: 边界修正列表
        - applied: 是否实际应用
    """
    if base_config is None:
        base_config = DEFAULT_CONFIG

    config = apply_config_delta(base_config, {})
    adaptations = []
    matched_patterns = []
    matched_cases_count = 0

    # 步骤 1：检索 Gt
    confirmed = _load_confirmed_patterns(patterns_dir)
    for pattern in confirmed:
        if _matches_conditions(task_conditions, pattern.get("conditions", {})):
            matched_patterns.append(pattern["pattern_id"])
            delta = pattern.get("config_delta", {})
            config = apply_config_delta(config, delta)
            for dim, fields in delta.items():
                for field, value in fields.items():
                    adaptations.append({
                        "dimension": dim,
                        "field": field,
                        "value": value,
                        "reason": f"模式 {pattern['pattern_id']} 推荐",
                    })

    # 步骤 2：检索 Et
    similar = search_similar_cases(task_conditions, records_dir)
    matched_cases_count = len(similar)

    if similar:
        # 计算相似案例中各维度的平均配置值
        from collections import defaultdict
        dim_field_values = defaultdict(list)
        for record, sim in similar:
            hc = record.get("harness_config", {})
            for dim, fields in hc.items():
                for field, value in fields.items():
                    if isinstance(value, (int, float)):
                        dim_field_values[(dim, field)].append(value)

        # 对一致性高于 70% 的维度微调
        for (dim, field), values in dim_field_values.items():
            if len(values) < len(similar) * 0.7:
                continue
            avg = sum(values) / len(values)
            current = _deep_get(config, [dim, field])
            if current is not None and abs(avg - current) > 0.05:
                config = apply_config_delta(config, {dim: {field: round(avg, 4)}})
                adaptations.append({
                    "dimension": dim,
                    "field": field,
                    "value": round(avg, 4),
                    "reason": f"相似案例一致推荐 ({len(values)}/{len(similar)} 案例一致)",
                })

    # 步骤 3：边界检查
    clamped = clamp_config(config)
    if clamped:
        adaptations.extend([
            {
                "dimension": c["path"].split(".")[0],
                "field": c["path"].split(".")[1],
                "from": c["from"],
                "to": c["to"],
                "reason": "安全边界修正",
            }
            for c in clamped
        ])

    # 步骤 4：影子模式处理
    if shadow_mode:
        config = base_config  # 影子模式不实际应用

    return {
        "adapted_config": config,
        "matched_patterns": matched_patterns,
        "matched_cases": matched_cases_count,
        "adaptations": adaptations,
        "clamped": clamped,
        "applied": not shadow_mode,
    }


def log_adaptation(
    result: dict,
    trace_id: str,
    symbol: str,
    log_dir: Path,
) -> Path:
    """记录适配日志到文件"""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_entry = {
        "trace_id": trace_id,
        "symbol": symbol,
        "timestamp": datetime.now().isoformat(),
        "matched_patterns": result["matched_patterns"],
        "matched_cases": result["matched_cases"],
        "adaptations": result["adaptations"],
        "clamped": result["clamped"],
        "applied": result["applied"],
    }
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{symbol}_{date_str}_{trace_id[:4]}_adaptation.json"
    filepath = log_dir / filename
    filepath.write_text(
        json.dumps(log_entry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return filepath
