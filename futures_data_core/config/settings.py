"""运行参数配置 [INDEPENDENT]。

配置来源（优先级从低到高）：
  1. ``data_sources.yaml`` 中的缓存 / 数据源声明
  2. 环境变量（``FDC_CACHE_DIR`` / ``FDC_TTL_HOURS`` / ``FDC_DEFAULT_SOURCE`` /
     ``FDC_LOG_LEVEL`` / ``FDC_CACHE_BACKEND`` / ``FDC_TXN_BACKEND`` /
     ``FDC_PG_DSN`` / ``FDC_REDIS_URL``）

缓存后端（门禁 B）：
  - ``FDC_CACHE_BACKEND``（默认 ``memory``）：全链路数据库缓存 = ``postgres+redis``，
    本地无中间件时 ``memory`` 回退。
  - ``FDC_TXN_BACKEND``（默认 ``sqlite``）：临时事务（SQLite）/ ``memory``。

设计原则：
  - 不引入 pydantic 等重依赖，纯标准库 + PyYAML（已声明为主依赖）。
  - ``get_settings()`` 进程内缓存，避免重复读取文件。
  - 解析失败（如 TTL 非数字）安全降级为默认值，不抛异常。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
_DEFAULT_YAML = os.path.join(_CONFIG_DIR, "data_sources.yaml")


@dataclass
class Settings:
    """运行参数集合（全部可经环境变量覆盖）。"""

    cache_dir: str = "~/.fdc_cache"
    ttl_hours: float = 4.0
    default_source: str = "auto"
    log_level: str = "INFO"
    cache_backend: str = "memory"
    txn_backend: str = "sqlite"
    pg_dsn: str = ""
    redis_url: str = ""
    degrade: dict = field(default_factory=dict)
    freshness: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str = _DEFAULT_YAML) -> "Settings":
        """从 YAML 文件加载配置，环境变量覆盖默认值。"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        sources = data.get("sources", [])

        cache_dir = os.environ.get("FDC_CACHE_DIR", "~/.fdc_cache")
        try:
            ttl = float(os.environ.get("FDC_TTL_HOURS", 4.0))
        except (TypeError, ValueError):
            ttl = 4.0

        return cls(
            cache_dir=cache_dir,
            ttl_hours=ttl,
            default_source=os.environ.get("FDC_DEFAULT_SOURCE", "auto"),
            log_level=os.environ.get("FDC_LOG_LEVEL", "INFO").upper(),
            cache_backend=os.environ.get("FDC_CACHE_BACKEND", "memory"),
            txn_backend=os.environ.get("FDC_TXN_BACKEND", "sqlite"),
            pg_dsn=os.environ.get("FDC_PG_DSN", ""),
            redis_url=os.environ.get("FDC_REDIS_URL", ""),
            degrade=data.get("degrade", {}) or {},
            freshness=data.get("freshness", {}) or {},
            sources=sources,
        )

    def to_dict(self) -> dict:
        """序列化为普通 dict（便于调试 / 测试断言）。"""
        return {
            "cache_dir": self.cache_dir,
            "ttl_hours": self.ttl_hours,
            "default_source": self.default_source,
            "log_level": self.log_level,
            "cache_backend": self.cache_backend,
            "txn_backend": self.txn_backend,
            "pg_dsn": self.pg_dsn,
            "redis_url": self.redis_url,
            "degrade": self.degrade,
            "freshness": self.freshness,
            "sources": self.sources,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程级缓存的 :class:`Settings` 单例。"""
    return Settings.from_yaml()


def reload_settings() -> None:
    """清空缓存，强制下次调用重新读取配置文件。"""
    get_settings.cache_clear()
