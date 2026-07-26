"""数据适配层 — 数据源抽象基类（G23 接口分层）。

层次结构:

    DataSource (通用接口: K线/行情/批量行情/宏观)
      ├── FuturesDataSource (期货专有: 仓单/库存/持仓排名/基差/期限结构)
      ├── EquityDataSource (权益通用: 财务/分红/北向)
      │     ├── ConvertibleBondDataSource (可转债: 转股价/溢价率/纯债价值)
      │     └── REITDataSource (REITs: 底层运营/NAV折价)

用法:
    新增数据源只需继承对应基类，实现全部抽象方法。
    在 __init__.py 注册路由，下游零修改。
"""

from abc import ABC, abstractmethod
from typing import Optional

from data_adapter.types import KlineResult, QuoteResult


# ═══════════════════════════════════════════════════════
# Layer 0: 通用接口 — 全品种通用的数据方法
# ═══════════════════════════════════════════════════════

class DataSource(ABC):
    """数据源插座接口（G23 §3.2 通用层）。

    所有品种类型均需实现的 3 个通用数据方法 + 2 个宏观方法。
    """

    @abstractmethod
    async def get_kline(self, symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
        """获取 K 线数据。

        Args:
            symbol: 品种代码（如 "RB", "600519"）。
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

    @staticmethod
    def _unavailable_dict(reason: str = "数据源不可用") -> dict:
        return {"data": {}, "summary": reason, "data_grade": "UNAVAILABLE"}


# ═══════════════════════════════════════════════════════
# Layer 1: 期货专有接口（G23 §3.2 FuturesDataSource）
# ═══════════════════════════════════════════════════════

class FuturesDataSource(DataSource):
    """期货专有数据源（G23 §3.2）。

    在 DataSource 通用方法之上，增加期货特有的数据方法。
    """

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

    async def get_price_adjustment(self, symbol: str) -> float:
        """计算连续合约与具体合约的价差（G97）。

        基类默认返回 0.0（无调整）。子类可覆盖以实现实际价差计算。
        正值表示连续合约价格低于具体合约。

        Args:
            symbol: 品种代码（如 "RB"）。

        Returns:
            float 价差值。
        """
        return 0.0


# ═══════════════════════════════════════════════════════
# Layer 1: 权益通用接口（G23 §3.2 EquityDataSource）
# ═══════════════════════════════════════════════════════

class EquityDataSource(DataSource):
    """权益通用数据源（G23 §3.2）—— 股票/ETF 共用。

    在 DataSource 通用方法之上，增加权益专有数据方法。
    """

    @abstractmethod
    async def get_financials(self, symbol: str) -> dict:
        """获取财务报表核心指标（三表）。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 revenue / net_profit / total_assets / total_liabilities / cash_flow。
        """
        ...

    @abstractmethod
    async def get_dividend(self, symbol: str) -> dict:
        """获取分红记录。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 dividend_yield / payout_ratio / dividend_years。
        """
        ...

    @abstractmethod
    async def get_north_flow(self, symbol: str) -> dict:
        """获取北向资金流向（沪/深股通）。

        Args:
            symbol: 品种代码。

        Returns:
            dict 含 north_net_buy / north_holding / north_holding_pct。
        """
        ...

    # ── ETF 专有接口（G23 Phase 4 重点） ──

    @abstractmethod
    async def get_etf_nav(self, symbol: str) -> dict:
        """获取 ETF 净值数据（实时净值 + 历史净值序列）。

        Args:
            symbol: ETF 代码。

        Returns:
            dict 含 nav / nav_date / nav_history / accum_nav。
        """
        ...

    @abstractmethod
    async def get_etf_constituents(self, symbol: str) -> dict:
        """获取 ETF 成分股列表及权重。

        Args:
            symbol: ETF 代码。

        Returns:
            dict 含 constituents（[{stock, weight, amount}]）/ total_count。
        """
        ...

    @abstractmethod
    async def get_etf_premium(self, symbol: str) -> dict:
        """获取 ETF 溢价率。

        Args:
            symbol: ETF 代码。

        Returns:
            dict 含 premium_pct / market_price / nav / discount_pct。
        """
        ...


# ═══════════════════════════════════════════════════════
# Layer 2: 可转债专有接口（G23 §3.2 ConvertibleBondDataSource）
# ═══════════════════════════════════════════════════════

class ConvertibleBondDataSource(EquityDataSource):
    """可转债专有数据源（G23 §3.2）。

    继承 EquityDataSource（可转债有正股逻辑），
    增加可转债特有数据方法。
    """

    @abstractmethod
    async def get_cb_info(self, symbol: str) -> dict:
        """获取可转债基本信息（转股价/纯债价值/到期日等）。

        Args:
            symbol: 可转债代码。

        Returns:
            dict 含 conversion_price / pure_bond_value / maturity_date / coupon_rate。
        """
        ...

    @abstractmethod
    async def get_cb_premium(self, symbol: str) -> dict:
        """获取可转债溢价率。

        Args:
            symbol: 可转债代码。

        Returns:
            dict 含 conversion_premium / pure_bond_premium / ytm。
        """
        ...


# ═══════════════════════════════════════════════════════
# Layer 2: REITs 专有接口（G23 §3.2 REITDataSource）
# ═══════════════════════════════════════════════════════

class REITDataSource(EquityDataSource):
    """REITs 专有数据源（G23 §3.2）。

    继承 EquityDataSource（REITs 有分红/财务逻辑），
    增加 REITs 特有数据方法。
    """

    @abstractmethod
    async def get_reit_ops(self, symbol: str) -> dict:
        """获取 REITs 底层运营数据。

        Args:
            symbol: REITs 代码。

        Returns:
            dict 含 occupancy_rate / rent_per_sqm / total_area / revenue。
        """
        ...

    @abstractmethod
    async def get_reit_valuation(self, symbol: str) -> dict:
        """获取 REITs 估值数据。

        Args:
            symbol: REITs 代码。

        Returns:
            dict 含 nav / nav_discount / dividend_rate / p_ffo。
        """
        ...
