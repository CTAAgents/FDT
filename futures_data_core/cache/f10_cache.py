"""F10 静态缓存访问 [INDEPENDENT]。

提供对 ``cache/fundamental_cache/`` 下静态快照的读取入口，封装
:func:`~futures_data_core.f10.fundamentals._load_cache`，便于上层与缓存目录
路径解耦。静态缓存为预采集快照，标注 ``cached_at``，用户可手动替换。
"""

from __future__ import annotations

from typing import Optional

from futures_data_core.f10.fundamentals import CACHE_DIR as _DEFAULT_DIR
from futures_data_core.f10.fundamentals import _load_cache


def fundamental_cache_dir() -> str:
    """返回 F10 静态基本面缓存目录的绝对路径。"""
    return _DEFAULT_DIR


def load_fundamental(
    symbol: str, data_type: str = "all", cache_dir: Optional[str] = None
):
    """从静态缓存加载品种基本面。

    Args:
        symbol: 品种代码。
        data_type: ``supply`` / ``demand`` / ``inventory`` / ``margin`` / ``all``。
        cache_dir: 缓存目录覆盖；``None`` 用包内默认目录。

    Returns:
        合并后的 dict（含 ``cached_at``）；无匹配返回 ``None``。
    """
    return _load_cache(symbol, data_type, cache_dir or _DEFAULT_DIR)
