"""QMT/xtquant 采集器 [INDEPENDENT]。

通过 xtquant.xtdata 获取期货 K 线数据，本地 TCP 直取，零网络延迟。
xtquant 为可选依赖，未安装时 :meth:`check_available` 返回 ``False``，
降级链自动跳过。

当前实现仅覆盖 K 线；行情快照等其他接口后续可按需扩展。
"""

from __future__ import annotations

from typing import Any, Optional

from futures_data_core.collectors.base import (
    BaseCollector,
    CollectorType,
    CollectorUnavailableError,
)
from futures_data_core.core.types import KlineBar, KlineData


# QMT 周期 -> xtdata period 映射
_PERIOD_MAP: dict[str, str] = {
    "tick": "tick",
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "60m",
    "daily": "1d",
    "1d": "1d",
    "weekly": "1w",
    "1w": "1w",
    "1mon": "1mon",
}


class QMTCollector(BaseCollector):
    """QMT/xtquant 采集器（priority=2，第三数据源）。"""

    name = "qmt_xtquant"
    priority = 2
    collector_type = CollectorType.INDEPENDENT
    llm_requirement = ""

    async def check_available(self) -> bool:
        """探测 xtquant 是否可导入。"""
        try:
            __import__("xtquant")
            return True
        except Exception:
            return False

    async def get_kline(
        self,
        symbol: str,
        period: str = "daily",
        days: int = 120,
        contract: Optional[str] = None,
    ) -> KlineData:
        """获取 K 线数据。

        Args:
            symbol: 品种代码（如 ``"CU"``）。
            period: 周期（见 _PERIOD_MAP）。
            days: 回溯交易日数。
            contract: 可选，显式合约代码；缺省用主力连续。

        Raises:
            CollectorUnavailableError: xtquant 未安装、连接失败或拉取异常。
        """
        if not await self.check_available():
            raise CollectorUnavailableError(self.name, "xtquant 未安装")

        qmt_period = _PERIOD_MAP.get(period, "1d")
        try:
            import asyncio

            df = await asyncio.wait_for(
                asyncio.to_thread(
                    self._fetch_sync, symbol, qmt_period, days, contract
                ),
                timeout=20.0,
            )
        except asyncio.TimeoutError:
            # 🛡️ 2026-07-15 修复：xtdata.connect() 在 QMT 半通环境下无限挂死，
            # 加 20s 超时，超时即降级到末位 TqSDK，绝不阻塞整条降级链。
            raise CollectorUnavailableError(
                self.name, f"QMT get_kline 超时(20s) — {symbol}"
            )
        except CollectorUnavailableError:
            raise
        except Exception as exc:
            raise CollectorUnavailableError(self.name, str(exc)) from exc

        bars = self._parse(df, days)
        con_code = contract or f"{symbol.upper()}00"
        return KlineData(
            symbol=symbol,
            period=period,
            source=self.name,
            bars=bars,
            contract=con_code,
        )

    # ───────────────────────────────────────────────────────────
    # 同步底层
    # ───────────────────────────────────────────────────────────

    def _fetch_sync(
        self, symbol: str, period: str, days: int, contract: Optional[str]
    ) -> Any:
        """同步拉取 K 线（在 ``asyncio.to_thread`` 中执行）。"""
        from xtquant import xtdata

        con_code = contract or f"{symbol.upper()}00"
        try:
            xtdata.connect()
        except Exception as exc:
            raise CollectorUnavailableError(
                self.name, f"QMT 连接失败: {exc}"
            ) from exc

        result = xtdata.get_market_data_ex(
            [],
            [con_code],
            period=period,
            count=days,
            dividend_type="none",
        )
        if result is None or not isinstance(result, dict):
            raise CollectorUnavailableError(
                self.name, f"QMT 返回空数据: {con_code}"
            )
        return result

    # ───────────────────────────────────────────────────────────
    # 解析
    # ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse(df: Any, days: int) -> list[KlineBar]:
        """从 QMT DataFrame dict 解析为 KlineBar 列表。

        QMT ``get_market_data_ex`` 返回 ``{code: DataFrame}``，
        DataFrame 列含 time/open/high/low/close/volume/amount/settle/openInterest。
        """
        bars: list[KlineBar] = []
        try:
            import pandas as pd
        except ImportError:
            return bars

        if not isinstance(df, dict):
            return bars
        codes = list(df.keys())
        if not codes:
            return bars
        data = df[codes[0]]
        if not isinstance(data, pd.DataFrame) or data.empty:
            return bars

        rows = data.tail(days) if len(data) > days else data
        for _, row in rows.iterrows():
            try:
                bars.append(
                    KlineBar(
                        date=str(getattr(row, "time", "")),
                        open=_sf(getattr(row, "open", None)),
                        high=_sf(getattr(row, "high", None)),
                        low=_sf(getattr(row, "low", None)),
                        close=_sf(getattr(row, "close", None)),
                        volume=_sf(getattr(row, "volume", 0.0)),
                        amount=_sf(getattr(row, "amount", 0.0)),
                        open_interest=_sf(getattr(row, "openInterest", 0.0)),
                    )
                )
            except (TypeError, ValueError):
                continue
        return bars

    async def get_quote(self, symbol: str) -> None:
        """QMT 行情快照未实现，保持基类语义。"""
        raise CollectorUnavailableError(self.name, "QMT 行情快照未实现")


def _sf(value: Any) -> float:
    """安全浮点转换。"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
