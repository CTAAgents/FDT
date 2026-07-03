from pydantic import BaseModel, Field
from typing import Literal, Optional
from .base import BaseSkillOutput


class DimensionItem(BaseModel):
    dim: str                                # 供给 / 需求 / 库存 / 基差 / 宏观
    claim: str                              # 核心观点
    evidence: str                           # 数据支撑（必须包含可核验数字）
    confidence: float = Field(ge=0, le=1)   # 该维度置信度
    source: str = ""                        # 数据来源，可选


class BullOutput(BaseSkillOutput):
    """证真（正方辩手）的输出"""
    variant: Literal["bull"]
    dimensions: list[DimensionItem] = Field(min_length=5, max_length=5)
    summary_4_risk: str                     # 给风控的精简版摘要
    full_text: str                          # 完整论证文本（用于 HTML 报告）
    confidence: float = Field(ge=0, le=1)   # 整体置信度
    rebuttal_targets: list[str] = []        # 本轮反驳了熊的哪些维度，首轮为空


class BearOutput(BaseSkillOutput):
    """慎思（反方辩手）的输出"""
    variant: Literal["bear"]
    dimensions: list[DimensionItem] = Field(min_length=5, max_length=5)
    summary_4_risk: str
    full_text: str
    confidence: float = Field(ge=0, le=1)
    rebuttal_targets: list[str] = []


# 未来扩展：2.1 版本增加 rebuttal_quality_score
class BullOutputV21(BullOutput):
    version: Literal["2.1"] = "2.1"
    rebuttal_quality_score: Optional[float] = Field(None, ge=0, le=1)
