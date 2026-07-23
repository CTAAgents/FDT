"""品种知识检索 — 封装 KnowledgeStore 的查询"""

from __future__ import annotations

from pathlib import Path

from ..manager.schemas import KnowledgeEntry
from ..store.knowledge_store import KnowledgeStore


class KnowledgeRetriever:
    """品种知识检索层"""

    def __init__(self, memory_dir: Path):
        self._store = KnowledgeStore(memory_dir)

    def query(self, symbol: str) -> KnowledgeEntry | None:
        """查询单个品种知识"""
        return self._store.query(symbol)

    def list_symbols(self) -> list[str]:
        """列出所有有知识记录的品种"""
        return self._store.list_symbols()

    def search_by_driver(self, keyword: str) -> list[dict]:
        """按驱动因子关键词搜索品种"""
        results = []
        for sym in self._store.list_symbols():
            entry = self._store.query(sym)
            if entry and entry.get("drivers"):
                for d in entry["drivers"]:
                    if keyword.lower() in d.get("name", "").lower():
                        results.append({"symbol": sym, "driver": d})
        return results
