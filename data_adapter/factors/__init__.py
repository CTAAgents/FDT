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
    FactorMatrixResult,
    FactorSignal,
    GrowthResult,
    DividendResult,
    HoldingSentimentResult,
    MomentumResult,
    QualityResult,
    TermStructureResult,
    ValueResult,
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
        money_flow: dict[str, dict] | None = None,
        north_flow: dict[str, dict] | None = None,
        etf_premium: dict[str, dict] | None = None,
    ) -> FactorDashboardResult:
        """构建多因子信号一致性看板。"""
        from .dashboard import build_dashboard
        return build_dashboard(symbols, term_structure, volatility,
                               holding_sentiment, cross_spreads,
                               money_flow=money_flow,
                               north_flow=north_flow,
                               etf_premium=etf_premium)

    def build_matrix(self, dashboard: FactorDashboardResult) -> FactorMatrixResult:
        """将看板升级为因子信号矩阵（G23 FactorMatrixResult）。"""
        from .dashboard import build_matrix
        return build_matrix(dashboard)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    # ── G23 新增因子模块骨架 ──

    def compute_value(self, symbol: str, financials: dict | None = None) -> ValueResult:
        """计算价值因子（PE/PB/PS 历史分位 + EV/EBITDA）。"""
        from .value import compute_value
        return compute_value(symbol, financials)

    def compute_quality(self, symbol: str, financials: dict | None = None) -> QualityResult:
        """计算质量因子（ROE 杜邦分解 + 毛利率 + 负债率）。"""
        from .quality import compute_quality
        return compute_quality(symbol, financials)

    def compute_momentum(self, symbol: str, closes: list[float] | None = None) -> MomentumResult:
        """计算动量因子（时序动量 12-1M/6M/3M）。"""
        from .momentum import compute_momentum
        return compute_momentum(symbol, closes)

    def compute_momentum_batch(self, data: dict[str, list[float]]) -> dict[str, MomentumResult]:
        """批量计算动量因子（含截面排序 + 残差动量）。"""
        from .momentum import compute_momentum_batch
        return compute_momentum_batch(data)

    def compute_growth(self, symbol: str, financials: dict | None = None) -> GrowthResult:
        """计算成长因子（营收/利润增长率）。"""
        from .growth import compute_growth
        return compute_growth(symbol, financials)

    def compute_dividend(self, symbol: str, financials: dict | None = None) -> DividendResult:
        """计算红利因子（股息率/分红支付率/稳定性）。"""
        from .dividend import compute_dividend
        return compute_dividend(symbol, financials)


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
