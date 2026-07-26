"""AKShare 权益数据源 [INDEPENDENT] — A股个股/ETF 数据（G23 Phase 4 第一波）。

通过 AKShare 获取 A 股个股财务数据、分红记录、北向资金。
独立于期货数据管线，无交叉依赖。

实现 ``EquityDataSource`` ABC 的全部抽象方法。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from data_adapter.base import EquityDataSource
from data_adapter.types import KlineResult, QuoteResult

logger = logging.getLogger(__name__)


class AKShareEquitySource(EquityDataSource):
    """AKShare 权益数据源 — A股个股 + **ETF（重点）** 数据实现。

    K 线/行情使用 AKShare A股/ETF 相关接口；
    财务数据使用 stock_financial_abstract / stock_individual_info；
    北向资金使用 stock_hsgt_north_net_flow_in_em；
    ETF 专有数据使用 fund_etf_spot_em / fund_etf_composition / fund_etf_nav。
    """

    # ── Layer 0: 通用方法 ──

    async def get_kline(self, symbol: str, period: str = "daily", days: int = 120) -> KlineResult:
        """获取 A 股 K 线数据。"""
        try:
            import akshare as ak
            import pandas as pd

            # 适配 AKShare 股票 K 线接口
            adj = "qfq"  # 前复权
            df = ak.stock_zh_a_hist(symbol=symbol, period=period, adjust=adj)
            if df is None or df.empty:
                return KlineResult(symbol=symbol, meta={"data_grade": "NO_DATA", "source": "akshare"})

            # AKShare 返回列名含中文，映射到标准格式
            col_map = {
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude",
                "涨跌幅": "pct_change", "涨跌额": "change",
                "换手率": "turnover",
            }
            df = df.rename(columns=col_map)
            if "date" in df.columns:
                df["date"] = df["date"].astype(str)

            bars = df.tail(days).to_dict("records")
            return KlineResult(
                symbol=symbol,
                bars=bars,
                total=len(bars),
                meta={"data_grade": "PRIMARY", "source": "akshare", "adjust": adj},
            )
        except ImportError:
            logger.error("[AKShareEquity] akshare 未安装")
            return KlineResult(symbol=symbol, meta={"data_grade": "UNAVAILABLE"})
        except Exception as e:
            logger.warning("[AKShareEquity] get_kline(%s) 失败: %s", symbol, e)
            return KlineResult(symbol=symbol, meta={"data_grade": "ERROR", "error": str(e)})

    async def get_quote(self, symbol: str) -> QuoteResult:
        """获取 A 股行情快照。"""
        try:
            import akshare as ak
            import pandas as pd

            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return QuoteResult(symbol=symbol, meta={"data_grade": "NO_DATA"})

            # 寻找匹配的股票
            code_col = _find_column(df, ["代码", "symbol", "code"])
            price_col = _find_column(df, ["最新价", "current_price", "price", "close"])
            name_col = _find_column(df, ["名称", "name", "stock_name"])

            if not code_col or not price_col:
                return QuoteResult(symbol=symbol, meta={"data_grade": "NO_DATA"})

            row = df[df[code_col].astype(str).str.strip() == symbol]
            if row.empty:
                # 尝试匹配无前缀版本
                row = df[df[code_col].astype(str).str.replace(".SH", "").str.replace(".SZ", "").str.strip() ==
                         symbol.replace(".SH", "").replace(".SZ", "")]
            if row.empty:
                return QuoteResult(symbol=symbol, meta={"data_grade": "NO_DATA"})

            latest = row.iloc[0]
            price = float(latest.get(price_col, 0) or 0)
            name = str(latest.get(name_col, "")) if name_col else ""

            return QuoteResult(
                symbol=symbol,
                price=price,
                name=name,
                meta={"data_grade": "PRIMARY", "source": "akshare"},
            )
        except ImportError:
            return QuoteResult(symbol=symbol, meta={"data_grade": "UNAVAILABLE"})
        except Exception as e:
            logger.warning("[AKShareEquity] get_quote(%s) 失败: %s", symbol, e)
            return QuoteResult(symbol=symbol, meta={"data_grade": "ERROR"})

    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        """批量获取行情。"""
        results: dict[str, QuoteResult] = {}
        for sym in symbols:
            results[sym] = await self.get_quote(sym)
        return results

    async def get_macro_pmi(self) -> dict:
        """获取 PMI 宏观数据。"""
        return self._unavailable_dict("PMI 数据需从期货数据源获取")

    async def get_macro_rate(self) -> dict:
        """获取利率宏观数据。"""
        return self._unavailable_dict("利率数据需从期货数据源获取")

    # ── Layer 1: 权益专有方法 ──

    async def get_financials(self, symbol: str) -> dict:
        """获取财务报表核心指标。

        使用 AKShare stock_financial_abstract 获取三表核心数据。

        Returns:
            dict 含 revenue / net_profit / total_assets / total_liabilities / cash_flow。
        """
        try:
            import akshare as ak
            import pandas as pd

            # 利润表
            df = ak.stock_financial_abstract(symbol=symbol, indicator="利润表")
            if df is not None and not df.empty:
                latest = df.iloc[0].to_dict()
                revenue = _safe_ak_value(latest, ["营业收入", "revenue"])
                net_profit = _safe_ak_value(latest, ["净利润", "net_profit"])
            else:
                revenue = net_profit = None

            # 资产负债表
            bs = ak.stock_financial_abstract(symbol=symbol, indicator="资产负债表")
            total_assets = total_liabilities = None
            if bs is not None and not bs.empty:
                bl = bs.iloc[0].to_dict()
                total_assets = _safe_ak_value(bl, ["资产总计", "total_assets"])
                total_liabilities = _safe_ak_value(bl, ["负债合计", "total_liabilities"])

            # 现金流量表
            cf = ak.stock_financial_abstract(symbol=symbol, indicator="现金流量表")
            cash_flow = None
            if cf is not None and not cf.empty:
                cl = cf.iloc[0].to_dict()
                cash_flow = _safe_ak_value(cl, ["经营活动现金净流量", "cash_flow"])

            # 每股指标（补齐 PE/PB）
            indicator_df = ak.stock_individual_info(symbol=symbol)
            pe = pb = None
            if indicator_df is not None and not indicator_df.empty:
                for _, row in indicator_df.iterrows():
                    item = str(row.get("item", row.iloc[0])).strip()
                    val = row.get("value", row.iloc[1])
                    if "市盈率" in item:
                        pe = _safe_float(val)
                    elif "市净率" in item:
                        pb = _safe_float(val)

            return {
                "symbol": symbol,
                "revenue": revenue,
                "net_profit": net_profit,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "cash_flow": cash_flow,
                "pe": pe,
                "pb": pb,
                "data_grade": "PRIMARY",
            }
        except ImportError:
            return {"symbol": symbol, "data_grade": "UNAVAILABLE", "error": "akshare 未安装"}
        except Exception as e:
            logger.warning("[AKShareEquity] get_financials(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR", "error": str(e)}

    async def get_dividend(self, symbol: str) -> dict:
        """获取分红记录。

        使用 AKShare stock_dividents 获取分红数据。

        Returns:
            dict 含 dividend_yield / payout_ratio / dividend_years。
        """
        try:
            import akshare as ak
            import pandas as pd

            df = ak.stock_dividents(symbol=symbol)
            if df is None or df.empty:
                return {"symbol": symbol, "data_grade": "NO_DATA"}

            # 计算连续分红年数
            date_col = _find_column(df, ["股权登记日", "除权除息日", "公告日", "date"])
            if date_col:
                years = df[date_col].dropna().apply(lambda x: str(x)[:4]).unique()
                dividend_years = len(years)
            else:
                dividend_years = len(df)

            # 最近一期分红
            latest = df.iloc[0].to_dict()
            div_yield = _safe_ak_value(latest, ["股息率", "股息", "dividend_yield", "每10股派息"])

            return {
                "symbol": symbol,
                "dividend_yield": div_yield,
                "dividend_years": dividend_years,
                "total_records": len(df),
                "data_grade": "PRIMARY",
            }
        except ImportError:
            return {"symbol": symbol, "data_grade": "UNAVAILABLE"}
        except Exception as e:
            logger.warning("[AKShareEquity] get_dividend(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

    async def get_north_flow(self, symbol: str) -> dict:
        """获取北向资金流向（沪/深股通）。

        使用 AKShare stock_hsgt_north_net_flow_in_em 获取北向数据。

        Returns:
            dict 含 north_net_buy / north_holding / north_holding_pct。
        """
        try:
            import akshare as ak
            import pandas as pd

            df = ak.stock_hsgt_north_net_flow_in_em(symbol=symbol)
            if df is None or df.empty:
                return {"symbol": symbol, "data_grade": "NO_DATA"}

            latest = df.iloc[0].to_dict()
            net_buy = _safe_ak_value(latest, ["沪股通净流入", "深股通净流入", "沪股通", "深股通", "net_buy"])
            total = _safe_ak_value(latest, ["累计净流入", "total"])

            return {
                "symbol": symbol,
                "north_net_buy": net_buy,
                "north_total": total,
                "data_grade": "PRIMARY",
            }
        except ImportError:
            return {"symbol": symbol, "data_grade": "UNAVAILABLE"}
        except Exception as e:
            logger.warning("[AKShareEquity] get_north_flow(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

    # ── ETF 专有方法（G23 Phase 4 重点） ──

    async def get_etf_nav(self, symbol: str) -> dict:
        """获取 ETF 净值数据。

        使用 AKShare fund_etf_spot_em 获取 ETF 实时行情（含净值），
        fund_etf_nav 获取历史净值序列。

        Returns:
            dict 含 nav / nav_date / nav_history / accum_nav / market_price。
        """
        try:
            import akshare as ak
            import pandas as pd

            # 实时行情（含净值）
            spot = ak.fund_etf_spot_em()
            if spot is not None and not spot.empty:
                code_col = _find_column(spot, ["代码", "symbol", "code"])
                nav_col = _find_column(spot, ["单位净值", "净值", "nav", "基金净值"])
                price_col = _find_column(spot, ["最新价", "现价", "price", "current_price"])
                name_col = _find_column(spot, ["名称", "name", "etf_name"])

                if code_col and nav_col:
                    clean_sym = symbol.replace(".SH", "").replace(".SZ", "")
                    row = spot[spot[code_col].astype(str).str.strip() == clean_sym]
                    if not row.empty:
                        latest = row.iloc[0]
                        nav = _safe_ak_value(latest, [nav_col])
                        mkt_price = _safe_ak_value(latest, [price_col]) if price_col else None
                        name = str(latest.get(name_col, "")) if name_col else ""

                        # 历史净值
                        try:
                            nav_hist = ak.fund_etf_nav(symbol=clean_sym)
                            nav_history = nav_hist.tail(20).to_dict("records") if nav_hist is not None and not nav_hist.empty else []
                        except Exception:
                            nav_history = []

                        return {
                            "symbol": symbol,
                            "name": name,
                            "nav": nav,
                            "market_price": mkt_price,
                            "nav_history": nav_history,
                            "data_grade": "PRIMARY",
                        }

            return {"symbol": symbol, "data_grade": "NO_DATA", "note": "实时行情未匹配"}
        except ImportError:
            return {"symbol": symbol, "data_grade": "UNAVAILABLE"}
        except Exception as e:
            logger.warning("[AKShareEquity] get_etf_nav(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

    async def get_etf_constituents(self, symbol: str) -> dict:
        """获取 ETF 成分股列表及权重。

        使用 AKShare fund_etf_composition 获取成分股数据。

        Returns:
            dict 含 constituents（[{stock, weight, amount}]）/ total_count / top10。
        """
        try:
            import akshare as ak
            import pandas as pd

            clean_sym = symbol.replace(".SH", "").replace(".SZ", "")
            df = ak.fund_etf_composition(symbol=clean_sym)
            if df is None or df.empty:
                return {"symbol": symbol, "data_grade": "NO_DATA"}

            # 识别列名
            stock_col = _find_column(df, ["股票代码", "成分股代码", "代码", "stock_code"])
            name_col = _find_column(df, ["股票名称", "成分股名称", "名称", "stock_name"])
            weight_col = _find_column(df, ["权重", "权重%", "持仓比例", "weight", "ratio"])
            amount_col = _find_column(df, ["持仓市值", "市值", "amount", "market_value"])
            shares_col = _find_column(df, ["持股数量", "股数", "shares"])

            constituents = []
            for _, row in df.iterrows():
                item = {}
                if stock_col:
                    item["stock"] = str(row.get(stock_col, ""))
                if name_col:
                    item["name"] = str(row.get(name_col, ""))
                if weight_col:
                    item["weight"] = _safe_ak_value(row, [weight_col])
                if amount_col:
                    item["amount"] = _safe_ak_value(row, [amount_col])
                if shares_col:
                    item["shares"] = _safe_ak_value(row, [shares_col])
                if item:
                    constituents.append(item)

            # 按权重降序
            constituents.sort(key=lambda x: x.get("weight", 0) or 0, reverse=True)
            total_count = len(constituents)
            top10 = [c.get("stock", "") for c in constituents[:10] if c.get("stock")]

            return {
                "symbol": symbol,
                "constituents": constituents,
                "total_count": total_count,
                "top10": top10,
                "data_grade": "PRIMARY",
            }
        except ImportError:
            return {"symbol": symbol, "data_grade": "UNAVAILABLE"}
        except Exception as e:
            logger.warning("[AKShareEquity] get_etf_constituents(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}

    async def get_etf_premium(self, symbol: str) -> dict:
        """获取 ETF 溢价率。

        从 get_etf_nav 获取净值 + 市价，计算溢价率。
        溢价率 = (市场价 - 净值) / 净值 × 100。

        Returns:
            dict 含 premium_pct / market_price / nav / discount_pct。
        """
        try:
            nav_data = await self.get_etf_nav(symbol)
            if nav_data.get("data_grade") != "PRIMARY":
                return {"symbol": symbol, "data_grade": nav_data.get("data_grade", "NO_DATA")}

            nav = nav_data.get("nav")
            mkt_price = nav_data.get("market_price")
            premium = None
            discount = None

            if nav is not None and mkt_price is not None and nav > 0:
                premium = round((mkt_price - nav) / nav * 100, 2)
                discount = round((nav - mkt_price) / nav * 100, 2)

            return {
                "symbol": symbol,
                "premium_pct": premium,    # 正=溢价，负=折价
                "discount_pct": discount,  # 正=折价
                "market_price": mkt_price,
                "nav": nav,
                "data_grade": "PRIMARY",
            }
        except Exception as e:
            logger.warning("[AKShareEquity] get_etf_premium(%s) 失败: %s", symbol, e)
            return {"symbol": symbol, "data_grade": "ERROR"}


# ── 辅助工具 ──


def _find_column(df: "pd.DataFrame", candidates: list[str]) -> Optional[str]:
    """在 DataFrame 中找到第一个匹配的列名。"""
    for col in candidates:
        if col in df.columns:
            return col
    for col in df.columns:
        for c in candidates:
            if c.lower() in col.lower():
                return col
    return None


def _safe_ak_value(row: dict, candidates: list[str]) -> Optional[float]:
    """安全提取 AKShare 返回字段的数值。"""
    for c in candidates:
        val = row.get(c)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def _safe_float(val: Any) -> Optional[float]:
    """将任意值转为 float。"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
