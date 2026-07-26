"""补丁自动创建器 — Phase 2: 3 种触发点自动生成补丁记忆。

触发点:
    1. 规则变更 (CLAUDE.md / harness-rules.yaml 被修改)
    2. 知识库变动 (knowledge/ 下文件新增重大内容)
    3. 裁决偏差 (P5 风控连续偏差超阈值)

用法:
    from memory.maintenance.patch_creator import PatchCreator
    creator = PatchCreator(memory_dir)
    creator.create_from_rule_change("CLAUDE.md", "新增右侧交易铁律")
    creator.create_from_rule_change("harness-rules.yaml", "新增 C18 secret_leak 规则")
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..store.patch_store import PatchStore

logger = logging.getLogger(__name__)

# ── 域推断映射 ──
_PATH_DOMAIN_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"CLAUDE\.md$"), "规则|Harness"),
    (re.compile(r"harness-rules\.yaml$"), "规则|Harness"),
    (re.compile(r"10-coding-standards\.md$"), "规则|编码规范"),
    (re.compile(r"08-gap-analysis\.md$"), "运维|差距"),
    (re.compile(r"knowledge/.+"), "知识库"),
    (re.compile(r"_nodes_verdict|_nodes_debate|_nodes_prepare"), "架构|图节点"),
    (re.compile(r"state\.py$"), "架构|状态"),
    (re.compile(r"graph\.py$"), "架构|图编排"),
]


def _infer_domain_from_path(file_path: str) -> str:
    """从文件路径推断 domain 标签。"""
    for pattern, domain in _PATH_DOMAIN_MAP:
        if pattern.search(file_path):
            return domain
    return "未分类"


class PatchCreator:
    """补丁自动创建器 — 封装 3 种触发点的补丁生成逻辑。"""

    def __init__(self, memory_dir: str | Path):
        self.memory_dir = Path(memory_dir)
        self._patch_store = PatchStore(self.memory_dir)

    # ── 触发点 1: 规则变更 ──────────────────────────

    def create_from_rule_change(
        self,
        changed_file: str,
        change_summary: str,
        rationale: str = "",
        evidence: list[str] | None = None,
    ) -> str | None:
        """规则/引擎文件变更时创建补丁。

        Args:
            changed_file: 变更的文件路径（相对项目根）。
            change_summary: 变更摘要。
            rationale: 变更理由（可选）。
            evidence: 证据链（可选）。

        Returns:
            patch_id 或 None（跳过时）。
        """
        domain = _infer_domain_from_path(changed_file)
        if domain == "未分类":
            logger.debug("[PatchCreator] 跳过未分类文件: %s", changed_file)
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        patch = {
            "domain": domain,
            "pre_state": f"变更前: {changed_file} 文件有旧规则",
            "post_state": f"变更后: {changed_file} — {change_summary}",
            "rationale": rationale or f"文件 {changed_file} 发生变更 ({change_summary})",
            "evidence": evidence or [f"文件变更: {changed_file}"],
            "conditions": {
                "applicable_regime": ["all"],
                "inapplicable_regime": [],
                "valid_from": today,
                "valid_until": None,
            },
            "intent": f"规则变更: {change_summary}",
            "actions": [f"修改文件: {changed_file}"],
            "outcome": change_summary,
            "learned": f"【规则变更】{change_summary}",
            "message_summary_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_id": f"auto-patch-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        }
        patch_id = self._patch_store.store(patch)
        logger.info("[PatchCreator] 规则变更补丁已创建: %s (domain=%s)", patch_id, domain)
        return patch_id

    # ── 触发点 2: 知识库变动 ─────────────────────────

    def create_from_knowledge_change(
        self,
        knowledge_path: str,
        change_type: str = "new",  # "new" | "update" | "restructure"
        summary: str = "",
        old_version: str = "",
        new_version: str = "",
    ) -> str | None:
        """知识库文件重大变更时创建补丁。

        Args:
            knowledge_path: 知识库文件路径（相对 memory/）。
            change_type: 变更类型 (new/update/restructure)。
            summary: 变更摘要。
            old_version: 旧版本描述。
            new_version: 新版本描述。

        Returns:
            patch_id 或 None。
        """
        # 提取品种/产业链标签
        path_parts = Path(knowledge_path).parts
        industry = "unknown"
        for part in path_parts:
            if part in ("agricultural", "energy_chemical", "ferrous_metals", "nonferrous_metals",
                        "precious_metals", "building_materials", "polyester_chain",
                        "financial_futures", "new_energy", "shipping", "etf_index"):
                industry = part
                break

        today = datetime.now().strftime("%Y-%m-%d")
        change_type_label = {"new": "新增", "update": "更新", "restructure": "重构"}.get(change_type, "变更")

        patch = {
            "domain": f"知识库|{industry}",
            "pre_state": old_version or f"知识库文件 {knowledge_path} 旧版本",
            "post_state": new_version or f"{change_type_label}: {summary or knowledge_path}",
            "rationale": f"知识库{change_type_label}触发: {knowledge_path}",
            "evidence": [f"知识库变更: {knowledge_path} ({change_type})"],
            "conditions": {
                "applicable_regime": ["all"],
                "inapplicable_regime": [],
                "valid_from": today,
                "valid_until": None,
            },
            "intent": f"知识库{change_type_label}: {summary or knowledge_path}",
            "actions": [f"修改知识库: {knowledge_path}"],
            "outcome": f"{change_type_label}: {summary or knowledge_path}",
            "learned": f"【知识库】{industry}: {summary or knowledge_path}",
            "message_summary_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_id": f"auto-kb-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        }
        patch_id = self._patch_store.store(patch)
        logger.info("[PatchCreator] 知识库补丁已创建: %s (domain=%s)", patch_id, patch["domain"])
        return patch_id

    # ── 触发点 3: 裁决偏差 ──────────────────────────

    def create_from_deviation(
        self,
        symbol: str,
        direction: str,
        expected_direction: str,
        confidence: float,
        deviation_count: int,
        details: str = "",
    ) -> str | None:
        """P5 风控检测到连续裁决偏差时创建补丁。

        Args:
            symbol: 品种代码。
            direction: 实际裁决方向。
            expected_direction: 预期方向（事后验证）。
            confidence: 置信度。
            deviation_count: 连续偏差次数。
            details: 偏差详情。

        Returns:
            patch_id 或 None（未达阈值时跳过）。
        """
        # 阈值: 连续 3 次偏差才触发
        if deviation_count < 3:
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        patch = {
            "domain": f"裁决偏差|{symbol}",
            "pre_state": f"裁决方向={direction}, 预期={expected_direction}, 置信度={confidence}",
            "post_state": f"需根因分析: 连续{deviation_count}次裁决偏差 ({details})",
            "rationale": f"{symbol} 连续 {deviation_count} 次裁决方向与事后验证结果不一致",
            "evidence": [
                f"品种: {symbol}",
                f"连续偏差次数: {deviation_count}",
                f"最近裁决: direction={direction} vs expected={expected_direction}",
            ],
            "conditions": {
                "applicable_regime": ["all"],
                "inapplicable_regime": [],
                "valid_from": today,
                "valid_until": None,
            },
            "intent": f"{symbol} 裁决偏差根因分析 ({deviation_count}次)",
            "actions": [
                f"检测到 {symbol} 连续 {deviation_count} 次裁决偏差",
                "触发根因分析",
            ],
            "outcome": f"创建偏差补丁: {details or '待分析'}",
            "learned": f"【裁决偏差】{symbol}: 连续{deviation_count}次偏差, 当前方向={direction}",
            "message_summary_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_id": f"auto-deviation-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        }
        patch_id = self._patch_store.store(patch)
        logger.warning("[PatchCreator] 裁决偏差补丁已创建: %s (%s 连续%d次偏差)",
                       patch_id, symbol, deviation_count)
        return patch_id
