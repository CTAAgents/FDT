"""WebSearch 新闻源 — Python 级 HTTP 新闻搜索，不依赖 LLM 工具调用。

实现方式：
1. 主源：RSS 订阅（新浪财经期货频道、东方财富期货等固定源）
2. 辅助：通过通用新闻 API（当前使用 RSS 作为主通道，后续可接入商业新闻 API）

当前问题修复：原来 WebSearch 仅在 LLM prompt 中提示但无法执行（FdtAgentExecutor
不支持 tool calling）。本实现在 Python 层直接执行 HTTP 请求，确保搜索真实发生。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

import httpx

from ..types import NewsItem, NewsQuery, NewsResult, NewsSourceType
from . import NewsSourceBase

logger = logging.getLogger(__name__)

# ── 固定新闻源 RSS 列表（中文期货/大宗商品相关） ──
_RSS_FEEDS: list[dict] = [
    # 新浪财经期货频道
    {"url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=155&lid=1558&num=20",
     "source_name": "新浪期货"},
    # 东方财富期货
    {"url": "https://push2.eastmoney.com/api/qt/list/get?fltt=1&secid=1.113&fields=f14,f15,f16,f17,f18&invt=2",
     "source_name": "东方财富"},
    # 和讯期货 RSS（如果可用）
    # 备用：通用财经 RSS
]

_TIMEOUT = 10.0
_MAX_RESULTS = 50


class WebSearchSource(NewsSourceBase):
    """Web 搜索新闻源 — 通过 RSS/HTTP 获取实时财经新闻。"""

    def __init__(self, feeds: Optional[list[dict]] = None):
        self._feeds = feeds or _RSS_FEEDS

    @property
    def source_name(self) -> str:
        return "web_search"

    @property
    def priority(self) -> int:
        return 50

    async def fetch(self, query: NewsQuery) -> NewsResult:
        result = NewsResult()
        tasks = [self._fetch_feed(feed, query) for feed in self._feeds]
        feed_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[NewsItem] = []
        for fr in feed_results:
            if isinstance(fr, Exception):
                result.errors.append(str(fr)[:100])
                continue
            if isinstance(fr, list):
                all_items.extend(fr)

        # 按品种过滤 + 去重
        seen = set()
        symbol_set = {s.upper() for s in query.symbols}
        for item in all_items:
            if item.symbol.upper() not in symbol_set:
                continue
            key = (item.content[:100], item.source_name)
            if key in seen:
                continue
            seen.add(key)
            result.items.append(item)

        result.source_stats[self.source_name] = len(result.items)
        result.total_count = len(result.items)
        return result

    async def _fetch_feed(self, feed: dict, query: NewsQuery) -> list[NewsItem]:
        """从单个 RSS/HTTP 源获取新闻并尝试匹配品种。"""
        url = feed.get("url", "")
        source_name = feed.get("source_name", "财经新闻")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        except Exception as e:
            logger.debug("[WebSearch] %s 请求失败: %s", source_name, e)
            return []

        items = self._parse_feed(data, source_name, query)
        return items

    def _parse_feed(self, data: dict, source_name: str, query: NewsQuery) -> list[NewsItem]:
        """解析 RSS/API 返回，产出 NewsItem。"""
        news_items: list[NewsItem] = []
        articles = self._extract_articles(data)
        seen_texts: set[str] = set()

        # 构建品种关键词映射（用于模糊匹配）
        from .jin10_source import SYMBOL_TO_KEYWORDS, _DEFAULT_KEYWORDS
        symbol_kw_map: dict[str, list[str]] = {}
        for sym in query.symbols:
            symbol_kw_map[sym.upper()] = SYMBOL_TO_KEYWORDS.get(sym.upper(), _DEFAULT_KEYWORDS)

        for article in articles:
            title = (article.get("title") or "").strip()
            content = (article.get("content") or article.get("summary") or article.get("description") or title)[:500]
            pub_time = (article.get("time") or article.get("date") or article.get("pubDate") or "")
            link = (article.get("link") or article.get("url") or article.get("source_url") or "")

            if not title and not content:
                continue
            dedup_key = (title or content)[:100]
            if dedup_key in seen_texts:
                continue
            seen_texts.add(dedup_key)

            # 匹配品种：通过标题/正文中的中文关键词反向匹配
            matched_symbols = self._match_symbol(content + title, symbol_kw_map)
            for sym in matched_symbols:
                news_items.append(NewsItem(
                    symbol=sym,
                    source_type=NewsSourceType.WEB_SEARCH,
                    source_name=source_name,
                    title=title[:120] or content[:80],
                    content=content,
                    time=_normalize_time(pub_time),
                    confidence=0.6,
                    url=link,
                    event_type="other",
                ))

        return news_items

    def _extract_articles(self, data: dict) -> list[dict]:
        """从不同 API 响应格式中提取文章列表。"""
        if not isinstance(data, dict):
            return []
        # 新浪格式
        result = data.get("result", {})
        if isinstance(result, dict):
            items = result.get("data", [])
            if isinstance(items, list):
                return items
        # 通用格式
        for key in ("data", "items", "list", "news", "articles"):
            val = data.get(key, [])
            if isinstance(val, list):
                return val
        return []

    def _match_symbol(self, text: str, symbol_kw_map: dict[str, list[str]]) -> list[str]:
        """通过中文关键词反向匹配品种。"""
        t = text.lower()
        matched = []
        for sym, keywords in symbol_kw_map.items():
            for kw in keywords:
                if kw.lower() in t:
                    matched.append(sym)
                    break
        return matched if matched else []


def _normalize_time(time_str: str) -> str:
    """归一化时间格式为 ISO 格式。"""
    if not time_str:
        return datetime.now().isoformat()
    try:
        from datetime import datetime as dt
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%a, %d %b %Y %H:%M:%S %z",
                     "%Y/%m/%d %H:%M", "%Y-%m-%d"):
            try:
                return dt.strptime(time_str, fmt).isoformat()
            except ValueError:
                continue
    except Exception:
        pass
    return time_str
