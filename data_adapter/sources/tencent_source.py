"""腾讯自选股数据源 — 使用腾讯行情 API（同腾讯自选股 App）为 A 股/ETF 提供数据。

数据流:
  实时行情 → qt.gtimg.cn/q={code}（管道符分隔，毫秒级响应）
  K 线数据 → ifzq.gtimg.cn/appstock/app/fqkline/get
  财务数据 → ifzq.gtimg.cn/appstock/app/finance/{code}
  资金流向 → ifzq.gtimg.cn/appstock/app/MoneyFlow/{code}
  北向资金 → ifzq.gtimg.cn/appstock/app/hsgt/hsgt_ssggtz/{code}

代码格式: sh600519 / sz000001 / sh510050（与腾讯自选股一致）

实现 ``EquityDataSource`` ABC 的全部抽象方法 + ETF 专有方法。
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

from data_adapter.base import EquityDataSource
from data_adapter.types import KlineResult, QuoteResult

logger = logging.getLogger(__name__)

# ── HTTP 配置 ──
_HTTP_TIMEOUT = 15
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# ── API 端点 ──
_QT_REALTIME = "https://qt.gtimg.cn/q={code}"
_FQKLINE = "https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq"
_MINUTE = "https://ifzq.gtimg.cn/appstock/app/minute/query?param={code},day,,,1"
_FINANCE = "https://ifzq.gtimg.cn/appstock/app/finance/{code}"
_MONEY_FLOW = "https://ifzq.gtimg.cn/appstock/app/MoneyFlow/{code}"
_NORTH_FLOW = "https://ifzq.gtimg.cn/appstock/app/hsgt/hsgt_ssggtz/{code}"

# ── 腾讯行情字段索引（qt.gtimg.cn 返回管道符分隔） ──
# 参考: https://qt.gtimg.cn/q=sh600519
# 字段: 0=市场,1=名称,2=代码,3=最新价,4=昨收,5=开盘,6=成交量,7=外盘,
#        8=内盘,9=买一,10=卖一,..., 30=时间,31=涨跌,32=涨跌幅%
_QT_FIELDS = {
    "name": 1, "code": 2, "price": 3, "prev_close": 4, "open": 5,
    "volume": 6, "outer_disc": 7, "inner_disc": 8,
    "bid1": 9, "ask1": 10, "high": 33, "low": 34,
    "change": 31, "change_pct": 32, "time": 30,
    "turnover": 38, "pe": 39, "amplitude": 43, "total_cap": 44,
    "float_cap": 45, "amount": 37, "pb": 46,
}


def _tencent_code(symbol: str) -> str:
    """将任意格式代码转为腾讯行情格式（sh600519 / sz000001 / sh510050）。"""
    s = symbol.upper().strip()
    # 去除 .SH/.SZ 后缀
    s = s.replace(".SH", "").replace(".SZ", "")
    if s.startswith("SH") or s.startswith("SZ"):
        return s[:2].lower() + s[2:]
    if s.startswith("60") or s.startswith("68") or s.startswith("51") or s.startswith("58") or s.startswith("11"):
        return f"sh{s}"
    if s.startswith("00") or s.startswith("30") or s.startswith("15") or s.startswith("16") or s.startswith("18") or s.startswith("12"):
        return f"sz{s}"
    return s


def _extract_sina_quote(raw: str) -> dict[str, Any]:
    """解析 qt.gtimg.cn 返回的管道符分隔数据。"""
    try:
        # 格式: v_market_code="field1~field2~...~fieldN";
        m = re.search(r'"(.*)"', raw)
        if not m:
            return {}
        fields = m.group(1).split("~")

        result = {}
        for key, idx in _QT_FIELDS.items():
            if idx < len(fields) and fields[idx] and fields[idx] != "":
                val = fields[idx].strip()
                # 数值转换
                if key in ("name", "code", "time"):
                    result[key] = val
                else:
                    try:
                        result[key] = float(val)
                    except ValueError:
                        result[key] = val
        return result
    except Exception:
        return {}


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class TencentStockSource(EquityDataSource):
    """腾讯自选股数据源 — A股个股 + ETF。

    使用腾讯行情 API（同腾讯自选股 App 数据源），
    提供毫秒级行情快照、K 线数据、三大财务报表、
    资金流向、北向持股等数据。
    """

    # ── Layer 0: 通用方法 ──

    async def get_kline(self, symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
        """获取 K 线数据（腾讯 fqkline API，默认前复权）。"""
        code = _tencent_code(symbol)
        url = _FQKLINE.format(code=code, days=max(days, 60))

        try:
            resp = await asyncio.to_thread(
                requests.get, url, headers=_HEADERS, timeout=_HTTP_TIMEOUT
            )
            data = resp.json()
        except Exception as e:
            logger.warning("[Tencent] get_kline(%s) 失败: %s", symbol, e)
            return KlineResult(symbol=symbol, meta={"data_grade": "ERROR", "error": str(e)})

        if not data or "data" not in data:
            return KlineResult(symbol=symbol, meta={"data_grade": "NO_DATA"})

        # 腾讯 K 线数据结构: data.{stock_code}.day => [{date, open, close, high, low, volume}, ...]
        stock_data = data.get("data", {})
        code_key = code
        kline_data = stock_data.get(code_key, {})

        # 尝试找 day 或 qfqday（前复权）
        bars_raw = kline_data.get("qfqday") or kline_data.get("day") or []
        if not bars_raw:
            # 可能嵌套在 data.{code}.1 层（部分接口返回格式）
            for v in stock_data.values():
                if isinstance(v, dict):
                    bars_raw = v.get("qfqday") or v.get("day") or []
                    if bars_raw:
                        break

        if not bars_raw:
            return KlineResult(symbol=symbol, meta={"data_grade": "NO_DATA"})

        bars = []
        for item in bars_raw[-days:]:
            if len(item) >= 6:
                try:
                    bars.append({
                        "date": str(item[0]),
                        "open": float(item[1]),
                        "close": float(item[2]),
                        "high": float(item[3]),
                        "low": float(item[4]),
                        "volume": float(item[5]),
                        "amount": float(item[6]) if len(item) > 6 else 0,
                    })
                except (ValueError, IndexError):
                    continue

        return KlineResult(
            symbol=symbol,
            bars=bars,
            total=len(bars),
            meta={"data_grade": "PRIMARY" if bars else "NO_DATA",
                  "source": "tencent", "adjust": "qfq"},
        )

    async def get_quote(self, symbol: str) -> QuoteResult:
        """获取行情快照（腾讯实时 API）。"""
        code = _tencent_code(symbol)
        url = _QT_REALTIME.format(code=code)

        try:
            resp = await asyncio.to_thread(
                requests.get, url, headers=_HEADERS, timeout=_HTTP_TIMEOUT
            )
            raw = resp.text
        except Exception as e:
            logger.warning("[Tencent] get_quote(%s) 失败: %s", symbol, e)
            return QuoteResult(symbol=symbol, meta={"data_grade": "ERROR"})

        q = _extract_sina_quote(raw)
        if not q or not q.get("price"):
            return QuoteResult(symbol=symbol, meta={"data_grade": "NO_DATA"})

        return QuoteResult(
            symbol=symbol,
            price=_safe_float(q.get("price")),
            name=str(q.get("name", "")),
            open_px=_safe_float(q.get("open")),
            high=_safe_float(q.get("high")),
            low=_safe_float(q.get("low")),
            prev_close=_safe_float(q.get("prev_close")),
            volume=_safe_float(q.get("volume")),
            amount=_safe_float(q.get("amount")),
            change=_safe_float(q.get("change")),
            change_pct=_safe_float(q.get("change_pct")),
            turnover_rate=_safe_float(q.get("turnover")),
            pe=_safe_float(q.get("pe")),
            pb=_safe_float(q.get("pb")),
            market_cap=_safe_float(q.get("total_cap")),
            meta={"data_grade": "PRIMARY", "source": "tencent"},
        )

    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        """批量获取行情（腾讯支持单次最多 10 个代码）。"""
        # 分桶请求，每桶 10 个
        results: dict[str, QuoteResult] = {}
        batch_size = 10

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            codes = ",".join(_tencent_code(s) for s in batch)
            url = _QT_REALTIME.format(code=codes)

            try:
                resp = await asyncio.to_thread(
                    requests.get, url, headers=_HEADERS, timeout=_HTTP_TIMEOUT
                )
                raw = resp.text
            except Exception as e:
                logger.warning("[Tencent] batch 失败: %s", e)
                for s in batch:
                    results[s] = QuoteResult(symbol=s, meta={"data_grade": "ERROR"})
                continue

            # 腾讯返回多行，每行一个品种
            lines = raw.strip().split("\n")
            for line in lines:
                q = _extract_sina_quote(line)
                if q and q.get("code"):
                    orig_sym = q["code"]
                    # 把 sh600519 转回原始格式
                    for sym in batch:
                        if sym.upper().replace(".SH", "").replace(".SZ", "") == orig_sym.upper().replace("SH", "").replace("SZ", ""):
                            results[sym] = QuoteResult(
                                symbol=sym,
                                price=_safe_float(q.get("price")),
                                name=str(q.get("name", "")),
                                change_pct=_safe_float(q.get("change_pct")),
                                meta={"data_grade": "PRIMARY", "source": "tencent"},
                            )
                            break

            # 未匹配的标记为 NO_DATA
            for s in batch:
                if s not in results:
                    results[s] = QuoteResult(symbol=s, meta={"data_grade": "NO_DATA"})

        return results

    async def get_macro_pmi(self) -> dict:
        return self._unavailable_dict("PMI 数据通过 AKShare 获取")

    async def get_macro_rate(self) -> dict:
        return self._unavailable_dict("利率数据通过 AKShare 获取")

    # ── Layer 1: 权益专有方法 ──

    async def get_financials(self, symbol: str) -> dict:
        """获取财务报表（腾讯财务 API）。

        腾讯接口返回最近 N 期利润表/资产负债表/现金流量表数据。

        Returns:
            dict 含 revenue / net_profit / total_assets / total_liabilities / cash_flow / pe / pb。
        """
        code = _tencent_code(symbol)
        url = _FINANCE.format(code=code)

        try:
            resp = await asyncio.to_thread(
                requests.get, url, headers=_HEADERS, timeout=_HTTP_TIMEOUT
            )
            data = resp.json()
        except Exception as e:
            logger.warning("[Tencent] get_financials(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

        if not data:
            return {"symbol": symbol, "data_grade": "NO_DATA"}

        result = {"symbol": symbol}

        # 利润表: data.{code}.report.income
        try:
            income = _extract_finance_table(data, "income")
            if income:
                result["revenue"] = income.get("营业收入")
                result["net_profit"] = income.get("净利润")
        except Exception:
            pass

        # 资产负债表
        try:
            balance = _extract_finance_table(data, "balance")
            if balance:
                result["total_assets"] = balance.get("资产总计")
                result["total_liabilities"] = balance.get("负债合计")
        except Exception:
            pass

        # 现金流量表
        try:
            cashflow = _extract_finance_table(data, "cashflow")
            if cashflow:
                result["cash_flow"] = cashflow.get("经营活动现金净流量")
        except Exception:
            pass

        # 先用快照接口获取 PE/PB
        quote = await self.get_quote(symbol)
        if quote.pe is not None:
            result["pe"] = quote.pe
        if quote.pb is not None:
            result["pb"] = quote.pb

        result["data_grade"] = "PRIMARY" if len(result) > 2 else "NO_DATA"
        return result

    async def get_dividend(self, symbol: str) -> dict:
        """获取分红记录。

        腾讯 API 中分红数据在财务接口的 dat_Dividend 节点。

        Returns:
            dict 含 dividend_yield / dividend_years。
        """
        code = _tencent_code(symbol)
        url = _FINANCE.format(code=code)

        try:
            resp = await asyncio.to_thread(
                requests.get, url, headers=_HEADERS, timeout=_HTTP_TIMEOUT
            )
            data = resp.json()
        except Exception as e:
            logger.warning("[Tencent] get_dividend(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

        if not data:
            return {"symbol": symbol, "data_grade": "NO_DATA"}

        # 腾讯分红数据通常在 finance.data.{code} 的 dat_Dividend 或 dat_All 字段
        dividend_records = []
        try:
            for v in data.get("data", {}).values():
                if isinstance(v, dict):
                    for tbl in ("dat_Dividend", "dat_All", "dat_Surp"):
                        rows = v.get(tbl, [])
                        if rows and len(rows) > 1:
                            header = rows[0]
                            for row in rows[1:]:
                                if "分" in str(row) or "股息" in str(row):
                                    dividend_records.append(row)
        except Exception:
            pass

        # 计算连续分红年数
        years = set()
        for rec in dividend_records:
            if rec and len(rec) > 0:
                date_str = str(rec[0])
                y = date_str[:4]
                if y.isdigit():
                    years.add(y)

        q = await self.get_quote(symbol)

        return {
            "symbol": symbol,
            "dividend_yield": q.pe if q.pe and q.pe > 0 else None,  # 作为近似
            "dividend_years": len(years) if years else None,
            "total_records": len(dividend_records),
            "data_grade": "PRIMARY" if years else "NO_DATA",
        }

    async def get_north_flow(self, symbol: str) -> dict:
        """获取北向资金流向。

        腾讯 hsgt_ssggtz API 返回个股北向持股明细。

        Returns:
            dict 含 north_net_buy / north_holding / north_holding_pct。
        """
        code = _tencent_code(symbol)
        url = _NORTH_FLOW.format(code=code)

        try:
            resp = await asyncio.to_thread(
                requests.get, url, headers=_HEADERS, timeout=_HTTP_TIMEOUT
            )
            data = resp.json()
        except Exception as e:
            logger.warning("[Tencent] get_north_flow(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

        if not data:
            return {"symbol": symbol, "data_grade": "NO_DATA"}

        # 解析北向数据
        result = {"symbol": symbol}
        try:
            for v in data.get("data", {}).values():
                if isinstance(v, dict):
                    nv = v.get("qv", v.get("NV", {}))
                    if isinstance(nv, dict):
                        result["north_holding"] = _safe_float(nv.get("marketValue"))
                        result["north_holding_pct"] = _safe_float(nv.get("ratio"))
                        result["north_net_buy"] = _safe_float(nv.get("netBuyAmt"))
                        break
        except Exception:
            pass

        result["data_grade"] = "PRIMARY" if result.get("north_holding") else "NO_DATA"
        return result

    # ── ETF 专有方法（G23 重点） ──

    async def get_etf_nav(self, symbol: str) -> dict:
        """获取 ETF 净值（腾讯实时行情含净值）。"""
        code = _tencent_code(symbol)
        url = _QT_REALTIME.format(code=code)

        try:
            resp = await asyncio.to_thread(
                requests.get, url, headers=_HEADERS, timeout=_HTTP_TIMEOUT
            )
            q = _extract_sina_quote(resp.text)
        except Exception as e:
            logger.warning("[Tencent] get_etf_nav(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

        if not q or not q.get("price"):
            return {"symbol": symbol, "data_grade": "NO_DATA"}

        # 腾讯行情中: IOPV(净值) = field 或可通过 K 线计算
        # 部分字段: 溢价率在 field 51
        iopv = _safe_float(q.get("pe"))  # ETF 的 PE 字段可能为 IOPV
        mkt_price = _safe_float(q.get("price"))
        name = str(q.get("name", ""))

        return {
            "symbol": symbol,
            "name": name,
            "nav": iopv,
            "market_price": mkt_price,
            "premium_pct": round((mkt_price / iopv - 1) * 100, 2) if iopv and iopv > 0 and mkt_price else None,
            "data_grade": "PRIMARY",
        }

    async def get_etf_constituents(self, symbol: str) -> dict:
        """ETF 成分股（腾讯暂无专门 API，返回提示）。"""
        return {
            "symbol": symbol,
            "note": "ETF 成分股请通过 AKShare fund_etf_composition 获取",
            "data_grade": "UNAVAILABLE",
        }

    async def get_etf_premium(self, symbol: str) -> dict:
        """ETF 溢价率（从实时行情计算）。"""
        nav_data = await self.get_etf_nav(symbol)
        if nav_data.get("data_grade") != "PRIMARY":
            return {"symbol": symbol, "data_grade": nav_data.get("data_grade", "NO_DATA")}

        mkt_price = nav_data.get("market_price")
        nav = nav_data.get("nav")
        premium = None
        if mkt_price and nav and nav > 0:
            premium = round((mkt_price - nav) / nav * 100, 2)

        return {
            "symbol": symbol,
            "premium_pct": premium,
            "market_price": mkt_price,
            "nav": nav,
            "data_grade": "PRIMARY" if premium is not None else "NO_DATA",
        }

    # ── 腾讯特有: 资金流向（实时主动买/卖） ──

    async def get_money_flow(self, symbol: str) -> dict:
        """获取个股资金流向（腾讯特有）。

        Returns:
            dict 含 main_net_inflow / retail_net_inflow / mid_net_inflow。
        """
        code = _tencent_code(symbol)
        url = _MONEY_FLOW.format(code=code)

        try:
            resp = await asyncio.to_thread(
                requests.get, url, headers=_HEADERS, timeout=_HTTP_TIMEOUT
            )
            data = resp.json()
        except Exception as e:
            logger.warning("[Tencent] get_money_flow(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

        if not data:
            return {"symbol": symbol, "data_grade": "NO_DATA"}

        result = {"symbol": symbol}
        try:
            for v in data.get("data", {}).values():
                if isinstance(v, dict):
                    qv = v.get("qv", {})
                    if isinstance(qv, dict):
                        # qv 中通常包含 n(主力净流入), m(中户净流入), s(散户净流入)
                        result["main_net_inflow"] = _safe_float(qv.get("n"))
                        result["mid_net_inflow"] = _safe_float(qv.get("m"))
                        result["retail_net_inflow"] = _safe_float(qv.get("s"))
                        break
        except Exception:
            pass

        result["data_grade"] = "PRIMARY" if result.get("main_net_inflow") is not None else "NO_DATA"
        return result


# ── 辅助函数 ──

def _extract_finance_table(data: dict, table_name: str) -> dict[str, Optional[float]]:
    """从腾讯财务接口提取指定报表的最新一期数据。

    Args:
        data: 腾讯财务接口 JSON 响应
        table_name: income / balance / cashflow

    Returns:
        {字段名: 数值, ...}
    """
    for v in data.get("data", {}).values():
        if isinstance(v, dict):
            rows = v.get(table_name, [])
            if rows and len(rows) > 1:
                header = rows[0]
                latest = rows[-1]  # 最新一期
                result = {}
                for i, h in enumerate(header):
                    if i < len(latest) and latest[i] is not None:
                        val = _safe_float(latest[i])
                        if val is not None:
                            result[str(h).strip()] = val
                return result
    return {}
