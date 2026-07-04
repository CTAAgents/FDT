from pydantic import BaseModel, Field
from typing import Literal, Optional
from .base import BaseSkillOutput


class VerdictItem(BaseModel):
    dim: str                                # 维度名
    ruling: Literal["include", "watch", "exclude"]
    winner: Optional[Literal["bull", "bear"]] = None  # null 表示无明确胜方
    rebuttal_quality: Literal["接住", "部分接住", "糊弄"]
    reason: str                             # 裁决理由，必须引用具体 evidence


class OverallJudgment(BaseModel):
    tendency: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0, le=1)
    core_conflict: str                      # 多空分歧本质
    suggested_position_pct: float = Field(ge=0, le=100)


class RiskOutput(BaseSkillOutput):
    """风控明的输出"""
    variant: Literal["risk"]
    verdicts: list[VerdictItem] = Field(min_length=5, max_length=5)
    overall: OverallJudgment
    full_report: str                        # 自然语言报告全文（用于 HTML）


# 2.1 版本：增加风险等级字段
class RiskOutputV21(RiskOutput):
    version: Literal["2.1"] = "2.1"
    risk_level: Literal["low", "medium", "high"] = "medium"
