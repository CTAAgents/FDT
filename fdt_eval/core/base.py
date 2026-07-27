"""
Eval Framework 核心数据类型 — EvalCase 基类 + EvalResult + EvalContext。

本模块无外部依赖，不引用 fdt_langgraph / scripts 等业务模块。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# ── 类型字面量 ──

EvalStatus = Literal["PASS", "FAIL", "ERROR", "SKIP"]
EvalStage = Literal["runtime", "post_hoc", "gate", "evolution", "meta"]
EvalSeverity = Literal["block", "warn", "info"]
DataCost = Literal["low", "medium", "high"]


# ── 数据类型 ──


@dataclass
class EvalMetric:
    """单个维度的量化指标。"""
    name: str
    value: float
    threshold: float | None = None
    unit: str = ""


@dataclass
class EvalAction:
    """评估结果触发的闭环动作配置。"""
    severity: EvalSeverity
    on_fail: str                     # "block_commit" / "log_gap" / "trigger_retrain" / "notify"
    on_pass: str | None = None       # "auto_update_doc" / None


@dataclass
class EvalResult:
    """统一的评估结果契约 — 所有 EvalCase.run() 必须返回此类型。"""
    case_id: str
    trace_id: str
    stage: EvalStage
    status: EvalStatus
    score: float                     # 0.0 - 1.0
    metrics: list[EvalMetric]
    detail: str                      # 单行摘要
    raw: dict | None = None
    action: EvalAction | None = None
    duration_ms: float = 0.0
    cache_hit: bool = False
    timestamp: datetime = field(default_factory=datetime.now)
    version: str = "1.0"


@dataclass
class EvalContext:
    """评估上下文，由 Runner 在 run() 时注入。"""
    trace_id: str
    workspace: str | None = None
    overrides: dict = field(default_factory=dict)


# ── 基类 ──


class EvalCase(ABC):
    """所有评估用例的抽象基类。

    子类必须定义类属性:
        case_id:    全局唯一标识，如 "runtime.quality_inspector.p3_5"
        stage:      所属阶段
        description: 简短说明
        weight:     聚合权重 (默认 1.0)
        threshold:  通过阈值 (默认 0.9)
        action:     闭环动作 (可选)
        cache_ttl:  缓存秒数 (0=永不缓存)
        data_cost:  数据成本标签 (low/medium/high)
        depends_on: 依赖的文件 glob (用于缓存判断)
    """

    # 注册元数据
    case_id: str = ""
    stage: EvalStage = "runtime"
    description: str = ""
    weight: float = 1.0
    threshold: float = 0.9
    action: EvalAction | None = None

    # 缓存/增量
    cache_ttl: int = 0
    data_cost: DataCost = "low"
    depends_on: list[str] = []  # 依赖的文件 glob (用于缓存判断)

    @abstractmethod
    def run(self, context: EvalContext) -> EvalResult:
        """执行评估，返回 EvalResult。"""
        ...


@dataclass
class EvalReport:
    """一次 run() 调用的完整报告。"""
    profile: str
    context: EvalContext
    results: list[EvalResult]
    duration_ms: float = 0.0
    aggregate: dict | None = None      # 聚合记分结果 (§6)
