"""
evolution_nodes.py — 自进化闭环节点函数 (APM-CS 五轴驱动)

以 APM-CS 五轴评分卡 (D1-D5) 为核心评估标准，结合品藻质检、D3 Generation
质量、D6 Output 质量，决定是否触发校准/进化/ML 训练等改进步骤。

每个节点独立容错，失败不阻断后续步骤。
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fdt_langgraph.evolution_state import (
    EvolutionState, APM_DEGENERATE_THRESHOLDS,
    CALIBRATE_MIN_VALIDATED, EVOLVE_MIN_SAMPLES, ML_TRAIN_MIN_SAMPLES,
    STATE_ACTIVE, STATE_DEGENERATE, STATE_FALLBACK,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ─── 辅助 ─────────────────────────────────────────────

def _run_script(script_rel: str, *args: str, timeout: int = 120) -> tuple[bool, str]:
    """运行项目脚本并返回 (success, summary/message)。"""
    script_path = PROJECT_ROOT / script_rel
    if not script_path.exists():
        return False, f"脚本不存在: {script_path}"
    candidates = [
        str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
        str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe"),
    ]
    venv_python = sys.executable
    for c in candidates:
        if Path(c).exists():
            venv_python = c
            break
    cmd = [venv_python, str(script_path)] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                encoding="utf-8", errors="replace")
        if result.returncode == 0:
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            summary = lines[-1] if lines else "完成"
            return True, summary
        return False, result.stderr.strip()[:200]
    except subprocess.TimeoutExpired:
        return False, f"超时({timeout}s)"
    except Exception as e:
        return False, str(e)


# ─── 数据读取辅助 ─────────────────────────────────────

def _load_json(rel_path: str) -> dict:
    """安全加载 JSON 文件，失败返回空 dict。"""
    p = PROJECT_ROOT / rel_path
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


# ═══════════════════════════════════════════════════════
#  Step 1: 收集辩论质量指标
# ═══════════════════════════════════════════════════════

def node_collect_metrics(state: EvolutionState) -> EvolutionState:
    """从辩论输出与 memory 中收集全量质量指标。"""
    state["phase"] = "collecting"
    metrics = state.setdefault("collected_metrics", {})

    # 1. 品藻质检结果 (从 quality_report 读取)
    qi_path = "memory/quality_reports/latest.json"
    qi_data = _load_json(qi_path)
    if qi_data:
        metrics["quality_inspector"] = {
            "status": qi_data.get("status", "unknown"),
            "total_issues": len(qi_data.get("issues", [])),
            "error_count": sum(1 for i in qi_data.get("issues", []) if i.get("severity") == "error"),
            "warning_count": sum(1 for i in qi_data.get("issues", []) if i.get("severity") == "warning"),
        }

    # 2. D3 Generation Metrics
    try:
        from scripts.generation_metrics import GenerationMetrics
        gm = GenerationMetrics()
        gsum = gm.get_summary()
        metrics["generation_metrics"] = {
            "total_records": gsum.get("total_records", 0),
            "schema_pass_rate": gsum.get("overall_schema_pass_rate", 100.0),
            "success_rate": gsum.get("overall_success_rate", 100.0),
        }
    except Exception:
        pass

    # 3. D6 Output Metrics (最新评分)
    out_path = "memory/output_metrics/latest.json"
    out_data = _load_json(out_path)
    if out_data:
        metrics["output_metrics"] = {
            "total_score": out_data.get("total_score", 100),
            "completeness": out_data.get("dimensions", {}).get("completeness", 100),
            "consistency": out_data.get("dimensions", {}).get("consistency", 100),
            "conformity": out_data.get("dimensions", {}).get("conformity", 100),
            "conciseness": out_data.get("dimensions", {}).get("conciseness", 100),
        }

    logger.info(f"[Evolution] 指标收集完成: qi={metrics.get('quality_inspector', {})}, "
                f"d3={metrics.get('generation_metrics', {})}")
    return state


# ═══════════════════════════════════════════════════════
#  Step 2: APM 五轴评分评估
# ═══════════════════════════════════════════════════════

def node_apm_eval(state: EvolutionState) -> EvolutionState:
    """运行 APM 评分卡 (D1-D5)，或在脚本不可用时读取已有评分。"""
    state["phase"] = "apm_eval"

    # 优先运行 APM 评分卡脚本
    ok, msg = _run_script("scripts/apm_scorecard.py", timeout=120)
    if ok:
        apm_data = _load_json("memory/apm_scorecard.json")
        if apm_data:
            state["apm_scores"] = apm_data.get("scores", {})
            state["apm_overall"] = {
                "generated_at": apm_data.get("generated_at", ""),
                "scores": apm_data.get("scores", {}),
                "details": apm_data.get("details", {}),
            }
            logger.info(f"[Evolution] APM 评分卡运行成功: scores={apm_data.get('scores', {})}")
            return state

    # fallback: 读取已有评分
    apm_data = _load_json("memory/apm_scorecard.json")
    if apm_data:
        state["apm_scores"] = apm_data.get("scores", {})
        state["apm_overall"] = apm_data
        logger.info(f"[Evolution] APM 评分卡读取已有: scores={apm_data.get('scores', {})}")
    else:
        logger.warning("[Evolution] APM 评分卡不可用，标记所有轴为 blocked")

    return state


# ═══════════════════════════════════════════════════════
#  Step 3: 基于 APM 评分做出决策
# ═══════════════════════════════════════════════════════

def node_decide_actions(state: EvolutionState) -> EvolutionState:
    """根据 APM 五轴评分 + 样本量，决定需要执行的改进步骤。"""
    state["phase"] = "deciding"
    decisions = state.setdefault("decisions", {})
    scores = state.get("apm_scores", {})

    # ── 检查各轴是否 degenerate ──
    any_degenerate = False
    for axis, threshold in APM_DEGENERATE_THRESHOLDS.items():
        score = scores.get(axis)
        if score is not None and score < threshold:
            any_degenerate = True
            logger.warning(f"[Evolution] {axis} degenerate: {score:.3f} < {threshold}")

    # ── 从验证文件读取样本量 ──
    followup = _load_json("memory/execution_followup.json")
    records = followup.get("records", []) if followup else []
    validated_count = sum(1 for r in records if r.get("validated"))
    total_samples = len(records)

    # ── 决策 ──
    decisions["need_improve"] = any_degenerate    # 任一轴退化 → 自改进
    decisions["need_calibrate"] = (
        validated_count >= CALIBRATE_MIN_VALIDATED
    )   # 样本足够 → 校准
    decisions["need_evolve"] = (
        total_samples >= EVOLVE_MIN_SAMPLES
    )   # 总样本足够 → 进化
    decisions["need_ml_train"] = (
        total_samples >= ML_TRAIN_MIN_SAMPLES
    )   # 新样本足够 → ML 训练

    logger.info(f"[Evolution] 决策: improve={decisions['need_improve']}, "
                f"calibrate={decisions['need_calibrate']}(n={validated_count}), "
                f"evolve={decisions['need_evolve']}(n={total_samples}), "
                f"ml={decisions['need_ml_train']}")

    return state


# ═══════════════════════════════════════════════════════
#  Step 4: 自改进 (APM 退化时触发)
# ═══════════════════════════════════════════════════════

def node_improve(state: EvolutionState) -> EvolutionState:
    """基于 APM 退化轴生成自改进提案。"""
    state["phase"] = "improving"
    ok, msg = _run_script("scripts/self_improve.py", "--mode=analyze", timeout=120)
    state.setdefault("step_results", {})["improve"] = {
        "success": ok, "summary": msg,
        "timestamp": datetime.now().isoformat(),
    }
    logger.info(f"[Evolution] 自改进: {'✅' if ok else '❌'} {msg}")
    return state


# ═══════════════════════════════════════════════════════
#  Step 5: 权重校准
# ═══════════════════════════════════════════════════════

def node_calibrate(state: EvolutionState) -> EvolutionState:
    """校准评分权重。"""
    state["phase"] = "calibrating"
    ok, msg = _run_script("scripts/calibrate_weights.py", timeout=120)
    state.setdefault("step_results", {})["calibrate"] = {
        "success": ok, "summary": msg,
        "timestamp": datetime.now().isoformat(),
    }
    logger.info(f"[Evolution] 权重校准: {'✅' if ok else '❌'} {msg}")
    return state


# ═══════════════════════════════════════════════════════
#  Step 6: Agent 进化
# ═══════════════════════════════════════════════════════

def node_evolve(state: EvolutionState) -> EvolutionState:
    """进化 Agent 参数。"""
    state["phase"] = "evolving"
    ok, msg = _run_script("scripts/evolve_agents.py", timeout=180)
    state.setdefault("step_results", {})["evolve"] = {
        "success": ok, "summary": msg,
        "timestamp": datetime.now().isoformat(),
    }
    logger.info(f"[Evolution] Agent 进化: {'✅' if ok else '❌'} {msg}")
    return state


# ═══════════════════════════════════════════════════════
#  Step 7: ML 增量训练
# ═══════════════════════════════════════════════════════

def node_ml_train(state: EvolutionState) -> EvolutionState:
    """ML 增量训练 (LightGBM)。"""
    state["phase"] = "ml_training"
    ok, msg = _run_script("ml/trainer.py", timeout=300)
    state.setdefault("step_results", {})["ml_train"] = {
        "success": ok, "summary": msg,
        "timestamp": datetime.now().isoformat(),
    }
    logger.info(f"[Evolution] ML 训练: {'✅' if ok else '❌'} {msg}")
    return state


# ═══════════════════════════════════════════════════════
#  Step 8: 完成
# ═══════════════════════════════════════════════════════

def node_complete(state: EvolutionState) -> EvolutionState:
    """完成进化闭环，写入日志。"""
    state["phase"] = "completed"
    state["completed_at"] = datetime.now().isoformat()

    # 写入进化日志
    log_entry = {
        "trace_id": state.get("trace_id"),
        "source_trace_id": state.get("source_trace_id"),
        "started_at": state.get("started_at"),
        "completed_at": state["completed_at"],
        "apm_scores": state.get("apm_scores", {}),
        "decisions": state.get("decisions", {}),
        "step_results": state.get("step_results", {}),
        "errors": state.get("errors", []),
    }
    log_path = PROJECT_ROOT / "memory" / "evolution_log.json"
    try:
        existing = []
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        if isinstance(existing, list):
            existing.append(log_entry)
        else:
            existing = [log_entry]
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        state.setdefault("errors", []).append(f"写入进化日志失败: {e}")

    logger.info(f"[Evolution] 闭环完成, 耗时="
                f"{state.get('completed_at', '')} - {state.get('started_at', '')}")
    return state


# ═══════════════════════════════════════════════════════
#  路由函数
# ═══════════════════════════════════════════════════════

def route_after_decide(state: EvolutionState) -> str:
    """根据决策路由到对应改进步骤。优先顺序: improve → calibrate → evolve → ml → complete。"""
    d = state.get("decisions", {})
    if d.get("need_improve"):
        return "improve"
    if d.get("need_calibrate"):
        return "calibrate"
    if d.get("need_evolve"):
        return "evolve"
    if d.get("need_ml_train"):
        return "ml_train"
    return "complete"


def route_after_improve(state: EvolutionState) -> str:
    """improve 完成后继续执行后续步骤。"""
    d = state.get("decisions", {})
    if d.get("need_calibrate"):
        return "calibrate"
    if d.get("need_evolve"):
        return "evolve"
    if d.get("need_ml_train"):
        return "ml_train"
    return "complete"


def route_after_calibrate(state: EvolutionState) -> str:
    """calibrate 完成后继续。"""
    d = state.get("decisions", {})
    if d.get("need_evolve"):
        return "evolve"
    if d.get("need_ml_train"):
        return "ml_train"
    return "complete"


def route_after_evolve(state: EvolutionState) -> str:
    """evolve 完成后继续。"""
    d = state.get("decisions", {})
    if d.get("need_ml_train"):
        return "ml_train"
    return "complete"
