"""Redis 缓存后端（L1 热缓存 + 跨副本失效广播）[INDEPENDENT]。

需 redis-py（可选依赖 ``[distributed]``）；库未装 / 连接失败 / 未配置 URL 时
``build_redis_backend`` 返回 ``None``，由 ``CacheStore`` 回退 Memory。

连接参数：环境变量 ``FDC_REDIS_URL`` 或 settings.redis_url。
"""

from __future__ import annotations

import os
import pickle
from typing import Any, Optional

from futures_data_core.config.settings import get_settings


def _redis_available() -> bool:
    """探测 redis 是否可导入。"""
    try:
        __import__("redis")
        return True
    except ImportError:
        return False


class RedisBackend:
    """Redis 缓存后端（热缓存 + pub/sub 失效广播）。"""

    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.from_url(url, decode_responses=False)
        self._r.ping()

    async def get(self, key: str) -> Any | None:
        raw = self._r.get(key)
        if raw is None:
            return None
        return pickle.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        self._r.set(key, pickle.dumps(value), ex=int(ttl_seconds))

    async def invalidate(self, key: str) -> None:
        self._r.delete(key)
        # 跨副本失效广播
        try:
            self._r.publish("fdc_cache_invalidate", key)
        except Exception:
            pass

    async def purge(self) -> int:
        # Redis 自带 TTL 过期，无显式清过期需求
        return 0


def build_redis_backend() -> Optional[RedisBackend]:
    """构造 Redis 后端；不可用（库缺失 / 无 URL / 连接失败）返回 None。"""
    if not _redis_available():
        return None
    url = os.environ.get("FDC_REDIS_URL") or get_settings().redis_url
    if not url:
        return None
    try:
        return RedisBackend(url)
    except Exception:
        return None
