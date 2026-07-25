"""新闻数据层数据类型 — NewsItem / NewsQuery / NewsResult

行业通行方案：
- NewsItem 借鉴 Bloomberg News Datamodel 的字段设计（headline + body + category + timestamp）
- SentimentLabel 使用标准 -1.0 ~ 1.0 连续值（对标 Thomson Reuters MarketPsych）
- 多源标记兼容 Reuters Instrument Code 式 symbol 映射
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class NewsSourceType(str, Enum):
    """新闻来源类型"""
    JIN10 = "jin10"         # 金十数据 MCP
    WEB_SEARCH = "web"      # WebSearch HTTP 搜索
    RSS = "rss"             # 固定 RSS 源
    AKSHARE = "akshare"     # AKShare 新闻接口


@dataclass
class NewsItem:
    """统一新闻条目 — 所有新闻源输出的标准格式

    Fields:
        symbol: 关联期货品种代码（如 "FU"）
        source_type: 来源类型
        source_name: 来源名称（如 "金十快讯", "新浪财经"）
        title: 标题
        content: 正文/摘要
        time: 发布时间（ISO 格式）
        confidence: 置信度 0~1（多源印证时提升）
        url: 原文链接（可选）
        sentiment_score: 预标注情绪 -1~1（可选，由源提供）
        event_type: 事件类型（policy/supply_demand/macro/geopolitics/other）
    """
    symbol: str
    source_type: NewsSourceType
    source_name: str
    title: str
    content: str
    time: str
    confidence: float = 0.7
    url: str = ""
    sentiment_score: Optional[float] = None
    event_type: str = "other"

    def age_hours(self) -> float:
        """返回新闻距现在的小时数（用于时效加权）"""
        try:
            pub = datetime.fromisoformat(self.time)
            return (datetime.now() - pub).total_seconds() / 3600
        except (ValueError, TypeError):
            return 999.0


@dataclass
class NewsQuery:
    """新闻查询参数"""
    symbols: list[str]          # 品种代码列表
    keywords: list[str] = field(default_factory=list)  # 额外搜索关键词
    max_age_hours: float = 48   # 最大时效（超时不返回）
    max_per_symbol: int = 5     # 每品种最多返回条数


@dataclass
class NewsResult:
    """新闻查询结果"""
    items: list[NewsItem] = field(default_factory=list)
    source_stats: dict[str, int] = field(default_factory=dict)  # {source_name: count}
    total_count: int = 0
    errors: list[str] = field(default_factory=list)
    data_incomplete: bool = False  # 所有源均失效或数据不足时标记为 True


# ── 情绪分析产出物（SentimentStateVector 的简化版，供节点使用） ──

@dataclass
class SymbolNewsSummary:
    """单个品种的新闻情绪汇总"""
    symbol: str
    total_news: int = 0
    overall_sentiment: float = 0.0
    event_breakdown: dict[str, int] = field(default_factory=dict)
    top_events: list[NewsItem] = field(default_factory=list)
    data_grade: str = "NO_DATA"  # RICH / NORMAL / STALE / NO_DATA
