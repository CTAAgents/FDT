"""新闻数据适配层 — 统一新闻获取入口

用法:
    from data_adapter.news import NewsRouter

    router = NewsRouter()
    result = await router.fetch(NewsQuery(symbols=["FU", "RB"]))
    # result.items → list[NewsItem]

架构:
    NewsRouter 统一入口 → 按优先级调用多源 → 去重聚合 → 单次返回
    读心 Agent 只分析 result 中的结构化新闻，不再自行搜索。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .types import NewsItem, NewsQuery, NewsResult, SymbolNewsSummary
from .sources import NewsSourceBase
from .sources.jin10_source import Jin10NewsSource
from .sources.web_search_source import WebSearchSource

logger = logging.getLogger(__name__)


class NewsRouter:
    """新闻路由器 — 统一入口，管理多源采集与聚合。

    搜索策略：
    1. Jin10 MCP（优先级 10）— 最快最准
    2. WebSearch RSS（优先级 50）— 更广覆盖
    3. 所有源并行执行，结果合并去重

    扩展：调用 register_source() 注册自定义新闻源。
    """

    def __init__(self, min_news_threshold: int = 2):
        self._sources: list[NewsSourceBase] = []
        self._min_news_threshold = min_news_threshold  # 每品种最少新闻条数，不足时自动触发 WebSearch
        self._register_defaults()

    def _register_defaults(self):
        """注册默认新闻源（按优先级顺序）。"""
        self._sources.append(Jin10NewsSource())
        self._sources.append(WebSearchSource())
        # 按 priority 排序
        self._sources.sort(key=lambda s: s.priority)

    def register_source(self, source: NewsSourceBase):
        """注册自定义新闻源。"""
        self._sources.append(source)
        self._sources.sort(key=lambda s: s.priority)

    async def fetch(self, query: NewsQuery) -> NewsResult:
        """多源并行采集 + 去重聚合 + 时效过滤。

        Args:
            query: 查询参数（品种列表、关键词、时效上限）

        Returns:
            NewsResult: 合并后的新闻结果
        """
        import asyncio

        # 所有源并行执行
        tasks = [source.fetch(query) for source in self._sources]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: NewsResult = NewsResult()
        seen: set[tuple[str, str]] = set()  # (content_hash, source)

        for i, raw in enumerate(raw_results):
            source_name = self._sources[i].source_name if i < len(self._sources) else "unknown"
            if isinstance(raw, Exception):
                merged.errors.append(f"[{source_name}] {str(raw)[:120]}")
                continue
            if not isinstance(raw, NewsResult):
                continue

            merged.errors.extend(raw.errors)
            for item in raw.items:
                # 去重：相同内容 + 相同源不重复
                dedup_key = (item.content[:150], item.source_name)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # 时效过滤
                if query.max_age_hours > 0 and item.age_hours() > query.max_age_hours:
                    continue

                merged.items.append(item)

        # 按时间倒序排序
        merged.items.sort(key=lambda x: x.time, reverse=True)

        # 每品种限条数
        if query.max_per_symbol > 0:
            symbol_count: dict[str, int] = {}
            filtered: list[NewsItem] = []
            for item in merged.items:
                cnt = symbol_count.get(item.symbol, 0)
                if cnt >= query.max_per_symbol:
                    continue
                symbol_count[item.symbol] = cnt + 1
                filtered.append(item)
            merged.items = filtered

        merged.total_count = len(merged.items)
        merged.source_stats = self._collect_stats(merged.items)

        # 阈值判定：每品种有效新闻数低于 threshold 时标记 data_incomplete
        if self._min_news_threshold > 0:
            per_symbol_count: dict[str, int] = {}
            for item in merged.items:
                per_symbol_count[item.symbol] = per_symbol_count.get(item.symbol, 0) + 1
            below_threshold = sum(
                1 for cnt in per_symbol_count.values()
                if cnt < self._min_news_threshold
            )
            if below_threshold > 0 or not merged.items:
                merged.data_incomplete = True

        return merged

    def _collect_stats(self, items: list[NewsItem]) -> dict[str, int]:
        stats: dict[str, int] = {}
        for item in items:
            stats[item.source_name] = stats.get(item.source_name, 0) + 1
        return stats

    @staticmethod
    def build_prompt_context(result: NewsResult) -> str:
        """将 NewsResult 格式化为 LLM 可读的新闻上下文文本。

        替代 _build_jin10_context 的职责。
        """
        if not result.items:
            return "\n【实时新闻】暂无相关快讯。\n"

        lines = ["\n【实时新闻（多源聚合，来源已标注）】"]
        current_sym = ""
        for item in result.items:
            if item.symbol != current_sym:
                current_sym = item.symbol
                lines.append(f"\n  【{item.symbol}】")
            time_str = item.time[:16] if len(item.time) >= 16 else item.time
            source_tag = f"[{item.source_type.value}]"
            lines.append(f"    ⏱ {time_str} | {source_tag} {item.content[:150]}")

        lines.append("\n【引用规范】引用时按来源标注标签：[jin10] / [web]")
        return "\n".join(lines)

    @staticmethod
    def build_quality_report(result: NewsResult, symbols: list[str]) -> dict:
        """构建逐品种新闻质量报告（替代当前 news_quality 逻辑）。"""
        report = {}
        for sym in symbols:
            sym_items = [i for i in result.items if i.symbol.upper() == sym.upper()]
            total = len(sym_items)
            if total >= 5:
                grade = "RICH"
            elif total >= 2:
                grade = "NORMAL"
            elif total >= 1:
                grade = "STALE"
            else:
                grade = "NO_DATA"
            report[sym] = {
                "symbol": sym,
                "total_flash": total,
                "data_grade": grade,
                "sources": list({i.source_name for i in sym_items}),
            }
        return report

    @staticmethod
    def build_symbol_summaries(result: NewsResult, symbols: list[str]) -> dict[str, SymbolNewsSummary]:
        """构建逐品种情绪汇总（供 SentimentStateVector 使用）。"""
        summaries = {}
        for sym in symbols:
            sym_items = [i for i in result.items if i.symbol.upper() == sym.upper()]
            if not sym_items:
                summaries[sym] = SymbolNewsSummary(symbol=sym, data_grade="NO_DATA")
                continue

            event_breakdown: dict[str, int] = {}
            for item in sym_items:
                event_breakdown[item.event_type] = event_breakdown.get(item.event_type, 0) + 1

            # 简单情绪聚合（多源标注的情绪分均值）
            scores = [i.sentiment_score for i in sym_items if i.sentiment_score is not None]
            avg_sentiment = sum(scores) / len(scores) if scores else 0.0

            summaries[sym] = SymbolNewsSummary(
                symbol=sym,
                total_news=len(sym_items),
                overall_sentiment=round(avg_sentiment, 2),
                event_breakdown=event_breakdown,
                top_events=sorted(sym_items, key=lambda x: x.time, reverse=True)[:5],
                data_grade="RICH" if len(sym_items) >= 5 else "NORMAL" if len(sym_items) >= 2 else "STALE",
            )
        return summaries
