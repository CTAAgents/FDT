"""舆情 / 市场情绪数据能力 [INDEPENDENT + 可选 LLM-ENHANCED]。

方案 C：舆情本质是文本 / NLP 数据挖掘 → 市场数据，作为 **FDC 数据能力** 落地，
不独立成模块 / Agent。复用缓存层（Postgres+Redis+Memory）与 A2A 信封。
由数技源 scan-core / 基本面分析师消费为证据维度（保留背离信号）。

数据源可注入（``fetch_headlines``）；情绪打分可注入（``scorer``）或默认关键词极性规则。
源 / 打分不可用 → 中性情绪 + ``add_warning``（与现有降级哲学一致）。
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES
from futures_data_core.core.cache_store import CacheStore, get_default_store

# 简单中文情绪词极性表（默认规则打分，零依赖）
_POSITIVE = {"涨", "利多", "利好", "上扬", "走强", "突破", "增仓", "去库", "紧张", "短缺"}
_NEGATIVE = {"跌", "利空", "利淡", "走弱", "下挫", "跌破", "减仓", "累库", "宽松", "过剩"}


def _rule_score(text: str) -> float:
    """关键词极性规则打分，返回 [-1, 1]。"""
    if not text:
        return 0.0
    score = 0.0
    for w in _POSITIVE:
        if w in text:
            score += 0.2
    for w in _NEGATIVE:
        if w in text:
            score -= 0.2
    return max(-1.0, min(1.0, score))


async def get_sentiment(
    symbol: str,
    *,
    fetch_headlines: Optional[Callable[[str], Awaitable[list[dict]]]] = None,
    scorer: Optional[Callable[[str, list[dict]], Awaitable[float]]] = None,
    cache: Optional[CacheStore] = None,
    use_cache: bool = True,
) -> A2APayload:
    """获取品种舆情 / 市场情绪 [INDEPENDENT + 可选 LLM-ENHANCED]。

    Args:
        symbol: 品种代码。
        fetch_headlines: 注入的新闻 / 社媒标题抓取器，返回
            ``[{"title","source","url","ts"}]``；``None`` 时无真实源，返回中性情绪 + warning。
        scorer: 注入的情绪打分器 ``(symbol, headlines) -> float[-1,1]``；
            ``None`` 时用默认关键词极性规则。
        cache: 可选 ``CacheStore``；``None`` 用默认单例（Memory/PG/Redis）。
        use_cache: 是否查 / 写缓存。

    Returns:
        ``sentiment.daily`` A2APayload：{symbol, sentiment_score, trend, headlines, summary}。
    """
    store = cache or (get_default_store() if use_cache else None)
    cache_key = f"sentiment:{symbol}"

    if store is not None and use_cache:
        cached = await store.get(cache_key)
        if cached is not None:
            payload = A2APayload(
                type=DATA_TYPES["SENTIMENT"], runtime_mode="independent", data=cached
            )
            payload.set_grade(cached.get("data_grade", "CACHED"))
            payload.meta["sources"] = cached.get("sources", [])
            payload.meta["cached"] = True
            return payload

    headlines: list[dict] = []
    sources: list[str] = []
    if fetch_headlines is not None:
        try:
            headlines = await fetch_headlines(symbol) or []
        except Exception:
            headlines = []
    for h in headlines:
        src = h.get("source")
        if src and src not in sources:
            sources.append(src)

    # 打分
    if scorer is not None:
        try:
            score = await scorer(symbol, headlines)
        except Exception:
            score = 0.0
    else:
        combined = " ".join(h.get("title", "") for h in headlines)
        score = _rule_score(combined)

    score = max(-1.0, min(1.0, float(score)))
    if score > 0.15:
        trend = "bullish"
    elif score < -0.15:
        trend = "bearish"
    else:
        trend = "neutral"

    data = {
        "symbol": symbol,
        "sentiment_score": round(score, 3),
        "trend": trend,
        "headlines": headlines,
        "summary": f"{symbol} 舆情情绪分 {score:.2f}（{trend}）",
    }

    grade = "DAILY" if headlines else "UNAVAILABLE"
    payload = A2APayload(type=DATA_TYPES["SENTIMENT"], runtime_mode="independent", data=data)
    payload.set_grade(grade)
    payload.meta["sources"] = sources
    if not headlines:
        payload.add_warning("未配置舆情数据源，返回中性情绪（score=0）")

    if store is not None and use_cache and headlines:
        data["data_grade"] = grade
        data["sources"] = sources
        await store.set(cache_key, data)

    return payload
