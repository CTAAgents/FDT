"""归一化数据载体 [INDEPENDENT]。

采集器输出的统一数据结构，脱离具体数据源格式，便于 A2A 封装、缓存与跨源
对比。所有采集器（TDX / TqSDK / AKShare / 东方财富）均返回这些类型，
调用方无需关心底层协议差异。

设计要点：
    - 纯数据、可 JSON 序列化（``to_dict``）。
    - ``as_dataframe`` 为可选能力，仅在调用方安装了 pandas 时可用。
    - 不依赖任何网络或 LLM。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KlineBar:
    """单根 K 线（OHLCV）。"""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0


@dataclass
class KlineData:
    """归一化 K 线序列。

    Attributes:
        symbol: 品种代码（如 ``"CU"``）。
        period: 周期（``daily`` / ``60m`` / ``120m`` / ``240m`` / ``weekly``）。
        source: 数据来源采集器名（如 ``"tdx_tq_local"``）。
        bars: K 线列表（按日期升序）。
        contract: 实际使用的合约代码（如 ``"CU2408"``）；品种级查询时填充。
        collected_at: 采集时间戳（epoch 秒）。
    """

    symbol: str
    period: str
    source: str
    bars: list[KlineBar] = field(default_factory=list)
    contract: str = ""
    collected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """序列化为 JSON 友好的 dict。"""
        return {
            "symbol": self.symbol,
            "period": self.period,
            "source": self.source,
            "contract": self.contract,
            "count": len(self.bars),
            "collected_at": self.collected_at,
            "bars": [
                {
                    "date": b.date,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "amount": b.amount,
                }
                for b in self.bars
            ],
        }

    def as_dataframe(self):
        """转换为 pandas.DataFrame（懒加载 pandas）。

        Returns:
            列顺序为 ``date, open, high, low, close, volume, amount`` 的 DataFrame。

        Raises:
            ImportError: 运行环境未安装 pandas。
        """
        import pandas as pd

        return pd.DataFrame(
            [
                {
                    "date": b.date,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "amount": b.amount,
                }
                for b in self.bars
            ]
        )


@dataclass
class QuoteData:
    """归一化行情快照。

    Attributes:
        symbol: 品种代码。
        source: 数据来源采集器名。
        last_price: 最新价。
        open / high / low / pre_close: 开/高/低/昨收。
        volume: 成交量。
        collected_at: 采集时间戳（epoch 秒）。
    """

    symbol: str
    source: str
    last_price: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    pre_close: Optional[float] = None
    volume: Optional[float] = None
    collected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """序列化为 JSON 友好的 dict。"""
        return {
            "symbol": self.symbol,
            "source": self.source,
            "last_price": self.last_price,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "pre_close": self.pre_close,
            "volume": self.volume,
            "collected_at": self.collected_at,
        }
