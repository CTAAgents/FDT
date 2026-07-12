"""临时事务存储 [INDEPENDENT]。

临时事务（批处理暂存 / 中间聚合 / 回滚保护 / 事务性写缓冲）使用 SQLite
（标准库，零外部依赖）或进程内 MemoryTxnStore 回退。不跨副本共享，
任务结束即清 / 转存。详见实施计划书 §9.4（L0.5 临时事务层）。

配置：``FDC_TXN_BACKEND``（默认 ``sqlite``）；可选 ``memory``。
"""

from __future__ import annotations

import os
import pickle
import sqlite3
import tempfile
from typing import Any, Optional

from futures_data_core.config.settings import get_settings


class MemoryTxnStore:
    """进程内临时事务存储（零依赖回退）。"""

    def __init__(self) -> None:
        self._staging: dict[str, Any] = {}
        self._committed: dict[str, Any] = {}

    async def put(self, key: str, value: Any) -> None:
        self._staging[key] = value

    async def get(self, key: str) -> Any | None:
        if key in self._staging:
            return self._staging[key]
        return self._committed.get(key)

    async def commit(self) -> None:
        self._committed.update(self._staging)
        self._staging.clear()

    async def rollback(self) -> None:
        self._staging.clear()

    async def close(self) -> None:
        self._staging.clear()
        self._committed.clear()


class SqliteTxnStore:
    """SQLite 临时事务存储（嵌入式、强 ACID）。

    ``put`` 写入暂存区（未提交）；``commit`` 才落盘，``rollback`` 丢弃暂存，
    从而提供真实的事务隔离语义（回滚对未提交数据生效）。
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or os.path.join(tempfile.gettempdir(), f"fdc_txn_{os.getpid()}.db")
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS txn (key TEXT PRIMARY KEY, value BLOB)"
        )
        self._conn.commit()
        self._staging: dict[str, Any] = {}

    async def put(self, key: str, value: Any) -> None:
        self._staging[key] = value

    async def get(self, key: str) -> Any | None:
        if key in self._staging:
            return self._staging[key]
        cur = self._conn.execute("SELECT value FROM txn WHERE key = ?", (key,))
        row = cur.fetchone()
        return pickle.loads(row[0]) if row else None

    async def commit(self) -> None:
        for k, v in self._staging.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO txn (key, value) VALUES (?, ?)",
                (k, pickle.dumps(v)),
            )
        self._conn.commit()
        self._staging.clear()

    async def rollback(self) -> None:
        self._staging.clear()

    async def close(self) -> None:
        self._conn.close()
        if self._path and self._path.startswith(tempfile.gettempdir()):
            try:
                os.remove(self._path)
            except OSError:
                pass


def build_txn_store(backend: Optional[str] = None):
    """构造临时事务存储；默认按 ``FDC_TXN_BACKEND``（sqlite / memory）。"""
    spec = (backend or get_settings().txn_backend).strip().lower()
    if spec == "sqlite":
        return SqliteTxnStore()
    return MemoryTxnStore()
