"""
主力合约统一解析器 [INDEPENDENT]。

职责：
  1. 根据持仓量/成交量判定各品种当前主力合约
  2. 维护持久化映射表（memory/dominant_map.json）
  3. 检测换月事件并记录
  4. 提供 resolve() / refresh_all() / get_rollover_events() 三个核心接口

复用 logic：
  继承并迁移 skills/quant-daily/scripts/data/dominant_mapping.py 的
  DominantMappingCalculator 算法核心（持仓量排序、1.1倍阈值、金融期货成交量模式、
  最后交易日3日剔除规则），但去除文件系统依赖，改为纯内存 + 持久化存储。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from futures_data_core.collectors.base import BaseCollector
from futures_data_core.core.types import DominantMap, RolloverEvent

logger = logging.getLogger("fdt_dominant_resolver")

# 默认存储路径
_DEFAULT_STORAGE = Path("memory/dominant_map.json")
# 金融期货（中金所），按成交量判定
_FINANCIAL_VARIETIES = {"IF", "IC", "IM", "IH", "TS", "TF", "T", "TL"}


class DominantResolver:
    """主力合约统一解析器。

    Args:
        storage_path: 持久化映射表路径。None 时使用默认路径 memory/dominant_map.json。
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._storage = Path(storage_path) if storage_path else _DEFAULT_STORAGE
        self._mapping: dict[str, DominantMap] = {}      # variety -> DominantMap
        self._rollover_history: list[RolloverEvent] = []  # 换月事件列表
        self._loaded = False
        self._trade_date: str = datetime.now().strftime("%Y-%m-%d")

    # ── 持久化 ──────────────────────────────────────────────

    def load(self) -> None:
        """从持久化文件加载映射表。"""
        if not self._storage.exists():
            self._mapping = {}
            self._loaded = True
            return
        try:
            with open(self._storage, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._mapping = data.get("mapping", {})
            self._rollover_history = data.get("rollover_history", [])
            self._loaded = True
            logger.info("[DominantResolver] 已加载 %d 个品种的主力映射", len(self._mapping))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[DominantResolver] 加载映射表失败: %s，使用空映射", exc)
            self._mapping = {}
            self._loaded = True

    def save(self) -> None:
        """持久化当前映射表到文件。"""
        self._storage.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(),
            "mapping": self._mapping,
            "rollover_history": self._rollover_history,
        }
        with open(self._storage, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("[DominantResolver] 已持久化 %d 个品种的映射到 %s",
                     len(self._mapping), self._storage)

    # ── 核心接口 ────────────────────────────────────────────

    def resolve(self, variety: str) -> str:
        """返回品种当前主力合约代码。

        如 ``resolve("CU")`` 返回 ``"CU2409"``。

        Args:
            variety: 品种代码（2-6位字母）。

        Returns:
            当前主力合约代码，如无法确定则返回 ``f"{variety}00"`` 作为后备。
        """
        if not self._loaded:
            self.load()
        entry = self._mapping.get(variety)
        if entry and entry.get("main"):
            return entry["main"]  # type: ignore[return-value]
        # 后备：返回平台通用主力连续代码
        return f"{variety}00"

    def resolve_next(self, variety: str) -> str | None:
        """返回品种次主力合约代码。"""
        if not self._loaded:
            self.load()
        entry = self._mapping.get(variety)
        if entry and entry.get("next_main"):
            return entry["next_main"]  # type: ignore[return-value]
        return None

    def refresh_all(self, collector: BaseCollector) -> dict[str, DominantMap]:
        """遍历所有品种，基于数据源最新合约列表重新判定主力。

        使用 collector 获取全量合约列表和持仓量/成交量数据。

        Args:
            collector: 能提供全量合约列表的采集器（推荐 TDXCollector）。

        Returns:
            更新后的映射表 {variety: DominantMap}。
        """
        if not self._loaded:
            self.load()

        # 获取所有活跃合约（由 collector 实现）
        all_contracts = self._fetch_all_contracts(collector)
        if not all_contracts:
            logger.warning("[DominantResolver] 未获取到合约数据，跳过刷新")
            return self._mapping

        old_mapping = dict(self._mapping)
        new_mapping: dict[str, DominantMap] = {}
        switches: list[RolloverEvent] = []

        for variety, contracts in all_contracts.items():
            current_main = old_mapping.get(variety, {}).get("main")
            is_financial = variety in _FINANCIAL_VARIETIES
            result = self._calculate_dominant(
                variety=variety,
                contracts=contracts,
                current_main=current_main,
                trade_date=self._trade_date,
                is_financial=is_financial,
            )
            new_mapping[variety] = result
            if result.get("switched"):
                switches.append(RolloverEvent(
                    variety=variety,
                    prev_main=result.get("prev_main"),
                    new_main=result.get("main"),
                    switch_date=result.get("switch_date"),
                    gap=result.get("gap"),
                    prev_close=result.get("prev_close"),
                    new_open=None,
                ))

        self._mapping = new_mapping
        self._rollover_history.extend(switches)
        self.save()

        if switches:
            logger.info("[DominantResolver] 检测到 %d 个换月事件: %s",
                        len(switches), [(s["variety"], s["prev_main"], s["new_main"]) for s in switches])

        return self._mapping

    def get_rollover_events(self, variety: str | None = None,
                            since: str | None = None) -> list[RolloverEvent]:
        """获取换月事件列表。

        Args:
            variety: 品种过滤（None 返回全部）。
            since: 起始日期 YYYY-MM-DD（None 返回全部）。

        Returns:
            换月事件列表。
        """
        events = self._rollover_history
        if variety:
            events = [e for e in events if e.get("variety") == variety]
        if since:
            events = [e for e in events if (e.get("switch_date") or "") >= since]
        return events

    def get_mapping(self) -> dict[str, DominantMap]:
        """获取当前完整映射表。"""
        if not self._loaded:
            self.load()
        return dict(self._mapping)

    def resolve_with_gap_adjustment(self, variety: str, kline_bars: list) -> list:
        """获取主力连续合约 K 线，并对换月跳空做统一价差调整。

        将换月日前后价格的差值统一调整到所有历史价格上，保持序列连续。

        Args:
            variety: 品种代码。
            kline_bars: 原始 K 线数据（KlineBar 对象列表，按日期升序）。

        Returns:
            调整后的 K 线（原地修改 bars 中的 open/high/low/close）。
        """
        if len(kline_bars) < 2:
            return kline_bars

        events = self.get_rollover_events(variety)
        if not events:
            return kline_bars

        # 从最早到最晚排序
        events_sorted = sorted(
            [e for e in events if e.get("gap") is not None],
            key=lambda e: e.get("switch_date", "")
        )

        if not events_sorted:
            return kline_bars

        total_gap = sum(e["gap"] for e in events_sorted)  # type: ignore[operator]

        # 将累计跳空统一调整到所有 bar 的价格上
        for bar in kline_bars:
            bar.open -= total_gap   # type: ignore[operator]
            bar.high -= total_gap   # type: ignore[operator]
            bar.low -= total_gap    # type: ignore[operator]
            bar.close -= total_gap  # type: ignore[operator]

        return kline_bars

    # ── 内部方法 ────────────────────────────────────────────

    def _fetch_all_contracts(self, collector: BaseCollector) -> dict[str, list]:
        """从数据源获取全量合约列表（由调用方实现）。"""
        # 默认实现：期望 collector 有 get_all_contracts() 方法
        if hasattr(collector, "get_all_contracts"):
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(collector.get_all_contracts())
                loop.close()
                return result
            except Exception as exc:
                logger.warning("[DominantResolver] 获取全量合约失败: %s", exc)
        return {}

    def _calculate_dominant(
        self,
        variety: str,
        contracts: list,
        current_main: str | None = None,
        trade_date: str | None = None,
        is_financial: bool = False,
    ) -> DominantMap:
        """计算主力/次主力合约（复用 dominant_mapping.py 算法逻辑）。

        Args:
            variety: 品种代码
            contracts: 合约信息列表，每个元素需有 code/volume/open_interest/last_trade_date/close_price/delivery_month 属性
            current_main: 当前主力合约代码
            trade_date: 交易日
            is_financial: 是否为金融期货

        Returns:
            DominantMap
        """
        trade_dt = datetime.strptime(trade_date or self._trade_date, "%Y-%m-%d")

        # Step 1: 剔除最后交易日 ≤ T+3 的合约
        valid = [c for c in contracts
                 if _safe_dt(c.last_trade_date) > trade_dt + timedelta(days=3)]

        if not valid:
            return self._empty_result(variety, current_main, "所有合约临近交割")

        # Step 2: 按指标降序（商品=持仓量，金融=成交量）
        if is_financial:
            valid.sort(key=lambda c: getattr(c, "volume", 0), reverse=True)
        else:
            valid.sort(key=lambda c: getattr(c, "open_interest", 0), reverse=True)

        o1 = valid[0]
        o1_metric = o1.open_interest if not is_financial else o1.volume

        new_main: str | None = None
        switched = False
        switch_date: str | None = None
        gap: float | None = None
        prev_main = current_main

        if current_main and o1.code == current_main:
            new_main = o1.code
        elif current_main and o1.code != current_main:
            cur = next((c for c in valid if c.code == current_main), None)
            if cur:
                cur_metric = cur.open_interest if not is_financial else cur.volume
                if (o1_metric >= cur_metric * 1.1
                        and int(o1.delivery_month) > int(cur.delivery_month)):
                    new_main = o1.code
                    switched = True
                    switch_date = trade_date
                    gap = o1.close_price - cur.close_price
                else:
                    new_main = current_main
            else:
                new_main = o1.code
                switched = True
                switch_date = trade_date
        else:
            new_main = o1.code

        # 次主力
        next_main = None
        if len(valid) >= 2:
            for c in valid:
                if c.code != new_main:
                    next_main = c.code
                    break

        # 指数加权
        total_oi = sum(getattr(c, "open_interest", 0) for c in valid)
        index_price = (
            sum(c.open_interest * c.close_price for c in valid) / total_oi
            if total_oi > 0 else None
        )

        return DominantMap(
            variety=variety,
            main=new_main,
            next_main=next_main,
            index=f"{variety}99",
            index_price=index_price,
            prev_main=prev_main,
            switched=switched,
            switch_date=switch_date,
            gap=gap,
            prev_close=next(
                (c.close_price for c in contracts if c.code == prev_main), None
            ) if prev_main else None,
            updated_at=datetime.now().isoformat(),
        )

    @staticmethod
    def _empty_result(variety: str, prev_main: str | None, error: str) -> DominantMap:
        return DominantMap(
            variety=variety,
            main=None,
            next_main=None,
            index=None,
            index_price=None,
            prev_main=prev_main,
            switched=False,
            switch_date=None,
            gap=None,
            updated_at=datetime.now().isoformat(),
            error=error,
        )


def _safe_dt(date_str: str) -> datetime:
    """安全地将日期字符串转为 datetime。"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime(2099, 1, 1)


def has_month_suffix(symbol: str) -> bool:
    """判断品种代码是否包含合约月份后缀。

    ``"CU2409"`` → True，``"CU"`` → False。
    """
    if len(symbol) <= 4:
        return False
    suffix = symbol[-4:]
    return suffix.isdigit() and len(suffix) == 4
