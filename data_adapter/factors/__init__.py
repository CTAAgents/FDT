"""因子数据适配层 — P2.5 多因子注入

用法：
    collector = FactorCollector()
    await collector.collect_all(selected_symbols, kline_data)

架构：
    FactorCollector 聚合入口 → 按需调用各因子计算模块
    → 产出统一 FactorResult dict，供 node_prepare_data() 注入 state
"""

from __future__ import annotations

import logging
from typing import Optional

from .types import (
    CrossSpreadResult,
    FactorDashboardResult,
    FactorSignal,
    HoldingSentimentResult,
    TermStructureResult,
    VolatilityResult,
)

logger = logging.getLogger(__name__)


class FactorCollector:
    """因子采集器 — 统一入口，管理各因子模块的采集与聚合。"""

    def __init__(self):
        self._errors: list[str] = []

    async def collect_term_structure(self, symbols: list[str]) -> dict[str, TermStructureResult]:
        """采集期限结构因子。"""
        from .term_structure import collect_term_structure

        return await collect_term_structure(symbols)

    async def collect_holding_sentiment(self, symbols: list[str]) -> dict[str, HoldingSentimentResult]:
        """采集多空持仓因子。"""
        from .holding_sentiment import collect_holding_sentiment

        return await collect_holding_sentiment(symbols)

    def compute_volatility(self, symbols: list[str], kline_data: dict) -> dict[str, VolatilityResult]:
        """计算波动率因子（纯计算，从 K 线）。"""
        from .volatility import compute_volatility

        return compute_volatility(symbols, kline_data)

    def compute_cross_spreads(self, symbols: list[str], kline_data: dict) -> list[CrossSpreadResult]:
        """计算跨品种价差（纯计算，从 K 线）。"""
        from .cross_spread import compute_cross_spreads

        pairs = _DEFAULT_PAIRS
        return compute_cross_spreads(symbols, kline_data, pairs)

    def build_dashboard(
        self,
        symbols: list[str],
        term_structure: dict[str, TermStructureResult],
        volatility: dict[str, VolatilityResult],
        holding_sentiment: dict[str, HoldingSentimentResult],
        cross_spreads: list[CrossSpreadResult],
    ) -> FactorDashboardResult:
        """构建多因子信号一致性看板。"""
        from .dashboard import build_dashboard

        return build_dashboard(symbols, term_structure, volatility, holding_sentiment, cross_spreads)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)


# ── 默认配置（与设计文档对齐） ──

_DEFAULT_PAIRS: list[tuple[str, str]] = [
    ("RB", "HC"),
    ("J", "JM"),
    ("M", "RM"),
    ("Y", "P"),
    ("SC", "FU"),
    ("TA", "EG"),
    ("MA", "PP"),
]
