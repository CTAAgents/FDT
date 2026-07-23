"""MemoryManager 主类 — memory/ 目录的唯一读写入口"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from ..maintenance.archiver import Archiver
from ..maintenance.checker import Checker
from ..maintenance.cleaner import Cleaner
from ..maintenance.decay import Decay
from ..retrieval.historical_retriever import HistoricalRetriever
from ..retrieval.knowledge_retriever import KnowledgeRetriever
from ..retrieval.vector_retriever import VectorRetriever
from ..store.experience_store import ExperienceStore
from ..store.incident_store import IncidentStore
from ..store.journal_store import JournalStore
from ..store.knowledge_store import KnowledgeStore
from .config import MemoryConfig
from .schemas import (
    CURRENT_SCHEMA_VERSION,
    ExperienceEntry,
    GapReport,
    IncidentEntry,
    JournalEntry,
    KnowledgeEntry,
    MaintenanceReport,
    validate_schema,
)

logger = logging.getLogger(__name__)


class MemoryManager:
    """memory/ 目录的唯一读写入口

    - 所有 store/retrieve/maintenance 操作的统一门面
    - 不做过度抽象，直接委派给对应的 Store/Retriever/Maintenance 组件
    - 所有方法可独立使用，无强制调用顺序
    """

    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self.memory_dir = self.base_dir / "memory"
        self.config = MemoryConfig(base_dir=base_dir)

        # ── 存储层 ──
        self._journal_store = JournalStore(self.memory_dir)
        self._knowledge_store = KnowledgeStore(self.memory_dir)
        self._experience_store = ExperienceStore(self.memory_dir)
        self._incident_store = IncidentStore(self.memory_dir)

        # ── 检索层 ──
        self._vector_retriever = VectorRetriever(self.memory_dir)
        self._knowledge_retriever = KnowledgeRetriever(self.memory_dir)
        self._historical_retriever = HistoricalRetriever(self.memory_dir)

        # ── 维护层 ──
        self._cleaner = Cleaner(self.memory_dir)
        self._archiver = Archiver(self.memory_dir)
        self._decay = Decay(self.memory_dir)
        self._checker = Checker(self.memory_dir)

        # ── 上次维护时间 ──
        self._last_maintenance: str | None = None

        logger.info(
            f"MemoryManager initialized: {self.memory_dir} "
            f"(schema v{CURRENT_SCHEMA_VERSION})"
        )

    # ═══════════════════════════════════════════════════
    # 写入方法
    # ═══════════════════════════════════════════════════

    def store_journal(self, entry: JournalEntry) -> str:
        """写入辩论日志 → journal/debate_journal.json + SQLite 双写"""
        return self._journal_store.store(entry)

    def store_knowledge(self, entry: KnowledgeEntry) -> None:
        """写入品种知识 → knowledge/{symbol}/ 目录"""
        self._knowledge_store.store(entry)

    def store_experience(self, entry: ExperienceEntry) -> None:
        """写入经验记录 → experience/records/{symbol}.json"""
        self._experience_store.store(entry)

    def store_incident(self, entry: IncidentEntry) -> None:
        """写入事故 → incidents/incidents.md（追加模式）"""
        self._incident_store.store(entry)

    def store_schedule(self, task: str, state: dict) -> None:
        """持久化调度状态 → state/schedule_state.json"""
        self._journal_store.store_schedule(task, state)

    # ═══════════════════════════════════════════════════
    # 检索方法
    # ═══════════════════════════════════════════════════

    def retrieve_similar(self, symbol: str, top_k: int = 3,
                         regime: str | None = None) -> list[dict]:
        """基于 VectorMemory 的历史相似案例检索"""
        return self._vector_retriever.query(symbol, top_k, regime)

    def retrieve_journal(self, symbol: str | None = None,
                         limit: int = 10) -> list[JournalEntry]:
        """查询辩论历史"""
        return self._journal_store.query(symbol, limit)

    def retrieve_knowledge(self, symbol: str) -> KnowledgeEntry | None:
        """查询品种知识"""
        return self._knowledge_retriever.query(symbol)

    def retrieve_experience(self, symbol: str) -> list[ExperienceEntry]:
        """查询经验记录"""
        return self._experience_store.query(symbol)

    def retrieve_schedule(self) -> dict:
        """读取调度状态"""
        path = self.memory_dir / "state" / "schedule_state.json"
        if not path.exists():
            return {}
        import json
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    # ═══════════════════════════════════════════════════
    # 维护方法
    # ═══════════════════════════════════════════════════

    def run_maintenance(self) -> MaintenanceReport:
        """执行一次完整的维护周期（清理 + 归档 + 老化）"""
        now = datetime.now(timezone.utc)

        report: MaintenanceReport = {
            "timestamp": now.isoformat(),
            "cleaned_journals": 0,
            "archived_items": 0,
            "decayed_patterns": [],
            "storage_before_mb": 0.0,
            "storage_after_mb": 0.0,
        }

        # 清理
        report["cleaned_journals"] = self._cleaner.clean(
            self.config.journal_max_age_days
        )

        # 归档
        report["archived_items"] = self._archiver.archive()

        # 知识老化
        report["decayed_patterns"] = self._decay.run(
            self.config.knowledge_decay_days
        )

        # 存储统计
        report["storage_before_mb"] = self._calc_storage_mb()
        report["storage_after_mb"] = self._calc_storage_mb()

        self._last_maintenance = now.isoformat()
        logger.info(f"Maintenance complete: {report}")
        return report

    def check_gaps(self) -> GapReport:
        """检查记忆系统缺口"""
        return self._checker.run()

    def migrate_from_legacy(self) -> int:
        """从旧格式迁移到新 Schema，返回迁移条目数"""
        count = 0
        count += self._journal_store.migrate_from_legacy()
        count += self._knowledge_store.migrate_from_legacy()
        count += self._experience_store.migrate_from_legacy()
        logger.info(f"Legacy migration complete: {count} entries updated")
        return count

    def get_stats(self) -> dict:
        """获取记忆系统统计信息"""
        journal_entries = len(self._journal_store.load_all())
        knowledge_symbols = len(self._knowledge_store.list_symbols())
        experience_symbols = len(self._experience_store.list_symbols())
        storage_mb = self._calc_storage_mb()

        return {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "journal_entries": journal_entries,
            "knowledge_symbols": knowledge_symbols,
            "experience_symbols": experience_symbols,
            "storage_mb": round(storage_mb, 1),
            "last_maintenance": self._last_maintenance or "never",
            "memory_dir": str(self.memory_dir),
        }

    # ── 内部方法 ─────────────────────────────────────

    def _calc_storage_mb(self) -> float:
        """计算 memory/ 目录总存储（JSON + DB + MD）"""
        total = 0
        for f in self.memory_dir.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".db", ".md", ".py"):
                total += f.stat().st_size
        return total / (1024 * 1024)
