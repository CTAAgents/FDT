# -*- coding: utf-8 -*-
"""跨品种联动特征 — 板块内/跨板块的滚动相关系数计算。

功能：
- calc_correlation(): 两个品种的滚动皮尔逊相关系数
- get_correlation_peers(): 获取某品种的关联品种及相关系数
- build_correlation_matrix(): 构建品种相关性矩阵
- 输出可作为技术Agent预测模型的额外输入特征
"""

import math
from typing import Dict, List, Optional, Tuple

# ── 品种板块映射（与event_calendar共享） ──
SECTOR_MAP = {
    "黑色": ["RB", "HC", "I", "J", "JM", "SM", "SF"],
    "有色": ["CU", "AL", "ZN", "PB", "NI", "SN"],
    "贵金属": ["AU", "AG"],
    "化工油化": ["SC", "BU", "LU", "FU", "MA", "EB", "PP", "L", "V"],
    "化工聚酯": ["TA", "EG", "PF", "PR", "RU", "NR"],
    "农产品油粕": ["M", "RM", "Y", "P", "OI", "C", "CS"],
    "农产品其他": ["A", "B", "AP", "CJ", "PK", "LH", "JD"],
    "软商品": ["SR", "CF", "CY", "ZC"],
    "股指": ["IF", "IH", "IC"],
    "国债": ["T", "TF", "TS"],
}


def calc_correlation(
    prices1: List[float],
    prices2: List[float],
    window: int = 20,
) -> Tuple[float, float, int]:
    """计算两个品种的滚动皮尔逊相关系数。

    Args:
        prices1: 品种1的价格序列（最近的在最后）
        prices2: 品种2的价格序列
        window: 滚动窗口（默认20）

    Returns:
        (correlation, p_value, n): 相关系数(-1~1), 近似p值, 样本数
    """
    n = min(len(prices1), len(prices2), window)
    if n < 5:
        return (0.0, 1.0, 0)

    p1 = prices1[-n:]
    p2 = prices2[-n:]

    # 转日收益率
    r1 = [(p1[i] - p1[i - 1]) / p1[i - 1] if p1[i - 1] != 0 else 0 for i in range(1, n)]
    r2 = [(p2[i] - p2[i - 1]) / p2[i - 1] if p2[i - 1] != 0 else 0 for i in range(1, n)]

    m = len(r1)
    if m < 4:
        return (0.0, 1.0, 0)

    mean1 = sum(r1) / m
    mean2 = sum(r2) / m

    cov = sum((r1[i] - mean1) * (r2[i] - mean2) for i in range(m))
    var1 = sum((r1[i] - mean1) ** 2 for i in range(m))
    var2 = sum((r2[i] - mean2) ** 2 for i in range(m))

    if var1 == 0 or var2 == 0:
        return (0.0, 1.0, m)

    corr = cov / (math.sqrt(var1) * math.sqrt(var2))
    corr = max(-1.0, min(1.0, corr))

    # 近似p值（t分布）
    t_stat = corr * math.sqrt((m - 2) / max(1 - corr * corr, 0.001))
    p_value = 2 * (1 - _t_cdf(abs(t_stat), m - 2))

    return (round(corr, 3), round(p_value, 4), m)


def _t_cdf(t: float, df: int) -> float:
    """近似t分布的CDF（用正态近似+修正）"""
    if df <= 0:
        return 0.5
    x = t / math.sqrt(df)
    # 用 logistic 近似
    return 1.0 / (1.0 + math.exp(-1.702 * t * (1 - 0.5 / df)))


def get_sector(symbol: str) -> str:
    """查询品种所属板块"""
    for sector, symbols in SECTOR_MAP.items():
        if symbol in symbols:
            return sector
    return "未知"


def get_correlation_peers(
    symbol: str,
    all_prices: Dict[str, List[float]],
    window: int = 20,
    min_corr: float = 0.3,
    max_peers: int = 5,
) -> List[Dict]:
    """获取某品种的关联品种及相关系数（仅同板块内）。

    Args:
        symbol: 目标品种
        all_prices: {"RB": [p1, p2, ...], ...}
        window: 窗口
        min_corr: 最低相关系数阈值
        max_peers: 最多返回关联数

    Returns:
        [{"symbol": str, "correlation": float, "sector": str}, ...]
    """
    sector = get_sector(symbol)
    if sector == "未知":
        return []

    peers = []
    my_prices = all_prices.get(symbol, [])
    if not my_prices:
        return []

    for sym in SECTOR_MAP.get(sector, []):
        if sym == symbol:
            continue
        their_prices = all_prices.get(sym, [])
        if len(their_prices) < window:
            continue
        corr, p_val, n = calc_correlation(my_prices, their_prices, window)
        if abs(corr) >= min_corr:
            peers.append({"symbol": sym, "correlation": corr, "p_value": p_val, "sector": sector})

    peers.sort(key=lambda x: -abs(x["correlation"]))
    return peers[:max_peers]


def build_correlation_matrix(
    all_prices: Dict[str, List[float]],
    symbols: Optional[List[str]] = None,
    window: int = 20,
) -> Dict[str, Dict[str, float]]:
    """构建品种相关性矩阵。

    Returns:
        {"RB": {"HC": 0.85, "I": 0.65, ...}, ...}
    """
    if symbols is None:
        symbols = list(all_prices.keys())

    matrix = {}
    for s1 in symbols:
        matrix[s1] = {}
        for s2 in symbols:
            if s1 == s2:
                matrix[s1][s2] = 1.0
            else:
                p1 = all_prices.get(s1, [])
                p2 = all_prices.get(s2, [])
                corr, _, _ = calc_correlation(p1, p2, window)
                matrix[s1][s2] = corr
    return matrix
