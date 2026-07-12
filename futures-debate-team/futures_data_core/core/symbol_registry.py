"""品种注册与映射 [INDEPENDENT]。

从 ``config/symbol_map.yaml`` 加载品种元数据，提供查询与列表能力。
纯配置查询，不依赖任何外部服务或 LLM。
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import yaml

# 配置目录：相对本文件上一层 config/
_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
_SYMBOL_MAP_PATH = os.path.join(_CONFIG_DIR, "symbol_map.yaml")


def _load_symbols() -> list[dict]:
    """读取 symbol_map.yaml 并返回品种条目列表。"""
    with open(_SYMBOL_MAP_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("symbols", [])


@lru_cache(maxsize=1)
def _registry() -> dict:
    """构建 ``symbol -> 元数据`` 的缓存字典。"""
    return {item["symbol"]: item for item in _load_symbols()}


def reload() -> None:
    """清空缓存，强制下次查询重新加载配置。"""
    _registry.cache_clear()


def get_symbol(symbol: str) -> Optional[dict]:
    """按代码查询品种元数据。

    Args:
        symbol: 品种代码（如 ``"CU"``）。

    Returns:
        元数据 dict；不存在返回 ``None``。
    """
    return _registry().get(symbol.upper())


def list_symbols(exchange: Optional[str] = None) -> list[dict]:
    """列出品种。

    Args:
        exchange: 交易所过滤（如 ``"SHFE"``）；``None`` 返回全部。

    Returns:
        品种元数据列表。
    """
    items = list(_registry().values())
    if exchange:
        items = [i for i in items if i.get("exchange") == exchange]
    return items


def list_exchanges() -> list[str]:
    """返回所有出现的交易所代码列表（去重、保序）。"""
    seen: list[str] = []
    for item in _registry().values():
        ex = item.get("exchange")
        if ex and ex not in seen:
            seen.append(ex)
    return seen


def is_known(symbol: str) -> bool:
    """判断品种代码是否已知。"""
    return symbol.upper() in _registry()
