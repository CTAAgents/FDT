"""数据采集器抽象基类 [INDEPENDENT]。

所有具体采集器（TDX / TqSDK / AKShare / 东方财富）继承 :class:`BaseCollector`，
并通过 :class:`CollectorType` 声明运行模式。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class CollectorType(str, Enum):
    """采集器类型，对应运行模式。"""

    INDEPENDENT = "independent"     # 不依赖 LLM
    LLM_ENHANCED = "llm_enhanced"   # 可独立运行，LLM 为增强
    LLM_DRIVEN = "llm_driven"       # 必须 LLM 上下文


class BaseCollector(ABC):
    """数据采集器抽象基类。

    子类需定义类属性 ``name`` / ``priority``，并实现
    :meth:`check_available` 与 :meth:`get_kline`。
    """

    name: str = "base"
    priority: int = 99
    collector_type: CollectorType = CollectorType.INDEPENDENT
    llm_requirement: str = ""

    @abstractmethod
    async def check_available(self) -> bool:
        """探测当前环境是否可使用该数据源。"""
        raise NotImplementedError

    @abstractmethod
    async def get_kline(self, symbol: str, period: str = "daily", days: int = 120) -> Any:
        """获取 K 线数据。

        Args:
            symbol: 品种代码。
            period: 周期（``daily`` / ``60m`` / ``120m`` / ``240m``）。
            days: 回溯交易日数。

        Returns:
            K 线数据（具体类型由实现决定，通常为 pandas.DataFrame）。
        """
        raise NotImplementedError

    async def get_quote(self, symbol: str) -> Any:
        """获取行情快照（默认未实现）。"""
        raise NotImplementedError(f"{self.name} 不支持 get_quote")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<{type(self).__name__} name={self.name} priority={self.priority}>"


class CollectorUnavailableError(RuntimeError):
    """采集器不可用时抛出。"""

    def __init__(self, name: str, reason: str = "") -> None:
        self.collector_name = name
        super().__init__(f"采集器 {name} 不可用: {reason}")


def select_by_priority(collectors: list[BaseCollector]) -> list[BaseCollector]:
    """按优先级升序排序采集器列表（数值小者优先）。"""
    return sorted(collectors, key=lambda c: c.priority)
