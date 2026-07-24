"""
经验库 Schema — Et 逐案例记录 + Gt 全局蒸馏模式（v1.0 · 2026-07-22 MemoHarness 集成）

目的：
  为 FDT 辩论系统建立双层经验库的结构化 Schema。
  Et（ExecutionRecord）记录每轮辩论的完整执行上下文、Harness 配置和结果。
  Gt（DistilledPattern）存储从 Et 中蒸馏出的全局 Harness 调优模式。

用法：
  from contracts.experience_schema import (
      ExecutionRecord, DistilledPattern,
      ADX_RANGE, VOLATILITY_REGIME, FRESHNESS_LEVEL, SIGNAL_QUALITY,
      PATTERN_STATUS, validate_execution_record, validate_distilled_pattern,
  )
"""

from typing import Literal, Optional, TypedDict

# ── 枚举类型 ──

ADX_RANGE = Literal["low", "medium", "high"]       # <20 / 20-40 / >40
VOLATILITY_REGIME = Literal["low", "normal", "high"]
FRESHNESS_LEVEL = Literal["fresh", "acceptable", "stale"]
SIGNAL_QUALITY = Literal["actionable", "borderline", "skip"]
PATTERN_STATUS = Literal["staging", "confirmed", "deprecated"]
PATTERN_TYPE = Literal["success", "failure"]


# ── Et: 任务条件 ──

class TaskConditions(TypedDict, total=False):
    """辩论任务条件 — 用于相似案例检索"""
    symbol: str                                  # 品种代码
    adx_range: ADX_RANGE                         # ADX 区间
    volatility_regime: VOLATILITY_REGIME           # 波动率环境
    data_sources_available: list[str]             # 可用数据源列表
    data_freshness_level: FRESHNESS_LEVEL         # 数据新鲜度等级
    debate_divergence: float                      # 多空分歧度 (0.0-1.0)


# ── Et: Harness 配置快照 ──

class HarnessConfigSnapshot(TypedDict, total=False):
    """本轮实际使用的六维 Harness 配置快照"""
    d1_context: dict                             # 上下文组装参数
    d3_generation: dict                          # 解码控制参数
    d4_orchestration: dict                        # 编排参数
    d5_memory: dict                              # 记忆管理参数


# ── Et: 执行结果 ──

class ExecutionResult(TypedDict, total=False):
    """辩论执行结果"""
    success: bool                                # 是否成功完成
    verdict_direction: str                        # 裁决方向 (bullish/bearish/neutral)
    verdict_confidence: float                     # 裁决置信度 (0.0-1.0)
    signal_quality: SIGNAL_QUALITY                # 信号质量评级
    cost_tokens: int                              # Token 消耗
    duration_seconds: float                       # 耗时（秒）


# ── Et: 诊断信息 ──

class DiagnosisInfo(TypedDict, total=False):
    """失败诊断"""
    failure_step: str                             # 失败步骤
    failure_agent: str                            # 失败 Agent
    root_cause: str                               # 根因
    resolution: str                               # 解决方式


# ── Et: 完整记录 ──

class ExecutionRecord(TypedDict):
    """逐案例执行记录 — 对应 MemoHarness 的 Et"""
    trace_id: str                                # 全链路追踪 ID
    loop_id: str                                  # 循环 ID ("daily-debate")
    timestamp: str                                # ISO 8601 时间戳
    task_conditions: TaskConditions               # 任务条件
    harness_config: HarnessConfigSnapshot        # Harness 配置快照
    result: ExecutionResult                       # 执行结果
    diagnosis: Optional[DiagnosisInfo]            # 诊断信息（可选）


# ── Gt: 蒸馏模式 ──

class DistilledPattern(TypedDict):
    """全局蒸馏模式 — 对应 MemoHarness 的 Gt"""
    pattern_id: str                               # "P001"
    pattern_type: PATTERN_TYPE                     # success / failure
    created_at: str                                # ISO 8601
    last_updated: str                              # ISO 8601
    conditions: dict                               # 匹配条件
    config_delta: dict                              # 推荐的配置修正
    confidence: float                               # 0.0-1.0
    sample_count: int                               # 支撑案例数
    success_rate: float                              # 匹配案例中成功率
    source_trace_ids: list[str]                    # 支撑此模式的 Et trace_id 列表
    status: PATTERN_STATUS                           # staging / confirmed / deprecated


# ── 验证函数 ──

class ValidationError(Exception):
    """Schema 验证失败"""
    pass


def validate_execution_record(record: dict) -> list[str]:
    """验证 ExecutionRecord 完整性，返回错误列表（空列表=通过）"""
    errors = []
    required_fields = ["trace_id", "loop_id", "timestamp", "task_conditions", "harness_config", "result"]
    for f in required_fields:
        if f not in record:
            errors.append(f"缺少必填字段: {f}")

    if "trace_id" in record and not record["trace_id"]:
        errors.append("trace_id 不能为空")
    if "result" in record and "signal_quality" in record.get("result", {}):
        valid_qualities = ("actionable", "borderline", "skip")
        if record["result"]["signal_quality"] not in valid_qualities:
            errors.append(f"signal_quality 必须是 {valid_qualities} 之一")
    return errors


def validate_distilled_pattern(pattern: dict) -> list[str]:
    """验证 DistilledPattern 完整性，返回错误列表（空列表=通过）"""
    errors = []
    required_fields = ["pattern_id", "pattern_type", "conditions", "config_delta",
                       "confidence", "sample_count", "status"]
    for f in required_fields:
        if f not in pattern:
            errors.append(f"缺少必填字段: {f}")

    if "sample_count" in pattern and pattern["sample_count"] < 1:
        errors.append("sample_count 必须 >= 1")
    if "confidence" in pattern:
        c = pattern["confidence"]
        if not (0.0 <= c <= 1.0):
            errors.append("confidence 必须在 [0.0, 1.0] 范围内")
    if "status" in pattern:
        valid_statuses = ("staging", "confirmed", "deprecated")
        if pattern["status"] not in valid_statuses:
            errors.append(f"status 必须是 {valid_statuses} 之一")
    return errors
