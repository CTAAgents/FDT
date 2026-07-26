"""QQ/Sina 数据源实现 — 股指期货 + 国债期货行情数据获取。

通过腾讯 QQ 行情 API + 新浪财经 API 双源获取现货指数/国债指数数据，
结合股指期货/国债期货合约参数推导衍生品信息。

数据流:
  股指: IF2609 -> INDEX_FUTURES -> sh000300 -> QQ API -> 指数行情 -> 推导期货数据
  国债: TS2609 -> BOND_FUTURES -> sh000012 -> QQ API -> 国债指数 -> 推导期货数据

适用品种:
  - 股指期货: IF/IC/IH/IM (通过 sh000300/905/016/852)
  - 国债期货: TS/TF/T/TL (通过 sh000012 国债指数)

用法:
  FDT_DATA_SOURCE=qq_sina python fdt_cli.py run --mode deep_research
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from data_adapter.base import DataSource
from data_adapter.types import KlineBar, KlineResult, QuoteResult
from data_adapter.instrument_classifier import (
    classify, MarketType, get_spot_index_code, get_sina_spot_code,
    get_contract_params, parse_index_futures_code,
    parse_bond_futures_code, get_bond_params, get_bond_qq_code, get_bond_ref_price,
)

logger = logging.getLogger(__name__)

# ── HTTP 配置 ──
_HTTP_TIMEOUT = 15
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# ── QQ API 字段索引（指数格式，与股票格式不同！）──
# 验证方式: web.sqt.gtimg.cn/q=sh000300 返回 ~ 分隔字段
# [30]=datetime, [31]=change, [32]=change_pct, [33]=high, [34]=low
_QQ_FIELD_MAP = {
    "name": 1, "code": 2, "price": 3, "prev_close": 4, "open": 5,
    "volume": 6, "change": 31, "change_pct": 32,
    "high": 33, "low": 34,
    "turnover_rate": 38, "pe": 39,
    "high_52w": 67, "low_52w": 68, "amplitude": 43,
    "circ_mkt_cap": 44, "total_mkt_cap": 45, "volume_ratio": 49,
    "avg_price": 51, "ytd_pct": 63,
    "chg_10d": 69, "chg_20d": 70, "chg_60d": 71,
}

# ── 新浪 API 字段索引 ──
_SINA_FIELD_MAP = ["name", "price", "change", "change_pct", "volume_wan", "amount_wan"]


class QQSinaSource(DataSource):
    """QQ/Sina 数据源 — 股指期货 + 国债期货行情适配器。

    核心能力:
      - 股指期货 (IF/IC/IH/IM): 从 QQ 获取现货指数行情，推导期货价格
      - 国债期货 (TS/TF/T/TL): 从 QQ 获取国债指数行情，推导期货价格

    不适用的接口:
      - get_warrant / get_inventory / get_position_ranking
      - get_basis / get_term_structure / get_spread
      - get_fund_flow / get_foreign_hist
    """

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    # ═══════════════════════════════════════════
    # 核心方法
    # ═══════════════════════════════════════════

    async def get_quote(self, symbol: str) -> QuoteResult:
        """获取股指/国债期货行情快照。

        - 股指: IF2609 -> INDEX_FUTURES -> sh000300 -> QQ API
        - 国债: TS2609 -> BOND_FUTURES -> sh000012 -> QQ API
        """
        mt = classify(symbol)

        # ── 股指期货 ──
        if mt == MarketType.INDEX_FUTURES:
            spot_code = get_spot_index_code(symbol)
            qq_data = self._fetch_qq_quote(spot_code)
            if not qq_data:
                return QuoteResult(symbol=symbol, meta={"data_grade": "UNAVAILABLE", "source": "qq_sina",
                                                         "reason": "QQ API 无数据"})
            price_str = qq_data.get("price", "0")
            index_price = float(price_str) if price_str else 0.0
            params = get_contract_params(symbol)
            return QuoteResult(
                symbol=symbol, last_price=index_price,
                open=float(qq_data.get("open", 0)),
                high=float(qq_data.get("high", 0)),
                low=float(qq_data.get("low", 0)),
                volume=float(qq_data.get("volume", 0)),
                open_interest=0.0, change_pct=float(qq_data.get("change_pct", 0)),
                meta={"data_grade": "PRIMARY", "source": "qq_sina",
                      "spot_symbol": spot_code, "market_type": "index_futures",
                      "contract_multiplier": params["multiplier"],
                      "margin_rate": params["margin_rate"],
                      "notional_value": index_price * params["multiplier"],
                      "index_name": qq_data.get("name", ""),
                      "pe": qq_data.get("pe", "")},
            )

        # ── 国债期货 ──
        if mt == MarketType.BOND_FUTURES:
            bond_code = get_bond_qq_code(symbol)
            qq_data = self._fetch_qq_quote(bond_code)
            params = get_bond_params(symbol)
            ref_price = get_bond_ref_price(symbol)

            if qq_data and float(qq_data.get("price", 0)) > 0:
                # 用国债指数变化率近似推导期货价格
                index_price = float(qq_data.get("price", 0))
                return QuoteResult(
                    symbol=symbol, last_price=ref_price,
                    open=float(qq_data.get("open", 0)),
                    high=float(qq_data.get("high", 0)),
                    low=float(qq_data.get("low", 0)),
                    volume=float(qq_data.get("volume", 0)),
                    open_interest=0.0, change_pct=float(qq_data.get("change_pct", 0)),
                    meta={"data_grade": "PRIMARY", "source": "qq_sina",
                          "spot_symbol": bond_code, "market_type": "bond_futures",
                          "contract_multiplier": params["multiplier"],
                          "margin_rate": params["margin_rate"],
                          "notional_value": ref_price * params["multiplier"],
                          "bond_index_price": index_price,
                          "index_name": qq_data.get("name", "国债指数"),
                          "product_name": params["name"]},
                )

            # 国债指数不可用时，用参考价格
            return QuoteResult(
                symbol=symbol, last_price=ref_price,
                meta={"data_grade": "SECONDARY", "source": "qq_sina",
                      "spot_symbol": bond_code, "market_type": "bond_futures",
                      "contract_multiplier": params["multiplier"],
                      "margin_rate": params["margin_rate"],
                      "notional_value": ref_price * params["multiplier"],
                      "product_name": params["name"],
                      "reason": "国债指数可用，使用参考价格"},
            )

        return QuoteResult(symbol=symbol, meta={"data_grade": "UNAVAILABLE", "source": "qq_sina",
                                                 "reason": f"QQSinaSource 不支持 {mt}"})

    async def get_kline(self, symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
        """获取股指/国债期货对应现货指数的日K线数据。"""
        mt = classify(symbol)

        if mt == MarketType.INDEX_FUTURES:
            spot_code = get_spot_index_code(symbol)
        elif mt == MarketType.BOND_FUTURES:
            spot_code = get_bond_qq_code(symbol)
        else:
            return KlineResult(symbol=symbol, bars=[],
                               meta={"data_grade": "UNAVAILABLE", "source": "qq_sina"})

        bars = self._fetch_qq_kline(spot_code, days)
        if not bars:
            return KlineResult(symbol=symbol, bars=[],
                               meta={"data_grade": "UNAVAILABLE", "source": "qq_sina",
                                      "reason": "QQ Kline API 无数据"})

        return KlineResult(
            symbol=symbol, bars=bars,
            meta={"data_grade": "PRIMARY", "source": "qq_sina", "spot_symbol": spot_code,
                  "period": period, "count": len(bars)},
        )

    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        results = {}
        for sym in symbols:
            results[sym] = await self.get_quote(sym)
        return results

    async def get_contract_info(self, symbol: str) -> dict:
        """返回股指期货或国债期货合约信息。"""
        try:
            mt = classify(symbol)
            params = get_contract_params(symbol)

            if mt == MarketType.INDEX_FUTURES:
                spot_code = get_spot_index_code(symbol)
                qq_data = self._fetch_qq_quote(spot_code)
                index_price = float(qq_data.get("price", 0)) if qq_data else 0
                margin_per_lot = index_price * params["multiplier"] * params["margin_rate"]
                leverage = round(1 / params["margin_rate"], 1)
                info = {
                    "spot_index_code": spot_code,
                    "index_price": index_price,
                    "notional_value": index_price * params["multiplier"],
                    "margin_per_lot": margin_per_lot,
                    "leverage": leverage,
                    "data_grade": "PRIMARY" if index_price else "UNAVAILABLE",
                }
            elif mt == MarketType.BOND_FUTURES:
                spot_code = get_bond_qq_code(symbol)
                ref_price = get_bond_ref_price(symbol)
                qq_data = self._fetch_qq_quote(spot_code)
                bond_index = float(qq_data.get("price", 0)) if qq_data else 0
                contract_price = ref_price
                margin_per_lot = contract_price * params["multiplier"] * params["margin_rate"]
                leverage = round(1 / params["margin_rate"], 1)
                info = {
                    "spot_symbol": spot_code,
                    "bond_index": bond_index,
                    "contract_price": contract_price,
                    "notional_value": contract_price * params["multiplier"],
                    "margin_per_lot": margin_per_lot,
                    "leverage": leverage,
                    "data_grade": "PRIMARY" if bond_index else "SECONDARY",
                }
            else:
                return {"data": {}, "summary": f"{symbol} 非股指/国债期货", "data_grade": "UNAVAILABLE"}

            return {
                "symbol": symbol,
                "product_name": params["name"],
                "exchange": params["exchange"],
                "multiplier": params["multiplier"],
                "margin_rate": params["margin_rate"],
                "price_tick": params["price_tick"],
                "contract_type": f"{datetime.now().year}年9月" if "09" in symbol else "非标准合约",
                **info,
            }
        except ValueError as e:
            return {"data": {}, "summary": str(e), "data_grade": "UNAVAILABLE"}

    # ═══════════════════════════════════════════
    # 不适用的接口（股指期货无此维度）
    # ═══════════════════════════════════════════

    async def get_warrant(self, symbol: str, exchange: str = "SHFE") -> dict:
        return self._unavailable_dict("股指期货无仓单日报数据")

    async def get_inventory(self, symbol: str) -> dict:
        return self._unavailable_dict("股指期货无库存数据")

    async def get_position_ranking(self, symbol: str) -> dict:
        return self._unavailable_dict("股指期货持仓排名需从中金所获取，QQSinaSource 不支持")

    async def get_fund_flow(self, symbol: str) -> dict:
        return self._unavailable_dict("股指期货资金流向需从中金所获取")

    async def get_foreign_hist(self, symbol: str) -> dict:
        return self._unavailable_dict("股指期货无外盘历史数据")

    async def get_basis(self, symbol: str) -> dict:
        return self._unavailable_dict("股指期货基差需从实际期货价格计算")

    async def get_term_structure(self, symbol: str) -> dict:
        return self._unavailable_dict("股指期货期限结构需从中金所全合约数据获取")

    async def get_spread(self, symbol: str) -> dict:
        return self._unavailable_dict("股指期货跨期价差需从中金所全合约数据获取")

    async def get_macro_pmi(self) -> dict:
        return self._unavailable_dict("宏观数据请使用 AKShareSource")

    async def get_macro_rate(self) -> dict:
        return self._unavailable_dict("宏观数据请使用 AKShareSource")

    # ═══════════════════════════════════════════
    # 私有方法 — QQ/Sina API 调用
    # ═══════════════════════════════════════════

    def _fetch_qq_quote(self, spot_code: str) -> dict | None:
        """从 QQ 行情 API 获取现货指数行情。"""
        url = f"https://web.sqt.gtimg.cn/q={spot_code}"
        try:
            r = self._session.get(url, headers={"Referer": "https://finance.qq.com/"}, timeout=_HTTP_TIMEOUT)
            parts = r.text.strip().split("~")
            if len(parts) < 10:
                logger.warning(f"[QQSina] QQ API 返回格式异常: {r.text[:100]}")
                return None

            result = {}
            for key, idx in _QQ_FIELD_MAP.items():
                if idx < len(parts) and parts[idx]:
                    try:
                        result[key] = parts[idx].strip()
                    except (ValueError, IndexError):
                        pass
            return result
        except Exception as e:
            logger.warning(f"[QQSina] QQ API 请求失败 {spot_code}: {e}")
            return None

    def _fetch_sina_quote(self, spot_code: str) -> dict | None:
        """从新浪行情 API 获取现货指数行情（备选）。"""
        sina_code = f"s_{spot_code}"
        url = f"https://hq.sinajs.cn/list={sina_code}"
        try:
            r = self._session.get(url, headers={"Referer": "https://finance.sina.com.cn/"}, timeout=_HTTP_TIMEOUT)
            m = re.search(r'"([^"]+)"', r.text)
            if not m:
                return None
            items = m.group(1).split(",")
            names = ["name", "price", "change", "change_pct", "volume_wan", "amount_wan"]
            return {k: v for k, v in zip(names, items) if v}
        except Exception as e:
            logger.warning(f"[QQSina] Sina API 请求失败 {spot_code}: {e}")
            return None

    def _fetch_qq_kline(self, spot_code: str, days: int = 120) -> list[KlineBar]:
        """获取指数日K线数据。

        双源策略:
          1. 优先从新浪指数K线API（日线，无需token）
          2. 回退到从QQ行情快照提取当日数据
        """
        # ── 方案1: 新浪指数K线API（指数日线，非期货接口）──
        sina_vip_url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/"
            f"jsonp.php/var%20_=new%20Date().getTime()/"
            f"InnerIndexService.getDailyKLine?symbol={spot_code}&datalen={days}"
        )
        try:
            r = self._session.get(
                sina_vip_url,
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=_HTTP_TIMEOUT,
            )
            import re as _re
            m = _re.search(r'\[.*?\]', r.text)
            if m:
                data = json.loads(m.group())
                if data and len(data) > 3:
                    bars = []
                    for d in data:
                        bars.append(KlineBar(
                            date=str(d.get("d", "")).replace("-", ""),
                            open=float(d.get("o", 0)),
                            high=float(d.get("h", 0)),
                            low=float(d.get("l", 0)),
                            close=float(d.get("c", 0)),
                            volume=float(d.get("v", 0)),
                        ))
                    bars = [b for b in bars if b.close > 0]
                    logger.info(f"[QQSina] 新浪K线获取成功: {spot_code}, {len(bars)}条")
                    return bars[-days:]
        except Exception as e:
            logger.warning(f"[QQSina] 新浪K线API失败, 降级: {e}")

        # ── 方案2: QQ 当日行情（仅单日）──
        try:
            r = self._session.get(
                f"https://web.sqt.gtimg.cn/q={spot_code}",
                headers={"Referer": "https://finance.qq.com/"}, timeout=_HTTP_TIMEOUT)
            parts = r.text.strip().split("~")
            price = parts[3] if len(parts) > 3 else "0"
            if float(price) > 0:
                date_str = parts[30][:8] if len(parts) > 30 and parts[30] else datetime.now().strftime("%Y%m%d")
                bars = [KlineBar(
                    date=date_str,
                    open=float(parts[5]) if len(parts) > 5 and parts[5] else 0,
                    high=float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    low=float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    close=float(price),
                    volume=float(parts[6]) if len(parts) > 6 and parts[6] else 0,
                )]
                return bars
        except Exception as e:
            logger.warning(f"[QQSina] QQ 当日行情降级失败: {e}")

        return []
