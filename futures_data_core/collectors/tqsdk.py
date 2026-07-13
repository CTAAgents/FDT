"""天勤 TqSDK 采集器 [INDEPENDENT]。

基于 ``tqsdk`` 同步阻塞 API，通过 ``asyncio.to_thread`` 包装为异步接口。
``tqsdk`` 为可选依赖（见 ``pyproject.toml`` 的 ``tqsdk`` extra），未安装时
:meth:`check_available` 返回 ``False``，降级链自动跳过本采集器。

注意：天勤没有"主力连续"便捷接口，故 :meth:`get_kline` 需要显式传入合约代码
（如 ``"SHFE.cu2408"``）；未传合约时抛出 :class:`CollectorUnavailableError`，
由适配器跳过并降级到下一源。
"""

from __future__ import annotations

import asyncio
from typing import Any

from futures_data_core.collectors.base import (
    BaseCollector,
    CollectorType,
    CollectorUnavailableError,
)
from futures_data_core.core.types import KlineBar, KlineData

# 周期 -> TqSDK 秒级 duration
_PERIOD_SECONDS = {
    "daily": 86400,
    "1d": 86400,
    "60m": 3600,
    "120m": 7200,
    "240m": 14400,
    "weekly": 604800,
    "1w": 604800,
}


class TqSdkCollector(BaseCollector):
    """天勤 TqSDK 采集器（priority=1，第二数据源）。"""

    name = "tqsdk"
    priority = 1
    collector_type = CollectorType.INDEPENDENT
    llm_requirement = ""

    async def check_available(self) -> bool:
        """探测 tqsdk 是否可导入。"""
        try:
            __import__("tqsdk")
            return True
        except Exception:
            return False

    async def get_kline(
        self, symbol: str, period: str = "daily", days: int = 120, contract: str | None = None
    ) -> KlineData:
        """获取 K 线数据。

        Args:
            symbol: 品种代码（仅用于回填元数据）。
            period: 周期。
            days: 回溯交易日数。
            contract: TqSDK 合约代码（必填，如 ``"SHFE.cu2408"``）。

        Raises:
            CollectorUnavailableError: 未提供合约或拉取异常。
        """
        if contract is None:
            raise CollectorUnavailableError(
                self.name, "TqSDK 需要显式指定合约代码（如 SHFE.cu2408）"
            )
        try:
            df = await asyncio.to_thread(self._fetch_sync, contract, period, days)
        except CollectorUnavailableError:
            raise
        except Exception as exc:
            raise CollectorUnavailableError(self.name, str(exc)) from exc

        bars = self._parse(df, days)
        return KlineData(
            symbol=symbol,
            period=period,
            source=self.name,
            bars=bars,
            contract=contract,
        )

    def _fetch_sync(self, contract: str, period: str, days: int) -> Any:
        """同步拉取（在 ``asyncio.to_thread`` 中执行）。

        仅在安装了 ``tqsdk`` 时可用；未安装将抛出 ImportError 并被上层捕获。
        """
        from tqsdk import TqApi

        duration = _PERIOD_SECONDS.get(period, 86400)
        api = TqApi()
        try:
            df = api.get_kline_serial(contract, duration, data_length=days)
        finally:
            api.close()
        return df

    @staticmethod
    def _parse(df: Any, days: int) -> list[KlineBar]:
        """从 TqSDK K 线 DataFrame 解析为 KlineBar 列表。"""
        bars: list[KlineBar] = []
        try:
            rows = list(df.tail(days).itertuples(index=False))
        except Exception:
            return bars
        for row in rows:
            try:
                bars.append(
                    KlineBar(
                        date=str(getattr(row, "datetime")),
                        open=float(getattr(row, "open")),
                        high=float(getattr(row, "high")),
                        low=float(getattr(row, "low")),
                        close=float(getattr(row, "close")),
                        volume=float(getattr(row, "volume", 0.0) or 0.0),
                    )
                )
            except (TypeError, ValueError):
                continue
        return bars

    async def get_quote(self, symbol: str, contract: str | None = None) -> None:
        """TqSDK 快照需显式合约；未实现默认抛出（保持基类语义）。"""
        raise CollectorUnavailableError(
            self.name, "TqSDK 行情快照需显式指定合约，暂未实现"
        )
