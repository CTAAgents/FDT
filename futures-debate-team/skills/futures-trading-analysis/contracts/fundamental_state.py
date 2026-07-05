"""探源 — 基本面状态向量 v2

匹配 agent 升级后的结构化 Output JSON，链证源骨架→探源填肉→证真/慎思取用。
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from .base import BaseSkillOutput


class SupplyDemandBalance(BaseModel):
    """供需平衡表"""
    current: Literal["短缺", "小幅短缺", "紧平衡", "小幅过剩", "过剩", "中性"]
    trend_4w: str                           # "转向宽松" / "继续收紧" / "平稳"
    driver: str                             # 核心驱动因子描述


class InventoryItem(BaseModel):
    """库存单项"""
    value: Optional[float] = None           # 绝对值（万吨等）
    unit: str = ""                          # 单位
    yoy: Optional[float] = None             # 同比 %
    mom: Optional[float] = None             # 环比 %
    percentile_5y: Optional[float] = None   # 近5年同期分位数 0-100
    structure: str = ""                     # "厂库升_社库降=被动累" 等组合判断


class InventoryVector(BaseModel):
    """库存状态向量"""
    social: Optional[InventoryItem] = None
    mill: Optional[InventoryItem] = None
    warehouse_receipt: Optional[dict] = None  # 仓单趋势 + 备注


class ProfitVector(BaseModel):
    """利润状态"""
    value: Optional[float] = None
    percentile_5y: Optional[float] = None       # 0-100
    trend: str = ""                             # "高位回落" / "低位回升" / "平稳"
    warning: Optional[str] = None               # 利润>80%分位时填"高利润供给释放预期"


class BasisVector(BaseModel):
    """基差 & 期限结构"""
    spot: Optional[float] = None
    futures: Optional[float] = None
    basis: Optional[float] = None
    curve: Literal["backwardation", "contango", "flat", ""] = ""
    signal: str = ""                            # "现货偏紧" / "现货宽松" / "中性"


class LeadingIndicator(BaseModel):
    """领先指标"""
    name: str
    value: Optional[float] = None
    unit: str = ""
    lead: str                                   # "8-12周" / "2-4周" 等
    implication: str                            # 远期含义


class ExpectationGap(BaseModel):
    """预期差"""
    market_priced_in: str                       # 市场已price-in什么
    actual_vs_expected: str                     # 实际 vs 预期
    implication: str                            # "边际偏空" / "边际偏多"


class FundamentalStateVector(BaseSkillOutput):
    """探源的输出：基本面状态向量

    链证源搭产业链骨架，探源在骨架上填当下供需数据。
    """
    variant: Literal["fundamental_state"] = "fundamental_state"
    symbol: str                                 # 品种代码
    supply_demand_balance: SupplyDemandBalance
    inventory: Optional[InventoryVector] = None
    profit: Optional[ProfitVector] = None
    basis: Optional[BasisVector] = None
    leading_indicators: list[LeadingIndicator] = Field(default_factory=list, min_length=1)
    narrative_for_bull: list[str] = Field(min_length=1)
    narrative_for_bear: list[str] = Field(min_length=1)
    expectation_gap: Optional[ExpectationGap] = None
    confidence: float = Field(ge=0, le=100)     # 整体置信度 0-100
    data_reliable: bool = True
    data_staleness_days: int = Field(ge=0, le=90)
    warning: Optional[str] = None               # 换月扰动/政策突变等
