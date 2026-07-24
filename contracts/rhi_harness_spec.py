"""
RHI Harness 三层规范 — 代表 agent loop 的 prompt 级文本规范。

定义：
  HarnessSpec: 可序列化的三层 Harness 表示
  PairwisePreference: 两轮产出对比结果
  RHIHistory: RHI 迭代历史

参考：
  Recursive Harness Self-Improvement (RHI), arXiv:2607.15524
  MemoHarness: Agent Harnesses That Learn from Experience, arXiv:2607.14159
"""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

# ── RHI 三层 Harness 规范 ──


class AgentContract(TypedDict, total=False):
    """子Agent向编排器的输出契约。

    RHI 论文中 contract = 子Agent → orchestrator 的信息协议。
    """
    role: str                           # Agent 角色名
    instruction: str                    # Agent 系统指令（prompt 主体）
    contract_fields: list[str]          # 输出字段名列表（contract spec）
    llm_config: dict[str, Any]          # 可选：模型/温度等配置


class WorkflowHop(TypedDict, total=False):
    """工作流中的单步交互（Hop）。

    Hop 定义 orchestrator 与子 Agent 之间的单次交互步骤。
    """
    name: str                           # Hop 名称（如 "P3_四源并行"）
    agents: list[str]                   # 参与的 Agent 角色名
    input_from: list[str]               # 依赖的上游 Hop 或状态字段
    output_to: list[str]                # 输出写入的状态字段
    timeout: int                        # 超时秒数
    fallback: str                       # 降级策略名称


class Workflow(TypedDict, total=False):
    """工作流定义 = Contract + Hop 结构。

    Contract 指定子Agent间传递的信息内容；
    Hop 指定交互顺序和步骤。
    """
    contracts: dict[str, AgentContract]     # {role: contract}
    hops: list[WorkflowHop]                 # 有序的步骤列表
    orchestrator_instruction: str           # 编排器全局指令


class AuxiliaryRules(TypedDict, total=False):
    """辅助规则 — 验收门禁/回退/通信/召回。

    对应 RHI 论文 Figure 4 中的 Auxiliary Rules 区块。
    """
    acceptance_gates: list[str]             # 验收门禁规则文本
    fallback_rules: list[str]               # 回退/降级规则文本
    communication_rules: list[str]          # Agent 间通信约束
    recall_triggers: list[str]              # 条件触发的召回规则


class HarnessSpec(TypedDict, total=False):
    """RHI Harness 三层规范 — 完整的 agent loop prompt 级表示。

    对应 RHI 论文 Fig.4 结构：
      - agent_candidates → Agent Candidates 区块
      - workflow → Agent Orchestrator-Subagent Workflow 区块
      - auxiliary_rules → Auxiliary Rules 区块

    以及 MemoHarness 六维控制空间的 embedded 标注：
      - memoharness_dims: 本 Harness 在 D1-D6 上的配置快照
    """
    # RHI 三层
    agent_candidates: dict[str, AgentContract]  # {role: contract}
    workflow: Workflow
    auxiliary_rules: AuxiliaryRules

    # MemoHarness 六维控制空间快照（可选）
    memoharness_dims: Optional[dict[str, Any]]
    # RHI 元数据
    iteration: int                              # 当前迭代轮次
    trace_id: str                               # 关联的辩论 trace_id
    created_at: str                             # ISO 时间戳


# ── RHI 迭代状态 ──


class PairwisePreference(TypedDict, total=False):
    """两轮产出之间的 pairwise 偏好比较结果。

    对应 RHI Algorithm 1 中 Leval 的输出。
    """
    iteration: int                              # 迭代轮次 i
    preference: Literal["improve", "regress", "tie"]
                                                # 比较结果
    score_current: float                        # 本轮综合评分 (0-1)
    score_previous: float                       # 上轮综合评分 (0-1)
    score_breakdown: dict[str, float]           # 各维度细分得分
    rationale: str                              # LLM/规则生成的判断理由
    key_diffs: list[str]                        # 关键差异摘要


class RHIHistory(TypedDict, total=False):
    """RHI 迭代的完整历史记录。

    对应 RHI Algorithm 1 中的 Dx (pairwise 偏好历史)。
    """
    task_id: str                                # 任务标识（品种+日期）
    harnesses: list[HarnessSpec]                # 每轮的 Harness 快照
    outputs: list[str]                          # 每轮的产出路径引用
    preferences: list[PairwisePreference]        # 每轮的偏好比较
    improvement_rate: float                     # 当前改进率 sⁱ
    best_iteration: int                         # 最优 Harness 的轮次
    converged: bool                             # 是否收敛
    stopped_reason: str                         # 停止原因


# ── Harness 版本识别 ──


class HarnessVersion(TypedDict, total=False):
    """Harness 版本标识，用于版本追踪和回退。"""
    version: str                                # 语义版本（如 "v9.20.1-rhi.3"）
    timestamp: str
    rhi_iteration: int
    parent_version: Optional[str]               # 父版本
    diff_summary: str                           # 变更摘要
