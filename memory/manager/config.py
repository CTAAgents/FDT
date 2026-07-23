"""记忆系统配置 — 路径映射 + TTL + 存储限额"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MemoryConfig:
    """记忆系统统一配置"""

    # 根目录（由 MemoryManager 初始化时传入 base_dir 拼接）
    base_dir: str = "."

    # ── TTL 配置 ──────────────────────────────────
    journal_max_age_days: int = 30       # 超过 30 天的 journal 归档
    knowledge_decay_days: int = 60       # 60 天未辩论的品种知识老化
    knowledge_deprecate_failures: int = 3  # 连续 3 次失败 deprecated
    schedule_stale_days: int = 7         # 调度状态 7 天无心跳标记过期
    experience_max_age_days: int = 90    # 经验记录 90 天归档

    # ── 存储限额 ──────────────────────────────────
    max_storage_mb: int = 100            # memory/ 最大存储 (MB)
    journal_max_entries: int = 1000      # debate_journal.json 保留条目数

    # ── 维护间隔 ──────────────────────────────────
    maintenance_interval_hours: int = 24  # 维护周期
    checker_interval_hours: int = 24      # 缺口检查周期

    # ── 路径映射 ──────────────────────────────────
    paths: dict = field(default_factory=lambda: {
        "journal": "journal",
        "knowledge": "knowledge",
        "experience": "experience/records",
        "experience_patterns": "experience/patterns",
        "incidents": "incidents",
        "schedule": "state/schedule_state.json",
        "archive": "archive",
        "rules": "rules",
        "performance": "performance",
    })

    @property
    def memory_dir(self) -> Path:
        return Path(self.base_dir) / "memory"

    def resolve(self, key: str) -> Path:
        """解析逻辑路径为绝对 Path"""
        relative = self.paths.get(key)
        if relative is None:
            raise KeyError(f"Unknown path key: {key}")
        return self.memory_dir / relative

    def storage_limit_bytes(self) -> int:
        return self.max_storage_mb * 1024 * 1024
