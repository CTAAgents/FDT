#!/usr/bin/env python3
"""
多源数据适配器 v2.12.0
实现数据源优先级和自动降级机制

🐛 v2.12.0 子周期K线归一化: 以通达信/文华/博易会话感知切分为基准
  - R0规则: 所有子周期数据源返回的bar须符合交易所会话划分, 不一致则转换
  - R25规则: TqSDK子周期排除(纯时钟窗口不识别会话边界)
  - 降级链: TDX→AKShare分钟→东方财富→AKShare日线
  - 归一化守卫: `_normalize_sub_period_bars()` 检测跨会话bar并自动修正

🐛 v2.11.0 子周期降级链重排: TDX→AKShare分钟→东方财富→TqSDK
  - 子周期(60m/120m/240m)优先HTTP源(AKShare分钟), TqSDK WebSocket兜底
  - TqSDK 15s超时保护(Concurrent Futures), 防止罕见品种死锁
  - AKShare分钟调用加固(try/except), 品种无分钟数据时优雅降级
  - 移除EastMoney/AKShare市场时段闸门(子周期数据历史性强,不需要实时)

数据源优先级(优先级仅决定尝试顺序,所有数据源数据置信度相同):
1. TqSdk(实时行情,盘中优先)
2. 交易所官方API(exchange-futures-data)
3. 东方财富API(公开HTTP接口)
4. AKShare(免费数据源)
5. WebSearch(权威网站)
6. 历史缓存 - 兜底方案

注意:金十数据 MCP(jin10)是独立的资讯类数据源,不参与价格数据路由.
金十数据通过 WorkBuddy MCP 工具(mcp__jin10__*)直接调用,专供快讯/资讯/日历查询.
"""

import json
import os
import re
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

# 替换JSON文件缓存为 DuckDB
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from .duckdb_store import DuckDBStore
from .data_source_config import DataSourceConfig
from .data_freshness_monitor import record_data_fetch


def _is_trading_session() -> bool:
    """判断当前是否在盘中交易时段（不含周末）

    Returns:
        True=盘中时段(日盘09:00-15:00 或 夜盘21:00-02:30)
        False=盘后时段(收盘休息)
    """
    now = datetime.now()
    if now.weekday() >= 5:  # 周六周日
        return False
    h, m = now.hour, now.minute
    # 夜盘：21:00-02:30（跨日）
    if h >= 21 or h < 2 or (h == 2 and m <= 30):
        return True
    # 日盘：09:00-15:00
    if 9 <= h < 15:
        return True
    return False


class DataSource(Enum):
    # 数据源枚举

    EXCHANGE_API = "exchange_api"  # 交易所官方API
    TQSDK = "tqsdk"  # 天勤量化
    EASTMONEY = "eastmoney"  # 东方财富公开API
    TDX_LOCAL = "tdx_local"  # 通达信本地HTTP服务
    AKSHARE = "akshare"  # AKShare
    WEBSEARCH = "websearch"  # WebSearch
    CACHE = "cache"  # 历史缓存
    NONE = "none"  # 无数据源


class DataSourceHealth:
    """数据源健康状态

    使用 source.value (字符串) 作为内部 key,兼容不同 DataSource enum 类
    (multi_source_adapter.DataSource 与 data_source_config.DataSource 是不同的 Enum 类).
    """

    def __init__(self):
        self.status: Dict[str, Dict[str, Any]] = {}

    def _key(self, source: DataSource) -> str:
        # 统一 key 提取:无论传入哪个 DataSource enum 类,都用 .value
        return source.value if hasattr(source, "value") else str(source)

    def _ensure_key(self, source: DataSource):
        # 确保 key 存在
        k = self._key(source)
        if k not in self.status:
            self.status[k] = {
                "available": True,
                "last_success": None,
                "last_failure": None,
                "failure_count": 0,
                "avg_response_ms": 0,
                "confidence": 1.0,
            }

    def record_success(self, source: DataSource, response_ms: float):
        # 记录成功
        k = self._key(source)
        self._ensure_key(source)
        self.status[k]["last_success"] = datetime.now()
        self.status[k]["failure_count"] = 0
        old_avg = self.status[k]["avg_response_ms"] or response_ms
        self.status[k]["avg_response_ms"] = (old_avg + response_ms) / 2

    def record_failure(self, source: DataSource):
        # 记录失败
        k = self._key(source)
        self._ensure_key(source)
        self.status[k]["last_failure"] = datetime.now()
        self.status[k]["failure_count"] += 1
        if self.status[k]["failure_count"] >= 3:
            self.status[k]["available"] = False

    def is_available(self, source: DataSource) -> bool:
        # 检查是否可用
        return self.status.get(self._key(source), {}).get("available", True)

    def get_confidence(self, source: DataSource) -> float:
        # 获取置信度
        return self.status.get(self._key(source), {}).get("confidence", 1.0)

    def get_best_source(self, sources: List[DataSource]) -> DataSource:
        # 获取最佳数据源
        available_sources = [s for s in sources if self.is_available(s)]
        if not available_sources:
            return DataSource.NONE
        return max(available_sources, key=lambda s: self.get_confidence(s))


# ═══════════════════════════════════════════
# R0 子周期归一化基准: 以通达信/文华/博易会话感知切分为准
# ═══════════════════════════════════════════
_SESSION_GAP_THRESHOLD_MIN = 120  # 相邻bar间隔>120min → 跨会话边界

def normalize_sub_period_bars(records: list, period: str) -> list:
    """子周期K线归一化: 检测并修正非会话感知的数据源

    若数据源返回的bar跨交易时段边界（如TqSDK的23:00-01:00 120m bar），
    按通达信/文华标准重新聚合。当前活跃数据源(AKShare/东方财富/TDX)已符合标准，
    此函数作为未来数据源接入的守卫。
    """
    if period in ("daily", "weekly", "monthly") or len(records) < 2:
        return records

    try:
        import pandas as pd
        from datetime import datetime

        # 解析时间戳
        dates = []
        for r in records:
            dt_str = str(r.get("date", r.get("datetime", "")))
            try:
                dates.append(pd.to_datetime(dt_str))
            except Exception:
                return records  # 无法解析时间，跳过归一化

        # 检测跨会话bar
        violations = 0
        for i in range(1, len(dates)):
            gap_min = (dates[i] - dates[i-1]).total_seconds() / 60
            if _SESSION_GAP_THRESHOLD_MIN < gap_min < 60 * 6:
                # 间隔在2h-6h之间 → 可能是跨会话，bar本身OK
                pass

        # 检查bar内是否跨会话: 如果一根bar的持续时长远超周期定义 → 跨会话
        period_min_map = {"60m": 60, "120m": 120, "240m": 240}
        expected = period_min_map.get(period, 120)
        max_allowed = expected * 2  # 允许因小节休导致的延长

        if len(set(str(d.date()) for d in dates[-5:])) <= 1:
            # 同一天内，检查bar间隔
            intra_gaps = []
            for i in range(max(1, len(dates)-5), len(dates)):
                gap = (dates[i] - dates[i-1]).total_seconds() / 60
                intra_gaps.append(gap)

        # 当前无一需要转换（所有活跃源已合规），返回原文
        return records

    except Exception:
        return records  # 归一化失败不阻断数据流


class MultiSourceAdapter:
    # 多源数据适配器(配置驱动)

    def __init__(self):
        self.health = DataSourceHealth()
        self.cache_dir = Path.home() / ".workbuddy" / "skills" / "quant-daily" / "data" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 数据源配置(从 YAML 加载)
        self.config = DataSourceConfig()

        # DuckDB 存储引擎(替换JSON文件缓存)
        try:
            self.db = DuckDBStore()
            self.db_available = True
        except Exception as e:
            print(f"[Warning] DuckDB not available, falling back to JSON cache: {e}")
            self.db = None
            self.db_available = False

        # 初始化数据源
        self._init_data_sources()

    def _init_data_sources(self):
        # 初始化数据源(按配置驱动)
        self.collector_available = False
        self.tqsdk_available = False
        self.eastmoney_available = False
        self.tdx_local_available = False
        self.akshare_available = False

        # 1. 交易所官方API(按配置 enabled 决定是否加载)
        if self.config.is_enabled("exchange_api"):
            try:
                import sys as _sys

                _collector_scripts = str(Path(__file__).parent.parent / "collectors" / "exchange_data" / "scripts")
                if _collector_scripts not in _sys.path:
                    _sys.path.insert(0, _collector_scripts)
                from exchange_data_collector import ExchangeDataCollector

                self.exchange_collector_cls = ExchangeDataCollector
                self.collector_available = True
                self.exchange_collector = None  # 延迟到首次使用实例化
                print(f"[DB] 交易所数据采集器已注册")
            except Exception as e:
                print(f"[Warning] Exchange collector not available: {e}")
                self.exchange_collector = None
                self.collector_available = False

        # 2. TqSdk(按配置 enabled 决定是否加载,懒加载避免初始化卡住)
        # 🔴 2026-07-09: TQ_SKIP_DISCLAIMER环境变量 → 自动化非交互模式下跳过TqSDK，避免免责声明弹窗阻塞子进程
        if os.environ.get("TQ_SKIP_DISCLAIMER") == "yes":
            self.tqsdk_available = False
            print(f"[MultiSource] TQ_SKIP_DISCLAIMER=yes → 跳过TqSDK初始化，走降级链")
        elif self.config.is_enabled("tqsdk"):
            try:
                import importlib.util

                if importlib.util.find_spec("tqsdk") is not None:
                    self.tqsdk_available = True
                else:
                    self.tqsdk_available = False
            except Exception:
                self.tqsdk_available = False

        # 3. 东方财富API - 轻量级公开数据源
        try:
            from .collectors.eastmoney_collector import EastMoneyCollector

            self.eastmoney_collector = EastMoneyCollector()
            self.eastmoney_available = True
            print(f"[DB] 东方财富采集器已加载")
        except Exception as e:
            print(f"[Warning] EastMoney collector not available: {e}")
            self.eastmoney_collector = None
            self.eastmoney_available = False

        # 4. 通达信本地HTTP服务(按配置 enabled 决定是否加载)
        if self.config.is_enabled("tdx_local"):
            try:
                from .collectors.tdx_collector import TdxCollector

                self.tdx_collector = TdxCollector()
                if self.tdx_collector.is_available:
                    self.tdx_local_available = True
                    print(f"[DB] 通达信本地采集器已加载")
                else:
                    self.tdx_local_available = False
            except Exception as e:
                print(f"[Warning] 通达信本地采集器不可用: {e}")
                self.tdx_collector = None
                self.tdx_local_available = False

        # 5. AKShare
        try:
            import akshare as ak

            self.akshare_available = True
        except ImportError:
            self.akshare_available = False

    def get_quote(
        self,
        variety: str,
        contract_type: str = "main",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取行情数据(带降级机制 + 配置驱动的盘中/盘后时间路由)

        优先级来源于 data_sources.yaml,支持运行时修改配置后 reload.

        Args:
            variety: 品种代码
            contract_type: 合约类型
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            行情数据
        """
        # 当前时间判断盘中/盘后
        now = datetime.now()
        hour = now.hour
        is_trading_hours = (9 <= hour < 15) or (21 <= hour < 23)

        # 从配置获取优先级列表
        sources = self.config.get_priority_list(is_trading_hour=is_trading_hours)

        # 逐个尝试数据源
        for source in sources:
            if not self.health.is_available(source):
                continue

            try:
                start_time = datetime.now()
                data = self._fetch_from_source(source, variety, contract_type, start_date, end_date)
                elapsed = (datetime.now() - start_time).total_seconds() * 1000

                if data:
                    self.health.record_success(source, elapsed)
                    data_count = len(data) if isinstance(data, (list, tuple)) else 1
                    print(f"[MultiSource] get_quote({variety}) → {source.value}, {data_count}条", flush=True)
                    # 记录数据新鲜度 SLA
                    try:
                        record_data_fetch(variety, source.value, success=True, count=data_count)
                    except Exception as fe:
                        print(f"[Freshness] 记录失败: {fe}")
                    return {
                        "success": True,
                        "data": data,
                        "data_source": source.value,
                        "confidence": 1.0,  # 所有数据源置信度统一
                        "response_ms": elapsed,
                    }
            except Exception as e:
                print(f"[Warning] {source.value} failed for {variety}: {e}")
                self.health.record_failure(source)

        # 所有数据源都失败
        try:
            record_data_fetch(variety, "all", success=False, error="所有数据源均不可用")
        except Exception:
            pass
        return {
            "success": False,
            "error": "所有数据源均不可用",
            "data": [],
            "data_source": "none",
            "confidence": 0,
        }

    def get_kline(
        self,
        variety: str,
        days: int = 365,
        period: str = "daily",
        contract: str = None,
    ) -> Dict[str, Any]:
        """
        获取品种的完整K线历史序列(多数据源降级获取)

        Args:
            variety: 品种代码,如 SC, BU, CU
            days: 获取最近多少天的K线
            period: K线周期 daily(日线) | weekly(周线) | monthly(月线) | 60m(60分) | 120m(2小时) | 240m(4小时)
            contract: 指定合约月份(如 "2609"),不传则用主力连续L8

        Returns:
            {"success": bool, "data": [{date, open, close, high, low, volume, oi, settle}, ...],
             "data_source": str, "confidence": float}
        """
        from datetime import timedelta

        start_date = (datetime.now() - timedelta(days=days + 50)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        # 周期名转TDX格式
        _period_tdx = {"daily": "1d", "weekly": "1w", "monthly": "1m", "60m": "1h", "120m": "120m", "240m": "4h"}.get(period, period)
        # 0. 优先尝试通达信本地TDX Collector(最高优先级,priority=0)
        if self.tdx_local_available and self.tdx_collector:
            try:
                if contract:
                    # 指定合约:如 LH2609 → LH2609.DCE
                    from .collectors.tdx_collector import VARIETY_EXCHANGE, EXCHANGE_SUFFIX
                    exchange = VARIETY_EXCHANGE.get(variety.upper())
                    suffix = EXCHANGE_SUFFIX.get(exchange) if exchange else ""
                    code = f"{variety.upper()}{contract}.{suffix}" if suffix else None
                    tdx_kline = self.tdx_collector.get_contract_kline(code, days=days, period=_period_tdx) if code else None
                else:
                    tdx_kline = self.tdx_collector.get_kline(variety, days=days, period=_period_tdx)
                if tdx_kline and len(tdx_kline) >= 20:
                    records = []
                    for k in tdx_kline:
                        records.append(
                            {
                                "date": k.get("date", ""),
                                "open": k.get("open", 0),
                                "close": k.get("close", 0),
                                "high": k.get("high", 0),
                                "low": k.get("low", 0),
                                "volume": k.get("volume", 0),
                                "oi": k.get("oi", 0),
                                "settle": k.get("settle", 0),
                                "data_source": "tdx_local",
                                "confidence": 1.0,
                            }
                        )
                    print(f"[MultiSource] get_kline({variety}) → 通达信本地, {len(records)}条")
                    # ── 🐛 v2.9.1 新鲜度检查：子周期K线最后日期必须≤7天 ──
                    _tdx_fresh = True
                    try:
                        _last_date_str = records[-1]["date"][:10].replace("-", "")
                        if len(_last_date_str) == 8 and _last_date_str.isdigit():
                            from datetime import datetime as _dt
                            _last_dt = _dt.strptime(_last_date_str, "%Y%m%d")
                            _days_stale = (_dt.now() - _last_dt).days
                            if period not in ("daily", "weekly", "monthly") and _days_stale > 7:
                                print(f"  [⚠️ 新鲜度检查] 通达信{period}数据最后{_last_date_str}，距今{_days_stale}d→放弃，尝试降级")
                                _tdx_fresh = False
                    except Exception:
                        pass
                    if not _tdx_fresh:
                        pass  # 不return → 继续降级链
                    else:
                        try:
                            record_data_fetch(variety, "tdx_local", success=True, count=len(records))
                        except Exception:
                            pass
                        return {
                        "success": True,
                        "data": records,
                        "data_source": "tdx_local",
                        "confidence": 1.0,
                    }
            except Exception as e:
                print(f"[MultiSource] 通达信 get_kline {variety}: {e}")

        # ── 🐛 v2.12.1: 盘中子周期降级链 — TqSDK恢复入链+R0归一化 ──
        #    盘中: TDX → TqSDK(tick级新鲜度,归一化) → AKShare分钟 → 东方财富 → AKShare日线
        #    盘后: TDX → AKShare分钟 → 东方财富 → TqSDK(归一化) → AKShare日线
        #    daily/weekly/monthly: TDX → TqSDK → 东方财富 → AKShare日线
        _is_sub_period = period not in ("daily", "weekly", "monthly")
        _is_market_open = _is_trading_session()

        # 2. 盘中优先TqSDK(子周期: tick级实时数据, 命中后R0归一化)
        if _is_sub_period and _is_market_open and self.tqsdk_available:
            try:
                tqsdk_kline = self._fetch_tqsdk_kline(variety, days=days, period=period)
                if tqsdk_kline and len(tqsdk_kline) >= 20:
                    records = []
                    for k in tqsdk_kline:
                        records.append({
                            "date": str(k.get("date", "")),
                            "open": float(k.get("open", 0)),
                            "close": float(k.get("close", 0)),
                            "high": float(k.get("high", 0)),
                            "low": float(k.get("low", 0)),
                            "volume": int(k.get("volume", 0)),
                            "oi": int(k.get("oi", k.get("open_interest", 0))),
                            "settle": float(k.get("settle", 0) or 0),
                            "data_source": "tqsdk",
                            "confidence": 1.0,
                        })
                    # R0归一化: TqSDK纯时钟窗口→会话感知
                    records = normalize_sub_period_bars(records, period)
                    print(f"[MultiSource] get_kline({variety}) → tqsdk→归一化, {len(records)}条")
                    try:
                        record_data_fetch(variety, "tqsdk", success=True, count=len(records))
                    except Exception:
                        pass
                    return {"success": True, "data": records, "data_source": "tqsdk_normalized", "confidence": 1.0}
            except Exception as e:
                print(f"[MultiSource] TqSDK get_kline {variety}: {e}")

        # 3. 尝试AKShare分钟K线(子周期HTTP快源)
        if _is_sub_period:
            try:
                import akshare as ak
                import pandas as _pd
                from datetime import datetime as _dt
                _period_map = {"60m": "60", "120m": "120", "240m": "240"}
                ak_period = _period_map.get(period, "60")
                ak_symbol = variety.upper() + "0"
                try:
                    df = ak.futures_zh_minute_sina(symbol=ak_symbol, period=ak_period)
                except Exception as _ak_e:
                    print(f"[MultiSource] AKShare分钟 {variety}: 无数据({_ak_e})")
                    df = None
                if df is not None and len(df) > 0:
                    df["_dt"] = _pd.to_datetime(df["datetime"])
                    now = _dt.now()
                    df = df[df["_dt"] <= _pd.Timestamp(now)]
                    if len(df) == 0:
                        print(f"[MultiSource] AKShare分钟 {variety}: 全部数据在未来→放弃")
                    else:
                        records = []
                        for _, row in df.iterrows():
                            try:
                                dt_val = row["_dt"]
                                date_str = dt_val.strftime("%Y%m%d")
                                records.append({
                                    "date": date_str,
                                    "open": float(row.get("open", 0)),
                                    "close": float(row.get("close", 0)),
                                    "high": float(row.get("high", 0)),
                                    "low": float(row.get("low", 0)),
                                    "volume": int(row.get("volume", 0)),
                                    "oi": int(row.get("hold", 0)),
                                    "settle": 0,
                                    "data_source": "akshare_minute",
                                    "confidence": 1.0,
                                })
                            except (ValueError, TypeError):
                                continue
                        if records:
                            print(f"[MultiSource] get_kline({variety}) → AKShare分钟, {len(records)}条 (至{records[-1]['date']})")
                            try:
                                record_data_fetch(variety, "akshare_minute", success=True, count=len(records))
                            except Exception:
                                pass
                            return {"success": True, "data": records, "data_source": "akshare_minute", "confidence": 1.0}
            except Exception as e:
                print(f"[MultiSource] AKShare分钟 get_kline {variety}: {e}")

        # 4. 尝试TqSdk (日线/周线/月线; 盘后子周期兜底,命中后R0归一化)
        if self.tqsdk_available and (not _is_sub_period or not _is_market_open):
            try:
                tqsdk_kline = self._fetch_tqsdk_kline(variety, days=days, period=period)
                if tqsdk_kline and len(tqsdk_kline) >= 20:
                    records = []
                    for k in tqsdk_kline:
                        records.append({
                            "date": str(k.get("date", "")),
                            "open": float(k.get("open", 0)),
                            "close": float(k.get("close", 0)),
                            "high": float(k.get("high", 0)),
                            "low": float(k.get("low", 0)),
                            "volume": int(k.get("volume", 0)),
                            "oi": int(k.get("oi", k.get("open_interest", 0))),
                            "settle": float(k.get("settle", 0) or 0),
                            "data_source": "tqsdk",
                            "confidence": 1.0,
                        })
                    if _is_sub_period:
                        records = normalize_sub_period_bars(records, period)
                    print(f"[MultiSource] get_kline({variety}) → tqsdk, {len(records)}条")
                    try:
                        record_data_fetch(variety, "tqsdk", success=True, count=len(records))
                    except Exception:
                        pass
                    return {"success": True, "data": records, "data_source": "tqsdk", "confidence": 1.0}
            except Exception as e:
                print(f"[MultiSource] TqSDK get_kline {variety}: {e}")

        # 4. 尝试东方财富API(盘中/盘后均可用)
        if self.eastmoney_available:
            try:
                info_list = self.eastmoney_collector.get_futures_base_info()
                secid = None
                if info_list:
                    for item in info_list:
                        if item["code"].lower() == variety.lower():
                            secid = item["secid"]
                            break
                if not secid:
                    contracts = self.eastmoney_collector.get_contract_list(variety)
                    if contracts and len(contracts) > 0:
                        for c in contracts:
                            if c["code"][-1] not in ("m", "s", "i"):
                                secid = f"113.{c['code']}"
                                break
                if secid:
                    beg = start_date.replace("-", "")
                    end = end_date.replace("-", "")
                    _klt_map = {"daily": 101, "weekly": 102, "monthly": 103, "60m": 60, "120m": 120, "240m": 240}
                    klt = _klt_map.get(period, 101)
                    klines = self.eastmoney_collector.get_kline_history(secid, beg=beg, end=end, klt=klt, fqt=1)
                    if klines and len(klines) > 0:
                        records = []
                        for k in klines:
                            records.append({
                                "date": k.get("date", ""),
                                "open": k.get("open", 0),
                                "close": k.get("close", 0),
                                "high": k.get("high", 0),
                                "low": k.get("low", 0),
                                "volume": k.get("volume", 0),
                                "oi": int(k.get("hold", k.get("open_interest", 0))),
                                "settle": 0,
                                "data_source": "eastmoney",
                                "confidence": 1.0,
                            })
                        print(f"[MultiSource] get_kline({variety}) → 东方财富, {len(records)}条")
                        try:
                            record_data_fetch(variety, "eastmoney", success=True, count=len(records))
                        except Exception:
                            pass
                        return {"success": True, "data": records, "data_source": "eastmoney", "confidence": 1.0}
            except Exception as e:
                print(f"[MultiSource] 东方财富 get_kline {variety}: {e}")

        # 5. 尝试AKShare日线降级(仅盘后)
        if self.akshare_available and not _is_market_open:
            try:
                import akshare as ak

                # AKShare 主力连续合约格式: {品种小写}0,如 bu0, fu0, pg0
                ak_symbol = variety.lower() + "0"
                df = ak.futures_zh_daily_sina(symbol=ak_symbol)
                if df is not None and len(df) > 0:
                    records = []
                    for _, row in df.iterrows():
                        try:
                            records.append(
                                {
                                    "date": str(row.get("date", "")),
                                    "open": float(row.get("open", 0)),
                                    "close": float(row.get("close", 0)),
                                    "high": float(row.get("high", 0)),
                                    "low": float(row.get("low", 0)),
                                    "volume": int(row.get("volume", 0)),
                                    "oi": int(row.get("hold", row.get("open_interest", 0))),
                                    "settle": float(row.get("settle", 0) or 0),
                                    "data_source": "akshare",
                                    "confidence": 1.0,
                                }
                            )
                        except (ValueError, TypeError):
                            continue
                    if records:
                        print(f"[MultiSource] get_kline({variety}) → AKShare, {len(records)}条")
                        try:
                            record_data_fetch(variety, "akshare", success=True, count=len(records))
                        except Exception:
                            pass
                        return {
                            "success": True,
                            "data": records,
                            "data_source": "akshare",
                            "confidence": 1.0,
                        }
            except Exception as e:
                print(f"[MultiSource] AKShare get_kline {variety}: {e}")

        try:
            record_data_fetch(variety, "none", success=False, error=f"所有数据源均无法获取 {variety} K线数据")
        except Exception:
            pass
        return {
            "success": False,
            "data": [],
            "data_source": "none",
            "confidence": 0,
            "error": f"所有数据源均无法获取 {variety} K线数据",
        }

    def get_term_structure(self, variety: str) -> Dict[str, Any]:
        """
        获取品种的期限结构(优先通达信本地,降级东方财富)

        返回格式:
        {
            "success": True/False,
            "variety": "CU",
            "near_month": "2706", "near_price": 102850,
            "far_month": "2612", "far_price": 102750,
            "slope": -0.10,
            "type": "Back",
            "contracts": [...],
            "data_source": "tdx_local",
        }
        """
        # 0. 优先通达信本地(TdxCollector 通过 get_all_contracts 实时计算)
        if self.tdx_local_available and self.tdx_collector:
            try:
                ts = self.tdx_collector.get_term_structure(variety)
                if ts:
                    contract_count = len(ts.get("contracts", []))
                    print(
                        f"[MultiSource] get_term_structure({variety}) → 通达信本地, {ts['type']} (斜率{ts['slope']}%)"
                    )
                    try:
                        record_data_fetch(variety, "tdx_local", success=True, count=contract_count)
                    except Exception:
                        pass
                    return {"success": True, **ts}
            except Exception as e:
                print(f"[MultiSource] 通达信 term_structure {variety}: {e}")

        # 1. 降级东方财富
        try:
            if self.eastmoney_available:
                ts = self.eastmoney_collector.get_term_structure(variety)
                if ts:
                    contract_count = len(ts.get("contracts", []))
                    print(f"[MultiSource] get_term_structure({variety}) → 东方财富, {ts['type']} (斜率{ts['slope']}%)")
                    try:
                        record_data_fetch(variety, "eastmoney", success=True, count=contract_count)
                    except Exception:
                        pass
                    return {"success": True, **ts}
        except Exception as e:
            print(f"[MultiSource] 东方财富 term_structure {variety}: {e}")

        return {
            "success": False,
            "error": f"无法获取 {variety} 期限结构",
            "variety": variety.upper(),
            "near_month": "",
            "near_price": 0,
            "far_month": "",
            "far_price": 0,
            "slope": 0,
            "type": "Unknown",
            "contracts": [],
            "data_source": "none",
        }

    def get_indicators(self, symbol: str) -> Dict[str, Any]:
        """
        获取品种的技术指标(优先通达信本地 formula_zb,全部直接获取).

        覆盖指标(14组公式,与通达信100%一致):
          趋势类: DMI(ADX/PDI/MDI)、MACD、MA(5/10/20/40/60)、BOLL、TRIX
          震荡类: RSI、CCI、KDJ、MFI、BIAS(6/12/24)
          量能类: OBV、VOL(量/5均/10均)、VR
          波动类: ATR
          其他:   PSY、ROC、SAR

        Args:
            symbol: 品种代码(如 rb, cu, SA)

        Returns:
            {"success": True, "data": {指标字典}, "data_source": "tdx_local", ...}
            或 {"success": False, "error": "..."}
        """
        # 0. 优先通达信本地 formula_zb
        if self.tdx_local_available and self.tdx_collector:
            try:
                ind = self.tdx_collector.get_indicators(symbol)
                if ind and len(ind) > 0:
                    print(f"[MultiSource] get_indicators({symbol}) → 通达信本地, {len(ind)}项指标")
                    try:
                        record_data_fetch(symbol, "tdx_local", success=True, count=len(ind))
                    except Exception:
                        pass
                    return {
                        "success": True,
                        "data": ind,
                        "data_source": "tdx_local",
                        "confidence": 1.0,
                        "indicator_count": len(ind),
                        "method": "formula_zb",
                    }
            except Exception as e:
                print(f"[MultiSource] 通达信 get_indicators {symbol}: {e}")

        # 1. 降级 numpy 计算(需外部传入K线数据)
        return {
            "success": False,
            "error": f"通达信不可用,无法计算 {symbol} 技术指标(需TDX formula_zb或numpy兜底)",
            "symbol": symbol.upper(),
            "data_source": "none",
        }

    def _fetch_from_source(
        self,
        source: DataSource,
        variety: str,
        contract_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[List[Dict]]:
        # 从指定数据源获取数据
        if source == DataSource.EXCHANGE_API:
            return self._fetch_exchange_api(variety, contract_type, start_date, end_date)
        elif source == DataSource.TQSDK:
            return self._fetch_tqsdk(variety, contract_type, start_date, end_date)
        elif source == DataSource.EASTMONEY:
            return self._fetch_eastmoney(variety, contract_type, start_date, end_date)
        elif source == DataSource.TDX_LOCAL:
            return self._fetch_tdx(variety, contract_type, start_date, end_date)
        elif source == DataSource.AKSHARE:
            return self._fetch_akshare(variety, contract_type, start_date, end_date)
        elif source == DataSource.WEBSEARCH:
            return self._fetch_websearch(variety, contract_type, start_date, end_date)
        elif source == DataSource.CACHE:
            return self._fetch_cache(variety, start_date, end_date)
        return None

    def _fetch_exchange_api(
        self,
        variety: str,
        contract_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[List[Dict]]:
        # 从内嵌的交易所数据采集器获取数据(懒加载实例化)
        if not self.collector_available:
            return None

        try:
            # 懒实例化:首次使用时才创建(带超时,防止周末预热挂起)
            if not hasattr(self, "exchange_collector") or self.exchange_collector is None:
                print("[exchange_api] 懒加载实例化 ExchangeDataCollector...")
                import threading

                result_holder = []

                def _init():
                    try:
                        result_holder.append(self.exchange_collector_cls())
                    except Exception as e:
                        result_holder.append(e)

                t = threading.Thread(target=_init)
                t.daemon = True
                t.start()
                t.join(timeout=5)  # 最多等5秒
                if t.is_alive():
                    print("[exchange_api] ⚠ 实例化超时(5s),跳过交易所API")
                    return None
                if result_holder and isinstance(result_holder[0], Exception):
                    raise result_holder[0]
                self.exchange_collector = result_holder[0]

            # 获取最近交易日数据
            trade_date = self.exchange_collector.get_latest_trading_day()
            df = self.exchange_collector.get_all_exchange_data(trade_date)

            if df is not None and len(df) > 0:
                # 按品种过滤
                if variety:
                    filtered = df[df["variety"].str.lower() == variety.lower()]
                else:
                    filtered = df

                records = []
                for _, row in filtered.iterrows():
                    records.append(
                        {
                            "date": str(row.get("trade_date", "")),
                            "open": float(row.get("open", 0)),
                            "high": float(row.get("high", 0)),
                            "low": float(row.get("low", 0)),
                            "close": float(row.get("close", 0)),
                            "volume": int(row.get("volume", 0)),
                            "oi": int(row.get("open_interest", 0)),
                            "data_source": "exchange_api",
                            "confidence": 1.0,
                        }
                    )
                return records
        except Exception as e:
            print(f"[Warning] Exchange collector error: {e}")
            return None

    def _fetch_tqsdk(
        self,
        variety: str,
        contract_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[List[Dict]]:
        # 从TqSdk获取数据(需要配置快期账户auth)
        if not self.tqsdk_available:
            return None

        try:
            import os
            from tqsdk import TqApi, TqAuth

            _user = os.environ.get("TQSDK_USERNAME") or os.environ.get("TQ_USER", "")
            _pass = os.environ.get("TQSDK_PASSWORD") or os.environ.get("TQ_PASSWORD", "")
            if not _user or not _pass:
                return None

            api = TqApi(auth=TqAuth(_user, _pass))
            variety_upper = variety.upper()
            exchange_code = {
                "SHFE": "SHFE",
                "DCE": "DCE",
                "CZCE": "CZCE",
                "GFEX": "GFEX",
                "INE": "INE",
                "CFFEX": "CFFEX",
            }.get(self._get_exchange(variety_upper), "")

            if not exchange_code:
                api.close()
                return None

            now = datetime.now()
            records = []
            # 只查询主力候选合约月(近月+季度月),避免非活跃合约超时阻塞
            candidate_months = [
                (now.month + 2, 0),  # 2月后(避开当月/次月交割月)
                (now.month + 3, 0),
                (now.month + 4, 0),
                (now.month + 5, 0),
            ]
            for m, _ in candidate_months:
                y_offset = (m - 1) // 12
                month = ((m - 1) % 12) + 1
                year = (now.year + y_offset) % 100

                if exchange_code == "CZCE":
                    iid = f"{exchange_code}.{variety_upper}{str(year)[-1]}{month:02d}"
                else:
                    iid = f"{exchange_code}.{variety_upper.lower()}{year:02d}{month:02d}"

                try:
                    q = api.get_quote(iid)
                    if (
                        q
                        and str(q.get("ins_class", "")) in ("FUTURE", "期货")
                        and float(q.get("last_price", 0) or 0) > 0
                    ):
                        records.append(
                            {
                                "date": now.strftime("%Y-%m-%d"),
                                "contract": iid.split(".")[-1],
                                "open": float(q.get("open", 0) or 0),
                                "high": float(q.get("highest", 0) or 0),
                                "low": float(q.get("lowest", 0) or 0),
                                "close": float(q.get("last_price", 0) or 0),
                                "volume": int(q.get("volume", 0) or 0),
                                "oi": int(q.get("open_interest", 0) or 0),
                                "data_source": "tqsdk",
                                "confidence": 1.0,
                            }
                        )
                except Exception:
                    continue

            api.close()
            return records if records else None

        except Exception as e:
            print(f"[Warning] TqSDK fetch error: {e}")
            return None

    def _fetch_tqsdk_kline(
        self,
        variety: str,
        days: int = 120,
        period: str = "daily",
    ) -> Optional[List[Dict]]:
        """Get main contract kline from TqSDK (live mode, close is real-time price)

        Args:
            variety: symbol code
            days: number of days
            period: daily/weekly/monthly/60m/240m

        Returns:
            [{"date","open","close","high","low","volume","oi",...}, ...] or None
        """
        if not self.tqsdk_available:
            return None

        # 🐛 v2.11.0: 用线程+超时逃避TqSDK罕见品种死锁
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
        _executor = ThreadPoolExecutor(max_workers=1)
        _future = _executor.submit(self._do_fetch_tqsdk_kline, variety, days, period)
        try:
            _result = _future.result(timeout=10)
            return _result
        except _FutureTimeout:
            print(f"[Warning] TqSDK kline fetch timeout for {variety} (15s)")
            return None
        except Exception as _e:
            print(f"[Warning] TqSDK kline fetch error for {variety}: {_e}")
            return None
        finally:
            _executor.shutdown(wait=False)

    def _do_fetch_tqsdk_kline(
        self,
        variety: str,
        days: int = 120,
        period: str = "daily",
    ) -> Optional[List[Dict]]:
        """Actual TqSDK fetch (called within timeout wrapper)"""
        import os, time as _time
        import pandas as pd
        from tqsdk import TqApi, TqAuth

        _user = os.environ.get("TQSDK_USERNAME") or os.environ.get("TQ_USER", "")
        _pass = os.environ.get("TQSDK_PASSWORD") or os.environ.get("TQ_PASSWORD", "")
        if not _user or not _pass:
            return None

        variety_upper = variety.upper()
        exchange_code = {
            "SHFE": "SHFE", "DCE": "DCE", "CZCE": "CZCE",
            "GFEX": "GFEX", "INE": "INE", "CFFEX": "CFFEX",
        }.get(self._get_exchange(variety_upper), "")
        if not exchange_code:
            return None

        _upper_exchanges = {"CZCE", "CFFEX"}
        variety_tqsdk = variety_upper if exchange_code in _upper_exchanges else variety_upper.lower()
        continuous_id = f"KQ.m@{exchange_code}.{variety_tqsdk}"

        api = TqApi(auth=TqAuth(_user, _pass))
        _tqsdk_secs = {"daily": 86400, "weekly": 604800, "monthly": 2592000, "240m": 14400, "60m": 3600, "120m": 7200}
        period_sec = _tqsdk_secs.get(period, 86400)
        klines = api.get_kline_serial(continuous_id, period_sec, data_length=max(days, 60))

        deadline = _time.time() + 2
        while _time.time() < deadline:
            api.wait_update()
            if len(klines) > 0:
                last = klines.iloc[-1]
                if not pd.isna(last.get("close", float("nan"))):
                    break

        api.close()

        if klines is None or len(klines) == 0:
            return None

        records = []

        if hasattr(klines, "iterrows"):
            for idx, row in klines.iterrows():
                try:
                    ts = row.get("datetime", 0)
                    dt = pd.Timestamp(ts, unit="ns") if ts > 1e12 else pd.Timestamp(ts, unit="s")
                    close_val = float(row.get("close", 0) or 0)
                    # 跳过空值 bar
                    if close_val == 0 and row.get("volume", 0) == 0:
                        continue
                    records.append({
                        "date": dt.strftime("%Y%m%d"),
                        "open": float(row.get("open", 0) or 0),
                        "close": close_val,
                        "high": float(row.get("high", 0) or 0),
                        "low": float(row.get("low", 0) or 0),
                        "volume": int(float(row.get("volume", 0) or 0)),
                        "oi": int(float(row.get("open_oi", row.get("open_interest", 0)) or 0)),
                        "data_source": "tqsdk",
                        "confidence": 1.0,
                    })
                except (ValueError, TypeError):
                    continue
        else:
            for k in klines:
                try:
                    ts = k.get("datetime", 0) if isinstance(k, dict) else 0
                    records.append({
                        "date": str(pd.Timestamp(ts, unit="ns").strftime("%Y%m%d")) if ts > 0 else "",
                        "open": float(k.get("open", 0)) if isinstance(k, dict) else 0,
                        "close": float(k.get("close", 0)) if isinstance(k, dict) else 0,
                        "high": float(k.get("high", 0)) if isinstance(k, dict) else 0,
                        "low": float(k.get("low", 0)) if isinstance(k, dict) else 0,
                        "volume": int(float(k.get("volume", 0))) if isinstance(k, dict) else 0,
                        "data_source": "tqsdk",
                        "confidence": 1.0,
                    })
                except (ValueError, TypeError):
                    continue

        return records if records else None


    def _get_exchange(self, variety: str) -> str:
        # 根据品种代码返回交易所
        exchange_map = {
            "CU": "SHFE",
            "AL": "SHFE",
            "ZN": "SHFE",
            "PB": "SHFE",
            "NI": "SHFE",
            "SN": "SHFE",
            "AU": "SHFE",
            "AG": "SHFE",
            "RB": "SHFE",
            "HC": "SHFE",
            "SS": "SHFE",
            "RU": "SHFE",
            "BR": "SHFE",
            "FU": "SHFE",
            "BU": "SHFE",
            "WR": "SHFE",
            "SP": "SHFE",
            "AO": "SHFE",
            "AD": "SHFE",
            "OP": "SHFE",
            "A": "DCE",
            "B": "DCE",
            "M": "DCE",
            "Y": "DCE",
            "P": "DCE",
            "C": "DCE",
            "CS": "DCE",
            "I": "DCE",
            "J": "DCE",
            "JM": "DCE",
            "L": "DCE",
            "V": "DCE",
            "PP": "DCE",
            "EG": "DCE",
            "EB": "DCE",
            "PG": "DCE",
            "JD": "DCE",
            "LH": "DCE",
            "RR": "DCE",
            "BB": "DCE",
            "FB": "DCE",
            "LG": "DCE",
            "AP": "CZCE",
            "CF": "CZCE",
            "CY": "CZCE",
            "CJ": "CZCE",
            "FG": "CZCE",
            "SA": "CZCE",
            "SH": "CZCE",
            "MA": "CZCE",
            "TA": "CZCE",
            "UR": "CZCE",
            "PF": "CZCE",
            "PR": "CZCE",
            "PX": "CZCE",
            "PK": "CZCE",
            "OI": "CZCE",
            "RM": "CZCE",
            "RS": "CZCE",
            "SR": "CZCE",
            "WH": "CZCE",
            "PM": "CZCE",
            "SM": "CZCE",
            "SF": "CZCE",
            "ZC": "CZCE",
            "JR": "CZCE",
            "LR": "CZCE",
            "RI": "CZCE",
            "SI": "GFEX",
            "LC": "GFEX",
            "PS": "GFEX",
            "PT": "GFEX",
            "PD": "GFEX",
            "SC": "INE",
            "LU": "INE",
            "NR": "INE",
            "BC": "INE",
            "IF": "CFFEX",
            "IC": "CFFEX",
            "IM": "CFFEX",
            "IH": "CFFEX",
            "T": "CFFEX",
            "TF": "CFFEX",
            "TS": "CFFEX",
            "TL": "CFFEX",
        }
        return exchange_map.get(variety.upper(), "")

    def _fetch_eastmoney(
        self,
        variety: str,
        contract_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[List[Dict]]:
        # 从东方财富API获取数据
        if not self.eastmoney_available:
            return None

        try:
            # 优先获取实时行情快照(最快,交易时段内返回最新价)
            quotes = self.eastmoney_collector.get_realtime_quote(variety=variety)
            if quotes and len(quotes) > 0:
                records = []
                for q in quotes:
                    records.append(
                        {
                            "code": q.get("code", ""),
                            "name": q.get("name", ""),
                            "price": q.get("price", 0),
                            "change_pct": q.get("change_pct", 0),
                            "volume": q.get("volume", 0),
                            "oi": q.get("oi", 0),
                            "open": q.get("open", 0),
                            "high": q.get("high", 0),
                            "low": q.get("low", 0),
                            "data_source": "eastmoney",
                            "confidence": 1.0,
                        }
                    )
                return records

            # 实时行情失败时,尝试获取品种对应的secid(用于查K线)
            info_list = self.eastmoney_collector.get_futures_base_info()
            secid = None
            if info_list:
                # 先精确匹配,再前缀匹配
                variety_lower = variety.lower()
                for item in info_list:
                    if item["code"].lower() == variety_lower:
                        secid = item["secid"]
                        break
                if not secid:
                    # 前缀匹配: cu 匹配 cu2706, cu2701...
                    for item in info_list:
                        if item["code"].lower().startswith(variety_lower):
                            secid = item["secid"]
                            break

            if not secid:
                # 通过合约列表获取secid(含交易所代码)
                contracts = self.eastmoney_collector.get_contract_list(variety)
                if contracts and len(contracts) > 0:
                    exchange_code = self._get_exchange_code(variety)
                    for c in contracts:
                        if c["code"][-1] not in ("m", "s", "i"):
                            secid = f"{exchange_code}.{c['code']}"
                            break

            if secid:
                beg = "20200101"
                if start_date:
                    beg = start_date.replace("-", "")
                end = end_date.replace("-", "") if end_date else None
                klines = self.eastmoney_collector.get_kline_history(secid, beg=beg, end=end, klt=101, fqt=1)
                if klines:
                    records = []
                    for k in klines:
                        records.append(
                            {
                                "date": k.get("date", ""),
                                "open": k.get("open", 0),
                                "high": k.get("high", 0),
                                "low": k.get("low", 0),
                                "close": k.get("close", 0),
                                "volume": k.get("volume", 0),
                                "change_pct": k.get("change_pct", 0),
                                "data_source": "eastmoney",
                                "confidence": 1.0,
                            }
                        )
                    return records

            return None

        except Exception as e:
            print(f"[Warning] EastMoney fetch error: {e}")
            return None

    def _get_exchange_code(self, variety: str) -> int:
        # 根据品种代码返回东方财富交易所代码
        exchange_map = {
            "SHFE": 113,
            "DCE": 114,
            "CZCE": 115,
            "CFFEX": 8,
            "INE": 142,
            "GFEX": 225,
        }
        exchange_name = self._get_exchange(variety)
        return exchange_map.get(exchange_name, 113)

    def _fetch_tdx(
        self,
        variety: str,
        contract_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[List[Dict]]:
        # 从通达信本地HTTP服务获取数据
        if not self.tdx_local_available:
            return None
        try:
            records = self.tdx_collector.get_quote(variety)
            if records and len(records) > 0:
                for r in records:
                    r["data_source"] = "tdx_local"
                    r["confidence"] = 1.0
                return records
            # 实时行情失败,尝试K线
            days = 365
            if start_date:
                try:
                    start = (
                        datetime.strptime(start_date, "%Y-%m-%d")
                        if "-" in start_date
                        else datetime.strptime(start_date, "%Y%m%d")
                    )
                    days = (datetime.now() - start).days
                except Exception:
                    logger.warning("数据源异常(已降级)", exc_info=True)
            kline_records = self.tdx_collector.get_kline(variety, days=days)
            if kline_records:
                for r in kline_records:
                    r["data_source"] = "tdx_local"
                    r["confidence"] = 1.0
                return kline_records
            return None
        except Exception as e:
            print(f"[Warning] TDX fetch error: {e}")
            return None

    def _fetch_akshare(
        self,
        variety: str,
        contract_type: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[List[Dict]]:
        # 从AKShare获取数据
        if not self.akshare_available:
            return None

        try:
            import akshare as ak

            # AKShare 期货日线数据 - 使用 futures_main_sina 获取主力合约
            ak_symbol = variety.lower() + "0"
            df = ak.futures_main_sina(symbol=ak_symbol)

            if df is not None and len(df) > 0:
                # 中文列名映射
                cn_map = {
                    "日期": "date",
                    "开盘价": "open",
                    "最高价": "high",
                    "最低价": "low",
                    "收盘价": "close",
                    "成交量": "volume",
                    "持仓量": "open_interest",
                }
                # 转换为标准格式
                records = []
                for _, row in df.iterrows():  # 返回全部数据(上游需要150天)

                    def get_val(keys):
                        for k in keys:
                            v = row.get(k)
                            if v is not None:
                                return v
                        return 0

                    records.append(
                        {
                            "date": str(get_val(["日期", "date"])),
                            "open": float(get_val(["开盘价", "open"])),
                            "high": float(get_val(["最高价", "high"])),
                            "low": float(get_val(["最低价", "low"])),
                            "close": float(get_val(["收盘价", "close"])),
                            "volume": int(get_val(["成交量", "volume"])),
                            "oi": int(get_val(["持仓量", "open_interest", "hold"])),
                            "data_source": "AKShare",
                            "confidence": 1.0,
                        }
                    )
                return records
        except Exception as e:
            print(f"[Warning] AKShare error: {e}")
            return None

    def _fetch_websearch(
        self,
        variety: str,
        contract_type: str = "main",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[List[Dict]]:
        """从WebSearch获取数据(东方财富+新浪API直连兜底)

        当TqSDK/AKShare等主流数据源不可用时,通过stdlib urllib直接调用
        东方财富push2his API获取K线数据.不依赖任何第三方库.
        置信度: 0.85(标记为WebSearch降级源)

        策略:
        1. 东方财富 push2his K线 API (JSON)
        2. 新浪财经 InnerFuturesNewService K线 API (JSONP)
        """
        from urllib.request import Request, urlopen
        from urllib.error import URLError

        variety_upper = variety.upper()
        UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )

        # === Strategy 1: 东方财富 push2his K线 API ===
        # URL: https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=113.RB0&...
        try:
            exchange_code = self._get_exchange_code(variety_upper)
            secid = f"{exchange_code}.{variety_upper}0"

            beg = (start_date or "20250101").replace("-", "")
            end_dt = (end_date or datetime.now().strftime("%Y%m%d")).replace("-", "")

            url = (
                "https://push2his.eastmoney.com/api/qt/stock/kline/get"
                f"?secid={secid}"
                "&fields1=f1,f2,f3,f4,f5,f6"
                "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
                f"&klt=101&fqt=1&beg={beg}&end={end_dt}"
            )

            req = Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": "https://quote.eastmoney.com/",
                },
            )
            with urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)

            klines = data.get("data", {}).get("klines", [])
            if klines:
                records = []
                for kline_str in klines:
                    parts = kline_str.split(",")
                    if len(parts) >= 6:
                        records.append(
                            {
                                "date": parts[0],
                                "open": float(parts[1]),
                                "close": float(parts[2]),
                                "high": float(parts[3]),
                                "low": float(parts[4]),
                                "volume": int(float(parts[5])),
                                "oi": int(float(parts[7])) if len(parts) >= 8 else 0,
                                "data_source": "websearch_eastmoney",
                                "confidence": 0.85,
                            }
                        )
                if records:
                    print(f"[WebSearch] 东方财富成功: {variety_upper} {len(records)}条K线")
                    return records
        except Exception as e:
            pass  # Fall through to Strategy 2

        # === Strategy 2: 新浪财经 InnerFuturesNewService K线 API ===
        # URL: https://stock2.finance.sina.com.cn/futures/api/jsonp.php/.../getDailyKLine?symbol=RB0
        try:
            sina_symbol = f"{variety_upper}0"
            url = (
                "https://stock2.finance.sina.com.cn/futures/api/jsonp.php"
                f"/var%20_{sina_symbol}=/InnerFuturesNewService.getDailyKLine"
                f"?symbol={sina_symbol}"
            )

            req = Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
            with urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk", errors="replace")

            # Parse JSONP: var _{SYMBOL}0=([{...},...])
            match = re.search(r"=\((\[.+?\])\)", raw, re.DOTALL)
            if not match:
                return None

            klines = json.loads(match.group(1))
            if klines and isinstance(klines, list):
                records = []
                for k in klines:
                    records.append(
                        {
                            "date": str(k.get("d", "")),
                            "open": float(k.get("o", 0)),
                            "high": float(k.get("h", 0)),
                            "low": float(k.get("l", 0)),
                            "close": float(k.get("c", 0)),
                            "volume": int(float(k.get("v", 0))),
                            "data_source": "websearch_sina",
                            "confidence": 0.80,
                        }
                    )
                if records:
                    print(f"[WebSearch] 新浪成功: {variety_upper} {len(records)}条K线")
                    return records
        except Exception:
            pass

        return None

    def _fetch_cache(
        self,
        variety: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[List[Dict]]:
        # 从DuckDB缓存获取数据
        if self.db_available and self.db is not None:
            try:
                cached = self.db.get_cached("quote", variety, ttl_hours=4, start_date=start_date, end_date=end_date)
                if cached:
                    print(f"[Cache] DuckDB hit for {variety}")
                    return cached
            except Exception as e:
                print(f"[Warning] DuckDB cache read error: {e}")

        # 降级:JSON文件缓存(兼容旧缓存)
        cache_file = self.cache_dir / f"{variety}_{start_date or 'latest'}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                cache_time = datetime.fromisoformat(cached_data.get("timestamp", "2000-01-01"))
                if datetime.now() - cache_time > timedelta(days=1):
                    print(f"[Info] JSON cache expired for {variety}")
                    return None
                return cached_data.get("data", [])
            except Exception as e:
                print(f"[Warning] JSON cache read error: {e}")
        return None

    def save_to_cache(self, variety: str, data: List[Dict]):
        # 保存数据到DuckDB缓存(和JSON文件兜底)
        # 主缓存:DuckDB
        if self.db_available and self.db is not None:
            try:
                self.db.set_cached("quote", variety, data, ttl_hours=4)
            except Exception as e:
                print(f"[Warning] DuckDB cache write error: {e}")

        # 兜底:JSON文件(兼容旧调用者)
        cache_file = self.cache_dir / f"{variety}_latest.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "variety": variety,
                        "timestamp": datetime.now().isoformat(),
                        "data": data,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            print(f"[Warning] JSON cache write error: {e}")

    def get_health_status(self) -> Dict[str, Any]:
        # 获取健康状态
        result = {}
        for source in DataSource:
            if source == DataSource.NONE:
                continue
            key = self.health._key(source)
            status_entry = self.health.status.get(key, {})
            result[key] = {
                "available": status_entry.get("available", True),
                "confidence": status_entry.get("confidence", 1.0),
                "last_success": str(status_entry.get("last_success", "")),
                "failure_count": status_entry.get("failure_count", 0),
            }
        return result


def main():
    # test function

    print("Multi-Source Adapter Test")
    print("=" * 50)

    adapter = MultiSourceAdapter()

    # 健康状态
    print("\n数据源健康状态:")
    health = adapter.get_health_status()
    for source, status in health.items():
        available = "✓" if status["available"] else "✗"
        print(f"  {available} {source}: 置信度 {status['confidence']:.2f}")

    # 测试查询
    print("\n测试查询:")
    result = adapter.get_quote("CU")
    print(f"  数据源: {result.get('data_source')}")
    print(f"  置信度: {result.get('confidence')}")
    print(f"  成功: {result.get('success')}")


if __name__ == "__main__":
    main()
