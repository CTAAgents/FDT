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
    """市场类型枚举"""
    COMMODITY_FUTURES = "commodity_futures"  # 商品期货（现有）
    INDEX_FUTURES = "index_futures"          # 股指期货
    BOND_FUTURES = "bond_futures"            # 国债期货
    ETF = "etf"                               # ETF


# ── 分类规则 ─────────────────────────────────────────

# 股指期货代码
_INDEX_FUTURES_SYMBOLS = {"IF", "IC", "IH", "IM"}

# 国债期货代码
_BOND_FUTURES_SYMBOLS = {"T", "TF", "TS", "TL"}

# ETF 后缀
_ETF_SUFFIXES = (".SH", ".SZ")

# ETF 代码数字范围（上海 51xxxx, 深圳 15xxxx/16xxxx）
_ETF_CODE_PATTERNS = [
    lambda s: s.startswith("51") and len(s) == 6,   # 上交所 ETF (510xxx)
    lambda s: s.startswith("58") and len(s) == 6,   # 上交所 ETF (588xxx 科创板)
    lambda s: s.startswith("159") and len(s) == 6,  # 深交所 ETF
    lambda s: s.startswith("16") and len(s) == 6,   # 深交所 LOF/ETF
]


def _is_etf_code(symbol: str) -> bool:
    """判断是否为 ETF 代码（无后缀版本）"""
    clean = symbol.replace(".SH", "").replace(".SZ", "")
    if not clean.isdigit():
        return False
    return any(pattern(clean) for pattern in _ETF_CODE_PATTERNS)


def classify(symbol: str) -> MarketType:
    """识别品种的市场类型

    Args:
        symbol: 品种代码，不区分大小写（如 "IF", "RB", "510050.SH"）

    Returns:
        MarketType 枚举值

    Example:
        >>> classify("IF")       # → INDEX_FUTURES
        >>> classify("T")        # → BOND_FUTURES
        >>> classify("RB")       # → COMMODITY_FUTURES
        >>> classify("510050")   # → ETF
        >>> classify("159915")   # → ETF
    """
    sym_upper = symbol.upper().strip()

    # 1. 股指期货
    if sym_upper in _INDEX_FUTURES_SYMBOLS:
        return MarketType.INDEX_FUTURES

    # 2. 国债期货
    if sym_upper in _BOND_FUTURES_SYMBOLS:
        return MarketType.BOND_FUTURES

    # 3. ETF（含后缀或无后缀）
    if sym_upper.endswith(_ETF_SUFFIXES) or _is_etf_code(sym_upper):
        return MarketType.ETF

    # 4. 默认：商品期货
    return MarketType.COMMODITY_FUTURES


def get_market_label(market_type: MarketType) -> str:
    """返回市场类型的中文标签"""
    labels = {
        MarketType.COMMODITY_FUTURES: "商品期货",
        MarketType.INDEX_FUTURES: "股指期货",
        MarketType.BOND_FUTURES: "国债期货",
        MarketType.ETF: "ETF",
    }
    return labels.get(market_type, "未知")
