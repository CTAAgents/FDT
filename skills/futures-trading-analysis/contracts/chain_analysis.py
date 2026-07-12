from pydantic import BaseModel, Field
from typing import Literal
from .base import BaseSkillOutput


class ChainMetric(BaseModel):
    name: str  # 基差 / 仓单 / 持仓 / 期限结构
    value: float | str
    change: float  # 日/周环比
    signal: Literal["bullish", "bearish", "neutral"]


class ChainAnalysisOutput(BaseSkillOutput):
    """链证源的输出：产业链基本面分析"""

    variant: Literal["futures_chain"]
    metrics: list[ChainMetric]
    inventory_level: Literal["high", "medium", "low"]
    basis_status: Literal["contango", "backwardation", "flat"]
    summary: str
