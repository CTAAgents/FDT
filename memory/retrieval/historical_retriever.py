"""历史案例检索 — 从 journal 中检索相似案例"""

from __future__ import annotations

from pathlib import Path

from ..manager.schemas import JournalEntry
from ..store.journal_store import JournalStore


class HistoricalRetriever:
    """历史案例检索层"""

    def __init__(self, memory_dir: Path):
        self._store = JournalStore(memory_dir)

    def query_by_symbol(self, symbol: str, limit: int = 10) -> list[JournalEntry]:
        """按品种查询历史辩论"""
        return self._store.query(symbol, limit)

    def query_by_outcome(self, outcome: str, limit: int = 20) -> list[JournalEntry]:
        """按事后结果查询（hit_stop / hit_target / closed）"""
        all_entries = self._store.load_all()
        matched = [e for e in all_entries if e.get("outcome") == outcome]
        matched.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return matched[:limit]

    def get_recent(self, limit: int = 20) -> list[JournalEntry]:
        """获取最近 N 条辩论记录"""
        all_entries = self._store.load_all()
        all_entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return all_entries[:limit]
