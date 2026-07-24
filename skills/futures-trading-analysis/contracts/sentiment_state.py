"""读心 — 新闻情绪状态向量 v1

新闻情绪分析师（读心）的输出契约。作为与链证源（产业链）、观澜（技术面）、
探源（基本面）平级的第四分析因子，在 P3 阶段并行运行。

数据源：金十 MCP（主源）+ WebSearch/WebFetch（自主补充）
每条情绪事件必须标注来源 [sentiment:jin10] / [sentiment:web]
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .base import BaseSkillOutput


class SentimentEvent(BaseModel):
    """单条情绪事件"""

    event_type: Literal["policy", "supply_demand", "macro", "geopolitics", "other"]
    content: str  # 事件原文摘要
    sentiment: float = Field(ge=-1.0, le=1.0)  # -1.0（极空） ~ 1.0（极多）
    time: str  # 事件时间
    source: Literal["jin10", "web"]  # 数据来源
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)  # 置信度


class SymbolSentiment(BaseModel):
    """单品种情绪状态"""

    overall_sentiment: float = Field(ge=-1.0, le=1.0)  # 综合情绪评分
    sentiment_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="按事件类型分类的情绪评分，如 {'policy': 0.3, 'supply_demand': -0.2}",
    )
    hot_volume: int = Field(ge=0, default=0)  # 相关快讯数量（热度）
    key_events: list[SentimentEvent] = Field(default_factory=list)
    divergence: Optional[float] = Field(
        default=None,
        description="情绪偏离度：情绪评分与基本面/技术面综合得分的差异",
    )


class SentimentStateVector(BaseSkillOutput):
    """读心的输出：新闻情绪状态向量

    输入：金十 MCP 快讯 + WebSearch 自主采集
    输出：逐品种情绪评分 + 关键事件列表 + 偏离度
    """

    variant: Literal["sentiment_state"] = "sentiment_state"
    per_symbol: dict[str, SymbolSentiment] = Field(
        default_factory=dict,
        description="逐品种情绪状态，key为品种代码",
    )
    summary: str = ""  # 总体情绪摘要
