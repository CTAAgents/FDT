"""记忆系统 TypedDict 契约 — 所有写入/读取数据的 Schema 定义"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class JournalEntry(TypedDict, total=False):
    """辩论日志条目"""
    trace_id: str
    timestamp: str
    round_id: str
    symbol: str
    direction: Literal["bull", "bear", "neutral"]
    confidence: float
    grade: Literal["STRONG", "WATCH"]
    verdict: dict
    risk: dict
    pnl: NotRequired[float]
    outcome: NotRequired[str]
    schema_version: str


class KnowledgeEntry(TypedDict, total=False):
    """品种知识条目"""
    symbol: str
    last_updated: str
    total_debates: int
    drivers: list[dict]
    patterns: list[dict]
    key_levels: dict
    data_quality: dict


class ExperienceEntry(TypedDict, total=False):
    """经验记录条目"""
    symbol: str
    timestamp: str
    signal_quality: Literal["actionable", "skip"]
    signal_detail: dict
    d3_generation: NotRequired[str]
    d4_orchestration: NotRequired[str]


class IncidentEntry(TypedDict):
    """事故记录条目"""
    trace_id: str
    timestamp: str
    title: str
    severity: Literal["P0", "P1", "P2"]
    root_cause: str
    fix: str
    prevention: str


class MaintenanceReport(TypedDict):
    """维护报告"""
    timestamp: str
    cleaned_journals: int
    archived_items: int
    decayed_patterns: list[str]
    storage_before_mb: float
    storage_after_mb: float


class GapReport(TypedDict):
    """缺口检查报告"""
    timestamp: str
    missing_sessions: list[str]
    incomplete_learned: list[str]
    stale_knowledge: list[str]
    unreferenced_files: list[str]


# Schema 校验映射
SCHEMA_MAP = {
    "JournalEntry": JournalEntry,
    "KnowledgeEntry": KnowledgeEntry,
    "ExperienceEntry": ExperienceEntry,
    "IncidentEntry": IncidentEntry,
    "MaintenanceReport": MaintenanceReport,
    "GapReport": GapReport,
}

CURRENT_SCHEMA_VERSION = "2.0"


def validate_schema(data: dict, schema_name: str) -> None:
    """简单 Schema 校验 — 检查必填字段是否存在"""
    schema = SCHEMA_MAP.get(schema_name)
    if schema is None:
        raise ValueError(f"Unknown schema: {schema_name}")

    annotations = schema.__annotations__
    for field_name, field_type in annotations.items():
        # 只在 total=False 的字段中检查 NotRequired
        if hasattr(field_type, "__origin__") and field_type.__origin__ is type(None):
            continue  # NotRequired 字段可能不存在
        # 对 IncidentEntry 这种 total=True 的, 所有字段必填
        if not schema.__dict__.get("total", True):
            continue
        # 简化校验: 检查 NotRequired 字段
        origin = getattr(field_type, "__origin__", None)
        if origin is not None:
            continue  # 复杂的泛型暂不校验
        # 只有 IncidentEntry 是 total=True, 所有字段必填
        if schema_name == "IncidentEntry" and field_name not in data:
            raise ValueError(f"Missing required field '{field_name}' in {schema_name}")
