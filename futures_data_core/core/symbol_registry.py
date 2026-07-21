"""品种注册与映射 [INDEPENDENT]。

从 ``config/symbol_map.yaml`` 加载品种元数据，提供查询与列表能力。
纯配置查询，不依赖任何外部服务或 LLM。
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Optional

import yaml

# 配置目录：相对本文件上一层 config/
_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
_SYMBOL_MAP_PATH = os.path.join(_CONFIG_DIR, "symbol_map.yaml")

# 正则：从 "SM2609" 提取 ("SM", "2609")
_CONTRACT_SUFFIX_RE = re.compile(r"^([A-Za-z]{1,6})(\d{3,4})$")


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


def strip_contract_suffix(symbol: str) -> tuple[str, Optional[str]]:
    """解析品种代码，分离品种与合约月份后缀。

    ``"SM2609"`` -> (``"SM"``, ``"2609"``)
    ``"SM"``     -> (``"SM"``, None)

    Args:
        symbol: 品种代码（可含合约月份后缀）。

    Returns:
        ``(variety_code, contract_suffix)``。
    """
    m = _CONTRACT_SUFFIX_RE.match(symbol.upper())
    if m:
        return m.group(1), m.group(2)
    return symbol, None


def get_symbol(symbol: str) -> Optional[dict]:
    """按代码查询品种元数据。

    自动剥离合约月份后缀：``"SM2609"`` 自动降级为 ``"SM"`` 查询。

    Args:
        symbol: 品种代码（如 ``"CU"``、``"SM2609"``）。

    Returns:
        元数据 dict；不存在返回 ``None``。
    """
    reg = _registry()
    sym_upper = symbol.upper()
    # 精确匹配优先
    result = reg.get(sym_upper)
    if result is not None:
        return result
    # 含合约后缀（如 SM2609），剥离后重查
    bare, _ = strip_contract_suffix(sym_upper)
    if bare != sym_upper:
        return reg.get(bare)
    return None


# ── TqSDK 符号格式转换 ──────────────────────────────────────

# TqSDK 品种 -> 交易所映射
_TQ_EXCHANGE_MAP: dict[str, str] = {
    "CU": "SHFE", "AL": "SHFE", "ZN": "SHFE", "PB": "SHFE",
    "NI": "SHFE", "SN": "SHFE", "AU": "SHFE", "AG": "SHFE",
    "RB": "SHFE", "HC": "SHFE", "SS": "SHFE", "RU": "SHFE",
    "BR": "SHFE", "FU": "SHFE", "BU": "SHFE", "SP": "SHFE",
    "WR": "SHFE", "AO": "SHFE",
    "A": "DCE", "B": "DCE", "M": "DCE", "Y": "DCE", "C": "DCE",
    "P": "DCE", "J": "DCE", "JM": "DCE", "I": "DCE", "L": "DCE",
    "PP": "DCE", "V": "DCE", "JD": "DCE", "RR": "DCE", "LH": "DCE",
    "EB": "DCE", "EG": "DCE", "PG": "DCE",
    "SR": "CZCE", "CF": "CZCE", "TA": "CZCE", "OI": "CZCE",
    "RM": "CZCE", "MA": "CZCE", "FG": "CZCE",
    "SF": "CZCE", "SM": "CZCE", "CY": "CZCE", "AP": "CZCE",
    "CJ": "CZCE", "UR": "CZCE", "SA": "CZCE", "PF": "CZCE",
    "PK": "CZCE", "PX": "CZCE", "SH": "CZCE", "PR": "CZCE",
    "PS": "CZCE",
    "SC": "INE", "LU": "INE", "NR": "INE", "BC": "INE",
    "SI": "GFEX", "LC": "GFEX",
}


def to_tqsdk_continuous(symbol: str) -> str:
    """将 FDT 品种代码转为 TqSDK 主力连续合约符号。

    ``"SM"`` -> ``"KQ.m@CZCE.SM"``
    ``"SM2609"`` -> ``"KQ.m@CZCE.SM"``（自动剥离合约月份）

    Args:
        symbol: 品种代码（可含合约月份后缀）。

    Returns:
        TqSDK 主力连续合约符号。
    """
    bare, _ = strip_contract_suffix(symbol.upper())
    ex = _TQ_EXCHANGE_MAP.get(bare)
    if not ex:
        return symbol
    # CZCE 合约代码大写，其它小写
    sym_part = bare if ex == "CZCE" else bare.lower()
    return f"KQ.m@{ex}.{sym_part}"


def to_tqsdk_contract(symbol: str) -> Optional[str]:
    """将 FDT 含合约月份的品种代码转为 TqSDK 实际合约符号。

    ``"SM2609"`` -> ``"CZCE.SM609"``（CZCE 短年格式）
    ``"PK2609"`` -> ``"CZCE.PK609"``
    ``"RB2510"`` -> ``"SHFE.rb2510"``

    Args:
        symbol: 含合约月份的品种代码（如 ``"SM2609"``）。

    Returns:
        TqSDK 实际合约符号，或 ``None``（无合约月份或品种未知）。
    """
    bare, contract = strip_contract_suffix(symbol.upper())
    if not contract:
        return None
    ex = _TQ_EXCHANGE_MAP.get(bare)
    if not ex:
        return None
    # CZCE: 合约月份只取后3位（如 2609 -> 609）
    if ex == "CZCE":
        contract_str = contract[-3:]
        sym_part = bare
    else:
        contract_str = contract
        sym_part = bare.lower()
    return f"{ex}.{sym_part}{contract_str}"


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
    """判断品种代码是否已知。

    自动剥离合约月份后缀：``"SM2609"`` 降级为 ``"SM"`` 判断。

    Args:
        symbol: 品种代码。

    Returns:
        是否已知。
    """
    bare, _ = strip_contract_suffix(symbol.upper())
    return bare in _registry()
