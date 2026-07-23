"""
辩论输出质量校验 Schema — 明鉴秋质检标准（v1.0 · 2026-07-23）

目的：
  定义明鉴秋对 P3/P4/P5 各阶段 Agent 产出的数据质量校验标准。
  不合格数据退回重修，通过后进入下一阶段。

用法：
  validate_argument(data) → QualityReport
  validate_verdict(data) → QualityReport
  validate_risk(data) → QualityReport

质量等级:
  PASS / FAIL / SKIP
"""

from typing import TypedDict, Optional, Literal, Any


# ── 质量报告 ──

class QualityIssue(TypedDict, total=False):
    field: str
    message: str
    severity: Literal["error", "warning"]


class QualityReport(TypedDict, total=False):
    status: Literal["PASS", "FAIL", "SKIP"]
    issues: list[QualityIssue]
    passed: int
    failed: int
    skipped: int


# ── P3 论据 Schema ──

class ArgumentSchema(TypedDict, total=False):
    symbol: str
    arguments: list[str]
    confidence: float
    source_refs: list[str]


ARGUMENT_RULES = {
    "required_fields": ["symbol", "arguments", "confidence"],
    "field_types": {
        "symbol": str,
        "arguments": list,
        "confidence": (int, float),
    },
    "min_arguments": 1,
    "max_arguments": 10,
    "confidence_min": 0.0,
    "confidence_max": 1.0,
    "source_ref_required": False,  # 建议有，但不强制
}


# ── P4 闫判官裁决 Schema ──

class VerdictSchema(TypedDict, total=False):
    symbol: str
    direction: Literal["bull", "bear", "neutral"]
    confidence: str
    entry_price: float
    stop_loss: float
    target1: float
    target2: float
    adx: float
    atr: float
    reason: str


VERDICT_RULES = {
    "required_fields": [
        "symbol", "direction", "confidence",
        "entry_price", "stop_loss", "target1",
    ],
    "conditional_required": {           # 仅在非 neutral 方向时必填
        "fields": ["entry_price", "stop_loss", "target1"],
        "condition_key": "direction",
        "condition_values": ["bull", "bear"],
    },
    "field_types": {
        "symbol": str,
        "direction": str,
        "confidence": str,
        "entry_price": (int, float),
        "stop_loss": (int, float),
        "target1": (int, float),
    },
    "direction_valid": ["bull", "bear", "neutral"],
    "confidence_valid": ["高", "中", "低"],
    "entry_stop_min_spacing_pct": 0.3,    # 入场与止损最小间距 0.3%
    "take_profit_min_ratio": 1.2,          # 最小盈亏比 1.2
    "stop_loss_max_pct": 8.0,              # 止损最大幅度 8%
}


# ── P5 风控审核 Schema ──

class RiskSchema(TypedDict, total=False):
    symbol: str
    risk_level: Literal["green", "yellow", "red"]
    check_items: list[dict]
    conclusion: str


RISK_RULES = {
    "required_fields": ["symbol", "risk_level", "check_items", "conclusion"],
    "field_types": {
        "symbol": str,
        "risk_level": str,
        "check_items": list,
        "conclusion": str,
    },
    "risk_level_valid": ["green", "yellow", "red"],
    "min_check_items": 2,
}


# ── 自优化指标 ──

class PhaseTiming(TypedDict, total=False):
    phase: str
    symbol: str
    elapsed_seconds: float
    retry_count: int


class QualityMetrics(TypedDict, total=False):
    total_symbols: int
    passed_symbols: int
    failed_symbols: int
    total_retries: int
    max_retries_exceeded: list[str]       # 熔断的品种列表
    phase_timings: list[PhaseTiming]
    agent_failures: dict[str, int]        # {agent_name: failure_count}
