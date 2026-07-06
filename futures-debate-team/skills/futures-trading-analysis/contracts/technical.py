from pydantic import BaseModel, Field
from typing import Literal
from .base import BaseSkillOutput


class IndicatorSummary(BaseModel):
    name: str  # MACD / RSI / BOLL / KDJ
    value: float | str
    signal: Literal["bullish", "bearish", "neutral"]
    description: str = ""


class TechnicalOutput(BaseSkillOutput):
    """技研锋的输出：技术面分析"""

    variant: Literal["futures_technical"]
    trend_stage: Literal["uptrend", "downtrend", "sideways", "reversal_zone"]
    indicators: list[IndicatorSummary]
    key_pattern: str = ""  # 头肩顶 / 双底 / 旗形 等形态
    support_resistance: tuple[float, float]  # (支撑位, 阻力位)
    summary: str  # 一句话结论
