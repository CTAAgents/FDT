"""数据适配层 — 数据源抽象基类。

所有数据源必须实现 DataSource 接口。新增数据源只需：
1. class MySource(DataSource): 实现全部抽象方法
2. 在 __init__.py 注册路由
3. 设置环境变量 FDT_DATA_SOURCE=mysource

下游零修改，直接生效。
"""

from abc import ABC, abstractmethod
from typing import Optional

from data_adapter.types import KlineResult, QuoteResult


class DataSource(ABC):
    """数据源插座接口。"""

    @abstractmethod
    async def get_kline(self, symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
        """获取 K 线数据。

        Args:
            symbol: 品种代码（如 "RB", "CF"）。
            period: 周期（"daily", "weekly", "monthly"）。
            days: 需要的数据天数。

        Returns:
            KlineResult，meta.data_grade 标记数据等级。
        """
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> QuoteResult:
        """获取行情快照。

        Args:
            symbol: 品种代码。

        Returns:
            QuoteResult，含最新价等信息。
        """
        ...

    @abstractmethod
    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        """批量获取行情快照。

        Args:
            symbols: 品种代码列表。

        Returns:
            {symbol: QuoteResult, ...} 映射。
        """
        ...

    @abstractmethod
    async def get_contract_info(self, symbol: str) -> dict:
        """获取合约信息（乘数/保证金率/最小变动价位等）。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 symbol / multiplier / margin_rate / price_tick / exchange / product_name。
        """
        ...

    @abstractmethod
    async def get_warrant(self, symbol: str, exchange: str = "SHFE") -> dict:
        """获取仓单日报。

        Args:
            symbol: 品种代码。
            exchange: 交易所（SHFE/DCE/CZCE/GFEX）。

        Returns:
            dict 含 total / daily_change / exchange。
        """
        ...

    @abstractmethod
    async def get_inventory(self, symbol: str) -> dict:
        """获取库存数据。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 inventory / change 等信息。
        """
        ...

    @abstractmethod
    async def get_position_ranking(self, symbol: str) -> dict:
        """获取持仓排名。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 net_long / top5_long / top5_short 等信息。
        """
        ...

    @abstractmethod
    async def get_fund_flow(self, symbol: str) -> dict:
        """获取资金流向（持仓/多空比）。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 total_oi / long_short_ratio 等信息。
        """
        ...

    @abstractmethod
    async def get_foreign_hist(self, symbol: str) -> dict:
        """获取外盘历史数据。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 foreign_symbol / close / bars 等信息。
        """
        ...

    @abstractmethod
    async def get_basis(self, symbol: str) -> dict:
        """获取基差数据（现货价格）。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 spot_price / basis / basis_pct。
        """
        ...

    @abstractmethod
    async def get_term_structure(self, symbol: str) -> dict:
        """获取期限结构数据（从合约序列计算）。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 near_contract / near_price / far_contract / far_price / slope / term_type / contracts。
        """
        ...

    @abstractmethod
    async def get_spread(self, symbol: str) -> dict:
        """获取跨期价差数据。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 spreads（逐月价差列表）。
        """
        ...

    @abstractmethod
    async def get_macro_pmi(self) -> dict:
        """获取 PMI 宏观数据。

        Returns:
            dict 含 pmi / pmi_mom。
        """
        ...

    @abstractmethod
    async def get_macro_rate(self) -> dict:
        """获取利率宏观数据（LPR）。

        Returns:
            dict 含 rate / rate_mom。
        """
        ...

    async def get_price_adjustment(self, symbol: str) -> float:
        """计算连续合约与具体合约的价差（G97）。

        基类默认返回 0.0（无调整）。子类可覆盖以实现实际价差计算。
        正值表示连续合约价格低于具体合约（如连续合约 5,670，具体合约 5,858 → 返回 188）。

        Args:
            symbol: 品种代码（如 "RB"）。

        Returns:
            float 价差值。
        """
        return 0.0

    @staticmethod
    def _unavailable_dict(reason: str = "数据源不可用") -> dict:
        return {"data": {}, "summary": reason, "data_grade": "UNAVAILABLE"}
