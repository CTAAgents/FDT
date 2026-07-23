"""多源降级链路由 [INDEPENDENT]。

将多个 :class:`~futures_data_core.collectors.base.BaseCollector` 按优先级编排为
异步降级链：依次尝试可用数据源，首个成功者即返回（包装为 :class:`A2APayload`）；
全部失败时回退到缓存（Postgres / Redis / Memory）；仍无则标记 ``UNAVAILABLE``。

数据等级约定：
    - ``tdx_tq_local`` / ``tqsdk`` 成功 -> ``PRIMARY``
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
from futures_data_core.collectors.datacore import DataCoreCollector
from futures_data_core.collectors.qmt import QMTCollector
from futures_data_core.collectors.tdx import TDXCollector
from futures_data_core.collectors.tqsdk import TqSdkCollector
from futures_data_core.collectors.web_fallback import WebFallbackCollector
from futures_data_core.core.cache_store import CacheStore
from futures_data_core.core.circuit_breaker import CircuitBreaker
from futures_data_core.core.dominant_resolver import DominantResolver


def _default_collectors() -> list[BaseCollector]:
    """构建默认采集器列表（按优先级升序）。

    🔴 数据源优先级（2026-07-23 调整：TqSDK 升至第一数据源）：
        0. TqSdkCollector — 天勤量化（第一数据源，priority=-1，最高）
        1. DataCoreCollector — Data-Core 统一数据接口（priority=0）
        2. TDXCollector(TQ-Local) — 通达信本地TQ-Local（priority=0）
        3. WebFallbackCollector — 东方财富+新浪（priority=1）
        4. QMTCollector — QMT/xtquant（priority=2）
        各源数据过期时自动降级（新鲜度检查 >7 日继续下一源）。
    """
    return select_by_priority(
        [
            TqSdkCollector(),       # 第一数据源：天勤量化
            DataCoreCollector(),    # 降级：Data-Core 统一接口
            TDXCollector(),         # 降级：通达信TQ-Local
            WebFallbackCollector(), # 降级：东方财富+新浪
            QMTCollector(),         # 最后兜底：QMT/xtquant
        ]
    )


class MultiSourceAdapter:
    """多源降级链适配器。"""

    def __init__(
        self,
        collectors: Optional[list[BaseCollector]] = None,
        cache: Optional[CacheStore] = None,
        resolver: Optional[DominantResolver] = None,
    ) -> None:
        """初始化。

        Args:
            collectors: 采集器列表；``None`` 时使用默认四源。
            cache: 可选的 :class:`CacheStore` 用于最终回退与写入。
            resolver: 可选的 :class:`DominantResolver`；``None`` 时自动创建。
        """
        self._collectors = list(collectors) if collectors is not None else _default_collectors()
        self._cache = cache
        self._resolver = resolver or DominantResolver()
        # ── A1 数据源熔断：每个采集器名一个熔断器，连续失败自动屏蔽 ──
        self._breakers: dict[str, CircuitBreaker] = {}
        self._breaker_cfg = {"failure_threshold": 5, "cooldown": 60.0}

    def register(self, collector: BaseCollector) -> None:
        """注册/追加一个采集器（保持优先级有序）。"""
        self._collectors.append(collector)
        self._collectors = select_by_priority(self._collectors)

    # ───────────────────────────────────────────────────────────
    # A1 熔断辅助
    # ───────────────────────────────────────────────────────────
    def _breaker(self, name: str) -> CircuitBreaker:
        b = self._breakers.get(name)
        if b is None:
            b = CircuitBreaker(name=name, **self._breaker_cfg)
            self._breakers[name] = b
        return b

    def source_health(self) -> dict:
        """各数据源熔断状态：{'tdx_tq_local': 'closed'/'open'/'half_open', ...}。"""
        return {name: b.state() for name, b in self._breakers.items()}

    # ───────────────────────────────────────────────────────────
    # K 线
    # ───────────────────────────────────────────────────────────
    async def get_kline(
        self, symbol: str, period: str = "daily", days: int = 120, source: str = "auto"
    ) -> A2APayload:
        """获取 K 线（自动降级）。

        ``symbol`` 可以是品种代码（如 ``"RB"``）或合约代码（如 ``"RB2505"``）。
        各采集器内部自行处理品种→合约的转换（如 TqSdk 的 ``_resolve_continuous``
        将 ``"RB"`` 转为 ``"KQ.m@SHFE.rb"`` 主力连续合约）。

        🛡️ v9.4.1 修复：移除入口处的"自动主力解析"。之前 ``DominantResolver``
        在 ``memory/dominant_map.json`` 不存在时返回 ``f"{variety}00"`` 这种
        不存在的合约代码（如 ``"RB00"``），导致 WebFallback / TqSDK 等采集器
        都识别失败。改由各采集器内部根据自身能力处理 symbol 转换，避免
        平台无关的后备代码污染整个降级链。

        Args:
            symbol: 品种代码或合约代码。
            period: 周期。
            days: 回溯交易日数。
            source: ``"auto"`` 走降级链；否则指定采集器名（如 ``"tdx_tq_local"``）。

        Returns:
            :class:`A2APayload`，``data`` 为 KlineData 的 dict 表示。
        """
        return await self._collect_kline_impl(symbol, period, days, source)

    async def _collect_kline_impl(
        self, symbol: str, period: str = "daily", days: int = 120, source: str = "auto"
    ) -> A2APayload:
        """K 线采集实现（含降级链，不做主力解析）。"""
        if source != "auto":
            return await self._get_kline_explicit(symbol, period, days, source)

        tried: list[str] = []
        for collector in select_by_priority(self._collectors):
            br = self._breaker(collector.name)
            if br.is_open():
                tried.append(f"{collector.name}(breaker-open)")
                continue
            if not await collector.check_available():
                continue
            tried.append(collector.name)
            try:
                data = await collector.get_kline(symbol, period, days)
            except CollectorUnavailableError:
                br.record_failure()
                continue
            if data is None or not getattr(data, "bars", None):
                # 🛡️ 2026-07-15 修复：TQ-Local 等源可能返回空 KlineData（bars=[]）
                # 而非抛异常，原逻辑 data is None 判空漏掉此情况，导致空数据被当
                # 成功、降级链中断。判空后继续降级，确保落到 Web/QMT/TqSDK。
                br.record_failure()
                continue
            # 🛡️ 2026-07-23: 数据新鲜度检查 — 末根K线距今>7日(≈5交易日)视为过期
            # DataCore 等源可能返回已到期合约的旧数据（如 SM 停在2026-01-19），
            # 若无此检查，降级链将在此终止，WebFallback/天勤等有新鲜数据的源不被调用。
            _bars = data.bars
            if _bars:
                _lb = _bars[-1]
                _ds = getattr(_lb, 'date', '') or ''
                _clean = _ds[:10].replace('-', '')[:8]
                if _clean.isdigit():
                    from datetime import datetime as _dt
                    _bd = _dt.strptime(_clean, "%Y%m%d")
                    _sd = (_dt.now() - _bd).days
                    if _sd > 7:
                        import logging as _lg
                        _lg.getLogger(__name__).info(
                            "[Freshness] %s 末根K线(%s)距今%sd，视为过期，继续降级",
                            symbol, _ds, _sd,
                        )
                        br.record_failure()
                        continue
            br.record_success()
            return await self._wrap_kline(collector, data, tried)

        return await self._fallback_kline(symbol, period, tried)

    async def get_contract_kline(
        self, contract: str, period: str = "daily", days: int = 120, source: str = "auto"
    ) -> A2APayload:
        """F10 用：按指定合约代码精确查询，不经过主力解析。

        Args:
            contract: 合约代码（如 ``"CU2409"``）。
            period: 周期。
            days: 回溯交易日数。
            source: 数据源。

        Returns:
            :class:`A2APayload`。
        """
        return await self._collect_kline_impl(contract, period, days, source)

    async def get_all_active_contracts(self, variety: str) -> list[str]:
        """期限结构用：获取品种所有活跃合约月份。

        委托给首个支持 get_all_contracts 的采集器；不支持则返回空列表。

        Args:
            variety: 品种代码。

        Returns:
            活跃合约代码列表。
        """
        for collector in select_by_priority(self._collectors):
            if hasattr(collector, "get_all_contracts") and await collector.check_available():
                import asyncio
                try:
                    contracts = await collector.get_all_contracts(variety)
                    return [c.code for c in contracts]
                except Exception:
                    continue
        return []

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
        br = self._breaker(target.name)
        if br.is_open():
            return await self._fallback_kline(symbol, period, [source])
        if not await target.check_available():
            return await self._fallback_kline(symbol, period, [source])
        try:
            data = await target.get_kline(symbol, period, days)
        except CollectorUnavailableError as exc:
            br.record_failure()
            return self._unavailable(
                DATA_TYPES["KLINE"], symbol, f"{source} 拉取失败: {exc}", tried=[source]
            )
        if data is None:
            return await self._fallback_kline(symbol, period, [source])
        br.record_success()
        return await self._wrap_kline(target, data, [source])

    async def _wrap_kline(self, collector: BaseCollector, data, tried: list[str]) -> A2APayload:
        """将成功的 KlineData 包装为 A2APayload 并写入缓存。"""
        grade = "PRIMARY" if collector.name in ("tqsdk", "tdx_tq_local", "qmt_xtquant") else "DAILY"
        # ── 统一 K 线数据标准化 ──
        # normalize_kline_row 处理所有采集器的字段名/日期格式差异，确保下游一致消费
        from futures_data_core.core.field_normalizer import normalize_kline_row
        normalized_bars = [normalize_kline_row(b.__dict__ if hasattr(b, '__dict__') else b) for b in data.bars]
        payload = A2APayload(
            type=DATA_TYPES["KLINE"],
            runtime_mode="independent",
            data={"bars": normalized_bars, "contract": getattr(data, "contract", "")},
        )
        payload.set_grade(grade)
        payload.meta["sources"] = [collector.name]
        payload.meta["contract"] = getattr(data, "contract", "")
        payload.meta["tried_sources"] = tried
        if self._cache is not None:
            key = self._kline_key(data.symbol, data.period)
            await self._cache.set(key, payload.data)
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
            br = self._breaker(collector.name)
            if br.is_open():
                tried.append(f"{collector.name}(breaker-open)")
                continue
            if not await collector.check_available():
                continue
            tried.append(collector.name)
            try:
                quote = await collector.get_quote(symbol)
            except CollectorUnavailableError:
                br.record_failure()
                continue
            if quote is None:
                continue
            br.record_success()
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
    # 批量行情快照（双源融合用）
    # ───────────────────────────────────────────────────────────
    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """批量获取行情快照，返回 {symbol: {last_price, pre_close, ...}}。

        双源融合用：scan_all.py Step 1.5 批量采集，不支持则返回空 dict。
        """
        quotes_map = {}
        # 仅选择支持 get_quote 的采集器（TQ-Local 优先）
        for collector in select_by_priority(self._collectors):
            if not hasattr(collector, "get_quote"):
                continue
            if not await collector.check_available():
                continue
            # 用首个可用源批量拉取
            import asyncio
            tasks = {}
            for sym in symbols:
                try:
                    tasks[sym] = asyncio.ensure_future(collector.get_quote(sym))
                except Exception:
                    continue
            if not tasks:
                continue
            # 等待所有报价返回（超时5s）
            done, _ = await asyncio.wait(tasks.values(), timeout=5.0)
            for sym, fut in tasks.items():
                if fut in done and not fut.exception():
                    try:
                        q = fut.result()
                        if q:
                            quotes_map[sym] = {
                                "last_price": q.last_price,
                                "pre_close": q.pre_close,
                                "open": q.open,
                                "high": q.high,
                                "low": q.low,
                                "volume": q.volume,
                                "source": q.source,
                            }
                    except Exception:
                        continue
            # 只要 TDX 成功就够，不降级到其他源
            break
        return quotes_map

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
