"""质量因子 — ROE 杜邦分解 + 毛利率稳定性 + 资产负债率（G23 §3.3 P0）。

计算方式（G23 §5 代码-推理边界）：
  - ROE 杜邦分解：代码从三表数据精确计算
  - 毛利率稳定性：代码从历史毛利率序列计算变异系数倒数
  - 资产负债率/流动比率：代码从资产负债表精确计算
  - 综合评分：代码加权聚合
  - LLM 只负责解读：质量趋势、同行业对比、杜邦拆解异常项
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .types import QualityResult

logger = logging.getLogger(__name__)


def _dupont_decompose(net_margin: float | None,
                      asset_turnover: float | None,
                      equity_multiplier: float | None) -> dict:
    """ROE 杜邦分解。

    ROE = 净利润率 × 资产周转率 × 权益乘数

    Returns:
        dict {net_margin, asset_turnover, equity_multiplier, roe_implied}
    """
    result = {}
    if net_margin is not None:
        result["net_margin"] = round(net_margin, 2)
    if asset_turnover is not None:
        result["asset_turnover"] = round(asset_turnover, 4)
    if equity_multiplier is not None:
        result["equity_multiplier"] = round(equity_multiplier, 2)
    if net_margin is not None and asset_turnover is not None and equity_multiplier is not None:
        result["roe_implied"] = round(net_margin * asset_turnover * equity_multiplier, 2)
    return result


def compute_quality(symbol: str, financials: dict | None = None) -> QualityResult:
    """计算质量因子。

    输入 financials 支持字段：
      - roe: ROE（%）
      - net_margin: 净利润率（%）
      - asset_turnover: 资产周转率
      - equity_multiplier: 权益乘数
      - gross_margin: 毛利率（%）
      - gross_margin_history: [float] 历史毛利率序列（用于计算稳定性）
      - debt_ratio: 资产负债率（%）
      - current_ratio: 流动比率

    Args:
        symbol: 品种代码。
        financials: 财务数据字典。

    Returns:
        QualityResult。
    """
    if not financials:
        return QualityResult(symbol=symbol, data_grade="NO_DATA")

    try:
        roe = financials.get("roe")
        net_margin = financials.get("net_margin")
        asset_turnover = financials.get("asset_turnover")
        equity_multiplier = financials.get("equity_multiplier")
        gross_margin = financials.get("gross_margin")

        # 毛利率稳定性：历史毛利率的变异系数倒数
        gross_margin_stability = financials.get("gross_margin_stability")
        if gross_margin_stability is None and financials.get("gross_margin_history"):
            hist = np.array(financials["gross_margin_history"], dtype=float)
            if len(hist) >= 3 and np.mean(hist) != 0:
                cv = np.std(hist) / np.mean(hist)
                gross_margin_stability = round(max(0, min(1 - cv, 1.0)), 3)

        debt_ratio = financials.get("debt_ratio")
        current_ratio = financials.get("current_ratio")

        # 杜邦分解
        dupont = _dupont_decompose(net_margin, asset_turnover, equity_multiplier)

        # 综合质量评分（满分100）
        scores = []
        weights = []

        if roe is not None:
            scores.append(min(roe / 20, 1.0) * 100)
            weights.append(0.40)
        elif dupont.get("roe_implied") is not None:
            ri = dupont["roe_implied"]
            scores.append(min(ri / 20, 1.0) * 100)
            weights.append(0.40)

        if gross_margin is not None:
            scores.append(min(gross_margin / 60, 1.0) * 100)
            weights.append(0.25)

        if debt_ratio is not None:
            scores.append(max(0, 1 - debt_ratio / 100) * 100)
            weights.append(0.20)

        if current_ratio is not None:
            scores.append(min(current_ratio / 2, 1.0) * 100)
            weights.append(0.15)

        composite = round(sum(s * w for s, w in zip(scores, weights)) / sum(weights), 1) if weights else None

        return QualityResult(
            symbol=symbol,
            roe=roe,
            roe_dupont=dupont,
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
