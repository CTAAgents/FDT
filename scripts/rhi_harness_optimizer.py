"""
RHI Harness Optimizer — LLM 基于 pairwise 偏好历史更新 Harness。

对应 RHI Algorithm 1 中的 Lharness 函数:
  Hⁱ⁺¹ = Lharness(Hⁱ, Dⁱ)

Lharness 接收当前 Harness 和累积的偏好历史，生成新的 Harness 文本规范。
Lharness 不直接观察 x_eval（评价 prompt），仅从偏好历史中隐式学习。

参考:
  RHI: Recursive Harness Self-Improvement, arXiv:2607.15524
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from contracts.rhi_harness_spec import (
    HarnessSpec, PairwisePreference, RHIHistory,
)

logger = logging.getLogger(__name__)


def _preferences_to_context(preferences: list[PairwisePreference]) -> str:
    """将偏好历史格式化为 LLM 可读的文本上下文。"""
    if not preferences:
        return "（无偏好历史 — 首次迭代）"

    lines = ["## Pairwise 偏好历史"]
    for p in preferences:
        pref_icon = {"improve": "✅ 改进", "regress": "❌ 退步", "tie": "➡️ 持平"}
        icon = pref_icon.get(p.get("preference", "tie"), "➡️")
        lines.append(
            f"- 迭代 #{p.get('iteration', '?')}: {icon} "
            f"(cur={p.get('score_current', 0):.3f} vs prev={p.get('score_previous', 0):.3f})"
        )
        if p.get("key_diffs"):
            for d in p["key_diffs"]:
                lines.append(f"  - {d}")
    return "\n".join(lines)


def _current_harness_to_text(spec: HarnessSpec) -> str:
    """将当前 Harness 格式化为 LLM 可读的文本描述。"""
    lines = ["## 当前 Harness 规范", f"迭代: {spec.get('iteration', 0)}"]

    # Agent Candidates
    agents = spec.get("agent_candidates", {})
    lines.append("\n### Agent Candidates")
    for role, ac in agents.items():
        fields = ", ".join(ac.get("contract_fields", []))
        lines.append(f"- **{role}**: contract=[{fields}]")

    # Workflow
    wf = spec.get("workflow", {})
    lines.append("\n### Workflow (Hops)")
    for hop in wf.get("hops", []):
        agents_str = ", ".join(hop.get("agents", []))
        lines.append(f"- **{hop.get('name', '?')}**: agents=[{agents_str}]")

    # Auxiliary Rules
    ar = spec.get("auxiliary_rules", {})
    lines.append("\n### Auxiliary Rules")
    for gate in ar.get("acceptance_gates", []):
        lines.append(f"- 验收: {gate}")
    for rule in ar.get("fallback_rules", []):
        lines.append(f"- 回退: {rule}")

    return "\n".join(lines)


def build_optimizer_prompt(current_spec: HarnessSpec,
                           preferences: list[PairwisePreference],
                           task_desc: str = "") -> str:
    """构建 Harness Optimizer 的 LLM prompt。

    对应 RHI Algorithm 1 中 Lharness 的输入构造。

    Args:
        current_spec: 当前 Harness Hⁱ
        preferences: 累积的偏好历史 Dⁱ
        task_desc: 任务描述（可选）

    Returns:
        LLM prompt 文本
    """
    harness_text = _current_harness_to_text(current_spec)
    history_text = _preferences_to_context(preferences)

    prompt = f"""你是一个 Harness Optimizer。你的任务是根据当前的 Harness 配置和 Pairwise 偏好历史，生成改进后的 Harness。

## 任务描述
{task_desc or "FDT 期货品种辩论"}

{harness_text}

{history_text}

## 优化指导原则
1. **优先优化 Workflow (Contract + Hop)**：调整子Agent间的信息传递契约和交互步骤，减少冗余上下文传播
2. **保持 Agent Design 稳定**：尽量不修改 agent role 和 instruction，主要通过调整 contract 字段和 hop 顺序来改进
3. **遵循偏好信号**：如果偏好历史显示某维度持续改进，保持该方向的修改；如果持续退步，撤销相关修改
4. **修改幅度控制**：每次只改 1-3 处，避免过度修改导致性能退化
5. **参考 RHI 论文发现**：改进主要来自更有效的 inter-agent 信息流管理，而非更长的推理链

## 输出格式
请以 JSON 格式返回新的 Harness 规范（仅包含需要修改的部分）：

```json
{{"workflow": {{
    "contracts": {{
        "agent_role": {{"contract_fields": ["field1", "field2", ...]}}
    }},
    "hops": [{{"name": "hop_name", ...}}]
}},
"auxiliary_rules": {{
    "recall_triggers": ["..."]
}},
"change_summary": "简要说明本次修改内容和理由"
}}
```

返回完整的 JSON 对象，change_summary 字段必填。
"""
    return prompt


def parse_optimizer_response(response: str) -> tuple[Optional[dict], Optional[str]]:
    """解析 LLM Optimizer 的 JSON 响应。

    Args:
        response: LLM 原始输出

    Returns:
        (config_delta: dict | None, change_summary: str | None)
    """
    import json
    import re

    if not response or not response.strip():
        return None, None

    try:
        # 尝试直接解析
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            cleaned = response[start:end]
            parsed = json.loads(cleaned)
            change_summary = parsed.pop("change_summary", None)
            return parsed, change_summary
    except json.JSONDecodeError:
        pass

    return None, None


def apply_config_delta(current: HarnessSpec, delta: dict) -> HarnessSpec:
    """将配置 delta（LLM 返回的修改）合并到当前 Harness 上。

    Args:
        current: 当前 Harness Hⁱ
        delta: LLM Optimizer 返回的修改

    Returns:
        新的 Harness Hⁱ⁺¹
    """
    import copy

    new_spec: HarnessSpec = {
        "agent_candidates": copy.deepcopy(current.get("agent_candidates", {})),
        "workflow": copy.deepcopy(current.get("workflow", {})),
        "auxiliary_rules": copy.deepcopy(current.get("auxiliary_rules", {})),
        "memoharness_dims": copy.deepcopy(current.get("memoharness_dims")),
        "iteration": current.get("iteration", 0) + 1,
        "trace_id": current.get("trace_id", ""),
        "created_at": datetime.now().isoformat(),
    }

    # 合并 workflow 修改
    wf_delta = delta.get("workflow", {})
    if wf_delta:
        contracts_delta = wf_delta.get("contracts", {})
        if contracts_delta:
            for role, updates in contracts_delta.items():
                if role in new_spec["workflow"].get("contracts", {}):
                    # 合并 contract_fields
                    if "contract_fields" in updates:
                        new_spec["workflow"]["contracts"][role]["contract_fields"] = updates["contract_fields"]
                else:
                    new_spec["workflow"]["contracts"][role] = updates

        hops_delta = wf_delta.get("hops", [])
        if hops_delta:
            # 按 name 匹配更新现有 hop
            hop_names = {h.get("name"): i for i, h in enumerate(new_spec["workflow"].get("hops", []))}
            for hop in hops_delta:
                name = hop.get("name")
                if name and name in hop_names:
                    idx = hop_names[name]
                    new_spec["workflow"]["hops"][idx] = {**new_spec["workflow"]["hops"][idx], **hop}
            # 新增不在现有列表中的 hop
            new_names = [h.get("name") for h in new_spec["workflow"].get("hops", [])]
            for hop in hops_delta:
                if hop.get("name") not in new_names:
                    new_spec["workflow"]["hops"].append(hop)

    # 合并 auxiliary_rules 修改
    ar_delta = delta.get("auxiliary_rules", {})
    if ar_delta:
        for key in ["acceptance_gates", "fallback_rules", "communication_rules", "recall_triggers"]:
            if key in ar_delta:
                existing = new_spec["auxiliary_rules"].get(key, [])
                # 追加不重复的条目
                seen = set(existing)
                for item in ar_delta[key]:
                    if item not in seen:
                        existing.append(item)
                        seen.add(item)
                new_spec["auxiliary_rules"][key] = existing

    return new_spec
