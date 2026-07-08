"""子 skill 输出版本迁移工具，编排层在 parse_fence 后选择性调用"""

from typing import Any


def migrate_bull_v20_to_v21(data: dict) -> dict:
    """2.0 → 2.1：增加 rebuttal_quality_score 字段"""
    if data.get("version") != "2.0":
        return data
    data["version"] = "2.1"
    data["rebuttal_quality_score"] = None
    return data


def migrate_risk_v20_to_v21(data: dict) -> dict:
    """2.0 → 2.1：增加 risk_level 字段"""
    if data.get("version") != "2.0":
        return data
    data["version"] = "2.1"
    data["risk_level"] = "medium"
    return data


def migrate_risk_v21_to_v20(data: dict) -> dict:
    """2.1 → 2.0：移除新字段，兼容旧下游"""
    if data.get("version") != "2.1":
        return data
    data.pop("risk_level", None)
    data["version"] = "2.0"
    return data


# 注册迁移路径，编排层自动调用
MIGRATION_REGISTRY = {
    ("bull", "2.0", "2.1"): migrate_bull_v20_to_v21,
    ("risk", "2.0", "2.1"): migrate_risk_v20_to_v21,
    ("risk", "2.1", "2.0"): migrate_risk_v21_to_v20,
}

# v3.0 版本矩阵
VERSION_MATRIX = {
    "data_collection": ["2.0", "3.0"],
    "technical": ["2.0", "3.0"],
    "chain_analysis": ["2.0", "3.0"],
    "fundamental_state": ["1.0"],
    "bull": ["2.0", "3.0"],
    "bear": ["2.0", "3.0"],
    "debate": ["2.0", "2.1", "3.0"],
    "evidence_brief": ["1.0"],
    "judge": ["2.0", "3.0"],
    "risk": ["2.0", "2.1", "3.0"],
    "trading_plan": ["2.0", "3.0"],
    "team_decision": ["1.0"],
}


def apply_migration(skill_type: str, data: dict, target_version: str) -> dict:
    """按需将 data 迁移到 target_version"""
    current = data.get("version", "2.0")
    if current == target_version:
        return data
    key = (skill_type, current, target_version)
    if key in MIGRATION_REGISTRY:
        return MIGRATION_REGISTRY[key](data)
    raise ValueError(f"No migration path from {current} to {target_version} for {skill_type}")
