"""WestockSource 数据源实现 — 国际期货行情数据获取。

通过 westock MCP 获取国际期货（WTI原油/布伦特/天然气/黄金等）行情数据。
MCP 仅在 agent 会话中可用，因此本数据源采用"预取缓存"模式:

  1. Agent 调用 prefetch_westock.py 脚本 (通过 run_mcp 获取原始数据)
  2. 脚本将行情数据写入 JSON 缓存文件
  3. WestockSource 读取缓存文件返回标准化 KlineResult/QuoteResult

缓存路径: d:\Programs\FDT\data_adapter\.westock_cache\{symbol}.json

适用品种 (标准代码/ westock 代码):
  CL/fuCL  - WTI原油     NG/fuNG  - 天然气     GC/fuGC  - COMEX黄金
  OIL/hf_OIL - 布伦特原油  RB/fuRB  - RBOB汽油   SI/fuSI  - COMEX白银
  HO/fuHO  - 取暖油      HG/fuHG  - COMEX铜
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from data_adapter.base import DataSource
from data_adapter.types import KlineBar, KlineResult, QuoteResult
from data_adapter.instrument_classifier import (
    classify, MarketType, get_international_futures_params,
    get_westock_code, intl_get_market_label,
)

logger = logging.getLogger(__name__)

# ── 缓存配置 ──
_CACHE_DIR = Path(__file__).parent / ".westock_cache"
_CACHE_TTL = 3600  # 1小时


class WestockSource(DataSource):
    """westock 数据源 — 国际期货行情适配器（通过MCP预取缓存桥接）。

    核心能力:
      - get_quote: 读取MCP预取的行情快照缓存
      - get_kline: 读取MCP预取的K线缓存
      - get_contract_info: 返回国际期货合约标准参数

    不适用的接口:
      - get_warrant / get_inventory / get_position_ranking
      - get_fund_flow / get_foreign_hist
      - get_basis / get_term_structure / get_spread
    """

    def __init__(self):
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════
    # 核心方法
    # ═══════════════════════════════════════════

    async def get_quote(self, symbol: str) -> QuoteResult:
        """从预取缓存读取国际期货行情快照。"""
        mt = classify(symbol)
        if mt != MarketType.INTERNATIONAL_FUTURES:
            return QuoteResult(symbol=symbol,
                               meta={"data_grade": "UNAVAILABLE", "source": "westock",
                                      "reason": f"WestockSource 仅支持国际期货，收到 {mt}"})

        # 读取缓存
        cache = self._read_cache(symbol)
        if cache is None or not cache.get("quote"):
            return QuoteResult(symbol=symbol,
                               meta={"data_grade": "UNAVAILABLE", "source": "westock",
                                      "reason": "数据未预取，请先运行 prefetch_westock.py",
                                      "hint": f"python prefetch_westock.py --symbol {symbol}"})

        q = cache["quote"]
        params = get_international_futures_params(symbol)
        std_symbol = params.get("symbol", symbol)

        return QuoteResult(
            symbol=std_symbol,
            last_price=float(q.get("lastPrice", 0)),
            open=float(q.get("open", 0)),
            high=float(q.get("high", 0)),
            low=float(q.get("low", 0)),
            volume=float(q.get("volume", 0)),
            open_interest=float(q.get("openInterest", 0)),
            change_pct=float(q.get("changePct", 0)),
            meta={
                "data_grade": "PRIMARY",
                "source": "westock",
                "westock_code": q.get("code", ""),
                "name": params.get("name", ""),
                "currency": params.get("currency", "USD"),
                "exchange": params.get("exchange", ""),
                "prev_close": q.get("prevClose", 0),
                "prev_settlement": q.get("prevSettlement", 0),
                "vwap": q.get("vwap", 0),
                "week52_high": q.get("week52High", 0),
                "week52_low": q.get("week52Low", 0),
                "update_time": q.get("updateTime", ""),
                "is_delayed": q.get("isDelayed", True),
            },
        )

    async def get_kline(self, symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
        """从预取缓存读取国际期货K线。"""
        mt = classify(symbol)
        if mt != MarketType.INTERNATIONAL_FUTURES:
            return KlineResult(symbol=symbol, bars=[],
                               meta={"data_grade": "UNAVAILABLE", "source": "westock"})

        cache = self._read_cache(symbol)
        if cache is None or not cache.get("kline"):
            return KlineResult(symbol=symbol, bars=[],
                               meta={"data_grade": "UNAVAILABLE", "source": "westock",
                                      "reason": "K线数据未预取，请先运行 prefetch_westock.py"})

        params = get_international_futures_params(symbol)
        std_symbol = params.get("symbol", symbol)
        nodes = cache["kline"]

        bars = []
        for n in nodes:
            try:
                bars.append(KlineBar(
                    date=str(n.get("date", "")).replace("-", ""),
                    open=float(n.get("open", 0)),
                    high=float(n.get("high", 0)),
                    low=float(n.get("low", 0)),
                    close=float(n.get("last", n.get("close", 0))),
                    volume=float(n.get("volume", 0)),
                ))
            except (ValueError, KeyError):
                continue

        bars = [b for b in bars if b.close > 0][-days:]
        return KlineResult(
            symbol=std_symbol, bars=bars,
            meta={"data_grade": "PRIMARY" if bars else "UNAVAILABLE",
                  "source": "westock", "period": period, "count": len(bars)},
        )

    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        results = {}
        for sym in symbols:
            results[sym] = await self.get_quote(sym)
        return results

    async def get_contract_info(self, symbol: str) -> dict:
        """返回国际期货合约信息（含实时价格）。"""
        try:
            params = get_international_futures_params(symbol)
            cache = self._read_cache(symbol)
            price = 0.0
            if cache and cache.get("quote"):
                price = float(cache["quote"].get("lastPrice", 0))

            return {
                "symbol": params.get("symbol", symbol),
                "product_name": params.get("name", ""),
                "exchange": params.get("exchange", ""),
                "currency": params.get("currency", "USD"),
                "multiplier": params.get("multiplier", 1),
                "westock_code": params.get("westock", ""),
                "last_price": price,
                "trading_hours": "CME Globex 几乎24小时",
                "data_grade": "PRIMARY" if price else "UNAVAILABLE",
            }
        except ValueError as e:
            return {"data": {}, "summary": str(e), "data_grade": "UNAVAILABLE"}

    # ═══════════════════════════════════════════
    # 不适用的接口
    # ═══════════════════════════════════════════

    async def get_warrant(self, symbol: str, exchange: str = "SHFE") -> dict:
        return self._unavailable_dict("国际期货无仓单日报")

    async def get_inventory(self, symbol: str) -> dict:
        return self._unavailable_dict("库存数据请通过 agent 查询 EIA/API 报告")

    async def get_position_ranking(self, symbol: str) -> dict:
        return self._unavailable_dict("CFTC COT 持仓报告请通过 agent 查询")

    async def get_fund_flow(self, symbol: str) -> dict:
        return self._unavailable_dict("国际期货无 A 股风格资金流数据")

    async def get_foreign_hist(self, symbol: str) -> dict:
        return self._unavailable_dict("国际期货自身即为外盘，无外盘历史")

    async def get_basis(self, symbol: str) -> dict:
        return self._unavailable_dict("基差请通过 agent 查询")

    async def get_term_structure(self, symbol: str) -> dict:
        return self._unavailable_dict("期限结构需通过 agent 用 run_mcp 获取多合约数据")

    async def get_spread(self, symbol: str) -> dict:
        return self._unavailable_dict("跨期价差需通过 agent 用 run_mcp 获取")

    async def get_macro_pmi(self) -> dict:
        return self._unavailable_dict("宏观数据请使用 AKShareSource")

    async def get_macro_rate(self) -> dict:
        return self._unavailable_dict("宏观数据请使用 AKShareSource")

    # ═══════════════════════════════════════════
    # 缓存管理
    # ═══════════════════════════════════════════

    def _read_cache(self, symbol: str) -> dict | None:
        """读取缓存JSON文件。自动处理标准代码和westock代码。"""
        params = get_international_futures_params(symbol)
        std = params.get("symbol", symbol)
        cache_file = _CACHE_DIR / f"{std}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 检查TTL
            ts = data.get("timestamp", 0)
            age = datetime.now().timestamp() - ts
            if age > _CACHE_TTL:
                logger.warning(f"[Westock] 缓存过期 ({age:.0f}s > {_CACHE_TTL}s): {cache_file}")
                return None

            return data
        except Exception as e:
            logger.warning(f"[Westock] 缓存读取失败: {cache_file}: {e}")
            return None

    @staticmethod
    def write_cache(symbol: str, quote: dict | None = None,
                    kline: list | None = None) -> str:
        """写入预取数据到缓存。由 prefetch_westock.py 调用。"""
        params = get_international_futures_params(symbol)
        std = params.get("symbol", symbol)
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = _CACHE_DIR / f"{std}.json"

        existing = {}
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    existing = json.load(f)
            except Exception:
                pass

        data = {
            "symbol": std,
            "westock_code": params.get("westock", ""),
            "timestamp": datetime.now().timestamp(),
            "name": params.get("name", ""),
        }
        if quote is not None:
            data["quote"] = quote
        elif existing.get("quote"):
            data["quote"] = existing["quote"]
        if kline is not None:
            data["kline"] = kline
        elif existing.get("kline"):
            data["kline"] = existing["kline"]

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(cache_file)
