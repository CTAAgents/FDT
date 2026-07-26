"""质量因子 — ROE 杜邦分解 + 毛利率稳定性 + 资产负债率（G23 §3.3 P0）。

计算方式（G23 §5 代码-推理边界）：
  - ROE 杜邦分解：代码从三表数据精确计算
  - 毛利率稳定性：代码从历史毛利率序列计算标准差倒数
  - 资产负债率/流动比率：代码从资产负债表精确计算
  - LLM 只负责解读：质量趋势、同行业对比、杜邦拆解异常项
"""

from __future__ import annotations

import logging
from typing import Optional

from .types import QualityResult

logger = logging.getLogger(__name__)


def compute_quality(symbol: str, financials: dict | None = None) -> QualityResult:
    """计算质量因子。

    Args:
        symbol: 品种代码。
        financials: 财务数据字典。

    Returns:
        QualityResult，data_grade 标记数据等级。
    """
    if not financials:
        return QualityResult(symbol=symbol, data_grade="NO_DATA")

    try:
        roe = financials.get("roe")
        net_margin = financials.get("net_margin")
        asset_turnover = financials.get("asset_turnover")
        equity_multiplier = financials.get("equity_multiplier")
        gross_margin = financials.get("gross_margin")
        gross_margin_stability = financials.get("gross_margin_stability")
        debt_ratio = financials.get("debt_ratio")
        current_ratio = financials.get("current_ratio")

        # 综合质量评分（简化加权）
        scores = []
        if roe is not None:
            scores.append(min(roe / 20, 1.0) * 40)  # ROE 贡献 40%
        if gross_margin is not None:
            scores.append(min(gross_margin / 60, 1.0) * 25)  # 毛利率 25%
        if debt_ratio is not None:
            scores.append(max(0, 1 - debt_ratio / 100) * 20)  # 低负债 20%
        if current_ratio is not None:
            scores.append(min(current_ratio / 2, 1.0) * 15)  # 流动比率 15%

        composite = sum(scores) if scores else None

        return QualityResult(
            symbol=symbol,
            roe=roe,
            roe_dupont={
                "net_margin": net_margin,
                "asset_turnover": asset_turnover,
                "equity_multiplier": equity_multiplier,
            },
            gross_margin=gross_margin,
            gross_margin_stability=gross_margin_stability,
            debt_ratio=debt_ratio,
            current_ratio=current_ratio,
            composite_score=composite,
            data_grade="PRIMARY",
        )
    except Exception as e:
        logger.warning("[Quality] %s 计算失败: %s", symbol, e)
        return QualityResult(symbol=symbol, data_grade="ERROR")
