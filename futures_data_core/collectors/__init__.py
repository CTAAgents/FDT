"""采集器层：数据源抽象与具体实现。"""

from futures_data_core.collectors.base import (
    BaseCollector,
    CollectorType,
    CollectorUnavailableError,
    select_by_priority,
)

__all__ = [
    "BaseCollector",
    "CollectorType",
    "CollectorUnavailableError",
    "select_by_priority",
]
