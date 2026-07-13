"""多源降级链路由 [INDEPENDENT]。

将多个 :class:`~futures_data_core.collectors.base.BaseCollector` 按优先级编排为
异步降级链：依次尝试可用数据源，首个成功者即返回（包装为 :class:`A2APayload`）；
全部失败时回退到缓存（Postgres / Redis / Memory）；仍无则标记 ``UNAVAILABLE``。

数据等级约定：
    - ``tqsdk`` 成功 -> ``PRIMARY``
    - 其它实时源成功 -> ``DAILY``
    - 缓存命中 -> ``CACHED``
    - 全部失败 -> ``UNAVAILABLE``

无 LLM 依赖，可独立运行。
"""

from __future__ import annotations

from typing import Optional

from futures_data_core._a2a import A2APayload, DATA_TYPES
from futures_data_core.collectors.base import (
    BaseCollector,
    CollectorUnavailableError,
    select_by_priority,
)
from futures_data_core.collectors.qmt import QMTCollector
from futures_data_core.collectors.tdx import TDXCollector
from futures_data_core.collectors.tqsdk import TqSdkCollector
from futures_data_core.collectors.web_fallback import WebFallbackCollector
from futures_data_core.core.cache_store import CacheStore


def _default_collectors() -> list[BaseCollector]:
    """构建默认采集器列表（按优先级升序）。"""
    return select_by_priority(
        [
            TqSdkCollector(),       # 第一数据源：TqSDK免费版（24h可用，无需本地服务）
            QMTCollector(),         # 降级：QMT/xtquant
            TDXCollector(),         # 降级：通达信TQ-Local
            WebFallbackCollector(), # 最后兜底：东方财富+新浪
        ]
    )


class MultiSourceAdapter:
    """多源降级链适配器。"""

    def __init__(
        self,
        collectors: Optional[list[BaseCollector]] = None,
        cache: Optional[CacheStore] = None,
    ) -> None:
        """初始化。

        Args:
            collectors: 采集器列表；``None`` 时使用默认四源。
            cache: 可选的 :class:`CacheStore` 用于最终回退与写入。
        """
        self._collectors = list(collectors) if collectors is not None else _default_collectors()
        self._cache = cache

    def register(self, collector: BaseCollector) -> None:
        """注册/追加一个采集器（保持优先级有序）。"""
        self._collectors.append(collector)
        self._collectors = select_by_priority(self._collectors)

    # ───────────────────────────────────────────────────────────
    # K 线
    # ───────────────────────────────────────────────────────────
    async def get_kline(
        self, symbol: str, period: str = "daily", days: int = 120, source: str = "auto"
    ) -> A2APayload:
        """获取 K 线（自动降级）。

        Args:
            symbol: 品种代码。
            period: 周期。
            days: 回溯交易日数。
            source: ``"auto"`` 走降级链；否则指定采集器名（如 ``"tdx_tq_local"``）。

        Returns:
            :class:`A2APayload`，``data`` 为 KlineData 的 dict 表示。
        """
        if source != "auto":
            return await self._get_kline_explicit(symbol, period, days, source)

        tried: list[str] = []
        for collector in select_by_priority(self._collectors):
            if not await collector.check_available():
                continue
            tried.append(collector.name)
            try:
                data = await collector.get_kline(symbol, period, days)
            except CollectorUnavailableError:
                continue
            if data is None:
                continue
            return await self._wrap_kline(collector, data, tried)

        return await self._fallback_kline(symbol, period, tried)

    async def _get_kline_explicit(
        self, symbol: str, period: str, days: int, source: str
    ) -> A2APayload:
        """指定数据源获取 K 线。"""
        target = next(
            (c for c in self._collectors if c.name == source), None
        )
        if target is None:
            return self._unavailable(
                DATA_TYPES["KLINE"], symbol, f"未知数据源: {source}", tried=[]
            )
        if not await target.check_available():
            return await self._fallback_kline(symbol, period, [source])
        try:
            data = await target.get_kline(symbol, period, days)
        except CollectorUnavailableError as exc:
            return self._unavailable(
                DATA_TYPES["KLINE"], symbol, f"{source} 拉取失败: {exc}", tried=[source]
            )
        if data is None:
            return await self._fallback_kline(symbol, period, [source])
        return await self._wrap_kline(target, data, [source])

    async def _wrap_kline(self, collector: BaseCollector, data, tried: list[str]) -> A2APayload:
        """将成功的 KlineData 包装为 A2APayload 并写入缓存。"""
        grade = "PRIMARY" if collector.name in ("tqsdk", "tdx_tq_local", "qmt_xtquant") else "DAILY"
        payload = A2APayload(
            type=DATA_TYPES["KLINE"],
            runtime_mode="independent",
            data=data.to_dict(),
        )
        payload.set_grade(grade)
        payload.meta["sources"] = [collector.name]
        payload.meta["contract"] = getattr(data, "contract", "")
        payload.meta["tried_sources"] = tried
        if self._cache is not None:
            key = self._kline_key(data.symbol, data.period)
            await self._cache.set(key, data.to_dict())
        return payload

    async def _fallback_kline(
        self, symbol: str, period: str, tried: list[str]
    ) -> A2APayload:
        """K 线最终回退：先查缓存，再标记不可用。"""
        if self._cache is not None:
            cached = await self._cache.get(self._kline_key(symbol, period))
            if cached is not None:
                payload = A2APayload(
                    type=DATA_TYPES["KLINE"],
                    runtime_mode="independent",
                    data=cached,
                )
                payload.set_grade("CACHED")
                payload.meta["sources"] = ["cache"]
                payload.meta["tried_sources"] = tried
                payload.add_warning("所有实时源不可用，返回缓存数据")
                return payload
        return self._unavailable(
            DATA_TYPES["KLINE"],
            symbol,
            f"所有数据源不可用，已尝试: {tried or '无可用源'}",
            tried=tried,
        )

    # ───────────────────────────────────────────────────────────
    # 行情快照
    # ───────────────────────────────────────────────────────────
    async def get_quote(self, symbol: str, source: str = "auto") -> A2APayload:
        """获取行情快照（自动降级；仅实现 get_quote 的源参与）。"""
        collectors = (
            [c for c in self._collectors if c.name == source]
            if source != "auto"
            else select_by_priority(self._collectors)
        )
        tried: list[str] = []
        for collector in collectors:
            if not await collector.check_available():
                continue
            tried.append(collector.name)
            try:
                quote = await collector.get_quote(symbol)
            except CollectorUnavailableError:
                continue
            if quote is None:
                continue
            payload = A2APayload(
                type=DATA_TYPES["QUOTE"],
                runtime_mode="independent",
                data=quote.to_dict(),
            )
            payload.set_grade("PRIMARY" if collector.name == "tdx_tq_local" else "DAILY")
            payload.meta["sources"] = [collector.name]
            return payload

        if self._cache is not None:
            cached = await self._cache.get(self._quote_key(symbol))
            if cached is not None:
                payload = A2APayload(
                    type=DATA_TYPES["QUOTE"],
                    runtime_mode="independent",
                    data=cached,
                )
                payload.set_grade("CACHED")
                payload.meta["sources"] = ["cache"]
                payload.meta["tried_sources"] = tried
                payload.add_warning("所有实时源不可用，返回缓存行情")
                return payload
        return self._unavailable(
            DATA_TYPES["QUOTE"],
            symbol,
            f"所有行情源不可用，已尝试: {tried or '无可用源'}",
            tried=tried,
        )

    # ───────────────────────────────────────────────────────────
    # 工具
    # ───────────────────────────────────────────────────────────
    @staticmethod
    def _kline_key(symbol: str, period: str) -> str:
        return f"kline:{symbol}:{period}"

    @staticmethod
    def _quote_key(symbol: str) -> str:
        return f"quote:{symbol}"

    @staticmethod
    def _unavailable(dtype: str, symbol: str, reason: str, tried: list | None = None) -> A2APayload:
        """构造 UNAVAILABLE 信封。"""
        payload = A2APayload(
            type=dtype,
            runtime_mode="independent",
            data={"symbol": symbol, "bars": [] if "kline" in dtype else None},
        )
        payload.set_grade("UNAVAILABLE")
        payload.meta["tried_sources"] = tried or []
        payload.add_warning(reason)
        return payload
