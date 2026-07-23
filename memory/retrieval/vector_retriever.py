"""VectorMemory 封装 — 修复检索断层"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class VectorRetriever:
    """封装 VectorMemory 的历史相似案例检索"""

    def __init__(self, memory_dir: Path):
        self._memory_dir = memory_dir
        self._vector_memory = None
        self._initialized = False

    def query(self, symbol: str, top_k: int = 3,
              regime: str | None = None) -> list[dict]:
        """基于 VectorMemory 查询历史相似案例"""
        vm = self._get_vector_memory()
        if vm is None:
            return []
        try:
            return vm.query(symbol, regime=regime, top_k=top_k)
        except Exception as e:
            logger.debug(f"VectorMemory query failed (non-fatal): {e}")
            return []

    def _get_vector_memory(self):
        """懒初始化 VectorMemory"""
        if self._initialized:
            return self._vector_memory
        self._initialized = True
        try:
            from scripts.vector_memory import VectorMemory
            self._vector_memory = VectorMemory()
        except Exception as e:
            logger.debug(f"VectorMemory init failed (non-fatal): {e}")
            self._vector_memory = None
        return self._vector_memory
