"""
RHI LangGraph 子图 — Recursive Harness Self-Improvement。

集成到 evolution_graph.py 的 decision_actions 分支中：
  RHI 分支与 improve/calibrate/evolve/ml_train 同级。

参考:
  RHI: Recursive Harness Self-Improvement, arXiv:2607.15524
  MemoHarness: Agent Harnesses That Learn from Experience, arXiv:2607.14159
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from contracts.rhi_harness_spec import (
    HarnessSpec, PairwisePreference, RHIHistory,
)
from scripts.rhi_pairwise_eval import (
    evaluate_pairwise,
    compute_improvement_rate,
)
from scripts.rhi_harness_optimizer import (
    build_optimizer_prompt,
    parse_optimizer_response,
    apply_config_delta,
)
from fdt_langgraph.agents import FdtAgentExecutor

logger = logging.getLogger(__name__)

# ── RHI 配置 ──
RHI_MAX_ITER = int(os.environ.get("FDT_RHI_MAX_ITER", "5"))
RHI_EPSILON = float(os.environ.get("FDT_RHI_EPSILON", "0.3"))

# ── 全局 Harness 快照路径（供 rhi_global_harness.py 引用） ──
_DEFAULT_HARNESS_DIR = Path(__file__).parent.parent / "memory" / "rhi"
_DEFAULT_HARNESS_FILE = _DEFAULT_HARNESS_DIR / "current_harness.json"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RHI 节点函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _build_base_harness() -> HarnessSpec:
    """从 FDT 现有文件中构建初始 Harness H⁰。

    映射:
      - agent_candidates: 从 agents/*.yaml 和 agent_profiles.json
      - workflow: 从 graph.py 的 Hop 定义
      - auxiliary_rules: 从 harness-rules.yaml
    """
    return {
        "agent_candidates": {
            "technical_researcher": {
                "role": "technical_researcher",
                "instruction": "作为技术面研究员（观澜），请分析品种的技术面状态",
                "contract_fields": ["trend", "key_levels", "volume_price", "divergence", "pattern", "score"],
            },
            "fundamental_researcher": {
                "role": "fundamental_researcher",
                "instruction": "作为基本面研究员（探源），请分析品种的基本面状态",
                "contract_fields": ["supply_demand", "inventory", "profit_margin", "basis_term", "macro_external", "leading_signals"],
            },
            "chain_researcher": {
                "role": "chain_researcher",
                "instruction": "作为产业链分析师（链证源），请分析品种的产业链状态",
                "contract_fields": ["chain_structure", "cost_profit", "capacity", "policy_impact"],
            },
            "bullish_analyst": {
                "role": "bullish_analyst",
                "instruction": "作为多头分析员，请构建做多论据",
                "contract_fields": ["arguments", "confidence", "source_refs"],
            },
            "bearish_analyst": {
                "role": "bearish_analyst",
                "instruction": "作为空头分析员，请构建做空论据",
                "contract_fields": ["arguments", "confidence", "source_refs"],
            },
            "judge": {
                "role": "judge",
                "instruction": "作为闫判官，请基于辩论论据做出终裁",
                "contract_fields": ["direction", "confidence", "entry_price", "stop_loss", "target1", "reason"],
            },
            "risk_manager": {
                "role": "risk_manager",
                "instruction": "作为风控明，请审核裁决风险",
                "contract_fields": ["risk_level", "check_items", "conclusion"],
            },
        },
        "workflow": {
            "contracts": {
                "technical_researcher": {"contract_fields": ["trend", "key_levels", "volume_price", "divergence", "pattern", "score"]},
                "fundamental_researcher": {"contract_fields": ["supply_demand", "inventory", "profit_margin", "basis_term", "macro_external", "leading_signals"]},
                "chain_researcher": {"contract_fields": ["chain_structure", "cost_profit", "capacity", "policy_impact"]},
                "bullish_analyst": {"contract_fields": ["arguments", "confidence", "source_refs"]},
                "bearish_analyst": {"contract_fields": ["arguments", "confidence", "source_refs"]},
                "judge": {"contract_fields": ["direction", "confidence", "entry_price", "stop_loss", "target1", "reason"]},
                "risk_manager": {"contract_fields": ["risk_level", "check_items", "conclusion"]},
            },
            "hops": [
                {"name": "P0_扫描", "agents": ["scan"], "input_from": [], "output_to": ["scan_results"], "timeout": 300, "fallback": "D06"},
                {"name": "P1_产业链", "agents": ["chain_researcher"], "input_from": ["scan_results"], "output_to": ["chain_reports"], "timeout": 300, "fallback": "D06"},
                {"name": "P2_初判", "agents": ["judge"], "input_from": ["scan_results"], "output_to": ["selected_symbols"], "timeout": 120, "fallback": "D06"},
                {"name": "P3_四源并行", "agents": ["technical_researcher", "fundamental_researcher", "chain_researcher", "sentiment_analyst"], "input_from": ["fdc_data"], "output_to": ["per_symbol_tech", "per_symbol_fund"], "timeout": 300, "fallback": "D06"},
                {"name": "P3_辩论", "agents": ["bullish_analyst", "bearish_analyst"], "input_from": ["per_symbol_tech", "per_symbol_fund", "chain_reports"], "output_to": ["bullish_arguments", "bearish_arguments"], "timeout": 600, "fallback": "debate_skip"},
                {"name": "P4_裁决", "agents": ["judge"], "input_from": ["bullish_arguments", "bearish_arguments"], "output_to": ["verdict"], "timeout": 120, "fallback": "D06"},
                {"name": "P5_风控", "agents": ["risk_manager"], "input_from": ["verdict"], "output_to": ["risk_check"], "timeout": 120, "fallback": "default_green"},
                {"name": "P6_输出", "agents": ["reporter"], "input_from": ["verdict", "risk_check"], "output_to": ["report_path"], "timeout": 120, "fallback": "skip"},
            ],
        },
        "auxiliary_rules": {
            "acceptance_gates": [
                "12 项 commit 前检查清单 (C01-C12)",
                "10 条反模式检测 (AP01-AP10)",
            ],
            "fallback_rules": [
                "D06 降级: 任一源超时(300s)跳过，其余继续",
                "辩论降级: 辩论阶段超时(600s)跳过",
                "DataCore→TDX→TqSdk→QMT→WebFallback 四级降级链",
            ],
            "communication_rules": [
                "Agent 只写文件不通信",
                "辩手禁搜 (依赖分析师供弹)",
                "禁止代写",
            ],
            "recall_triggers": [
                "ADX<20: 增加基本面权重",
                "ADX≥60: 不得作为致命伤",
                "分歧度>0.7: 追加深度辩论轮次",
            ],
        },
        "memoharness_dims": None,
        "iteration": 0,
        "trace_id": "",
        "created_at": datetime.now().isoformat(),
    }


def node_rhi_initialize(state: dict) -> dict:
    """RHI 初始化节点 — 构建 H⁰ 并保存快照。

    对应 RHI Algorithm 1 的初始化步骤。
    """
    logger.info("[RHI] 初始化 Harness H⁰")
    _DEFAULT_HARNESS_DIR.mkdir(parents=True, exist_ok=True)

    harness = _build_base_harness()
    harness["trace_id"] = state.get("trace_id", str(datetime.now().timestamp()))

    history: RHIHistory = {
        "task_id": f"{state.get('trace_id', 'unknown')}_{datetime.now().strftime('%Y%m%d')}",
        "harnesses": [harness],
        "outputs": [],
        "preferences": [],
        "improvement_rate": 0.0,
        "best_iteration": 0,
        "converged": False,
        "stopped_reason": "",
    }

    # 保存当前状态
    _save_harness(harness, history)

    return {
        **state,
        "rhi_harness": harness,
        "rhi_history": history,
        "rhi_iteration": 0,
        "rhi_converged": False,
    }


def node_rhi_step(state: dict) -> dict:
    """RHI 单步迭代节点。

    执行一轮 RHI 迭代:
      1. 读取上轮产出路径
      2. 执行 pairwise 比较（Leval）
      3. 调用 Harness Optimizer (Lharness) 生成 Hⁱ⁺¹
      4. 检查停止条件

    对应 RHI Algorithm 1 的循环体。
    """
    harness: HarnessSpec = state.get("rhi_harness", _build_base_harness())
    history: RHIHistory = state.get("rhi_history", {
        "task_id": "",
        "harnesses": [harness],
        "outputs": [],
        "preferences": [],
        "improvement_rate": 0.0,
        "best_iteration": 0,
        "converged": False,
        "stopped_reason": "",
    })
    iteration: int = state.get("rhi_iteration", 0)

    # 步骤 1: 获取上轮和本轮产出的路径
    report_path = state.get("report_path", "")
    previous_outputs = history.get("outputs", [])
    prev_output = previous_outputs[-1] if previous_outputs else None

    if not report_path:
        logger.warning(f"[RHI] 迭代 {iteration}: 无 report_path，跳过 evaluation")
        history["converged"] = True
        history["stopped_reason"] = "no_output"
        return {**state, "rhi_history": history, "rhi_converged": True}

    # 步骤 2: Pairwise Evaluation
    if prev_output:
        pref = evaluate_pairwise(
            output_path_current=report_path,
            output_path_previous=prev_output,
            iteration=iteration,
        )
        logger.info(f"[RHI] 迭代 {iteration}: {pref['preference']} "
                     f"(cur={pref['score_current']:.3f}, prev={pref['score_previous']:.3f})")
    else:
        # 首轮无前次输出，默认为 tie
        pref: PairwisePreference = {
            "iteration": iteration,
            "preference": "tie",
            "score_current": 1.0,
            "score_previous": 1.0,
            "score_breakdown": {"current": {}, "previous": {}},
            "rationale": "首轮迭代，无前次产出可比较",
            "key_diffs": [],
        }

    # 更新历史
    new_preferences = list(history.get("preferences", []))
    new_preferences.append(pref)
    new_outputs = list(history.get("outputs", []))
    new_outputs.append(report_path)

    s_i = compute_improvement_rate(new_preferences)
    logger.info(f"[RHI] 改进率 s^{iteration} = {s_i:.3f}")

    # 步骤 4-5: 检查停止条件
    next_iter = iteration + 1
    converged = False
    stopped_reason = ""

    if s_i < RHI_EPSILON and len(new_preferences) >= 2:
        converged = True
        stopped_reason = f"改进率 s={s_i:.3f} < ε={RHI_EPSILON}"
    elif next_iter >= RHI_MAX_ITER:
        converged = True
        stopped_reason = f"达最大轮次 RHI_MAX_ITER={RHI_MAX_ITER}"

    # 步骤 6: Harness Optimizer（除非已收敛）
    new_harness: HarnessSpec = harness
    if not converged and next_iter <= RHI_MAX_ITER:
        prompt = build_optimizer_prompt(
            current_spec=harness,
            preferences=new_preferences,
            task_desc=f"FDT 期货品种辩论 - trace={state.get('trace_id', '')}",
        )

        # 调用 LLM optimizer
        optimizer_agent = FdtAgentExecutor("rhi_harness_optimizer")
        result = optimizer_agent.run(prompt, state.get("trace_id", ""))
        delta, change_summary = parse_optimizer_response(result.get("output", ""))

        if delta:
            new_harness = apply_config_delta(harness, delta)
            logger.info(f"[RHI] Harness 已更新 H{iteration}→H{next_iter}: {change_summary}")
        else:
            logger.warning(f"[RHI] LLM Optimizer 返回无效 response，保持当前 Harness")

    # 找出最优迭代
    best_iter = 0
    best_score = -1.0
    for k, p in enumerate(new_preferences):
        if p.get("score_current", 0) > best_score:
            best_score = p["score_current"]
            best_iter = p.get("iteration", k)

    new_history: RHIHistory = {
        "task_id": history.get("task_id", ""),
        "harnesses": list(history.get("harnesses", [])) + [new_harness],
        "outputs": new_outputs,
        "preferences": new_preferences,
        "improvement_rate": s_i,
        "best_iteration": best_iter,
        "converged": converged,
        "stopped_reason": stopped_reason,
    }

    # 保存状态
    _save_harness(new_harness, new_history)

    # 更新 state
    return {
        **state,
        "rhi_harness": new_harness,
        "rhi_history": new_history,
        "rhi_iteration": next_iter,
        "rhi_converged": converged,
        "rhi_last_preference": pref,
        "rhi_improvement_rate": s_i,
    }


def _save_harness(harness: HarnessSpec, history: RHIHistory) -> None:
    """持久化 Harness 快照和 RHI 历史。"""
    import json
    _DEFAULT_HARNESS_DIR.mkdir(parents=True, exist_ok=True)

    state_file = _DEFAULT_HARNESS_DIR / "current_harness.json"
    history_file = _DEFAULT_HARNESS_DIR / "rhi_history.json"

    def _json_default(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return str(obj)

    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(harness, f, ensure_ascii=False, indent=2, default=_json_default)
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2, default=_json_default)
    except OSError as e:
        logger.warning(f"[RHI] 无法持久化: {e}")
