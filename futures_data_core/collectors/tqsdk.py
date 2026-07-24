"""天勤 TqSDK 采集器 — 全能力封装 [INDEPENDENT]。

封装 TqSDK 所有数据查询和交易方法，作为 FDC 的统一量化数据引擎入口。
所有方法通过 ``asyncio.to_thread`` 包装为异步接口。

```python
# 使用示例
from futures_data_core.collectors.tqsdk import TqSdkCollector
c = TqSdkCollector()
kline = await c.get_kline('CU')
quote = await c.get_quote('CU')
account = await c.get_account()
shares = await c.query_cont_quotes('SHFE')
```
"""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import date, datetime
from typing import Any, Optional

from futures_data_core.collectors.base import (
    BaseCollector,
    CollectorType,
    CollectorUnavailableError,
)
from futures_data_core.core.types import KlineBar, KlineData, QuoteData, SymbolInfo, TickBar, TickData

# ── wait_update 泵送辅助 ──
def _pump(api, data_obj, min_rows=1, max_wait=5.0):
    """泵送 wait_update，等待 data_obj 有足够数据。

    TqSDK 的 get_kline_serial/get_tick_serial 只创建 DataFrame 结构，
    实际数据要通过 WebSocket 推送 + wait_update 驱动事件循环才能灌入。
    不加 wait_update 返回的是空 DataFrame → _parse_kline 返回0行 → 数据获取失败。

    TqSDK 3.10.1 的 wait_update 参数为 deadline（绝对时间戳），非 timeout。
    """
    import time
    _pump_deadline = time.time() + max_wait
    while time.time() < _pump_deadline:
        try:
            api.wait_update(deadline=time.time() + 0.5)
        except Exception:
            break
        try:
            if len(data_obj) >= min_rows:
                return True
        except (TypeError, AttributeError):
            pass
    return bool(data_obj is not None and (hasattr(data_obj, '__len__') and len(data_obj) >= min_rows))

# ── pd_isna helper ──
def _pd_isna(v) -> bool:
    try:
        import pandas as pd
        return pd.isna(v)
    except ImportError:
        return v is None or (isinstance(v, float) and str(v) == "nan")

# ── 周期常量 ──
_PERIOD_SECONDS = {
    "daily": 86400, "1d": 86400,
    "60m": 3600, "120m": 7200, "240m": 14400,
    "weekly": 604800, "1w": 604800,
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
}

# ── 品种 → 交易所 ──
# 单真相已迁移至 futures_data_core.core.symbol_registry._TQ_EXCHANGE_MAP
# 此处保留仅用于 _resolve_continuous() 向后兼容
from futures_data_core.core.symbol_registry import to_tqsdk_continuous, to_tqsdk_contract
_EXCHANGE_MAP: dict[str, str] = {
    "CU": "SHFE", "AL": "SHFE", "ZN": "SHFE", "PB": "SHFE",
    "NI": "SHFE", "SN": "SHFE", "AU": "SHFE", "AG": "SHFE",
    "RB": "SHFE", "HC": "SHFE", "SS": "SHFE", "RU": "SHFE",
    "BR": "SHFE", "FU": "SHFE", "BU": "SHFE", "SP": "SHFE",
    "WR": "SHFE", "AO": "SHFE",
    "A": "DCE", "B": "DCE", "M": "DCE", "Y": "DCE", "C": "DCE",
    "P": "DCE", "J": "DCE", "JM": "DCE", "I": "DCE", "L": "DCE",
    "PP": "DCE", "V": "DCE", "JD": "DCE", "RR": "DCE", "LH": "DCE",
    "EB": "DCE", "EG": "DCE", "PG": "DCE",
    "SR": "CZCE", "CF": "CZCE", "TA": "CZCE", "OI": "CZCE",
    "RM": "CZCE", "MA": "CZCE", "FG": "CZCE",
    "SF": "CZCE", "SM": "CZCE", "CY": "CZCE", "AP": "CZCE",
    "CJ": "CZCE", "UR": "CZCE", "SA": "CZCE", "PF": "CZCE",
    "PK": "CZCE", "PX": "CZCE", "SH": "CZCE", "PR": "CZCE",
    "SC": "INE", "LU": "INE", "NR": "INE", "BC": "INE",
    "SI": "GFEX", "LC": "GFEX",
}


class TqSdkCollector(BaseCollector):
    """天勤 TqSDK 采集器（全能力封装，连接复用）。"""

    name = "tqsdk"
    priority = 0  # 第一数据源
    collector_type = CollectorType.INDEPENDENT
    llm_requirement = ""

    def __init__(self) -> None:
        self._api_instance: Any = None
        self._api_lock = threading.Lock()

    async def close(self) -> None:
        """关闭 TqApi 连接（超时兜底，杜绝 300s 挂死）。"""
        with self._api_lock:
            if self._api_instance is not None:
                _inst = self._api_instance
                self._api_instance = None
                self._safe_close(_inst)

    # ── 可用性 ──
    async def check_available(self) -> bool:
        """TqSDK 可用性：库已装 + 认证已配。"""
        try:
            __import__("tqsdk")
            return bool(self._user() and self._pass())
        except Exception:
            return False

    @staticmethod
    def _user() -> str:
        return os.environ.get("TQSDK_USERNAME") or os.environ.get("TQ_USER", "")

    @staticmethod
    def _pass() -> str:
        return os.environ.get("TQSDK_PASSWORD") or os.environ.get("TQ_PASSWORD", "")

    # ── 主力连续合约自动解析 ──
    def _resolve_continuous(self, symbol: str) -> str:
        """将 FDT 品种代码转为 TqSDK 主力连续合约符号。

        ``"SM2609"`` -> ``"KQ.m@CZCE.SM"``（自动剥离合约月份后缀）

        委托给 ``symbol_registry.to_tqsdk_continuous()``。
        """
        return to_tqsdk_continuous(symbol)

    def _resolve_tqsdk_symbol(self, symbol: str, contract: str | None = None) -> str:
        return contract or self._resolve_continuous(symbol)

    def _api(self, timeout: float = 15.0):
        """获取或创建 TqApi 实例（连接复用）。

        Args:
            timeout: 首次建连超时秒数；超时抛出 CollectorUnavailableError。

        🛡️ 超时保护：首次 ``TqApi()`` 建连（WebSocket）在非交互/自动化模式下
        可能无限挂起。用 ``concurrent.futures`` 线程池 + 超时兜底，超时后
        标记为不可用并抛出异常，不阻塞整个降级链。
        """
        if self._api_instance is not None:
            return self._api_instance
        with self._api_lock:
            if self._api_instance is not None:
                return self._api_instance
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
            from tqsdk import TqApi, TqAuth

            _executor = ThreadPoolExecutor(max_workers=1)
            _future = _executor.submit(lambda: TqApi(auth=TqAuth(self._user(), self._pass())))
            try:
                self._api_instance = _future.result(timeout=timeout)
            except _FutureTimeout:
                # 超时后标记不可用，避免后续重试
                self._api_instance = None
                raise CollectorUnavailableError(
                    self.name, f"TqSDK 建连超时({timeout}s) — 环境变量 TQSDK_USERNAME/PASSWORD 可能无效或网络不通"
                )
            except Exception as exc:
                self._api_instance = None
                raise CollectorUnavailableError(self.name, f"TqSDK 建连失败: {exc}")
            finally:
                _executor.shutdown(wait=False)
        return self._api_instance

    # ═══════════════════════════════════════════════════════════
    # 1. K 线
    # ═══════════════════════════════════════════════════════════
    async def get_kline(
        self, symbol: str, period: str = "daily", days: int = 120, contract: str | None = None
    ) -> KlineData:
        """获取 K 线数据（向后拉取 N 根）。

        🛡️ ``asyncio.wait_for(timeout=25.0)`` — 即便建连成功，拉取 K 线也可能
        因 WebSocket 推送延迟挂起；超时后抛出 CollectorUnavailableError，
        降级链自动跳过 TqSDK。
        """
        eff = self._resolve_tqsdk_symbol(symbol, contract)
        dur = _PERIOD_SECONDS.get(period, 86400)
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(self._klines_sync, eff, dur, days),
                timeout=25.0,
            )
        except asyncio.TimeoutError:
            raise CollectorUnavailableError(
                self.name, f"TqSDK get_kline 超时(25s) — {eff}"
            )
        except CollectorUnavailableError:
            raise
        except Exception as exc:
            raise CollectorUnavailableError(self.name, str(exc)) from exc
        bars = self._parse_kline(df, days)
        return KlineData(symbol=symbol, period=period, source=self.name, bars=bars, contract=eff)

    def _close_api(self) -> None:
        """关闭 TqApi 连接并重置缓存，防止跨 asyncio.run() 边界复用损坏实例。

        当外部调用方（如 data/multi_source_adapter）用 ``asyncio.run()`` 逐品种
        调用 ``get_kline()`` 时，每次 ``asyncio.run()`` 结束后其事件循环被关闭，
        TqApi 内部 10 余个 WebSocket 守护任务随之损坏。若不关闭重建，下一个品种
        调用时 ``get_kline_serial`` 会因 ``RuntimeError: Event loop is closed`` 挂死。

        见 2026-07-13 17:44 故障诊断。

        🛡️ C 修复（2026-07-15）：``TqApi.close()`` 在异常环境下会挂死 300s
        （executor did not finish joining threads within 300 seconds）。改为守护线程
        + 5s 超时，超时即放弃并置空实例，绝不阻塞降级链。
        """
        with self._api_lock:
            if self._api_instance is not None:
                _inst = self._api_instance
                self._api_instance = None
                self._safe_close(_inst)

    def _safe_close(self, inst: Any) -> None:
        """在守护线程中关闭 TqApi，最多等待 5s，超时放弃（避免 300s 挂死）。"""
        if inst is None:
            return
        try:
            import threading
            _done = threading.Event()

            def _do_close() -> None:
                try:
                    inst.close()
                except Exception:
                    pass
                finally:
                    _done.set()

            _t = threading.Thread(target=_do_close, daemon=True)
            _t.start()
            _done.wait(timeout=5.0)
        except Exception:
            pass

    def _klines_sync(self, sym: str, dur: int, days: int, _retry_event_loop: bool = True):
        """_retry_event_loop: 首次因事件循环损坏失败后关闭实例并重试一次。"""
        try:
            api = self._api()
            klines = api.get_kline_serial(sym, dur, data_length=days)
            _pump(api, klines, min_rows=min(days, 5))
            return klines
        except (RuntimeError, Exception) as _e:
            if _retry_event_loop and ("Event loop" in str(_e) or "event loop" in str(_e) or "no running event" in str(_e)):
                # 事件循环损坏 → 关闭实例，重试一次（_api() 会重建）
                self._close_api()
                return self._klines_sync(sym, dur, days, _retry_event_loop=False)
            raise
        finally:
            # 每次调用后关闭连接，防止跨 asyncio.run() 边界复用损坏的 TqApi。
            # 下次调用 _api() 会重建（~1s），保证实例与当前事件循环生命周期一致。
            self._close_api()

    async def get_kline_data_series(
        self, symbol: str, period: str = "daily",
        start_dt: str | None = None, end_dt: str | None = None,
        contract: str | None = None,
    ) -> dict:
        """获取指定时间段的 K 线序列（带 TqSDK 缓存）。"""
        eff = self._resolve_tqsdk_symbol(symbol, contract)
        dur = _PERIOD_SECONDS.get(period, 86400)
        sd = datetime.strptime(start_dt, "%Y-%m-%d") if start_dt else datetime(2020, 1, 1)
        ed = datetime.strptime(end_dt, "%Y-%m-%d") if end_dt else datetime.now()
        df = await asyncio.to_thread(self._kline_series_sync, eff, dur, sd, ed)
        bars = self._parse_kline(df, len(df)) if df is not None else []
        return {"symbol": symbol, "contract": eff, "bars": [b.__dict__ for b in bars]}

    def _kline_series_sync(self, sym: str, dur: int, sd: datetime, ed: datetime):
        api = self._api()
        try:
            klines = api.get_kline_data_series(sym, dur, start_dt=sd, end_dt=ed)
            if klines is not None:
                _pump(api, klines, min_rows=5)
            return klines
        finally:
            self._close_api()

    @staticmethod
    def _parse_kline(df, days: int) -> list[KlineBar]:
        bars: list[KlineBar] = []
        try:
            rows = list(df.tail(days).itertuples(index=False))
        except Exception:
            return bars
        for row in rows:
            try:
                _dt_val = getattr(row, "datetime")
                if hasattr(_dt_val, "strftime"):
                    _date_str = _dt_val.strftime("%Y%m%d")
                else:
                    try:
                        # TqSDK uses nanosecond Unix timestamps
                        _ts = float(_dt_val) / 1_000_000_000
                        _date_str = __import__('datetime').datetime.fromtimestamp(_ts).strftime("%Y%m%d")
                    except (TypeError, ValueError, OSError):
                        _date_str = str(_dt_val)[:10].replace("-", "").replace("/", "")
                bars.append(KlineBar(
                    date=_date_str,
                    open=float(getattr(row, "open")),
                    high=float(getattr(row, "high")),
                    low=float(getattr(row, "low")),
                    close=float(getattr(row, "close")),
                    volume=float(getattr(row, "volume", 0.0) or 0.0),
                    open_interest=float(getattr(row, "open_interest", 0.0) or 0.0),
                ))
            except (TypeError, ValueError, AttributeError):
                continue
        return bars

    # ── TqSDK K线 fallback（同步，无 asyncio，供 scan_all.py 等非异步环境使用）──
    @staticmethod
    def fetch_kline_sync(symbol: str, period: str = "daily", days: int = 120, min_bars: int = 50) -> list[dict] | None:
        """同步获取 K 线数据（asyncio-free），返回 FDC 兼容的 bar list。

        当 FDC 主链路（TDX/TqSDK multi-source）无数据时作为 fallback，
        自建临时 TqSdkCollector 实例，生命周期完全自包含。

        Args:
            symbol: FDT 品种代码（如 "CF", "RB2601"）。
            period: K 线周期，默认 "daily"。
            days: 获取天数。
            min_bars: 最少返回 K 线根数。

        Returns:
            与 _fdc_get_kline_sync 兼容的 bar list，每项含 date/open/high/low/close/volume。
            失败或数据不足返回 None。
        """
        try:
            # 每个临时实例自包含完整的 TqApi 生命周期
            _inst = TqSdkCollector()
            eff = _inst._resolve_tqsdk_symbol(symbol)
            dur = _PERIOD_SECONDS.get(period, 86400)
            df = _inst._klines_sync(eff, dur, days)
            if df is None or len(df) < min_bars:
                return None
            bars = []
            for row in df.tail(min_bars).itertuples():
                try:
                    _dt_val = getattr(row, "datetime")
                    if hasattr(_dt_val, "strftime"):
                        _date_str = _dt_val.strftime("%Y%m%d")
                    else:
                        # TqSDK nanosecond Unix timestamp
                        _ts = float(_dt_val) / 1_000_000_000
                        _date_str = __import__("datetime").datetime.fromtimestamp(_ts).strftime("%Y%m%d")
                    bars.append({
                        "date": _date_str,
                        "open": float(getattr(row, "open", 0)),
                        "high": float(getattr(row, "high", 0)),
                        "low": float(getattr(row, "low", 0)),
                        "close": float(getattr(row, "close", 0)),
                        "volume": int(getattr(row, "volume", 0)),
                    })
                except (TypeError, ValueError, AttributeError):
                    continue
            return bars if len(bars) >= min_bars else None
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════
    # 2. Tick
    # ═══════════════════════════════════════════════════════════
    async def get_tick(
        self, symbol: str, days: int = 200, contract: str | None = None
    ) -> TickData:
        """获取 Tick 逐笔成交数据。"""
        eff = self._resolve_tqsdk_symbol(symbol, contract)
        df = await asyncio.to_thread(self._ticks_sync, eff, days)
        ticks: list[TickBar] = []
        try:
            for row in df.tail(min(days, len(df))).itertuples(index=False):
                try:
                    ticks.append(TickBar(
                        datetime=str(getattr(row, "datetime")),
                        last_price=float(getattr(row, "last_price", 0) or 0),
                        volume=float(getattr(row, "volume", 0) or 0),
                        open_interest=float(getattr(row, "open_interest", 0) or 0),
                    ))
                except (TypeError, ValueError, AttributeError):
                    continue
        except Exception:
            pass
        return TickData(symbol=symbol, source=self.name, ticks=ticks)

    async def get_tick_data_series(
        self, symbol: str,
        start_dt: str, end_dt: str,
        contract: str | None = None,
    ) -> dict:
        """获取指定时间段的 Tick 序列（带 TqSDK 缓存）。"""
        eff = self._resolve_tqsdk_symbol(symbol, contract)
        sd = datetime.strptime(start_dt, "%Y-%m-%d")
        ed = datetime.strptime(end_dt, "%Y-%m-%d")
        df = await asyncio.to_thread(self._tick_series_sync, eff, sd, ed)
        ticks = []
        if df is not None:
            for row in df.itertuples(index=False):
                try:
                    ticks.append({
                        "datetime": str(getattr(row, "datetime")),
                        "last_price": float(getattr(row, "last_price", 0) or 0),
                        "volume": float(getattr(row, "volume", 0) or 0),
                        "open_interest": float(getattr(row, "open_interest", 0) or 0),
                    })
                except (TypeError, ValueError, AttributeError):
                    continue
        return {"symbol": symbol, "contract": eff, "tick_count": len(ticks), "ticks": ticks}

    def _ticks_sync(self, sym: str, days: int):
        api = self._api()
        try:
            ticks = api.get_tick_serial(sym, data_length=days)
            _pump(api, ticks, min_rows=min(days, 5))
            return ticks
        finally:
            self._close_api()

    def _tick_series_sync(self, sym: str, sd: datetime, ed: datetime):
        api = self._api()
        try:
            ticks = api.get_tick_data_series(sym, start_dt=sd, end_dt=ed)
            if ticks is not None:
                _pump(api, ticks, min_rows=5)
            return ticks
        finally:
            self._close_api()

    # ═══════════════════════════════════════════════════════════
    # 3. 行情快照
    # ═══════════════════════════════════════════════════════════
    async def get_quote(self, symbol: str, contract: str | None = None) -> QuoteData:
        """获取盘口行情快照。"""
        eff = self._resolve_tqsdk_symbol(symbol, contract)
        q = await asyncio.to_thread(self._quote_sync, eff)
        return QuoteData(
            symbol=symbol, source=self.name,
            last_price=self._gf(q, "last_price") or self._gf(q, "lastPrice"),
            open=self._gf(q, "open"),
            high=self._gf(q, "highest") or self._gf(q, "high"),
            low=self._gf(q, "lowest") or self._gf(q, "low"),
            pre_close=self._gf(q, "pre_close") or self._gf(q, "preClose"),
            volume=self._gf(q, "volume"),
        )

    def _quote_sync(self, sym: str):
        api = self._api()
        try:
            return api.get_quote(sym)
        finally:
            self._close_api()

    async def query_quotes(
        self, ins_class: str | None = None, exchange_id: str | None = None,
        product_id: str | None = None, expired: bool | None = None,
        has_night: bool | None = None,
    ) -> list:
        """批量查询合约列表。"""
        return await asyncio.to_thread(
            self._query_quotes_sync, ins_class, exchange_id, product_id, expired, has_night,
        )

    def _query_quotes_sync(self, ins_class, exchange_id, product_id, expired, has_night):
        api = self._api()
        try:
            return list(api.query_quotes(
                ins_class=ins_class, exchange_id=exchange_id,
                product_id=product_id, expired=expired, has_night=has_night,
            ))
        finally:
            self._close_api()

    @staticmethod
    def _gf(obj, key: str) -> Optional[float]:
        v = obj.get(key) if hasattr(obj, "get") else getattr(obj, key, None)
        if v in (None, ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError, AttributeError):
            return None

    # ═══════════════════════════════════════════════════════════
    # 4. 合约查询
    # ═══════════════════════════════════════════════════════════
    async def query_symbol_info(self, symbol: str) -> SymbolInfo:
        """查询合约基本信息。"""
        info = await asyncio.to_thread(self._sym_info_sync, symbol)
        return SymbolInfo(symbol=symbol, source=self.name, **info)

    def _sym_info_sync(self, symbol: str) -> dict:
        api = self._api()
        try:
            df = api.query_symbol_info(self._resolve_continuous(symbol))
            if df is not None and len(df) > 0:
                row = df.iloc[0]
                return {
                    "name": str(getattr(row, "product_name", "") or ""),
                    "product_id": str(getattr(row, "product_id", "") or ""),
                    "exchange": str(getattr(row, "exchange_id", "") or ""),
                    "price_tick": float(getattr(row, "price_tick", 0) or 0),
                    "margin_rate": float(getattr(row, "margin_rate", 0) or 0),
                    "multiplier": float(getattr(row, "multiplier", 0) or 0),
                    "delivery_months": str(getattr(row, "delivery_months", "") or ""),
                    "listed_date": str(getattr(row, "listed_date", "") or ""),
                }
        except Exception:
            pass
        return {}

    async def query_cont_quotes(
        self, exchange_id: str | None = None, product_id: str | None = None,
        has_night: bool | None = None,
    ) -> list:
        """查询主力连续合约对应的标的合约列表。"""
        return await asyncio.to_thread(self._cont_quotes_sync, exchange_id, product_id, has_night)

    def _cont_quotes_sync(self, exchange_id, product_id, has_night):
        api = self._api()
        try:
            return list(api.query_cont_quotes(
                exchange_id=exchange_id, product_id=product_id, has_night=has_night,
            ))
        finally:
            self._close_api()

    async def query_his_cont_quotes(self, symbol: str, n: int = 200) -> list:
        """查询主力连续合约的历史标的切换记录。"""
        eff = self._resolve_continuous(symbol)
        df = await asyncio.to_thread(self._his_cont_sync, eff, n)
        if df is None:
            return []
        records = []
        for row in df.itertuples(index=False):
            try:
                records.append({
                    "datetime": str(getattr(row, "datetime", "")),
                    "underlying_symbol": str(getattr(row, "underlying_symbol", "") or getattr(row, "symbol", "")),
                })
            except Exception:
                continue
        return records

    def _his_cont_sync(self, sym: str, n: int):
        api = self._api()
        try:
            return api.query_his_cont_quotes(sym, n=n)
        finally:
            self._close_api()

    async def query_symbol_ranking(
        self, symbol: str, ranking_type: str = "volume",
        days: int = 1, start_dt: str | None = None,
    ) -> dict:
        """查询合约成交/持仓排名。"""
        sd = datetime.strptime(start_dt, "%Y-%m-%d") if start_dt else None
        eff = self._resolve_tqsdk_symbol(symbol)
        df = await asyncio.to_thread(self._ranking_sync, eff, ranking_type, days, sd)
        if df is None:
            return {"symbol": symbol, "rows": []}
        rows = []
        for row in df.itertuples(index=False):
            try:
                rows.append({
                    "rank": int(getattr(row, "rank", 0)),
                    "broker": str(getattr(row, "broker", "") or ""),
                    "volume": float(getattr(row, "volume", 0) or 0),
                    "long": float(getattr(row, "long", 0) or 0),
                    "short": float(getattr(row, "short", 0) or 0),
                })
            except Exception:
                continue
        return {"symbol": symbol, "rows": rows}

    def _ranking_sync(self, sym: str, rtype: str, days: int, sd):
        api = self._api()
        try:
            return api.query_symbol_ranking(sym, ranking_type=rtype, days=days, start_dt=sd)
        finally:
            self._close_api()

    async def query_symbol_settlement(
        self, symbol: str, days: int = 1, start_dt: str | None = None,
    ) -> dict:
        """查询交易所合约每日结算价。需要实际合约代码（非主力连续）。"""
        sym_upper = symbol.upper()
        ex = _EXCHANGE_MAP.get(sym_upper)
        if not ex:
            return {"symbol": symbol, "rows": []}
        sd = datetime.strptime(start_dt, "%Y-%m-%d") if start_dt else None
        # settlement 不支持 KQ.m@ 连续合约，需要实际合约代码
        # 通过 query_cont_quotes 获取当前主力标的合约
        cont_list = await self.query_cont_quotes(exchange_id=ex, product_id=sym_upper)
        if not cont_list:
            return {"symbol": symbol, "rows": []}
        actual_contract = cont_list[0]  # 取第一个作为标的
        df = await asyncio.to_thread(self._settlement_sync, actual_contract, days, sd)
        if df is None:
            return {"symbol": symbol, "rows": []}
        rows = []
        for row in df.itertuples(index=False):
            try:
                rows.append({
                    "datetime": str(getattr(row, "datetime", "")),
                    "settlement": float(getattr(row, "settlement", 0) or 0),
                    "open_interest": float(getattr(row, "open_interest", 0) or 0),
                })
            except Exception:
                continue
        return {"symbol": symbol, "contract": actual_contract, "rows": rows}

    def _settlement_sync(self, sym: str, days: int, sd):
        api = self._api()
        try:
            return api.query_symbol_settlement(sym, days=days, start_dt=sd)
        finally:
            self._close_api()

    # ═══════════════════════════════════════════════════════════
    # 4b. EDB 非价量基本面数据
    # ═══════════════════════════════════════════════════════════
    async def query_edb_index_table(
        self, ids: list[int] | None = None, search: str | None = None,
    ) -> list:
        """查询EDB指标目录（通过REST API，需专业版权限）。

        也可在 https://edb.shinnytech.com 可视化浏览。

        Returns:
            [{"id": int, "cn_name": str, "table_name": str, "frequency": str,
              "unit": str, "start_date": str, "end_date": str}, ...]
        """
        payload: dict[str, Any] = {}
        if ids is not None:
            payload["ids"] = ids
        if search is not None:
            payload["search"] = search
        return await asyncio.to_thread(self._edb_table_rest_sync, payload)

    def _edb_table_rest_sync(self, payload: dict) -> list:
        """通过REST API查询EDB指标目录。"""
        import json as _json

        try:
            from urllib.request import Request, urlopen
        except ImportError:
            return []

        token = self._get_edb_token()
        if not token:
            return []
        req = Request(
            "https://edb.shinnytech.com/data/index_table",
            data=_json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=15) as resp:
                body = _json.loads(resp.read().decode())
                if body.get("error_code") == 0:
                    return body.get("data", [])
        except Exception:
            pass
        return []

    @staticmethod
    def _get_edb_token() -> str:
        """获取EDB JWT token（通过TqSDK账户）。"""
        try:
            from urllib.request import Request, urlopen
        except ImportError:
            return ""
        user = os.environ.get("TQSDK_USERNAME") or os.environ.get("TQ_USER", "")
        pwd = os.environ.get("TQSDK_PASSWORD") or os.environ.get("TQ_PASSWORD", "")
        if not user or not pwd:
            return ""
        import json as _json

        req = Request(
            "https://edb.shinnytech.com/token",
            data=_json.dumps({"username": user, "password": pwd}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=10) as resp:
                return _json.loads(resp.read().decode()).get("token", "")
        except Exception:
            return ""

    async def query_edb_data(
        self, ids: list[int],
        start_dt: str,
        end_dt: str,
        align: str | None = None,
        fill: str | None = None,
    ) -> dict:
        """查询EDB非价量指标数值序列。

        EDB包含：
          - 库存数据（交易所库存/社会库存）
          - 现货价格（各品种现货价）
          - 仓单数据（注册仓单量）
          - 基差数据
          - 供需数据（产量/消费量/开工率）
          - 宏观指标（M2/CPI/PMI等）
          - 利润/价差数据

        Args:
            ids: 指标ID列表（1-100个），可在 https://edb.shinnytech.com 查询。
            start_dt: 起始日期 "YYYY-MM-DD"。
            end_dt: 结束日期 "YYYY-MM-DD"。
            align: 对齐方式 None(稀疏)/"day"(自然日补齐)。
            fill: 填充方式 None/ffill/bfill（仅align="day"时生效）。

        Returns:
            {"ids": [int, ...], "values": {"YYYY-MM-DD": [val, ...], ...}}
        """
        sd = date.fromisoformat(start_dt)
        ed = date.fromisoformat(end_dt)
        df = await asyncio.to_thread(self._edb_data_sync, ids, sd, ed, align, fill)
        if df is None:
            return {"ids": ids, "values": {}}
        values: dict[str, list[Optional[float]]] = {}
        for idx, row in df.iterrows():
            date_str = str(idx)
            if len(date_str) >= 10:
                date_str = date_str[:10]
            values[date_str] = [None if pd_isna(v) else float(v) for v in row]
        return {"ids": ids, "values": values}

    def _edb_data_sync(self, ids, sd, ed, align, fill):
        api = self._api()
        try:
            return api.query_edb_data(ids=ids, start_dt=sd, end_dt=ed, align=align, fill=fill)
        except AttributeError:
            return None
        finally:
            self._close_api()

    # ═══════════════════════════════════════════════════════════
    # 5. 交易
    # ═══════════════════════════════════════════════════════════
    async def get_account(self) -> dict:
        """获取账户资金信息。"""
        return await asyncio.to_thread(self._account_sync)

    def _account_sync(self) -> dict:
        api = self._api()
        try:
            acct = api.get_account()
            return {
                "balance": float(getattr(acct, "balance", 0) or 0),
                "available": float(getattr(acct, "available", 0) or 0),
                "frozen": float(getattr(acct, "frozen", 0) or 0),
                "margin": float(getattr(acct, "margin", 0) or 0),
                "profit": float(getattr(acct, "profit", 0) or 0),
            }
        finally:
            self._close_api()

    async def get_position(self, symbol: str | None = None) -> list:
        """获取持仓信息。"""
        return await asyncio.to_thread(self._position_sync, symbol)

    def _position_sync(self, symbol):
        api = self._api()
        try:
            pos = api.get_position(symbol=symbol)
            if hasattr(pos, "keys") and callable(pos.keys):
                results = []
                for k in pos.keys():
                    p = pos[k]
                    results.append({
                        "symbol": str(getattr(p, "symbol", "")),
                        "volume": int(getattr(p, "volume", 0) or 0),
                        "position": str(getattr(p, "position", "")),
                        "cost_price": float(getattr(p, "cost_price", 0) or 0),
                        "float_profit": float(getattr(p, "float_profit", 0) or 0),
                    })
                return results
            return []
        finally:
            self._close_api()

    async def insert_order(
        self, symbol: str, direction: str, volume: int,
        offset: str = "", limit_price: float | None = None,
    ) -> str:
        """下单。返回 order_id。"""
        eff = self._resolve_tqsdk_symbol(symbol)
        return await asyncio.to_thread(
            self._insert_order_sync, eff, direction, offset, volume, limit_price,
        )

    def _insert_order_sync(self, sym, direction, offset, volume, limit_price):
        api = self._api()
        try:
            order = api.insert_order(sym, direction=direction, offset=offset,
                                     volume=volume, limit_price=limit_price)
            return str(getattr(order, "order_id", ""))
        finally:
            self._close_api()

    async def cancel_order(self, order_id: str) -> None:
        """撤单。"""
        await asyncio.to_thread(self._cancel_order_sync, order_id)

    def _cancel_order_sync(self, order_id):
        api = self._api()
        try:
            api.cancel_order(order_id)
        finally:
            self._close_api()

    async def get_order(self, order_id: str | None = None) -> list:
        """查询委托单。"""
        return await asyncio.to_thread(self._order_sync, order_id)

    def _order_sync(self, order_id):
        api = self._api()
        try:
            order = api.get_order(order_id=order_id)
            if hasattr(order, "keys") and callable(order.keys):
                results = []
                for k in order.keys():
                    o = order[k]
                    results.append({
                        "order_id": str(getattr(o, "order_id", "")),
                        "symbol": str(getattr(o, "symbol", "")),
                        "direction": str(getattr(o, "direction", "")),
                        "volume_orign": int(getattr(o, "volume_orign", 0) or 0),
                        "volume_left": int(getattr(o, "volume_left", 0) or 0),
                        "limit_price": float(getattr(o, "limit_price", 0) or 0),
                        "status": str(getattr(o, "status", "")),
                    })
                return results
            return []
        finally:
            self._close_api()

    async def get_trade(self, trade_id: str | None = None) -> list:
        """查询成交记录。"""
        return await asyncio.to_thread(self._trade_sync, trade_id)

    def _trade_sync(self, trade_id):
        api = self._api()
        try:
            trade = api.get_trade(trade_id=trade_id)
            if hasattr(trade, "keys") and callable(trade.keys):
                results = []
                for k in trade.keys():
                    t = trade[k]
                    results.append({
                        "trade_id": str(getattr(t, "trade_id", "")),
                        "symbol": str(getattr(t, "symbol", "")),
                        "direction": str(getattr(t, "direction", "")),
                        "volume": int(getattr(t, "volume", 0) or 0),
                        "price": float(getattr(t, "price", 0) or 0),
                    })
                return results
            return []
        finally:
            self._close_api()

    # ═══════════════════════════════════════════════════════════
    # 6. 工具
    # ═══════════════════════════════════════════════════════════
    async def is_serial_ready(self) -> bool:
        """判断是否已从服务器收到所有订阅数据。"""
        return await asyncio.to_thread(self._is_ready_sync)

    def _is_ready_sync(self) -> bool:
        api = self._api()
        try:
            kline = api.get_kline_serial("KQ.m@SHFE.cu", 86400, data_length=1)
            return api.is_serial_ready(kline)
        except Exception:
            return False
        finally:
            self._close_api()
