"""记忆规则注入器 — 按 Agent 身份从 MEMORY.md 提取相关规则

用法:
    from memory.retrieval.rules_injector import get_rules_for_agent

    context += "\\n\\n【记忆规则注入】\\n" + get_rules_for_agent("judge")

MEMORY.md 中每节标记 `<!-- agents: agent1,agent2 -->`，
系统根据 Agent 名称匹配并返回对应规则文本。
标签 `all` 匹配任何 Agent。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORY_MD_PATH = Path(__file__).resolve().parent.parent / "rules" / "MEMORY.md"
_CACHE: dict[str, str] = {}
_MD_MTIME: float = 0.0
_CACHED_TEXT: str = ""


def get_rules_for_agent(agent_name: str) -> str:
    """返回该 Agent 应遵守的记忆规则文本（空字符串 = 无相关规则）

    进程内缓存 MEMORY.md 的解析结果，
    文件修改后自动刷新（监听到 mtime 变化）。
    """
    global _MD_MTIME, _CACHED_TEXT

    if agent_name in _CACHE:
        return _CACHE[agent_name]

    # 检查文件是否修改
    current_mtime = _MEMORY_MD_PATH.stat().st_mtime
    if current_mtime != _MD_MTIME:
        _CACHE.clear()
        _CACHED_TEXT = _MEMORY_MD_PATH.read_text(encoding="utf-8")
        _MD_MTIME = current_mtime

    md_text = _CACHED_TEXT

    # 按 ### 标题切分（保留标题行）
    # 使用正则在每个 ### 前插入分隔符
    sections = re.split(r'(?=^### |^<!-- agents:)', md_text, flags=re.MULTILINE)
    results = []

    # Agent 别名映射 — 共享规则的 Agent 配对
    agent_aliases: dict[str, list[str]] = {
        "judge": ["judge", "risk_manager"],
        "risk_manager": ["risk_manager", "judge"],
        "quality_assurance": ["quality_assurance"],
        "bullish_analyst": ["bullish_analyst", "bearish_analyst"],
        "bearish_analyst": ["bearish_analyst", "bullish_analyst"],
    }

    target_agents = agent_aliases.get(agent_name, [agent_name])

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # 提取 agent 标签
        tag_match = re.match(r'<!-- agents:\s*(.+?)\s*-->', section)
        if not tag_match:
            continue

        section_agents_str = tag_match.group(1).strip()
        section_agents = [a.strip() for a in section_agents_str.split(",")]

        # 检查是否匹配
        is_match = "all" in section_agents or any(
            a in target_agents for a in section_agents
        )
        if not is_match:
            continue

        # 去掉标签行，保留标题+内容
        content = re.sub(r'^<!-- agents:[^-]+-->\s*\n?', '', section, flags=re.MULTILINE).strip()
        if content:
            results.append(content)

    result = "\n\n".join(results) if results else ""
    _CACHE[agent_name] = result
    return result


def invalidate_cache() -> None:
    """手动清除缓存（通常用于测试）"""
    _CACHE.clear()
    global _MD_MTIME
    _MD_MTIME = 0.0
