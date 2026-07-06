from pydantic import BaseModel, Field
from typing import Literal
from .base import BaseSkillOutput


class JudgementItem(BaseModel):
    """单品种裁决"""

    verdict: str  # 维持做多/维持做空/转向做多/转向做空/搁置观察
    direction: Literal["BUY", "SELL", "HOLD"]
    confidence: Literal["高", "中", "低"]
    reasoning: str  # 裁决理由（100-200字）
    key_tension: str  # 证真最强点 vs 慎思最强点
    lean: str  # 偏向方
    risk_note: str  # 风险备注


class JudgeOutput(BaseSkillOutput):
    """闫判官的输出：辩论裁决"""

    variant: Literal["judge"]
    verdicts: dict[str, JudgementItem]  # 品种代码 → 裁决
    overall_assessment: str  # 整体多空格局判断（50字以内）
