"""数据适配层 — 统一数据格式定义。

所有数据源实现都返回这些类型，下游消费者不关心底层数据源差异。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StructuredFundamentalMeta:
    """基本面数据单字段的结构化元数据。

    用于 ``fundamental-data-collector`` 的硬编码数据升级，
    附加在每条文本值旁，供清洗层消费。

    Attributes:
        value: 数值（可清洗校验）
        unit: 单位（如 "元/吨", "%", "万吨"）
        direction: 趋势方向（"上升"/"下降"/"持平"）
        data_date: 数据日期 YYYY-MM-DD
        source: 数据来源（如 "Mysteel", "隆众资讯"）
        revision: 版本号（初始 "v1"）
    """

    value: float | None = None
    unit: str = ""
    direction: str = ""
    data_date: str = ""
    source: str = ""
    revision: str = "v1"


@dataclass
class CleaningAction:
    """单条清洗动作记录。"""

    action: str        # "removed" / "fixed" / "marked" / "adjusted" / "deduped"
    field: str         # 清洗字段（如 "high", "volume", "date"）
    index: int         # bar 索引
    reason: str        # 原因说明
    original: str = "" # 原始值
    new: str = ""      # 修正值


@dataclass
class CleaningReport:
    """清洗报告，附着在 KlineResult 中透传下游。"""

    cleaning_id: str
    actions: list[CleaningAction]

    @property
    def total_actions(self) -> int:
        return len(self.actions)

    @property
    def removed_count(self) -> int:
        return sum(1 for a in self.actions if a.action == "removed")

    @property
    def fixed_count(self) -> int:
        return sum(1 for a in self.actions if a.action == "fixed")


@dataclass
class KlineBar:
    """单根 K 线（OHLCVI）。"""

    date: str  # "YYYYMMDD"
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float = 0.0


@dataclass
class KlineResult:
    """归一化 K 线序列。

    Attributes:
        symbol: 品种代码（如 "RB"）。
        bars: K 线列表（按日期升序）。
        meta: 元信息（data_grade: PRIMARY/UNAVAILABLE, source: "akshare"）。
        cleaning: 清洗报告（清洗层启用时非空）。
    """

    symbol: str
    bars: list[KlineBar]
    meta: dict = field(default_factory=lambda: {"data_grade": "PRIMARY", "source": "akshare"})
    cleaning: Optional[CleaningReport] = None


@dataclass
class QuoteResult:
    """归一化行情快照。"""

    symbol: str
    last_price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    open_interest: float = 0.0
    change_pct: float = 0.0
    meta: dict = field(default_factory=lambda: {"data_grade": "PRIMARY", "source": "akshare"})
