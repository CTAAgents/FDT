"""多因子数据类型 — P2.5 因子注入的统一数据格式。

所有因子采集器产出这些类型，下游 context builder
从 state["factor_*"] 读取后格式化为 LLM prompt 区块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════
# 1. 期限结构因子
# ═══════════════════════════════════════════════════

@dataclass
class TermStructureResult:
    """期限结构因子 — 基差、升贴水、曲线形态。

    Attributes:
        symbol: 品种代码
        basis: 现货 - 期货价差（正=现货升水）
        basis_ratio: 基差率（基差/期货价格）
        near_contract: 近月合约代码
        far_contract: 远月合约代码
        spread: 远月 - 近月价差
        spread_ratio: 升贴水率
        curve_type: 曲线类型 backwardation / contango / flat
        curve_slope: 曲线斜率（主力-次主力价差）
        delivery_month: 交割月
        days_to_delivery: 距交割日天数
    """
    symbol: str
    basis: Optional[float] = None
    basis_ratio: Optional[float] = None
    near_contract: str = ""
    far_contract: str = ""
    spread: Optional[float] = None
    spread_ratio: Optional[float] = None
    curve_type: str = "flat"
    curve_slope: Optional[float] = None
    delivery_month: Optional[str] = None
    days_to_delivery: Optional[int] = None
    data_grade: str = "UNAVAILABLE"


# ═══════════════════════════════════════════════════
# 2. 波动率因子
# ═══════════════════════════════════════════════════

@dataclass
class VolatilityResult:
    """波动率因子 — 历史波动率、偏度、峰度、ATR。

    全部从 K 线数据计算，零外部依赖。
    """
    symbol: str
    hv_5: Optional[float] = None       # 5日历史波动率（%）
    hv_20: Optional[float] = None      # 20日历史波动率（%）
    hv_60: Optional[float] = None      # 60日历史波动率（%）
    skewness: Optional[float] = None   # 收益率偏度
    kurtosis: Optional[float] = None   # 收益率峰度
    max_drawdown: Optional[float] = None  # 区间最大回撤（%）
    atr: Optional[float] = None        # 平均真实波幅（价格单位）
    atr_pct: Optional[float] = None    # ATR 占价格百分比（%）
    data_grade: str = "PRIMARY"


# ═══════════════════════════════════════════════════
# 3. 多空持仓因子
# ═══════════════════════════════════════════════════

@dataclass
class HoldingSentimentResult:
    """多空持仓因子 — 全市场多空比 + 前20会员持仓。

    注意：此为持仓存量指标，非日内资金净流入流量。
    期货市场无类似北向资金的实时资金流 API。
    """
    symbol: str
    total_long: Optional[int] = None       # 多头总持仓
    total_short: Optional[int] = None      # 空头总持仓
    long_short_ratio: Optional[float] = None  # 多空持仓比
    long_change: Optional[int] = None      # 多单日变化
    short_change: Optional[int] = None     # 空单日变化
    top20_long: Optional[int] = None       # 前20多单合计
    top20_short: Optional[int] = None      # 前20空单合计
    top20_ratio: Optional[float] = None    # 前20多空比
    data_date: Optional[str] = None        # 数据日期
    data_grade: str = "PRIMARY"


# ═══════════════════════════════════════════════════
# 4. 跨品种价差
# ═══════════════════════════════════════════════════

@dataclass
class CrossSpreadResult:
    """跨品种价差 — 配对交易信号。

    从两个品种的 K 线收盘价计算价差序列，
    统计历史均值和标准差，产出 Z-Score。
    """
    pair: tuple[str, str]       # 品种对 (如 "RB", "HC")
    current_spread: float = 0.0    # 当前价差
    historical_mean: float = 0.0   # N日历史均值
    historical_std: float = 0.0    # N日历史标准差
    zscore: float = 0.0            # Z-Score
    percentile: float = 0.0        # 当前价差在历史中的百分位
    trend: str = "stable"          # widening / narrowing / stable
    data_grade: str = "PRIMARY"


# ═══════════════════════════════════════════════════
# 5. 因子信号 + 一致性看板
# ═══════════════════════════════════════════════════

@dataclass
class FactorSignal:
    """单个因子信号 — 供因子看板使用"""
    symbol: str
    direction: int       # -2 强烈看空, -1 看空, 0 中性, +1 看多, +2 强烈看多
    strength: float      # 0.0 ~ 1.0
    source: str          # 因子名称（如 "volatility", "term_structure"）


@dataclass
class FactorDashboardResult:
    """多因子信号一致性看板 — 注入闫判官终裁 prompt"""
    symbols: list[str] = field(default_factory=list)
    signals: dict[str, list[FactorSignal]] = field(default_factory=dict)  # {symbol: [signals]}
    consensus: dict[str, int] = field(default_factory=dict)  # {symbol: 方向汇总}
    divergence: dict[str, float] = field(default_factory=dict)  # {symbol: 分歧度 0~1}
    data_grade: str = "PRIMARY"
