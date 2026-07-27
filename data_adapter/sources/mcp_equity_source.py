"""MCP 权益数据源 — 通过 iFinD/Wind/Westock MCP 获取 A 股/ETF/可转债/REITs 数据。

架构:
  三层降级: iFinD (Python HTTPS) → Wind (CLI subprocess) → Westock (CLI npx) → Web HTTP

  1. iFinD: 通过 ifind-finance-data 插件的 call.py 直接 HTTPS 调用
  2. Wind:  通过 wind_source.py 的 subprocess CLI 模式
  3. Westock CLI: 通过 npx westock-data-clawhub 命令行
  4. Web HTTP: 直调东方财富 HTTP API (最后一层保底)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Any, Optional

from data_adapter.types import KlineBar, KlineResult, QuoteResult

logger = logging.getLogger(__name__)

# ── iFinD 调用库路径 ──
_IFIND_CALL_DIR = (
    "c:/Users/yangd/.trae-cn/plugins/trae-remote-official/"
    "ifind/1.3.0/skills/ifind-finance-data"
)
if _IFIND_CALL_DIR not in sys.path:
    sys.path.insert(0, _IFIND_CALL_DIR)

# ── Wind CLI 路径 ──
_WIND_SKILL_DIR = (
    "c:/Users/yangd/.trae-cn/plugins/trae-remote-official/"
    "wind-aifin/0.0.2/skills/wind-mcp-skill"
)
_WIND_CLI = "node scripts/cli.mjs"

# ── Westock CLI ──
_WESTOCK_CLI = "npx -y westock-data-clawhub@1.0.4"


class MCPEquitySource:
    """MCP 权益数据源 — 三层降级获取 A 股/ETF/可转债/REITs 数据。

    调用顺序:
      1. iFinD MCP (直调 HTTPS，最快)
      2. Wind MCP (subprocess CLI，已验证)
      3. Westock CLI (npx，最后 CLI 保底)
      4. Web HTTP (直调东方财富，最终保底)
    """

    # ═══════════════════════════════════════════════════════
    # Layer 0: 通用接口
    # ═══════════════════════════════════════════════════════

    async def get_kline(self, symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
        """获取 K 线数据。降级顺序: iFinD -> Wind -> Westock CLI -> Web HTTP"""
        bare = symbol.replace(".SH", "").replace(".SZ", "").strip().upper()

        for tier_name, tier_fn in (
            ("iFinD", self._ifind_kline),
            ("Wind", self._wind_kline),
            ("Westock", self._westock_kline),
        ):
            try:
                result = await tier_fn(bare, days)
                if result and result.bars:
                    logger.info("[MCPEquity] %s K线成功(%s) -> %d bars", tier_name, bare, len(result.bars))
                    return result
            except Exception as e:
                logger.warning("[MCPEquity] %s K线失败(%s): %s", tier_name, bare, e)

        # Web HTTP fallback
        try:
            from data_adapter.sources.web_data_fetcher import fetch_equity_kline_from_web
            fallback_bars = await fetch_equity_kline_from_web(bare, days)
            if fallback_bars:
                logger.info("[MCPEquity] Web HTTP 降级成功(%s) -> %d bars", bare, len(fallback_bars))
                return KlineResult(
                    symbol=bare, bars=fallback_bars,
                    meta={"data_grade": "DERIVED", "source": "web_http_fallback",
                          "note": "所有 MCP 源不可用，Web HTTP 保底"},
                )
        except Exception as e:
            logger.warning("[MCPEquity] Web HTTP 降级也失败(%s): %s", bare, e)

        return KlineResult(symbol=bare, bars=[],
                           meta={"data_grade": "ERROR", "source": "mcp_equity",
                                 "error": "所有数据源均不可用"})

    async def get_quote(self, symbol: str) -> QuoteResult:
        """获取行情快照。"""
        bare = symbol.replace(".SH", "").replace(".SZ", "").strip().upper()

        for tier_name, tier_fn in (("iFinD", self._ifind_quote), ("Westock", self._westock_quote)):
            try:
                result = await tier_fn(bare)
                if result and result.last_price > 0:
                    return result
            except Exception as e:
                logger.warning("[MCPEquity] %s 行情失败(%s): %s", tier_name, bare, e)

        return QuoteResult(symbol=bare, meta={"data_grade": "UNAVAILABLE"})

    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        results: dict[str, QuoteResult] = {}
        for sym in symbols:
            results[sym] = await self.get_quote(sym)
        return results

    async def get_macro_pmi(self) -> dict:
        return {"data_grade": "UNAVAILABLE", "note": "PMI 需从期货数据源获取"}

    async def get_macro_rate(self) -> dict:
        return {"data_grade": "UNAVAILABLE", "note": "利率数据需从期货数据源获取"}

    # ═══════════════════════════════════════════════════════
    # Layer 1: 权益专有接口
    # ═══════════════════════════════════════════════════════

    async def get_financials(self, symbol: str) -> dict:
        bare = symbol.replace(".SH", "").replace(".SZ", "").strip().upper()
        try:
            r = await self._ifind_call("stock", "get_stock_financials", {"stockCodes": bare, "reportType": "latest"})
            if r.get("ok") and r.get("data"):
                return {"symbol": bare, "data_grade": "PRIMARY", "source": "ifind", "raw": r["data"]}
        except Exception as e:
            logger.warning("[MCPEquity] iFinD 财务失败(%s): %s", bare, e)
        return {"symbol": bare, "data_grade": "UNAVAILABLE"}

    async def get_dividend(self, symbol: str) -> dict:
        bare = symbol.replace(".SH", "").replace(".SZ", "").strip().upper()
        try:
            r = await self._ifind_call("stock", "get_stock_events", {"stockCodes": bare, "eventType": "dividend"})
            if r.get("ok") and r.get("data"):
                return {"symbol": bare, "data_grade": "PRIMARY", "source": "ifind", "raw": r["data"]}
        except Exception as e:
            logger.warning("[MCPEquity] iFinD 分红失败(%s): %s", bare, e)
        return {"symbol": bare, "data_grade": "UNAVAILABLE"}

    async def get_north_flow(self, symbol: str) -> dict:
        bare = symbol.replace(".SH", "").replace(".SZ", "").strip().upper()
        try:
            r = await self._ifind_call("stock", "get_stock_performance", {"stockCodes": bare})
            if r.get("ok"):
                return {"symbol": bare, "data_grade": "PRIMARY", "source": "ifind", "raw": r.get("data", {})}
        except Exception as e:
            logger.warning("[MCPEquity] iFinD 北向失败(%s): %s", bare, e)
        return {"symbol": bare, "data_grade": "UNAVAILABLE"}

    async def get_etf_nav(self, symbol: str) -> dict:
        bare = symbol.replace(".SH", "").replace(".SZ", "").strip().upper()
        try:
            r = await self._ifind_call("fund", "get_fund_profile", {"fundCodes": bare})
            if r.get("ok") and r.get("data"):
                return {"symbol": bare, "data_grade": "PRIMARY", "source": "ifind", "raw": r["data"]}
        except Exception as e:
            logger.warning("[MCPEquity] iFinD ETF净值失败(%s): %s", bare, e)
        try:
            return await self._westock_etf_nav(bare)
        except Exception as e:
            logger.warning("[MCPEquity] Westock ETF净值失败(%s): %s", bare, e)
        return {"symbol": bare, "data_grade": "UNAVAILABLE"}

    async def get_etf_constituents(self, symbol: str) -> dict:
        bare = symbol.replace(".SH", "").replace(".SZ", "").strip().upper()
        try:
            r = await self._ifind_call("fund", "get_fund_portfolio", {"fundCodes": bare})
            if r.get("ok") and r.get("data"):
                return {"symbol": bare, "data_grade": "PRIMARY", "source": "ifind", "raw": r["data"]}
        except Exception as e:
            logger.warning("[MCPEquity] iFinD ETF成分失败(%s): %s", bare, e)
        return {"symbol": bare, "data_grade": "UNAVAILABLE"}

    async def get_etf_premium(self, symbol: str) -> dict:
        bare = symbol.replace(".SH", "").replace(".SZ", "").strip().upper()
        try:
            nav_data = await self._westock_etf_nav(bare)
            if nav_data.get("data_grade") in ("PRIMARY", "DERIVED"):
                nav = nav_data.get("nav")
                mkt = nav_data.get("market_price")
                if nav and mkt and nav > 0:
                    premium = round((mkt - nav) / nav * 100, 2)
                    return {"symbol": bare, "premium_pct": premium, "market_price": mkt, "nav": nav,
                            "data_grade": "DERIVED", "source": "westock_cli"}
        except Exception as e:
            logger.warning("[MCPEquity] ETF溢价失败(%s): %s", bare, e)
        return {"symbol": bare, "data_grade": "UNAVAILABLE"}

    # ═══════════════════════════════════════════════════════
    # Tier 1: iFinD 实现
    # ═══════════════════════════════════════════════════════

    @staticmethod
    async def _ifind_call(server_type: str, tool_name: str, params: dict) -> dict:
        from call import call as ifind_call
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: ifind_call(server_type, tool_name, params))

    async def _ifind_kline(self, symbol: str, days: int) -> KlineResult | None:
        """通过 iFinD 自然语言 query 获取历史行情。"""
        from datetime import datetime, timedelta
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
        is_etf = any((
            symbol.startswith("51") and len(symbol) == 6,
            symbol.startswith("58") and len(symbol) == 6,
            symbol.startswith("159") and len(symbol) == 6,
        ))
        if is_etf:
            query = f"{symbol}在{start}-{end}的每日收盘价和收益率"
            r = await self._ifind_call("fund", "get_fund_market_performance",
                                       {"query": query})
        else:
            query = f"{symbol}在{start}-{end}的开盘价、收盘价、最高价、最低价、成交量"
            r = await self._ifind_call("stock", "get_stock_performance",
                                       {"query": query})
        if not r.get("ok"):
            return None
        return self._parse_ifind_kline(symbol, r.get("data", {}), days)

    @staticmethod
    def _parse_ifind_kline(symbol: str, raw: dict, days: int) -> KlineResult | None:
        bars = []
        result_data = raw.get("result", raw.get("data", raw))
        kline_data = []
        if isinstance(result_data, dict):
            kline_data = result_data.get("kline", result_data.get("priceList", result_data.get("list", [])))
        elif isinstance(result_data, list):
            kline_data = result_data
        if not isinstance(kline_data, list):
            kline_data = []
        for item in kline_data[-days:]:
            if not isinstance(item, dict):
                continue
            try:
                date_str = str(item.get("date", item.get("tradeDate", item.get("endDate", "")))
                              ).replace("-", "").replace("/", "")[:8]
                if not date_str.isdigit():
                    continue
                bar = KlineBar(
                    date=date_str,
                    open=float(item.get("open", item.get("openPrice", 0)) or 0),
                    high=float(item.get("high", item.get("highPrice", 0)) or 0),
                    low=float(item.get("low", item.get("lowPrice", 0)) or 0),
                    close=float(item.get("close", item.get("closePrice", item.get("nav", 0))) or 0),
                    volume=float(item.get("volume", item.get("turnoverVol", 0)) or 0),
                )
                if bar.close > 0:
                    bars.append(bar)
            except (ValueError, TypeError, IndexError):
                continue
        if not bars:
            return None
        return KlineResult(symbol=symbol, bars=bars, meta={"data_grade": "PRIMARY", "source": "ifind_mcp"})

    async def _ifind_quote(self, symbol: str) -> QuoteResult | None:
        is_etf = any((
            symbol.startswith("51") and len(symbol) == 6,
            symbol.startswith("58") and len(symbol) == 6,
            symbol.startswith("159") and len(symbol) == 6,
        ))
        if is_etf:
            r = await self._ifind_call("fund", "fund_highfreq_quotes", {
                "symbols": symbol, "indicators": "最新价,IOPV净值估值,涨跌幅", "data_mode": "real_time",
            })
        else:
            r = await self._ifind_call("stock", "stock_highfreq_quotes", {
                "symbols": symbol, "indicators": "最新价,涨跌幅,开盘价", "data_mode": "real_time",
            })
        if not r.get("ok"):
            return None
        raw = r.get("data", {})
        rd = raw.get("result", raw.get("data", raw))
        if isinstance(rd, dict):
            price = float(rd.get("最新价", rd.get("latestPrice", rd.get("price", 0))) or 0)
            change_pct = float(rd.get("涨跌幅", rd.get("changePct", rd.get("changePercent", 0))) or 0)
            if price > 0:
                return QuoteResult(symbol=symbol, last_price=price, change_pct=change_pct,
                                   meta={"data_grade": "PRIMARY", "source": "ifind_mcp"})
        return None

    # ═══════════════════════════════════════════════════════
    # Tier 2: Wind 实现
    # ═══════════════════════════════════════════════════════

    async def _wind_call(self, server_type: str, tool_name: str, params: dict) -> dict:
        params_json = json.dumps(params, ensure_ascii=False)
        escaped = params_json.replace('"', '\\"')
        cmd = f'cd /d "{_WIND_SKILL_DIR}" & {_WIND_CLI} call {server_type} {tool_name} "{escaped}"'
        loop = asyncio.get_event_loop()
        try:
            proc = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=60, shell=True),
            )
        except subprocess.TimeoutExpired:
            logger.warning("[Wind] 超时 %s %s", server_type, tool_name)
            return {"isError": True, "error": {"code": "TIMEOUT"}}
        except Exception as e:
            logger.warning("[Wind] 异常 %s %s: %s", server_type, tool_name, e)
            return {"isError": True, "error": {"code": "RUNTIME", "message": str(e)}}
        if proc.returncode != 0:
            logger.warning("[Wind] 非零 %d %s %s: %s", proc.returncode, server_type, tool_name, proc.stderr[:200])
            return {"isError": True, "error": {"code": "EXIT", "stderr": proc.stderr[:200]}}
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            logger.warning("[Wind] JSON解析失败 %s: %s", tool_name, e)
            return {"isError": True, "error": {"code": "JSON_PARSE", "message": str(e)}}

    async def _wind_kline(self, symbol: str, days: int) -> KlineResult | None:
        """通过 Wind get_stock_kline/get_fund_kline 获取 OHLC K 线。"""
        from datetime import datetime, timedelta
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
        is_etf = any((
            symbol.startswith("51") and len(symbol) == 6,
            symbol.startswith("58") and len(symbol) == 6,
            symbol.startswith("159") and len(symbol) == 6,
        ))
        st = "fund_data" if is_etf else "stock_data"
        tn = "get_fund_kline" if is_etf else "get_stock_kline"
        wind_code = f"{symbol}.SH" if symbol.startswith(("5", "6")) else f"{symbol}.SZ"
        wr = await self._wind_call(st, tn, {
            "windcode": wind_code,
            "begin_date": start, "end_date": end,
        })
        if wr.get("isError"):
            return None
        bars = self._extract_wind_kline_bars(wr, days)
        if bars:
            return KlineResult(symbol=symbol, bars=bars, meta={"data_grade": "PRIMARY", "source": "wind_mcp"})
        return None

    @staticmethod
    def _extract_wind_kline_bars(wr: dict, days: int) -> list:
        """解析 Wind CLI get_stock_kline/get_fund_kline 返回的深层嵌套格式。

        Wind CLI 返回格式:
        [{"type": "text", "text": "{\"data\": {\"columns\": [...], \"rows\": [...]}}"}]

        columns: TIME, OPEN, MATCH(close), HIGH, LOW, VOLUME, ...
        """
        import json as _json
        bars = []
        
        # 提取 text 字段中的嵌套 JSON
        raw_list = wr.get("content", wr.get("data", wr))
        if not isinstance(raw_list, list):
            return []
        
        text_content = None
        for item in raw_list:
            if isinstance(item, dict) and item.get("type") == "text":
                text_content = item.get("text", "")
                break
        
        if not text_content:
            return []
        
        try:
            parsed = _json.loads(text_content) if isinstance(text_content, str) else text_content
        except _json.JSONDecodeError:
            return []
        
        data = parsed.get("data", parsed) if isinstance(parsed, dict) else {}
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        
        if not columns or not rows:
            return []
        
        # 列名映射
        col_map = {}
        for idx, col in enumerate(columns):
            name = col.get("name", "") if isinstance(col, dict) else str(col)
            col_map[name.upper()] = idx
        
        for row in rows[-days:]:
            if not isinstance(row, list) or len(row) < 5:
                continue
            try:
                time_val = str(row[col_map.get("TIME", 0)] if "TIME" in col_map else row[0])
                date_str = time_val.replace("-", "").replace("/", "")[:8]
                if not date_str.isdigit():
                    continue
                open_idx = col_map.get("OPEN", 1)
                high_idx = col_map.get("HIGH", 3)
                low_idx = col_map.get("LOW", 4)
                close_idx = col_map.get("MATCH", 2)
                vol_idx = col_map.get("VOLUME", 5)
                
                bar = KlineBar(
                    date=date_str,
                    open=float(row[open_idx]) if row[open_idx] not in ("", None) else 0,
                    high=float(row[high_idx]) if row[high_idx] not in ("", None) else 0,
                    low=float(row[low_idx]) if row[low_idx] not in ("", None) else 0,
                    close=float(row[close_idx]) if row[close_idx] not in ("", None) else 0,
                    volume=float(row[vol_idx]) if len(row) > vol_idx and row[vol_idx] not in ("", None) else 0,
                )
                if bar.close > 0:
                    bars.append(bar)
            except (ValueError, TypeError, IndexError):
                continue
        
        return bars

    # ═══════════════════════════════════════════════════════
    # Tier 3: Westock CLI 实现
    # ═══════════════════════════════════════════════════════

    async def _westock_kline(self, symbol: str, days: int) -> KlineResult | None:
        eq = f"sh{symbol}" if symbol.startswith(("5", "6")) else f"sz{symbol}"
        output = await self._run_westock(["kline", eq, "--period", "day", "--limit", str(days)])
        if not output:
            return None
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return None
        data_list = parsed if isinstance(parsed, list) else parsed.get("data", parsed.get("result", []))
        bars = []
        for item in data_list:
            try:
                ds = str(item.get("date", item.get("tradeDate", ""))).replace("-", "").replace("/", "")[:8]
                if not ds.isdigit():
                    continue
                bar = KlineBar(
                    date=ds,
                    open=float(item.get("open", 0) or 0),
                    high=float(item.get("high", 0) or 0),
                    low=float(item.get("low", 0) or 0),
                    close=float(item.get("close", 0) or 0),
                    volume=float(item.get("volume", item.get("vol", 0)) or 0),
                )
                if bar.close > 0:
                    bars.append(bar)
            except (ValueError, TypeError):
                continue
        if bars:
            return KlineResult(symbol=symbol, bars=bars, meta={"data_grade": "DERIVED", "source": "westock_cli"})
        return None

    async def _westock_quote(self, symbol: str) -> QuoteResult | None:
        eq = f"sh{symbol}" if symbol.startswith(("5", "6")) else f"sz{symbol}"
        output = await self._run_westock(["quote", eq])
        if not output:
            return None
        try:
            parsed = json.loads(output)
            dl = parsed if isinstance(parsed, list) else parsed.get("data", [])
            if dl:
                item = dl[0] if isinstance(dl, list) else dl
                price = float(item.get("price", item.get("lastPrice", item.get("close", 0))) or 0)
                if price > 0:
                    return QuoteResult(symbol=symbol, last_price=price,
                                       change_pct=float(item.get("changePct", 0) or 0),
                                       meta={"data_grade": "DERIVED", "source": "westock_cli"})
        except (json.JSONDecodeError, (ValueError, TypeError)):
            pass
        return None

    async def _westock_etf_nav(self, symbol: str) -> dict:
        eq = f"sh{symbol}" if symbol.startswith("5") else f"sz{symbol}"
        output = await self._run_westock(["quote", eq])
        if not output:
            return {"symbol": symbol, "data_grade": "UNAVAILABLE"}
        try:
            parsed = json.loads(output)
            dl = parsed if isinstance(parsed, list) else parsed.get("data", [])
            if dl:
                item = dl[0] if isinstance(dl, list) else dl
                return {"symbol": symbol, "nav": float(item.get("nav", item.get("iopv", 0)) or 0),
                        "market_price": float(item.get("price", item.get("lastPrice", 0)) or 0),
                        "name": item.get("name", ""), "data_grade": "DERIVED", "source": "westock_cli"}
        except (json.JSONDecodeError, (ValueError, TypeError)):
            pass
        return {"symbol": symbol, "data_grade": "UNAVAILABLE"}

    @staticmethod
    async def _run_westock(args: list[str]) -> str | None:
        cmd = f"npx -y westock-data-clawhub@1.0.4 {' '.join(args)}"
        loop = asyncio.get_event_loop()
        try:
            proc = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30, shell=True),
            )
            return proc.stdout if proc.returncode == 0 else None
        except Exception as e:
            logger.warning("[Westock] CLI 异常(%s): %s", args[0], e)
            return None
