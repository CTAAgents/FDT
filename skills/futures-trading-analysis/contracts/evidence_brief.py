"""闫判官 — 证据简报 + 辩论主持 & 最终判决

PrepBrief: 闫判官在辩论前整理的证据简报，汇总数技源/链证源/探源/观澜4路证据。
JudgeVerdict: 闫判官最终判决（更新自 JudgeOutput，增加判决后决策追踪字段）。
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseSkillOutput

# ========================
# 证据简报（辩论前）
# ========================


class SignalSummary(BaseModel):
    """单路信号的摘要"""

    source: Literal["ml_ensemble", "chain", "fundamental", "technical"]
    direction: Literal["bull", "bear", "neutral", "mixed"]
    confidence: float = Field(ge=0, le=1)
    key_finding: str  # 一句话


class CrossValidation(BaseModel):
    """多路信号交叉验证结果"""

    consensus_level: Literal["全一致", "多数一致", "分歧", "对抗"]
    direction: Literal["bull", "bear", "neutral"]
    divergence_detail: str = ""  # 哪几条信号冲突
    debate_candidate_score: float = Field(ge=0, le=1)  # 适合辩论度


class TopicSelection(BaseModel):
    """辩论议题"""

    symbol: str
    assigned_direction: Literal["bull", "bear"]
    rationale: str  # 为什么选这个品种/方向


class EventCalendarBrief(BaseModel):
    """近期事件影响"""

    upcoming_events: list[dict] = Field(default_factory=list)
    fatal_scheduled: bool = False  # FOMC/USDA等在48h内


class PrepBrief(BaseModel):
    """闫判官辩论前准备的完整证据简报"""

    version: str = "1.0"
    trace_id: str
    topics: list[TopicSelection] = Field(min_length=1)
    signal_summaries: dict[str, list[SignalSummary]]  # symbol → 各路信号摘要
    cross_validations: dict[str, CrossValidation]  # symbol → 交叉验证
    event_calendar: Optional[EventCalendarBrief] = None
    past_pnl_ref: Optional[str] = None  # 历史同品种决策参考
    prepared_at: str = ""


# ========================
# 最终判决
# ========================


class JudgeVerdictPerSymbol(BaseModel):
    """单品种判决"""

    winner: Literal["bull", "bear"]
    direction: Literal["BUY", "SELL", "HOLD"]
    confidence: Literal["高", "中", "低"]
    reasoning: str
    key_tension: str  # 证真最强点 vs 慎思最强点
    lean: str  # 偏向方
    risk_note: str  # 风险备注
    scores: dict[str, float] = Field(default_factory=dict)  # 六维度评分


class FinalJudgment(BaseSkillOutput):
    """闫判官最终判决（辩论结束后）

    扩充自 JudgeOutput，增加 recommendation + scores。
    """

    variant: Literal["judge"] = "judge"
    verdicts: dict[str, JudgeVerdictPerSymbol]  # symbol → 判决
    overall_assessment: str  # 整体多空格局判断
    recommendation: Literal["execute", "hold", "rematch"]
    scores_summary: Optional[dict] = None  # 全品种平均评分
