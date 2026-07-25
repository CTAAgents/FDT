"""新闻源基类 + 源注册"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..types import NewsItem, NewsQuery, NewsResult

logger = logging.getLogger(__name__)


class NewsSourceBase(ABC):
    """新闻源抽象基类 — 所有新闻采集器必须实现此接口。"""

    @abstractmethod
    async def fetch(self, query: NewsQuery) -> NewsResult:
        """按查询参数获取新闻。"""

    async def health_check(self) -> bool:
        """数据源连通性检测，用于动态降级。默认返回 True。"""
        return True

    @property
    @abstractmethod
    def source_name(self) -> str:
        """来源唯一标识（如 "jin10", "web_search"）。"""

    @property
    def priority(self) -> int:
        """优先级（越小越优先），默认 100。"""
        return 100
