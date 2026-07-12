"""缓存引擎 [INDEPENDENT]。

缓存后端可插拔：
  - ``MemoryBackend``：进程内字典（默认 / 无中间件回退，零依赖）
  - ``PostgresBackend``：L2 持久共享（可选依赖 psycopg2）
  - ``RedisBackend``：L1 热缓存 + 跨副本失效广播（可选依赖 redis）

``CacheStore`` 按 ``FDC_CACHE_BACKEND`` 装配后端；未配置或后端库 / 服务不可用时
自动回退 ``MemoryBackend``（与现有降级哲学一致）。
全链路数据库缓存 = Postgres + Redis；临时事务见 ``core.txn_store``（SQLite）。
"""

from __future__ import annotations

import pickle
import time
from typing import Any, Optional

from futures_data_core.config.settings import get_settings


class MemoryBackend:
    """进程内字典后端（零依赖，默认 / 回退）。"""

    def __init__(self) -> None:
        self._mem: dict[str, tuple[bytes, float]] = {}

    async def get(self, key: str) -> Any | None:
        item = self._mem.get(key)
        if item is None:
            return None
        value, expires = item
        if expires < time.time():
            self._mem.pop(key, None)
            return None
        return pickle.loads(value)

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        self._mem[key] = (pickle.dumps(value), time.time() + ttl_seconds)

    async def invalidate(self, key: str) -> None:
        self._mem.pop(key, None)

    async def purge(self, now: Optional[float] = None) -> int:
        now = now if now is not None else time.time()
        expired = [k for k, (_, e) in self._mem.items() if e < now]
        for k in expired:
            self._mem.pop(k, None)
        return len(expired)


def _build_backends(spec: str) -> list:
    """按 ``FDC_CACHE_BACKEND`` 规格（如 'redis+postgres'）装配后端。

    不可用的后端（库未装 / 连接失败 / 未配置 DSN）被跳过；最终至少保留
    ``MemoryBackend`` 以保证可用。
    """
    backends: list = []
    for part in [p.strip().lower() for p in spec.split("+") if p.strip()]:
        if part in ("memory", "mem"):
            backends.append(MemoryBackend())
        elif part == "redis":
            from futures_data_core.core.backends.redis import build_redis_backend

            b = build_redis_backend()
            if b is not None:
                backends.append(b)
        elif part == "postgres":
            from futures_data_core.core.backends.postgres import build_postgres_backend

            b = build_postgres_backend()
            if b is not None:
                backends.append(b)
        # 未知后端名：容错忽略
    if not backends:
        backends.append(MemoryBackend())
    return backends


class CacheStore:
    """异步缓存存储（可插拔后端编排）。

    写：所有后端均写入（共享层一致）。读：顺序尝试后端，首个命中即返回。
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        ttl_hours: float = 4.0,
        backend: Any = None,
        backend_spec: Optional[str] = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_hours * 3600.0
        if backend is not None:
            self._backends = [backend]
        else:
            spec = backend_spec if backend_spec is not None else get_settings().cache_backend
            self._backends = _build_backends(spec)
        self.has_shared = any(
            type(b).__name__ in ("PostgresBackend", "RedisBackend") for b in self._backends
        )

    async def get(self, key: str, now: Optional[float] = None) -> Any | None:
        for b in self._backends:
            val = await b.get(key)
            if val is not None:
                return val
        return None

    async def set(self, key: str, value: Any, ttl_hours: Optional[float] = None) -> None:
        ttl = (ttl_hours if ttl_hours is not None else self.ttl_seconds / 3600.0) * 3600.0
        for b in self._backends:
            await b.set(key, value, ttl)

    async def invalidate(self, key: str) -> None:
        for b in self._backends:
            await b.invalidate(key)

    async def purge(self, ttl_hours: Optional[float] = None) -> int:
        total = 0
        for b in self._backends:
            if hasattr(b, "purge"):
                total += await b.purge()
        return total


_DEFAULT_STORE: Optional[CacheStore] = None


def make_cache_store(
    ttl_hours: Optional[float] = None,
    cache_dir: Optional[str] = None,
    backend_spec: Optional[str] = None,
) -> CacheStore:
    """构造缓存存储（进程级默认单例的工厂）。"""
    s = get_settings()
    return CacheStore(
        cache_dir=cache_dir or s.cache_dir,
        ttl_hours=ttl_hours if ttl_hours is not None else s.ttl_hours,
        backend_spec=backend_spec,
    )


def get_default_store() -> CacheStore:
    """返回进程级默认缓存单例（惰性创建）。"""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = make_cache_store()
    return _DEFAULT_STORE


def reset_default_store() -> None:
    """重置默认单例（主要用于测试隔离）。"""
    global _DEFAULT_STORE
    _DEFAULT_STORE = None
