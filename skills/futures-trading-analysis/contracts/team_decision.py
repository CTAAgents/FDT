"""明鉴秋 — 团队主管最终决策

接收闫判官 FinalJudgment，结合风控 verdict 做最终裁定。
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseSkillOutput


class DecisionItem(BaseModel):
    """单品种决策"""

    symbol: str
    decision: Literal["execute", "hold", "rematch"]
    rationale: str
    plan_snapshot: Optional[str] = None  # 执行方案的摘要
    risk_color: Literal["green", "yellow", "red"]
    position_pct: Optional[float] = Field(None, ge=0, le=100)
    entry_window: Optional[str] = None  # "开盘后30min" / "等待USDA后"


class TeamDecisionOutput(BaseSkillOutput):
    """明鉴秋的输出：最终决策汇总

    一轮辩论的最终执行意见，存档 + 传给 main 做报告。
    """

    variant: Literal["team_decision"] = "team_decision"
    round_id: str  # 轮次标识，如 "RB_20260705"
    decisions: dict[str, DecisionItem]  # symbol → 决策
    total_exposure_pct: float = Field(ge=0, le=100)
    summary_200: str  # ≤200字摘要
    debate_winner: Optional[Literal["bull", "bear", "draw"]] = None
    archive_refs: dict[str, str] = Field(default_factory=dict)  # 各 Agent 产出文件路径
