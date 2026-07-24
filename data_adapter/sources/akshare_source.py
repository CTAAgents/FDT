"""AKShare 数据源实现 [INDEPENDENT]。

直接通过 AKShare 库获取期货数据，无任何 intermediate adapter 依赖。
独立于 ``futures_data_core`` 包，纯 AKShare 调用。

实现 ``DataSource`` ABC 的全部 12 个抽象方法。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from data_adapter.base import DataSource
from data_adapter.cleaning import clean_kline
from data_adapter.types import KlineBar, KlineResult, QuoteResult

logger = logging.getLogger(__name__)

# ── 新浪 API 配置 ──
_SINA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ── 品种 → AKShare 外盘代码映射 ──
_FOREIGN_MAP: dict[str, str] = {
    "CF": "ICE.CF",
    "M": "CBOT.M",
    "Y": "CBOT.BO",
    "CU": "LME.CU",
    "AL": "LME.AL",
    "ZN": "LME.ZN",
    "SC": "NYMEX.CL",
    "AU": "COMEX.AU",
    "AG": "COMEX.AG",
    "RU": "TOCOM.RU",
}

# ── 品种 → AKShare 现货列名映射 ──
_AK_SPOT_MAP: dict[str, str] = {
    "CF": "棉花", "SR": "白糖", "TA": "PTA", "MA": "甲醇",
    "RB": "螺纹钢", "HC": "热卷", "I": "铁矿石",
    "CU": "铜", "AL": "铝", "ZN": "锌", "PB": "铅",
    "NI": "镍", "SN": "锡",
    "M": "豆粕", "Y": "豆油", "P": "棕榈油",
    "C": "玉米", "JD": "鸡蛋",
    "SC": "原油", "BU": "沥青", "FU": "燃料油",
    "RU": "橡胶", "V": "PVC", "PP": "聚丙烯", "L": "聚乙烯",
    "FG": "玻璃", "SA": "纯碱", "UR": "尿素",
    "OI": "菜油", "RM": "菜粕", "PK": "花生",
    "SI": "工业硅", "LC": "碳酸锂",
}

# ── 仓单交易所 → AKShare 函数名映射 ──
_WARRANT_FN_MAP: dict[str, str] = {
    "SHFE": "futures_shfe_warehouse_receipt",
    "CZCE": "futures_warehouse_receipt_czce",
    "DCE": "futures_warehouse_receipt_dce",
    "GFEX": "futures_gfex_warehouse_receipt",
}

# ── 持仓排名交易所 → AKShare 函数名映射 ──
_POSITION_FN_MAP: dict[str, str] = {
    "SHFE": "futures_stock_shfe_js",
    "DCE": "futures_dce_position_rank",
    "GFEX": "futures_gfex_position_rank",
}

# ── COMEX 库存品种映射 ──
_COMEX_SYMBOLS: dict[str, str] = {"CU": "铜", "AU": "金", "AG": "银"}


class AKShareSource(DataSource):
    """AKShare 数据源实现。

    所有方法均返回 DataSource 接口定义的规范类型：
      - ``get_kline`` → ``KlineResult``
      - ``get_quote`` / ``batch_get_quotes`` → ``QuoteResult``
      - 其他 → ``dict``（含 ``data`` / ``summary`` / ``data_grade``）
    """
    _CLEANING_ENABLED = os.environ.get("FDT_DATA_CLEANING_ENABLED", "true").lower() == "true"

    # ──────────────────────────────────────────────
    # K 线
    # ──────────────────────────────────────────────

    async def get_kline(
        self, symbol: str, period: str = "daily", days: int = 120
    ) -> KlineResult:
        """获取 K 线数据。

        优先：新浪财经 API（仅日线，快速稳定）。
        降级：AKShare 东方财富（``futures_hist_em``）。
        清洗：当 ``FDT_DATA_CLEANING_ENABLED=true``（默认）时, 自动执行
              OHLC 校验、去重、毛刺修复、复权处理。
        """
        bare = symbol.upper()
        try:
            import akshare as ak
            import pandas as pd

            # ── 路径 A: 新浪财经（仅日线）──
            if period in ("daily", "1d"):
                sina_bars = self._fetch_sina_kline(bare, days)
                if sina_bars:
                    logger.info(
                        "[AKShareSource] 新浪 get_kline 成功(%s) → %d bars",
                        bare, len(sina_bars),
                    )
                    dict_bars = sina_bars
                    cleaning_report = None
                    if self._CLEANING_ENABLED:
                        dict_bars, cleaning_report = clean_kline(dict_bars, config={"symbol": bare})
                    kline_bars = [
                        KlineBar(
                            date=b["date"],
                            open=b["open"],
                            high=b["high"],
                            low=b["low"],
                            close=b["close"],
                            volume=b["volume"],
                            open_interest=b.get("open_interest", 0),
                        )
                        for b in dict_bars
                    ]
                    result = KlineResult(
                        symbol=bare,
                        bars=kline_bars,
                        meta={"data_grade": "PRIMARY", "source": "sina"},
                    )
                    result.cleaning = cleaning_report
                    return result

            # ── 路径 B: 东方财富降级 ──
            period_map = {
                "daily": "daily", "1d": "daily",
                "weekly": "weekly", "1w": "weekly",
                "monthly": "monthly",
            }
            ak_period = period_map.get(period, "daily")
            akshare_symbol = self._to_akshare_symbol(symbol)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=int(days / 0.7) + 30)

            df = ak.futures_hist_em(
                symbol=akshare_symbol,
                period=ak_period,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )

            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                logger.warning(
                    "[AKShareSource] 东方财富 get_kline 为空(%s)", akshare_symbol,
                )
                return self._unavailable_kline(bare, "东方财富 K 线数据为空")

            raw_bars = self._parse_kline_df(df, days)
            if not raw_bars:
                return self._unavailable_kline(bare, "解析 K 线失败")

            # ── 数据清洗 ──
            dict_bars = [
                {"date": b.date, "open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume, "open_interest": b.open_interest}
                for b in raw_bars
            ]
            cleaning_report = None
            if self._CLEANING_ENABLED:
                dict_bars, cleaning_report = clean_kline(dict_bars, config={"symbol": bare})
            cleaned_bars = [
                KlineBar(
                    date=b["date"], open=b["open"], high=b["high"], low=b["low"],
                    close=b["close"], volume=b["volume"],
                    open_interest=b.get("open_interest", 0),
                )
                for b in dict_bars
            ]

            result = KlineResult(
                symbol=bare,
                bars=cleaned_bars,
                meta={"data_grade": "PRIMARY", "source": "akshare"},
            )
            result.cleaning = cleaning_report
            return result

        except Exception as e:
            logger.error("[AKShareSource] get_kline 异常(%s): %s", symbol, e)
            return self._unavailable_kline(bare, str(e)[:80])

    # ──────────────────────────────────────────────
    # 行情快照
    # ──────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> QuoteResult:
        """获取行情快照（AKShare ``futures_zh_realtime``）。"""
        bare = symbol.upper()
        try:
            import akshare as ak
            import pandas as pd

            df = ak.futures_zh_realtime()
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return self._unavailable_quote(bare, "行情数据为空")

            row = self._match_first_row(df, bare)
            if row is None:
                return self._unavailable_quote(bare, f"未匹配品种 {bare}")

            def _gf(cols, default=0.0) -> float:
                for c in cols:
                    v = row.get(c)
                    if v not in (None, "", "-"):
                        try:
                            return float(v)
                        except (ValueError, TypeError):
                            continue
                return default

            price_cols = ["current_price", "最新价", "现价", "price", "last_price"]
            open_cols = ["open", "开盘", "开盘价"]
            high_cols = ["high", "最高", "最高价"]
            low_cols = ["low", "最低", "最低价"]
            vol_cols = ["volume", "成交量", "volume"]
            oi_cols = ["open_interest", "持仓量", "持倉量"]

            last_price = _gf(price_cols)
            open_px = _gf(open_cols)
            high_px = _gf(high_cols)
            low_px = _gf(low_cols)
            volume = _gf(vol_cols)
            oi = _gf(oi_cols)
            change_pct = round((last_price - open_px) / open_px * 100, 2) if open_px > 0 else 0.0

            return QuoteResult(
                symbol=bare,
                last_price=last_price,
                open=open_px,
                high=high_px,
                low=low_px,
                volume=volume,
                open_interest=oi,
                change_pct=change_pct,
                meta={"data_grade": "PRIMARY", "source": "akshare"},
            )

        except Exception as e:
            logger.error("[AKShareSource] get_quote 异常(%s): %s", symbol, e)
            return self._unavailable_quote(bare, str(e)[:80])

    async def batch_get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        """批量获取行情快照。"""
        results: dict[str, QuoteResult] = {}
        for sym in symbols:
            results[sym] = await self.get_quote(sym)
        return results

    # ──────────────────────────────────────────────
    # 合约信息
    # ──────────────────────────────────────────────

    async def get_contract_info(self, symbol: str) -> dict:
        """获取合约信息（乘数/保证金率/最小变动价位等）。

        Returns:
            dict 含 ``symbol`` / ``product_name`` / ``exchange`` /
            ``multiplier`` / ``margin_rate`` / ``price_tick`` 等。
        """
        bare = symbol.upper()
        try:
            import akshare as ak
            import pandas as pd

            info: dict[str, Any] = {"symbol": bare}

            # 1. 品种交易信息
            df = ak.futures_comm_info()
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                row = self._match_first_row(df, bare)
                if row is not None:
                    col_map = {
                        "product_name": ["合约名称", "品种名称", "name", "product"],
                        "exchange": ["交易所", "exchange"],
                        "multiplier": ["合约乘数", "交易单位", "multiplier", "unit"],
                        "margin_rate": ["保证金", "保证金率", "margin"],
                        "price_tick": ["最小变动价位", "price_tick", "tick"],
                    }
                    for target, candidates in col_map.items():
                        v = self._first_match_value(row, candidates)
                        if v not in (None, "", "-"):
                            info[target] = v

            # 2. 合约详情
            df2 = ak.futures_contract_detail_em()
            if df2 is not None and isinstance(df2, pd.DataFrame) and not df2.empty:
                row2 = self._match_first_row(df2, bare)
                if row2 is not None:
                    col_map2 = {
                        "delivery_date": ["交割日期", "交割日", "delivery", "delivery_date"],
                        "last_trading_day": ["最后交易日", "last_trade", "last_trading_day"],
                    }
                    for target, candidates in col_map2.items():
                        v = self._first_match_value(row2, candidates)
                        if v not in (None, "", "-"):
                            info[target] = v

            return {
                "data": info,
                "summary": f"{bare} 合约信息",
                "data_grade": "PRIMARY" if len(info) > 1 else "UNAVAILABLE",
            }

        except Exception as e:
            logger.error("[AKShareSource] get_contract_info 异常(%s): %s", symbol, e)
            return self._unavailable_dict(f"get_contract_info 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 仓单日报
    # ──────────────────────────────────────────────

    async def get_warrant(self, symbol: str, exchange: str = "SHFE") -> dict:
        """获取仓单日报。

        Returns:
            dict 含 ``total`` / ``daily_change`` / ``exchange`` / ``symbol``。
        """
        bare = symbol.upper()
        exchange = exchange.upper()
        try:
            import akshare as ak
            import pandas as pd

            fn_name = _WARRANT_FN_MAP.get(exchange)
            if not fn_name:
                return self._unavailable_dict(f"不支持的交易所: {exchange}")

            fn = getattr(ak, fn_name, None)
            if fn is None:
                return self._unavailable_dict(f"AKShare 无此函数: {fn_name}")

            result = fn()
            # akshare SHFE 仓单接口返回 dict[str, DataFrame]（品种名→数据表）
            if isinstance(result, dict):
                frames = []
                for variety, frame in result.items():
                    if isinstance(frame, pd.DataFrame) and not frame.empty:
                        frame = frame.copy()
                        if "品种" not in frame.columns:
                            frame["品种"] = variety
                        frames.append(frame)
                df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            else:
                df = result
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return self._unavailable_dict(f"{exchange} 仓单数据为空")

            sym_col = self._find_column(df, ["品种", "品种代码", "symbol", "variety", "商品名称"])
            if sym_col:
                matched = df[df[sym_col].astype(str).str.upper().str.contains(bare, na=False)]
                if matched.empty:
                    # 模糊匹配：去数字
                    for _, row in df.iterrows():
                        val = str(row.get(sym_col, "")).upper().strip()
                        val_bare = "".join(c for c in val if c.isalpha())
                        if val_bare == bare or bare in val_bare:
                            matched = pd.concat([matched, row.to_frame().T])
                    if matched.empty:
                        return self._unavailable_dict(f"未匹配品种 {bare} ({exchange})")
            else:
                matched = df

            rows = matched.to_dict("records") if hasattr(matched, "to_dict") else matched

            warrant_keys = {"warrant", "receipt", "仓单", "仓单量", "仓单数量"}
            change_keys = {"change", "delta", "日变动", "增减", "仓单变动"}

            total = None
            daily_change = None

            if rows:
                headers = list(rows[0].keys()) if rows else []
                wc = self._find_column_name(headers, warrant_keys)
                cc = self._find_column_name(headers, change_keys)

                if wc:
                    vals = []
                    for r in rows:
                        try:
                            vals.append(float(str(r.get(wc, "")).replace(",", "")))
                        except (ValueError, TypeError):
                            pass
                    if vals:
                        total = sum(vals)

                if cc:
                    changes = []
                    for r in rows:
                        try:
                            changes.append(float(str(r.get(cc, "")).replace(",", "")))
                        except (ValueError, TypeError):
                            pass
                    if changes:
                        daily_change = sum(changes)

            return {
                "data": {
                    "symbol": bare,
                    "exchange": exchange,
                    "total": total,
                    "daily_change": daily_change,
                },
                "summary": f"{bare} ({exchange}) 仓单 {total or 'N/A'}",
                "data_grade": "PRIMARY" if total is not None else "UNAVAILABLE",
            }

        except Exception as e:
            logger.error("[AKShareSource] get_warrant 异常(%s/%s): %s", symbol, exchange, e)
            return self._unavailable_dict(f"get_warrant 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 库存数据
    # ──────────────────────────────────────────────

    async def get_inventory(self, symbol: str) -> dict:
        """获取库存数据。

        Returns:
            dict 含 ``inventory`` / ``change`` / ``unit`` / ``data_date`` / ``source``。
        """
        bare = symbol.upper()
        try:
            import akshare as ak
            import pandas as pd

            # 先试东方财富库存
            df = ak.futures_inventory_em()
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                result = self._parse_em_inventory(df, bare)
                if result is not None:
                    return result

            # COMEX 后备（仅有色品种）
            if bare in _COMEX_SYMBOLS:
                result = await self._comex_inventory(bare)
                if result is not None:
                    return result

            return self._unavailable_dict(f"库存数据不可用({bare})")

        except Exception as e:
            logger.error("[AKShareSource] get_inventory 异常(%s): %s", symbol, e)
            return self._unavailable_dict(f"get_inventory 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 持仓排名
    # ──────────────────────────────────────────────

    async def get_position_ranking(self, symbol: str) -> dict:
        """获取持仓排名。

        Returns:
            dict 含 ``net_long`` / ``long_volume`` / ``short_volume`` /
            ``top5_long`` / ``top5_short`` / ``long`` / ``short``。
        """
        bare = symbol.upper()
        try:
            import akshare as ak
            import pandas as pd

            # 交易所判断：尝试 SHFE → DCE → GFEX
            for exchange, fn_name in _POSITION_FN_MAP.items():
                try:
                    fn = getattr(ak, fn_name, None)
                    if fn is None:
                        continue

                    result = fn()
                    # 兼容 dict 返回（GFEX 等接口）
                    if isinstance(result, dict):
                        frames = []
                        for variety, frame in result.items():
                            if isinstance(frame, pd.DataFrame) and not frame.empty:
                                frame = frame.copy()
                                frames.append(frame)
                        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                    else:
                        df = result
                    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                        continue
                except Exception as inner_e:
                    logger.warning("[AKShareSource] get_position_ranking 跳过 %s: %s", exchange, inner_e)
                    continue

                sym_col = self._find_column(
                    df, ["品种", "品种代码", "symbol", "variety", "商品名称"],
                )
                if sym_col:
                    mask = df[sym_col].astype(str).str.upper().str.contains(bare, na=False)
                    filtered = df[mask]
                else:
                    filtered = df

                if filtered.empty:
                    continue

                long_col = self._find_column(
                    filtered, ["持买单量", "持买", "long", "long_open_interest", "多头持仓"],
                )
                short_col = self._find_column(
                    filtered, ["持卖单量", "持卖", "short", "short_open_interest", "空头持仓"],
                )
                name_col = self._find_column(
                    filtered, ["会员简称", "会员", "member", "broker", "abbr"],
                )

                if not long_col and not short_col:
                    continue

                long_list = []
                short_list = []
                for _, row in filtered.iterrows():
                    member = str(row.get(name_col, "")) if name_col else ""
                    if long_col:
                        try:
                            lots = int(float(row.get(long_col, 0) or 0))
                            if lots > 0:
                                long_list.append({
                                    "rank": len(long_list) + 1,
                                    "member": member,
                                    "lots": lots,
                                })
                        except (ValueError, TypeError):
                            pass
                    if short_col:
                        try:
                            lots = int(float(row.get(short_col, 0) or 0))
                            if lots > 0:
                                short_list.append({
                                    "rank": len(short_list) + 1,
                                    "member": member,
                                    "lots": lots,
                                })
                        except (ValueError, TypeError):
                            pass

                long_vol = sum(x["lots"] for x in long_list)
                short_vol = sum(x["lots"] for x in short_list)

                return {
                    "data": {
                        "symbol": bare.lower(),
                        "exchange": exchange,
                        "total_oi": None,
                        "long_volume": long_vol,
                        "short_volume": short_vol,
                        "net_long": long_vol - short_vol,
                        "top5_long": sum(x["lots"] for x in long_list[:5]),
                        "top5_short": sum(x["lots"] for x in short_list[:5]),
                        "long": long_list,
                        "short": short_list,
                        "data_source": f"akshare_{exchange.lower()}",
                    },
                    "summary": f"{bare} 持仓排名（{exchange}）",
                    "data_grade": "PRIMARY",
                }

            return self._unavailable_dict(f"持仓排名不可用({bare})")

        except Exception as e:
            logger.error("[AKShareSource] get_position_ranking 异常(%s): %s", symbol, e)
            return self._unavailable_dict(f"get_position_ranking 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 资金流向
    # ──────────────────────────────────────────────

    async def get_fund_flow(self, symbol: str) -> dict:
        """获取资金流向（持仓/多空比）。

        Returns:
            dict 含 ``total_oi`` / ``long_volume`` / ``short_volume`` /
            ``long_short_ratio`` / ``data_date``。
        """
        bare = symbol.upper()
        try:
            import akshare as ak
            import pandas as pd

            df = ak.futures_hold_pos_sina()
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return self._unavailable_dict("资金流向数据为空")

            sym_col = self._find_column(
                df, ["品种", "品种代码", "symbol", "variety", "商品名称"],
            )
            if sym_col:
                matched = df[df[sym_col].astype(str).str.upper().str.contains(bare, na=False)]
            else:
                matched = df

            if matched.empty:
                return self._unavailable_dict(f"未匹配品种 {bare}")

            latest = matched.iloc[-1]

            oi = self._safe_float_df(latest, ["持仓量", "open_interest", "total_oi", "oi"])
            long_v = self._safe_float_df(latest, ["多头持仓", "long", "long_pos", "buy"])
            short_v = self._safe_float_df(latest, ["空头持仓", "short", "short_pos", "sell"])
            dt = self._get_date_str(latest, ["日期", "date", "trade_date"])

            ratio = round(long_v / short_v, 4) if (long_v and short_v and short_v > 0) else None

            return {
                "data": {
                    "symbol": bare,
                    "total_oi": int(oi) if oi else None,
                    "long_volume": int(long_v) if long_v else None,
                    "short_volume": int(short_v) if short_v else None,
                    "long_short_ratio": ratio,
                    "data_date": dt,
                },
                "summary": f"{bare} 多头 {long_v} / 空头 {short_v}",
                "data_grade": "PRIMARY",
            }

        except Exception as e:
            logger.error("[AKShareSource] get_fund_flow 异常(%s): %s", symbol, e)
            return self._unavailable_dict(f"get_fund_flow 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 外盘数据
    # ──────────────────────────────────────────────

    async def get_foreign_hist(self, symbol: str) -> dict:
        """获取外盘历史数据。

        Returns:
            dict 含 ``foreign_symbol`` / ``close`` / ``change_pct`` / ``bars``。
        """
        bare = symbol.upper()
        try:
            import akshare as ak
            import pandas as pd

            foreign_sym = _FOREIGN_MAP.get(bare)
            if not foreign_sym:
                return self._unavailable_dict(f"无外盘映射: {bare}")

            df = ak.futures_foreign_hist(symbol=foreign_sym)
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return self._unavailable_dict(f"外盘数据为空({foreign_sym})")

            latest = df.iloc[-1]
            close = self._safe_float_df(latest, ["收盘", "close", "收盘价", "last"])

            prev = df.iloc[-2] if len(df) > 1 else None
            prev_close = self._safe_float_df(prev, ["收盘", "close", "收盘价", "last"]) if prev is not None else None
            change_pct = (
                round((close - prev_close) / prev_close * 100, 2)
                if (close is not None and prev_close is not None and prev_close > 0)
                else None
            )

            date_col = self._find_column(df, ["日期", "date", "trade_date"])
            dt = str(latest.get(date_col, ""))[:10] if date_col else ""

            bars = []
            for _, row in df.tail(60).iterrows():
                d = str(row.get(date_col, ""))[:10] if date_col else ""
                o = self._safe_float_df(row, ["开盘", "open"])
                h = self._safe_float_df(row, ["最高", "high"])
                l = self._safe_float_df(row, ["最低", "low"])
                c = self._safe_float_df(row, ["收盘", "close", "收盘价", "last"])
                if d and c:
                    bars.append({"date": d, "open": o, "high": h, "low": l, "close": c})

            return {
                "data": {
                    "symbol": bare,
                    "foreign_symbol": foreign_sym,
                    "close": close,
                    "change_pct": change_pct,
                    "data_date": dt,
                    "bars": bars[-30:],
                },
                "summary": f"{bare}({foreign_sym}) {close}" + (f" ({change_pct:+.2f}%)" if change_pct else ""),
                "data_grade": "PRIMARY",
            }

        except Exception as e:
            logger.error("[AKShareSource] get_foreign_hist 异常(%s): %s", symbol, e)
            return self._unavailable_dict(f"get_foreign_hist 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 基差
    # ──────────────────────────────────────────────

    async def get_basis(self, symbol: str) -> dict:
        """获取基差数据（现货 - 期货）。

        Returns:
            dict 含 ``spot_price`` / ``basis`` / ``basis_pct``。
        """
        bare = symbol.upper()
        try:
            import akshare as ak
            import pandas as pd

            df = ak.futures_spot_price_daily()
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return self._unavailable_dict("现货价格数据为空")

            # 尝试按品种名称列匹配
            spot_price = None
            for _, row in df.iterrows():
                name = str(row.get("商品名称", row.get("品种", ""))).strip().upper()
                ak_name = _AK_SPOT_MAP.get(bare, "").upper()
                if bare in name or name in bare or (ak_name and ak_name in name):
                    val = row.get("现货价格", row.get("价格", row.get("收盘价", None)))
                    if val not in (None, "", "-"):
                        try:
                            spot_price = float(val)
                            break
                        except (ValueError, TypeError):
                            continue

            # 按列名匹配
            if spot_price is None:
                for col in [bare, bare.lower(), _AK_SPOT_MAP.get(bare, "")]:
                    if col and col in df.columns:
                        val = df[col].iloc[-1]
                        if val not in (None, "", "-"):
                            try:
                                spot_price = float(val)
                                break
                            except (ValueError, TypeError):
                                continue

            if spot_price is None:
                return self._unavailable_dict(f"未匹配品种现货价({bare})")

            return {
                "data": {
                    "symbol": bare,
                    "spot_price": round(spot_price, 2),
                    "basis": None,
                    "basis_pct": None,
                },
                "summary": f"{bare} 现货价 {spot_price}",
                "data_grade": "PRIMARY",
            }

        except Exception as e:
            logger.error("[AKShareSource] get_basis 异常(%s): %s", symbol, e)
            return self._unavailable_dict(f"get_basis 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 宏观 — PMI
    # ──────────────────────────────────────────────

    async def get_macro_pmi(self) -> dict:
        """获取 PMI 宏观数据。

        Returns:
            dict 含 ``pmi`` / ``pmi_date`` / ``pmi_mom``。
        """
        try:
            import akshare as ak
            import pandas as pd

            df = ak.macro_china_pmi()
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return self._unavailable_dict("PMI 数据为空")

            latest = df.iloc[0]

            pmi_col = self._find_column(
                df, ["制造业-指数", "制造业PMI", "制造业", "pmi", "MAKE_INDEX", "value"],
            )
            date_col = self._find_column(
                df, ["日期", "date", "REPORT_DATE", "index", "time"],
            )

            pmi = self._safe_float_df(latest, [pmi_col]) if pmi_col else None
            date_val = str(latest.get(date_col, ""))[:10] if date_col else ""

            if pmi is None:
                return self._unavailable_dict("PMI 值缺失")

            return {
                "data": {
                    "pmi": pmi,
                    "pmi_date": date_val,
                    "pmi_mom": None,
                    "source": "akshare",
                },
                "summary": f"制造业PMI {pmi}（{date_val}）",
                "data_grade": "PRIMARY",
            }

        except Exception as e:
            logger.error("[AKShareSource] get_macro_pmi 异常: %s", e)
            return self._unavailable_dict(f"get_macro_pmi 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 宏观 — 利率
    # ──────────────────────────────────────────────

    async def get_macro_rate(self) -> dict:
        """获取利率宏观数据（LPR）。

        Returns:
            dict 含 ``rate`` / ``rate_date`` / ``rate_mom``。
        """
        try:
            import akshare as ak
            import pandas as pd

            df = ak.macro_china_lpr()
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return self._unavailable_dict("LPR 数据为空")

            rate_col = self._find_column(
                df, ["LPR1Y", "1年期LPR", "lpr1y", "rate", "value"],
            )
            date_col = self._find_column(
                df, ["TRADE_DATE", "日期", "date", "trade_date"],
            )

            rate = None
            date_val = ""
            if rate_col and rate_col in df.columns:
                non_null = df[df[rate_col].notna()]
                if not non_null.empty:
                    rate_row = non_null.iloc[-1]
                    rate = self._safe_float_df(rate_row, [rate_col])
                    date_val = str(rate_row.get(date_col, ""))[:10] if date_col else ""

            if rate is None:
                latest = df.iloc[0]
                rate = self._safe_float_df(latest, [rate_col]) if rate_col else None
                date_val = str(latest.get(date_col, ""))[:10] if date_col else ""

            if rate is None:
                return self._unavailable_dict("LPR1Y 值缺失")

            return {
                "data": {
                    "rate": rate,
                    "rate_date": date_val,
                    "rate_mom": None,
                    "source": "akshare",
                },
                "summary": f"LPR1Y {rate}%（{date_val}）",
                "data_grade": "PRIMARY",
            }

        except Exception as e:
            logger.error("[AKShareSource] get_macro_rate 异常: %s", e)
            return self._unavailable_dict(f"get_macro_rate 失败: {str(e)[:80]}")

    # ──────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────

    @staticmethod
    def _to_akshare_symbol(symbol: str) -> str:
        """FDT 品种代码 → AKShare 主力连续合约代码。

        如 "RB" → "RB0"，"CF" → "CF0"。
        """
        bare = symbol.upper().split(".")[0]
        # 去掉可能的数字后缀（如 "RB2401" → "RB"）
        pure = "".join(c for c in bare if c.isalpha())
        return f"{pure}0"

    @staticmethod
    def _parse_kline_df(df, days: int) -> list[KlineBar]:
        """从 AKShare DataFrame 解析 K 线列表。"""
        import pandas as pd

        if not isinstance(df, pd.DataFrame):
            return []

        bars: list[KlineBar] = []
        rows = df.tail(min(days, len(df)))
        for _, row in rows.iterrows():
            date_val = row.get("日期", row.get("date", ""))
            if not date_val:
                continue
            date_str = str(date_val).replace("-", "").replace("/", "").strip()
            if not (len(date_str) >= 8 and date_str[:8].isdigit()):
                continue
            try:
                bar = KlineBar(
                    date=date_str[:8],
                    open=float(row.get("开盘", row.get("open", 0))),
                    high=float(row.get("最高", row.get("high", 0))),
                    low=float(row.get("最低", row.get("low", 0))),
                    close=float(row.get("收盘", row.get("close", 0))),
                    volume=float(row.get("成交量", row.get("volume", 0)) or 0),
                    open_interest=float(row.get("持仓量", row.get("open_interest", 0)) or 0),
                )
                bars.append(bar)
            except (TypeError, ValueError):
                continue

        # 确保升序
        if len(bars) >= 2 and bars[0].date > bars[1].date:
            bars.reverse()
        return bars

    @staticmethod
    def _fetch_sina_kline(bare: str, days: int = 120) -> list[dict]:
        """从新浪财经 API 获取日 K 线。

        Returns:
            [{date, open, high, low, close, volume, amount, open_interest}, ...]
        """
        import requests

        url = (
            f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php"
            f"/var%20_{bare}0=/InnerFuturesNewService.getDailyKLine"
            f"?symbol={bare}0"
        )
        try:
            resp = requests.get(url, headers={"User-Agent": _SINA_UA}, timeout=15)
            if resp.status_code != 200:
                return []
            text = resp.text
            match = re.search(r"=\((\[.+?\])\)", text, re.DOTALL)
            if not match:
                return []
            raw = json.loads(match.group(1))
            if not raw:
                return []
            bars = []
            for item in raw[-days:]:
                try:
                    bars.append({
                        "date": str(item["d"]).replace("-", ""),
                        "open": float(item["o"]),
                        "high": float(item["h"]),
                        "low": float(item["l"]),
                        "close": float(item["c"]),
                        "volume": float(item["v"]),
                        "amount": float(item.get("s", 0) or 0),
                        "open_interest": float(item.get("p", 0) or 0),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
            return bars
        except Exception as e:
            logger.warning("[AKShareSource] 新浪 get_kline 失败(%s): %s", bare, e)
            return []

    @staticmethod
    def _match_first_row(df, bare: str) -> Optional[dict]:
        """从 DataFrame 中匹配品种并返回第一行。"""
        sym_col = None
        for col in ["symbol", "代码", "品种代码", "品种", "variety", "商品名称"]:
            if col in df.columns:
                sym_col = col
                break
        if sym_col:
            matched = df[df[sym_col].astype(str).str.upper().str.contains(bare, na=False)]
            if not matched.empty:
                return matched.iloc[-1]

        # 精确按代码列匹配
        for col in ["合约代码", "code", "contract"]:
            if col in df.columns:
                matched = df[df[col].astype(str).str.upper().str.startswith(bare, na=False)]
                if not matched.empty:
                    return matched.iloc[-1]

        return None

    @staticmethod
    def _find_column(df, candidates: list[str]) -> Optional[str]:
        """在 DataFrame 列中找到第一个匹配的列名。"""
        for c in candidates:
            if c in df.columns:
                return c
        return None

    @staticmethod
    def _find_column_name(headers: list[str], candidates: set[str]) -> Optional[str]:
        """在列名列表中找到第一个匹配项。"""
        for h in headers:
            key = str(h).strip()
            if key.lower() in candidates or key in candidates:
                return h
        return None

    @staticmethod
    def _first_match_value(row: dict, candidates: list[str]) -> Any:
        """从行中按候选列名取第一个非空值。"""
        for c in candidates:
            v = row.get(c)
            if v not in (None, "", "-"):
                return v
        return None

    @staticmethod
    def _safe_float_df(row, candidates) -> Optional[float]:
        """从行中按候选列名取 float 值。"""
        for c in candidates:
            v = row.get(c)
            if v not in (None, "", "-"):
                try:
                    val = float(v)
                    import math
                    if math.isnan(val):
                        return None
                    return val
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _get_date_str(row: dict, candidates: list[str]) -> str:
        """从行中取日期字符串。"""
        for c in candidates:
            v = row.get(c)
            if v:
                return str(v)[:10]
        return ""

    def _parse_em_inventory(self, df, bare: str) -> Optional[dict]:
        """解析东方财富库存 DataFrame。"""
        import pandas as pd

        sym_col = self._find_column(
            df, ["品种", "品种代码", "symbol", "variety", "商品名称"],
        )
        inv_col = self._find_column(
            df, ["库存", "库存量", "inventory", "仓单", "库存吨数"],
        )
        chg_col = self._find_column(
            df, ["增减", "变化", "change", "日变动"],
        )
        date_col = self._find_column(
            df, ["日期", "date", "trade_date"],
        )

        if sym_col:
            matched = df[df[sym_col].astype(str).str.upper().str.contains(bare, na=False)]
            if matched.empty:
                return None
            latest = matched.iloc[-1]
        elif inv_col:
            latest = df.iloc[-1]
        else:
            return None

        inv = self._safe_float_df(latest, [inv_col]) if inv_col else None
        chg = self._safe_float_df(latest, [chg_col]) if chg_col else None
        dt = str(latest.get(date_col, ""))[:10] if date_col else ""

        if inv is None:
            return None

        return {
            "data": {
                "symbol": bare,
                "inventory": inv,
                "unit": "吨",
                "change": chg,
                "data_date": dt,
                "source": "eastmoney",
            },
            "summary": f"{bare} 库存 {inv} 吨（{dt}）" + (f"，变动 {chg}" if chg else ""),
            "data_grade": "PRIMARY",
        }

    async def _comex_inventory(self, bare: str) -> Optional[dict]:
        """获取 COMEX 库存（后备源）。"""
        import akshare as ak
        import pandas as pd

        name = _COMEX_SYMBOLS.get(bare, "")
        if not name:
            return None

        df = ak.futures_comex_inventory()
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            return None

        sym_col = self._find_column(df, ["品种", "商品", "symbol", "variety"])
        if sym_col:
            matched = df[df[sym_col].astype(str).str.contains(name, na=False)]
        else:
            matched = df

        if matched.empty:
            return None

        latest = matched.iloc[-1]
        qty = self._safe_float_df(latest, ["库存"])
        dt = str(latest.get("日期", ""))[:10]

        if qty is None:
            return None

        return {
            "data": {
                "symbol": bare,
                "inventory": qty,
                "unit": "短吨",
                "change": None,
                "data_date": dt,
                "source": "comex",
            },
            "summary": f"{bare} COMEX 库存 {qty}（{dt}）",
            "data_grade": "PRIMARY",
        }

    @staticmethod
    def _unavailable_kline(symbol: str, reason: str) -> KlineResult:
        """返回不可用的 KlineResult。"""
        logger.warning("[AKShareSource] get_kline 不可用(%s): %s", symbol, reason)
        return KlineResult(
            symbol=symbol,
            bars=[],
            meta={"data_grade": "UNAVAILABLE", "source": "akshare"},
        )

    @staticmethod
    def _unavailable_quote(symbol: str, reason: str) -> QuoteResult:
        """返回不可用的 QuoteResult。"""
        logger.warning("[AKShareSource] get_quote 不可用(%s): %s", symbol, reason)
        return QuoteResult(
            symbol=symbol,
            meta={"data_grade": "UNAVAILABLE", "source": "akshare"},
        )
