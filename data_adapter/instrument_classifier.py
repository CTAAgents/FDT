"""品种分类器 — 识别品种市场类型，路由到对应分析管线。

市场类型定义:
  - commodity_futures: 商品期货（现有，默认）
  - index_futures: 股指期货（IF/IC/IH/IM）
  - bond_futures: 国债期货（T/TF/TS/TL）
  - etf: ETF 基金

用法:
    from data_adapter.instrument_classifier import classify, MarketType
    mt = classify("IF")     # MarketType.INDEX_FUTURES
    mt = classify("RB")     # MarketType.COMMODITY_FUTURES
"""

from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class MarketType(str, Enum):
    """市场类型枚举（G23 扩展至 7 种）"""
    COMMODITY_FUTURES = "commodity_futures"  # 商品期货
    INDEX_FUTURES = "index_futures"          # 股指期货
    BOND_FUTURES = "bond_futures"            # 国债期货
    ETF = "etf"                               # ETF 基金
    STOCK = "stock"                           # A股个股 ← G23 新增
    REIT = "reit"                             # REITs ← G23 新增
    CONVERTIBLE_BOND = "convertible_bond"     # 可转债 ← G23 新增


# ── 分类规则 ─────────────────────────────────────────

# 股指期货代码
_INDEX_FUTURES_SYMBOLS = {"IF", "IC", "IH", "IM"}

# 国债期货代码
_BOND_FUTURES_SYMBOLS = {"T", "TF", "TS", "TL"}

# ETF 后缀
_ETF_SUFFIXES = (".SH", ".SZ")

# ETF 代码数字范围（上海 51xxxx/58xxxx, 深圳 159xxx/16xxxx）
_ETF_CODE_PATTERNS = [
    lambda s: s.startswith("51") and len(s) == 6,   # 上交所 ETF (510xxx)
    lambda s: s.startswith("58") and len(s) == 6,   # 上交所 ETF (588xxx 科创板)
    lambda s: s.startswith("159") and len(s) == 6,  # 深交所 ETF
    lambda s: s.startswith("16") and len(s) == 6,   # 深交所 LOF/ETF
]

# 股票代码规则（G23 新增）
_STOCK_CODE_PATTERNS = [
    lambda s: s.startswith("60") and len(s) == 6,   # 沪主板
    lambda s: s.startswith("68") and len(s) == 6,   # 沪科创板
    lambda s: s.startswith("00") and len(s) == 6,   # 深主板
    lambda s: s.startswith("30") and len(s) == 6,   # 深创业板
    lambda s: s.startswith("4") and len(s) == 6,    # 北交所
    lambda s: s.startswith("8") and len(s) == 6,    # 北交所
]

# REITs 代码规则（G23 新增）
_REIT_CODE_PATTERNS = [
    lambda s: s.startswith("180") and len(s) == 6,  # 深交所 REITs
    lambda s: s.startswith("508") and len(s) == 6,  # 上交所 REITs
]

# 可转债代码规则（G23 新增）
_CB_CODE_PATTERNS = [
    lambda s: s.startswith("11") and len(s) == 6,   # 沪可转债
    lambda s: s.startswith("12") and len(s) == 6,   # 深可转债
]


def _is_etf_code(symbol: str) -> bool:
    """判断是否为 ETF 代码（无后缀版本）"""
    clean = symbol.replace(".SH", "").replace(".SZ", "")
    if not clean.isdigit():
        return False
    return any(pattern(clean) for pattern in _ETF_CODE_PATTERNS)


def _is_stock_code(symbol: str) -> bool:
    """判断是否为 A股个股代码（G23）"""
    clean = symbol.replace(".SH", "").replace(".SZ", "")
    if not clean.isdigit():
        return False
    return any(pattern(clean) for pattern in _STOCK_CODE_PATTERNS)


def _is_reit_code(symbol: str) -> bool:
    """判断是否为 REITs 代码（G23）"""
    clean = symbol.replace(".SH", "").replace(".SZ", "")
    if not clean.isdigit():
        return False
    return any(pattern(clean) for pattern in _REIT_CODE_PATTERNS)


def _is_cb_code(symbol: str) -> bool:
    """判断是否为可转债代码（G23）"""
    clean = symbol.replace(".SH", "").replace(".SZ", "")
    if not clean.isdigit():
        return False
    return any(pattern(clean) for pattern in _CB_CODE_PATTERNS)


def _clean_suffix(symbol: str) -> str:
    """去除 .SH / .SZ 后缀"""
    return symbol.upper().strip().replace(".SH", "").replace(".SZ", "")


def classify(symbol: str) -> MarketType:
    """识别品种的市场类型（G23 扩展 7 种）

    Args:
        symbol: 品种代码，不区分大小写（如 "IF", "RB", "510050.SH", "600519"）

    Returns:
        MarketType 枚举值

    Example:
        >>> classify("IF")          # → INDEX_FUTURES
        >>> classify("RB")          # → COMMODITY_FUTURES
        >>> classify("510050")      # → ETF
        >>> classify("600519")      # → STOCK
        >>> classify("180801")      # → REIT
        >>> classify("110045")      # → CONVERTIBLE_BOND
    """
    sym_upper = symbol.upper().strip()

    # 1. 股指期货（字母代码）
    if sym_upper in _INDEX_FUTURES_SYMBOLS:
        return MarketType.INDEX_FUTURES

    # 2. 国债期货（字母代码）
    if sym_upper in _BOND_FUTURES_SYMBOLS:
        return MarketType.BOND_FUTURES

    # 清理后缀后按数字代码模式匹配（ETF/股票/REITs/可转债共用数字代码，不能仅靠后缀判断）
    clean = _clean_suffix(symbol)

    # 3. ETF（优先匹配 ETF 代码范围）
    if _is_etf_code(clean):
        return MarketType.ETF

    # 4. REITs（G23 新增 — 180xxx/508xxx）
    if _is_reit_code(clean):
        return MarketType.REIT

    # 5. 可转债（G23 新增 — 11xxxx/12xxxx）
    if _is_cb_code(clean):
        return MarketType.CONVERTIBLE_BOND

    # 6. A股个股（G23 新增）
    if _is_stock_code(clean):
        return MarketType.STOCK

    # 7. 默认：商品期货
    return MarketType.COMMODITY_FUTURES


def get_market_label(market_type: MarketType) -> str:
    """返回市场类型的中文标签"""
    labels = {
        MarketType.COMMODITY_FUTURES: "商品期货",
        MarketType.INDEX_FUTURES: "股指期货",
        MarketType.BOND_FUTURES: "国债期货",
        MarketType.ETF: "ETF",
        MarketType.STOCK: "A股个股",
        MarketType.REIT: "REITs",
        MarketType.CONVERTIBLE_BOND: "可转债",
    }
    return labels.get(market_type, "未知")
