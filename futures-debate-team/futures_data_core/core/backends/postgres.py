"""Postgres 缓存后端（L2 持久共享）[INDEPENDENT]。

需 psycopg2（可选依赖 ``[distributed]``）；库未装或连接失败 / 未配置 DSN 时
``build_postgres_backend`` 返回 ``None``，由 ``CacheStore`` 回退 Memory。

连接参数：环境变量 ``FDC_PG_DSN`` 或 settings.pg_dsn。
"""

from __future__ import annotations

import os
import pickle
import time
from typing import Any, Optional

from futures_data_core.config.settings import get_settings


def _pg_available() -> bool:
    """探测 psycopg2 是否可导入。"""
    try:
        __import__("psycopg2")
        return True
    except ImportError:
        return False


class PostgresBackend:
    """Postgres 缓存后端（持久共享 source of truth）。"""

    def __init__(self, dsn: str) -> None:
        import psycopg2

        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = True
        self._ensure_table()

    def _ensure_table(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS fdc_cache ("
                "key TEXT PRIMARY KEY, value BYTEA, expires BIGINT)"
            )

    async def get(self, key: str) -> Any | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT value, expires FROM fdc_cache WHERE key = %s", (key,))
            row = cur.fetchone()
        if row is None:
            return None
        value, expires = row
        if expires < time.time():
            await self.invalidate(key)
            return None
        return pickle.loads(value)

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        expires = int(time.time() + ttl_seconds)
        blob = pickle.dumps(value)
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO fdc_cache (key, value, expires) VALUES (%s, %s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                "expires = EXCLUDED.expires",
                (key, blob, expires),
            )

    async def invalidate(self, key: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM fdc_cache WHERE key = %s", (key,))

    async def purge(self) -> int:
        now = int(time.time())
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM fdc_cache WHERE expires < %s", (now,))
            count = cur.fetchone()[0]
            cur.execute("DELETE FROM fdc_cache WHERE expires < %s", (now,))
        return int(count)


def build_postgres_backend() -> Optional[PostgresBackend]:
    """构造 Postgres 后端；不可用（库缺失 / 无 DSN / 连接失败）返回 None。"""
    if not _pg_available():
        return None
    dsn = os.environ.get("FDC_PG_DSN") or get_settings().pg_dsn
    if not dsn:
        return None
    try:
        return PostgresBackend(dsn)
    except Exception:
        return None
