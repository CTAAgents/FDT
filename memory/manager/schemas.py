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


class VerdictRecord(TypedDict, total=False):
    """裁决结果记录 — 与事后实际走势配对"""
    trace_id: str
    timestamp: str
    symbol: str
    direction: Literal["bull", "bear", "neutral"]
    confidence: float
    grade: Literal["STRONG", "WATCH"]
    entry_price: NotRequired[float]
    target_price: NotRequired[float]
    stop_loss_price: NotRequired[float]
    position_pct: NotRequired[float]
    risk_color: NotRequired[str]
    risk_approved: NotRequired[bool]
    outcome: NotRequired[str]
    outcome_actual: NotRequired[str]
    outcome_pnl: NotRequired[float]
    days_to_outcome: NotRequired[int]
    regime: NotRequired[str]
    schema_version: str


class CalibrationBucket(TypedDict):
    """置信度校准桶"""
    bucket_label: str
    low: float
    high: float
    count: int
    correct: int
    accuracy: float


class CalibrationResult(TypedDict):
    """校准结果"""
    timestamp: str
    symbol: str
    buckets: list[CalibrationBucket]
    total_verdicts: int
    overall_accuracy: float
    calibration_error: float


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


class PatchCondition(TypedDict, total=False):
    """补丁适用条件"""
    applicable_regime: list[str]     # 适用市场状态（空=全部适用）
    inapplicable_regime: list[str]   # 不适用状态
    valid_from: str                  # 生效日期 YYYY-MM-DD
    valid_until: str | None          # 失效日期（None=长期有效）


class PatchEntry(TypedDict, total=False):
    """EvoMem 补丁记忆条目 — 记录记忆/规则/知识的变更历史

    新增字段（EvoMem 风格）:
        patch_id: 全局唯一补丁 ID（如 "patch-20260726-001"）
        domain: 领域标签（多级，用 | 分隔），如 "生猪|止损规则"
        pre_state: 变更前的状态描述
        post_state: 变更后的状态描述
        rationale: 变更理由
        evidence: 支撑该变更的证据链
        conditions: 版本适用条件

    继承自 session_memory 的标准字段:
        intent / actions / outcome / learned / message_summary_time / message_id
    """
    patch_id: str
    domain: str
    pre_state: str
    post_state: str
    rationale: str
    evidence: list[str]
    conditions: PatchCondition

    # 标准 session_memory 字段（均可选）
    trace_id: NotRequired[str]
    intent: NotRequired[str]
    actions: NotRequired[list[str]]
    outcome: NotRequired[str]
    learned: NotRequired[str]
    message_summary_time: NotRequired[str]
    message_id: NotRequired[str]


# Schema 校验映射
SCHEMA_MAP = {
    "JournalEntry": JournalEntry,
    "KnowledgeEntry": KnowledgeEntry,
    "ExperienceEntry": ExperienceEntry,
    "IncidentEntry": IncidentEntry,
    "VerdictRecord": VerdictRecord,
    "CalibrationBucket": CalibrationBucket,
    "CalibrationResult": CalibrationResult,
    "MaintenanceReport": MaintenanceReport,
    "GapReport": GapReport,
    "PatchEntry": PatchEntry,
}

CURRENT_SCHEMA_VERSION = "2.2"


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
