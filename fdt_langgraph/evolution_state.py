"""
evolution_state.py — 自进化闭环状态定义 (APM-CS 五轴驱动)

EvolutionState 追踪外循环（Outer Loop）的全量状态，包括品藻质检指标、APM
五轴评分、进化决策与执行结果。与 DebateState 独立，可独立运行或作为辩论后步骤。
"""

from __future__ import annotations

from datetime import datetime


class EvolutionState(dict):
    """自进化闭环状态 (TypedDict 替代品，兼容 LangGraph 的 dict-based state)。

    字段说明:
        trace_id: 全链路追踪 ID
        phase: 当前阶段 (idle/collecting/apm_eval/deciding/improving/calibrating/evolving/ml_training/completed)
        source_trace_id: 触发本次进化的辩论 trace_id (空=独立运行)

        collected_metrics: 从辩论收集的质量指标
            ├── quality_inspector: {status, total_issues, error_count, warning_count}
            ├── generation_metrics: {total_records, schema_pass_rate, success_rate}
            └── output_metrics: {total_score, completeness, consistency, conformity, conciseness}

        apm_scores: APM-CS 五轴评分 (D1-D5)
            ├── D1_coherence: {score, status, detail}
            ├── D2_acuity: {score, status, detail}
            ├── D3_composure: {score, status, detail}
            ├── D4_discipline: {score, status, detail}
            └── D5_reliability: {score, status, detail}

        apm_overall: 综合评分与各轴退化标记

        decisions: 基于 APM 评分做出的决策
            ├── need_improve: bool (任一轴 degenerate)
            ├── need_calibrate: bool (D2/D4 偏低且样本足够)
            ├── need_evolve: bool (总样本足够)
            ├── need_ml_train: bool (新样本足够)
            └── need_inject_rules: bool (Checker 缺口 / 质检规则违反)

        injection_config: 记忆规则注入配置
            ├── active: bool  (是否启用注入)
            ├── agents: list  (启用注入的 Agent 列表)
            ├── triggered_by: str (触发原因)
            └── activated_at: str (时间戳)

        step_results: 各步骤执行结果
        errors: 非阻断错误列表
        started_at / completed_at: 时间戳
    """

    @classmethod
    def create(cls, trace_id: str = "", source_trace_id: str = "") -> "EvolutionState":
        return cls({
            "trace_id": trace_id,
            "phase": "idle",
            "source_trace_id": source_trace_id,
            "collected_metrics": {
                "quality_inspector": {},
                "generation_metrics": {},
                "output_metrics": {},
            },
            "apm_scores": {},
            "apm_overall": {},
            "decisions": {
                "need_improve": False,
                "need_calibrate": False,
                "need_evolve": False,
                "need_ml_train": False,
                "need_inject_rules": False,
            },
            "injection_config": {
                "active": False,
                "agents": [],
                "triggered_by": "",
                "activated_at": "",
            },
            "step_results": {},
            "errors": [],
            "started_at": datetime.now().isoformat() if trace_id else "",
            "completed_at": "",
        })


# ── 验证条件常量 ──

# APM 各轴退化阈值
APM_DEGENERATE_THRESHOLDS = {
    "D1_coherence": 0.5,    # < 0.5 = 裁决与论据一致性差
    "D2_acuity": 0.0,       # ≤ 0 = 无信号-噪音辨识力
    "D3_composure": 0.3,    # < 0.3 = 过度反应严重
    "D4_discipline": 0.7,   # < 0.7 = 规则遵守度不足
    "D5_reliability": 0.6,  # < 0.6 = 闭环完成率低
}

# 校准/进化/ML 触发阈值
CALIBRATE_MIN_VALIDATED = 5    # 校准：至少 5 条已验证样本
EVOLVE_MIN_SAMPLES = 5         # 进化：至少 5 条总样本
ML_TRAIN_MIN_SAMPLES = 50      # ML 训练：至少 50 条新样本

# APM 评分状态
STATE_ACTIVE = "active"
STATE_DEGENERATE = "degenerate"
STATE_FALLBACK = "fallback"
STATE_BLOCKED = "blocked"
