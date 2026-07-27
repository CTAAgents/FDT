"""Phase 1: Self-Refine 快环 — Agent 输出前自审查修正。

基于 Madaan et al. (2023) Self-Refine 方法：
同一 LLM 同时作为生成器、反馈提供者和精炼器。
每次 Agent 输出后，执行一次自我审查，发现问题则修正。

安全约束（Endure）：
  - 只修正文本级问题（逻辑/引用/遗漏），不涉及数值计算
  - 数值计算仍由代码层（L0）执行，Self-Refine 无权修改数据
  - 修正轮数上限 = 1（禁止递归修正）
  - 修正前的原始输出必须完整保留在追踪记录中
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fdt_langgraph.llm_provider import FdtLlm

logger = logging.getLogger(__name__)

# ── Self-Refine 开关（可通过环境变量控制） ──
SELF_REFINE_ENABLED = True

# ── Self-Critic 检查维度 ──
_CRITIC_DIMENSIONS = [
    "数据引用是否可溯源？是否提到了具体数值和来源？",
    "逻辑推理是否有明显跳跃？前提是否能支撑结论？",
    "是否遗漏了关键反面证据或相反观点？",
    "论证是否针对当前品种本身，而非泛泛而谈？",
]


def build_critic_prompt(original_output: str, agent_role: str) -> str:
    """构建 Self-Critic Prompt。

    Args:
        original_output: Agent 的原始输出
        agent_role: Agent 角色名称（如 "bullish_analyst", "verdict_judge"）

    Returns:
        完整的 Self-Critic Prompt
    """
    dimensions_str = "\n".join(f"  {i+1}. {d}" for i, d in enumerate(_CRITIC_DIMENSIONS))
    return f"""你是 FDT 辩论系统的质量审查员（Quality Reviewer）。
请审查以下{agent_role}的分析输出，检查是否存在问题。

审查维度：
{dimensions_str}

请逐个维度检查，并给出你的结论。

输出格式（JSON，必须严格遵循）：
{{"issues": ["问题1（如果有）", "问题2（如果有）"],
  "has_issues": true/false,
  "summary": "简要说明审查结果"}}

原始输出：
---
{original_output}
---
"""


def build_refine_prompt(original_output: str, critic_result: dict, agent_role: str) -> str:
    """构建 Refine Prompt。

    Args:
        original_output: Agent 的原始输出
        critic_result: Self-Critic 的结果（含 issues 列表）
        agent_role: Agent 角色名称

    Returns:
        完整的 Refine Prompt
    """
    issues_str = "\n".join(f"  - {issue}" for issue in critic_result.get("issues", []))
    return f"""你是 FDT 辩论系统的{agent_role}。
以下是你的原始分析输出，审查发现了以下问题：

{issues_str}

请根据上述批评修正你的分析。要求：
1. 保留原始分析中正确的部分，不要重复已正确的论证
2. 仅修正有问题的部分，不要引入新内容
3. 保持相同的输出格式和结构
4. 修正后的版本应该是完整的（可以直接使用的成品）

原始输出：
---
{original_output}
---
修正后的输出（保留原格式）：
"""


async def self_refine(
    original_output: str,
    agent_role: str,
    trace_id: str,
    refine_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对 Agent 输出执行 Self-Refine 流程。

    Args:
        original_output: Agent 原始输出文本
        agent_role: Agent 角色名称（用于 prompt 构建）
        trace_id: 全链路追踪 ID
        refine_config: 可选的配置覆盖
            - enabled: bool             是否启用（默认 True）
            - max_rounds: int           最大修正轮数（默认 1）
            - critic_model_override: str 可选，指定 critic 使用不同模型

    Returns:
        dict 包含:
          - refined_output: str     修正后的输出
          - original_output: str    原始输出（始终保留）
          - had_issues: bool        是否发现问题并修正
          - critic_issues: list[str] 审查发现的问题列表
          - refine_triggered: bool  是否触发了修正
    """
    config = refine_config or {}
    if not config.get("enabled", SELF_REFINE_ENABLED):
        return {
            "refined_output": original_output,
            "original_output": original_output,
            "had_issues": False,
            "critic_issues": [],
            "refine_triggered": False,
        }

    if not original_output or not original_output.strip():
        return {
            "refined_output": original_output or "",
            "original_output": original_output or "",
            "had_issues": False,
            "critic_issues": [],
            "refine_triggered": False,
        }

    # Step 1: Self-Critic — 审查分析输出
    try:
        llm = FdtLlm("self_refine_critic")
        critic_prompt = build_critic_prompt(original_output, agent_role)
        critic_raw = llm.chat(critic_prompt, system="你是一个严格但公平的辩论质量审查员。")
    except Exception as e:
        logger.warning("[SelfRefine] Self-Critic 调用失败: %s", e)
        return {
            "refined_output": original_output,
            "original_output": original_output,
            "had_issues": False,
            "critic_issues": [],
            "refine_triggered": False,
        }

    # 解析 Critic 结果
    critic_result = _parse_critic_output(critic_raw)

    if not critic_result.get("has_issues", False):
        return {
            "refined_output": original_output,
            "original_output": original_output,
            "had_issues": False,
            "critic_issues": [],
            "refine_triggered": False,
        }

    # Step 2: Refine — 修正输出
    max_rounds = config.get("max_rounds", 1)
    current_output = original_output
    all_issues = list(critic_result.get("issues", []))

    for round_idx in range(max_rounds):
        try:
            refine_prompt = build_refine_prompt(current_output, critic_result, agent_role)
            llm = FdtLlm(agent_role)
            refine_raw = llm.chat(refine_prompt, system=f"你是一位严谨的{agent_role}，正在修正你的分析。")
            refined = _extract_refined_output(refine_raw)
            if refined and len(refined) > len(original_output) * 0.3:
                current_output = refined
                logger.info("[SelfRefine] %s 第%d轮修正完成: %d问题", agent_role, round_idx + 1, len(all_issues))
                break
            else:
                logger.warning("[SelfRefine] %s 第%d轮修正输出过短，保留原输出", agent_role, round_idx + 1)
        except Exception as e:
            logger.warning("[SelfRefine] Refine 第%d轮失败: %s", round_idx + 1, e)
            break

    return {
        "refined_output": current_output,
        "original_output": original_output,
        "had_issues": True,
        "critic_issues": all_issues,
        "refine_triggered": True,
    }


def _parse_critic_output(raw: str) -> dict[str, Any]:
    """解析 Critic LLM 输出为结构化结果。"""
    if not raw:
        return {"issues": [], "has_issues": False, "summary": "空输出"}

    # 尝试 JSON 解析
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        # 移除 markdown 代码块标记
        cleaned = cleaned.split("```")[1] if "```" in cleaned else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return {
                "issues": parsed.get("issues", []),
                "has_issues": parsed.get("has_issues", False),
                "summary": parsed.get("summary", ""),
            }
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: 关键词检测
    has_issues = any(kw in raw.lower() for kw in ["问题", "缺陷", "遗漏", "跳跃", "不足", "issue", "missing"])
    issues = []
    lines = raw.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("-") or line.startswith("*") or line.startswith("1"):
            issues.append(line.lstrip("- *123456789.").strip())

    return {
        "issues": issues if has_issues else [],
        "has_issues": has_issues,
        "summary": raw[:200] if has_issues else "无问题",
    }


def _extract_refined_output(raw: str) -> str:
    """从 Refine LLM 回复中提取修正后的输出。"""
    if not raw:
        return ""

    cleaned = raw.strip()
    # 移除可能的 markdown 代码块包裹
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 3:
            cleaned = parts[1] if parts[1].strip() else parts[2]
        elif len(parts) == 2:
            cleaned = parts[1]
        # 移除语言标记
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        elif cleaned.startswith("text"):
            cleaned = cleaned[4:].strip()

    return cleaned.strip()
