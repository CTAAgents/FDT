"""
RHI 全局 Harness 优化 — CLAUDE.md 的递归自改进。

与 FDT 项目级 RHI 不同，本模块作用于项目根目录的 CLAUDE.md。
CLAUDE.md 本身是项目的"全局 Harness prompt" — 定义了 Agent 的角色、
约束、工作流规则。RHI 可迭代优化 CLAUDE.md 的内容。

参考:
  RHI: Recursive Harness Self-Improvement, arXiv:2607.15524
  MemoHarness: Agent Harnesses That Learn from Experience, arXiv:2607.14159
"""

from __future__ import annotations

import logging
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from contracts.rhi_harness_spec import PairwisePreference, RHIHistory
from scripts.rhi_pairwise_eval import compute_improvement_rate

logger = logging.getLogger(__name__)

# ── 全局 Harness 配置 ──
PROJECT_ROOT = Path(os.environ.get("FDT_PROJECT_ROOT", str(Path(__file__).parent.parent)))
CLAUDE_MD_PATH = PROJECT_ROOT / "CLAUDE.md"
RHI_MEMORY_DIR = PROJECT_ROOT / "memory" / "rhi" / "global"
MEMORY_FILE = RHI_MEMORY_DIR / "global_rhi_history.json"


def _read_claude_md() -> str:
    """读取当前 CLAUDE.md 内容。"""
    if not CLAUDE_MD_PATH.exists():
        logger.warning(f"[RHI-Global] CLAUDE.md 不存在: {CLAUDE_MD_PATH}")
        return ""
    return CLAUDE_MD_PATH.read_text(encoding="utf-8")


def _write_claude_md(content: str) -> None:
    """写入更新的 CLAUDE.md。"""
    CLAUDE_MD_PATH.write_text(content, encoding="utf-8")
    logger.info(f"[RHI-Global] CLAUDE.md 已更新 ({len(content)} chars)")


def _load_history() -> dict:
    """加载全局 RHI 历史。"""
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "versions": [],
        "preferences": [],
        "improvement_rate": 0.0,
        "best_version": 0,
        "converged": False,
    }


def _save_history(history: dict) -> None:
    """持久化全局 RHI 历史。"""
    RHI_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _score_output() -> dict:
    """对当前 CLAUDE.md 输出质量进行评分。

    评价维度:
      - project_memory 覆盖度 (0.30): 引用 memory/ 的完整度
      - 规则完整性 (0.30): anti-patterns, checklists 齐全
      - 一致性 (0.20): 与 docs/harness/ 的实际状态一致
      - 清晰度 (0.20): prompt 结构清晰度

    Returns:
        {score: float, breakdown: dict}
    """
    content = _read_claude_md()
    if not content:
        return {"score": 0.0, "breakdown": {}}

    scores = {}

    # project_memory 覆盖度
    has_project_memory = "project_memory" in content
    has_knowledge_ref = "Knowledge" in content or "knowledge" in content
    scores["memory_coverage"] = 1.0 if (has_project_memory and has_knowledge_ref) else (0.5 if (has_project_memory or has_knowledge_ref) else 0.0)

    # 规则完整性
    has_anti_patterns = "反模式" in content or "anti-pattern" in content
    has_12_checklist = "12" in content and "检查" in content
    scores["rule_completeness"] = 1.0 if (has_anti_patterns and has_12_checklist) else (0.5 if (has_anti_patterns or has_12_checklist) else 0.0)

    # 一致性
    has_harness_ref = "Harness" in content
    has_docs_ref = "docs/harness" in content
    scores["consistency"] = 1.0 if (has_harness_ref and has_docs_ref) else (0.5 if (has_harness_ref or has_docs_ref) else 0.0)

    # 清晰度
    total_lines = len(content.splitlines())
    clarity = 1.0 if total_lines < 300 else (0.5 if total_lines < 500 else 0.2)
    scores["clarity"] = clarity

    weights = {"memory_coverage": 0.30, "rule_completeness": 0.30, "consistency": 0.20, "clarity": 0.20}
    total = sum(scores[k] * weights[k] for k in weights)

    return {"score": round(total, 4), "breakdown": scores}


def run_global_rhi_step(max_iters: int = 3) -> dict:
    """执行一轮全局 Harness RHI 自优化。

    每次优化比较当前 CLAUDE.md 与上一版本的输出质量评分，
    基于 pairwise 偏好决定是否更新 CLAUDE.md 内容。

    对应 RHI Algorithm 1 在全局 Harness 层面的适配。

    Args:
        max_iters: 最大迭代轮次

    Returns:
        优化结果摘要
    """
    history = _load_history()
    versions = history.get("versions", [])
    preferences = history.get("preferences", [])
    iter_num = len(versions)

    if iter_num >= max_iters:
        return {"status": "converged", "iterations": iter_num, "reason": "max_iters"}

    current_content = _read_claude_md()
    current_score = _score_output()

    # 与上一版本比较
    if versions:
        prev_version = versions[-1]
        prev_score = prev_version.get("score", 0)

        delta = current_score["score"] - prev_score
        if delta > 0.02:
            preference: PairwisePreference = {
                "iteration": iter_num,
                "preference": "improve",
                "score_current": current_score["score"],
                "score_previous": prev_score,
                "score_breakdown": {"current": current_score["breakdown"], "previous": prev_version.get("breakdown", {})},
                "rationale": f"评分提升 {delta:+.3f}",
                "key_diffs": [],
            }
        elif delta < -0.02:
            preference = {
                "iteration": iter_num,
                "preference": "regress",
                "score_current": current_score["score"],
                "score_previous": prev_score,
                "score_breakdown": {"current": current_score["breakdown"], "previous": prev_version.get("breakdown", {})},
                "rationale": f"评分下降 {delta:+.3f}",
                "key_diffs": [],
            }
        else:
            preference = {
                "iteration": iter_num,
                "preference": "tie",
                "score_current": current_score["score"],
                "score_previous": prev_score,
                "score_breakdown": {"current": current_score["breakdown"], "previous": prev_version.get("breakdown", {})},
                "rationale": f"评分持平 (delta={delta:+.3f})",
                "key_diffs": [],
            }
        preferences.append(preference)
    else:
        # 首轮
        preferences.append({
            "iteration": 0,
            "preference": "tie",
            "score_current": current_score["score"],
            "score_previous": 0.0,
            "score_breakdown": {"current": current_score["breakdown"], "previous": {}},
            "rationale": "首轮基准评分",
            "key_diffs": [],
        })

    # 记录版本快照
    versions.append({
        "version": iter_num,
        "timestamp": datetime.now().isoformat(),
        "score": current_score["score"],
        "breakdown": current_score["breakdown"],
        "content_length": len(current_content),
    })

    # 计算改进率
    s_i = compute_improvement_rate(preferences)
    history["versions"] = versions
    history["preferences"] = preferences
    history["improvement_rate"] = s_i
    history["best_version"] = max(range(len(versions)), key=lambda i: versions[i].get("score", 0))

    # 停止检查
    if s_i < 0.3 and len(preferences) >= 2:
        history["converged"] = True
    elif iter_num >= max_iters - 1:
        history["converged"] = True

    _save_history(history)

    return {
        "status": "converged" if history["converged"] else "continue",
        "iterations": iter_num + 1,
        "current_score": current_score["score"],
        "improvement_rate": s_i,
        "preference": preferences[-1]["preference"],
        "reason": preferences[-1]["rationale"],
    }
