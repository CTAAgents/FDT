from pydantic import BaseModel, Field
from typing import Literal, Optional
from .base import BaseSkillOutput


class TradeAction(BaseModel):
    direction: Literal["long", "short", "wait"]
    contract: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_pct: float = Field(ge=0, le=100)
    rationale: str


class TradingPlanOutput(BaseSkillOutput):
    """策执远的输出：最终交易计划"""

    variant: Literal["trading_plan"]
    actions: list[TradeAction]
    total_exposure_pct: float = Field(ge=0, le=100)
    risk_reward_ratio: float
    summary: str
