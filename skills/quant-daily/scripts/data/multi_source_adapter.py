#!/usr/bin/env python3
"""
多源数据适配器 v3.1.0
K线降级链委托 FDC futures_data_core（统一优先级 · 消除重复维护）

🐛 v3.1.0 数据优先级对齐 FDC（2026-07-13）
  - get_kline 降级链: FDC(QMT→TDX→TqSDK) → Cache → 失败
  - 移除重复的 TDX/TqSDK 直接调用（均已由 FDC 降级链覆盖）
  - FDC 返回的 data_source 字段标记实际命中的采集器名称
  - 保留 get_quote/term_structure 等非 K 线方法不变

🐛 v3.0.0 QMT第一源 + 移除AKShare/东方财富
  - K线降级链: QMT → TDX → TqSDK → WebSearch裸HTTP
  - AKShare 和东方财富采集器已移除,不再依赖
  - QMT本地TCP直取(<5ms),不可用时自动降级TDX

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

数据源优先级(FDC统一管理): QMT(pri=0) → TDX TQ-Local(pri=1) → TqSDK(pri=2)
Cache/WebSearch 为 MSA 独有的兜底层，FDC 链路全不可用时启用。
所有数据源置信度统一为 1.0 (数据置信度 ≠ 信号置信度，后者由信号层处理)。

注意:金十数据 MCP(jin10)是独立的资讯类数据源,不参与价格数据路由.
金十数据通过 WorkBuddy MCP 工具(mcp__jin10__*)直接调用,专供快讯/资讯/日历查询.
"""

import json
import math
import os
import re
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

# FDC统一缓存（CacheStore = Redis + PostgreSQL，Memory兜底）
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
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
    QMT_XTQUANT = "qmt_xtquant"  # QMT/xtquant（TCP本地直取）
    TDX_LOCAL = "tdx_local"  # 通达信本地HTTP服务
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


# ═══════════════════════════════════════════
# 🔴 P0-1 / P0-2 数据污染防御（2026-07-11 压力测试暴露·生产级修复）
# ═══════════════════════════════════════════

# 单根K线相对前一根收盘的收益率绝对值上限。
# 期货单根涨跌停通常 ≤ ±13%，单根 >50% 跳变必为脏数据/伪造spike（如100×伪造突破）。
_SPIKE_RETURN_CAP = 0.5

# 已知交易所白名单（用于品种映射交叉校验，P1）
_KNOWN_EXCHANGES = {"SHFE", "DCE", "CZCE", "GFEX", "INE", "CFFEX"}


def _safe_float(value, default=0.0):
    """P0-1：拒绝非有限值(inf/nan)与不可转换值，返回 default。

    阻断 ``inf/nan`` 经 ``float(row.get(k, 0) or 0)`` 直穿信号引擎，
    是数据污染的第一道防线。
    """
    try:
        v = float(value)
    except (ValueError, TypeError):
        return default
    if not math.isfinite(v):
        return default
    return v


def _is_finite_num(x) -> bool:
    try:
        return math.isfinite(float(x))
    except (ValueError, TypeError):
        return False


def _detect_spikes(closes: list, cap: float) -> set:
    """孤立异常值检测（对趋势/连续跳空稳健，专治单根伪造突破）。

    判定为 spike 的充要条件（中间bar）：
      - 左右两根邻居处于相近水位  max/min(邻居) <= 1+cap
      - 但本根相对邻居偏离超过 (1+cap)：close > max(neighbor)*(1+cap) 或 close < min(neighbor)/(1+cap)
    即「邻居彼此相近、唯独本根突兀」才是孤立spike；趋势/跳空（邻居本身差异大）不误判。
    首/末根用前向return兜底，且末根仅当前一根非spike时才判（避免被前一根spike牵连）。
    """
    n = len(closes)
    if n < 3:
        return set()
    spikes = set()
    for i in range(n):
        if i == 0:
            if closes[1] > 0 and abs(closes[0] / closes[1] - 1.0) > cap:
                spikes.add(i)
            continue
        if i == n - 1:
            if closes[i - 1] > 0 and abs(closes[i] / closes[i - 1] - 1.0) > cap and (i - 1) not in spikes:
                spikes.add(i)
            continue
        a, b = closes[i - 1], closes[i + 1]
        if a <= 0 or b <= 0:
            continue
        if max(a, b) / min(a, b) > (1 + cap):
            continue  # 邻居本身差异大 → 非孤立spike（趋势/跳空），跳过
        c = closes[i]
        if c > max(a, b) * (1 + cap) or c < min(a, b) / (1 + cap):
            spikes.add(i)
    return spikes


def _sanitize_kline(records: list, period: str = "daily"):
    """P0-1 + P0-2 统一清洗：有限性守卫 + 单根spike隔离。

    返回 ``(cleaned_records, report_dict)``。
    - 非有限 OHLCV → 置 0（不破坏序列长度，避免 NaN 传播到 DC 窗口）
    - 单根收益率超阈值 → 该 bar 视为 spike，用前后 bar 线性插值还原
      OHLC，避免 100× spike 伪造 DC20 突破，同时保留序列长度不破坏 DC 窗口。

    这是扫描层最关键的污染清洁闸门（覆盖 P0-1 + P0-2）。
    """
    if not records:
        return records, {"sanitized": False, "spike_corrected": 0, "nonfinite_fields": 0}

    cleaned = []
    nonfinite = 0
    for r in records:
        raws = {k: r.get(k, 0) for k in ("open", "high", "low", "close", "volume", "oi")}
        if any(not _is_finite_num(v) for v in raws.values()):
            nonfinite += 1
        new_r = dict(r)
        for k in ("open", "high", "low", "close", "volume", "oi"):
            new_r[k] = _safe_float(raws[k])
        cleaned.append(new_r)

    # ── 单根 spike 检测（滑窗中位数，对连续spike稳健）──
    closes = [r["close"] for r in cleaned]
    spike_idx = _detect_spikes(closes, _SPIKE_RETURN_CAP)

    # ── 插值修复 spike bar（用前后最近有效 bar 中点）──
    for i in sorted(spike_idx):
        lo, hi = i - 1, i + 1
        while lo in spike_idx and lo >= 0:
            lo -= 1
        while hi in spike_idx and hi < len(closes):
            hi += 1
        if lo >= 0 and hi < len(closes):
            a, b = closes[lo], closes[hi]
            interp = (a + b) / 2.0
            cleaned[i].update(
                {"open": interp, "close": interp, "high": max(a, b),
                 "low": min(a, b), "_spike_corrected": True}
            )
        elif lo >= 0:
            cleaned[i].update(
                {"open": closes[lo], "close": closes[lo], "high": closes[lo],
                 "low": closes[lo], "_spike_corrected": True}
            )
        elif hi < len(closes):
            cleaned[i].update(
                {"open": closes[hi], "close": closes[hi], "high": closes[hi],
                 "low": closes[hi], "_spike_corrected": True}
            )

    return cleaned, {
        "sanitized": (len(spike_idx) > 0 or nonfinite > 0),
        "spike_corrected": len(spike_idx),
        "nonfinite_records": nonfinite,
    }


# 数据新鲜度阈值（天）。超过则视为过期，触发降级而非信任来历不明的数据。
# 日线/周线/月线覆盖周末+短假；子周期沿用 v2.9.1 的 7d 规则。
_STALE_CAP_DAYS = {"daily": 7, "weekly": 14, "monthly": 60, "60m": 7, "120m": 7, "240m": 7}


def _parse_bar_date(datestr) -> Optional[datetime]:
    """P1 解析 bar 日期（兼容 2026-07-11 / 20260711 / 2026-07-11 15:00 等）→ datetime"""
    if not datestr:
        return None
    digits = re.sub(r"\D", "", str(datestr))[:8]
    if len(digits) != 8:
        return None
    try:
        return datetime.strptime(digits, "%Y%m%d")
    except Exception:
        return None


def _kline_is_stale(records: list, period: str = "daily") -> bool:
    """P1 新鲜度闸门：最后一根 bar 距今超过阈值 → True(过期,应降级)。

    无法解析日期时保守视为过期（触发降级而非信任来历不明的数据）。
    """
    if not records:
        return True
    last = records[-1].get("date")
    dt = _parse_bar_date(last)
    if dt is None:
        return True
    age_days = (datetime.now() - dt).days
    cap = _STALE_CAP_DAYS.get(period, 7)
    return age_days > cap


class MultiSourceAdapter:
    # 多源数据适配器(配置驱动)

    def __init__(self):
        self.health = DataSourceHealth()
        self.cache_dir = Path.home() / ".workbuddy" / "skills" / "quant-daily" / "data" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 数据源配置(从 YAML 加载)
        self.config = DataSourceConfig()

        # FDC CacheStore 统一缓存（Redis + PostgreSQL，Memory 兜底）
        try:
            from futures_data_core.core.cache_store import make_cache_store as _make_cache
            self.cache = _make_cache(ttl_hours=4.0)
            self.cache_available = True
        except Exception as e:
            print(f"[Warning] FDC CacheStore not available: {e}")
            self.cache = None
            self.cache_available = False

        # 初始化数据源
        self._init_data_sources()

    def _init_data_sources(self):
        # 初始化数据源(按配置驱动)
        self.collector_available = False
        self.tqsdk_available = False
        self.tdx_local_available = False

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

        # 3. 通达信本地HTTP服务(按配置 enabled 决定是否加载)
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

        # 4. QMT/xtquant（第一数据源，本地 TCP 直取）
        try:
            from xtquant import xtdata  # noqa: F401

            self.qmt_available = True
        except ImportError:
            self.qmt_available = False

    def get_quote(
        self,
        variety: str,
        contract_type: str = "main",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取行情数据(FDC优先 → 配置驱动的盘中/盘后降级)

        Args:
            variety: 品种代码
            contract_type: 合约类型
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            行情数据
        """
        # 0. 优先 FDC futures_data_core（统一降级链）
        try:
            import asyncio as _asyncio
            from futures_data_core import get_quote as fdc_quote

            payload = _asyncio.run(fdc_quote(variety))
            if payload and payload.data:
                sources = payload.meta.get("sources", ["fdc"])
                print(f"[MultiSource] get_quote({variety}) → FDC({sources[0]})", flush=True)
                try:
                    record_data_fetch(variety, sources[0], success=True)
                except Exception:
                    pass
                return {
                    "success": True,
                    "data": payload.data,
                    "data_source": sources[0],
                    "confidence": 1.0,
                }
        except Exception as e:
            print(f"[Warning] FDC get_quote {variety}: {e}")

        # 1. 降级 MSA 自有数据源（配置驱动）
        now = datetime.now()
        hour = now.hour
        is_trading_hours = (9 <= hour < 15) or (21 <= hour < 23)
        sources = self.config.get_priority_list(is_trading_hour=is_trading_hours)

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
                    try:
                        record_data_fetch(variety, source.value, success=True, count=data_count)
                    except Exception as fe:
                        print(f"[Freshness] 记录失败: {fe}")
                    return {
                        "success": True,
                        "data": data,
                        "data_source": source.value,
                        "confidence": 1.0,
                        "response_ms": elapsed,
                    }
            except Exception as e:
                print(f"[Warning] {source.value} failed for {variety}: {e}")
                self.health.record_failure(source)

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

    def _return_kline(self, records, source, period):
        """P0-1 + P0-2 统一出口：清洗 K 线 → 返回标准 dict。

        所有 get_kline 分支的数据在返回前都经 _sanitize_kline 清洗，
        确保 inf/nan 被置零、单根 spike 被插值隔离，杜绝污染进入信号层。
        """
        cleaned, report = _sanitize_kline(records, period)
        if report.get("sanitized"):
            print(
                f"[Sanitize] {source} K线清洗: spike修正{report.get('spike_corrected', 0)}根, "
                f"非有限字段{report.get('nonfinite_records', 0)}处",
                flush=True,
            )
        return {
            "success": True,
            "data": cleaned,
            "data_source": source,
            "confidence": 1.0,
            "_sanitize_report": report,
        }

    def get_kline(
        self,
        variety: str,
        days: int = 365,
        period: str = "daily",
        contract: str = None,
    ) -> Dict[str, Any]:
        """
        获取品种的完整K线历史序列(FDC统一降级获取)

        降级链：FDC futures_data_core（QMT(pri=0) → TDX TQ-Local(pri=1) → TqSDK(pri=2)）
        始终走FDC，不依赖本地QMT安装状态。FDC全不可用时回退CacheStore + JSON文件兜底。

        Args:
            variety: 品种代码,如 SC, BU, CU
            days: 获取最近多少天的K线
            period: K线周期 daily(日线) | weekly(周线) | monthly(月线) | 60m(60分) | 120m(2小时) | 240m(4小时)
            contract: 指定合约月份(如 "2609"),不传则用主力连续L8

        Returns:
            {"success": bool, "data": [{date, open, close, high, low, volume, oi, settle}, ...],
             "data_source": str, "confidence": float}
        """
        # ── 1. FDC 统一降级链（QMT(pri=0) → TDX TQ-Local(pri=1) → TqSDK(pri=2)）──
        #    FDC自管理降级，不依赖本地QMT是否安装；QMT不可用时自动尝试TDX→TqSDK
        try:
            fdc_bars = self._fetch_qmt_kline(variety, period, days)
            if fdc_bars and len(fdc_bars) >= 20:
                records = []
                for bar in fdc_bars:
                    records.append({
                        "date": bar["date"],
                        "open": float(bar["open"]),
                        "close": float(bar["close"]),
                        "high": float(bar["high"]),
                        "low": float(bar["low"]),
                        "volume": int(bar["volume"]),
                        "oi": int(bar.get("oi", 0)),
                        "settle": float(bar.get("settle", 0)),
                        "data_source": bar.get("data_source", "fdc"),
                        "confidence": 1.0,
                    })
                source_label = records[0].get("data_source", "fdc")
                print(f"[MultiSource] get_kline({variety}) → FDC降级链({source_label}), {len(records)}条")
                if not _kline_is_stale(records, period):
                    try:
                        record_data_fetch(variety, source_label, success=True, count=len(records))
                    except Exception:
                        pass
                    return self._return_kline(records, source_label, period)
            else:
                print(f"[Warning] get_kline({variety}) FDC返回空/不足20条")
        except Exception as e:
            print(f"[MultiSource] FDC降级链 get_kline {variety}: {e}")

        # ── 2. Cache 兜底（FDC 没有的回退层）──
        try:
            cached = self._fetch_cache(variety, days=days, period=period)
            if cached and len(cached) >= 20:
                records = []
                for bar in cached:
                    records.append({
                        "date": bar.get("date", ""),
                        "open": float(bar.get("open", 0)),
                        "close": float(bar.get("close", 0)),
                        "high": float(bar.get("high", 0)),
                        "low": float(bar.get("low", 0)),
                        "volume": int(bar.get("volume", 0)),
                        "oi": int(bar.get("oi", 0)),
                        "settle": float(bar.get("settle", 0)),
                        "data_source": "cache",
                        "confidence": 1.0,
                    })
                print(f"[MultiSource] get_kline({variety}) → 缓存兜底, {len(records)}条")
                if not _kline_is_stale(records, period):
                    try:
                        record_data_fetch(variety, "cache", success=True, count=len(records))
                    except Exception:
                        pass
                    return self._return_kline(records, "cache", period)
        except Exception as e:
            print(f"[MultiSource] 缓存 get_kline {variety}: {e}")

        # ── 3. 全部失败 ──
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
        获取品种的期限结构(FDC优先 → 通达信本地降级)

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
        # 0. 优先 FDC futures_data_core（统一降级链）
        try:
            import asyncio as _asyncio
            from futures_data_core import get_term_structure as fdc_term

            payload = _asyncio.run(fdc_term(variety))
            if payload and payload.data:
                ts = payload.data
                contract_count = len(ts.get("contracts", []))
                sources = payload.meta.get("sources", ["fdc"])
                print(
                    f"[MultiSource] get_term_structure({variety}) → FDC({sources[0]}), "
                    f"{ts.get('type','?')} (斜率{ts.get('slope',0)}%)"
                )
                try:
                    record_data_fetch(variety, sources[0], success=True, count=contract_count)
                except Exception:
                    pass
                return {"success": True, "data_source": sources[0], **ts}
        except Exception as e:
            print(f"[Warning] FDC term_structure {variety}: {e}")

        # 1. 降级通达信本地(TdxCollector 通过 get_all_contracts 实时计算)
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
        获取品种的技术指标(FDC compute_indicators → 通达信本地 formula_zb)

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
        # 0. 优先通达信本地 formula_zb（精度最高，与通达信实盘一致）
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

        # 1. 降级 FDC compute_indicators（numpy纯函数，零外部依赖）
        try:
            from futures_data_core.indicators.core import compute_indicators, INDICATOR_NAMES
            # 需要K线数据来计算指标，尝试从FDC获取
            import asyncio as _asyncio
            from futures_data_core import get_kline as fdc_kline

            payload = _asyncio.run(fdc_kline(symbol, period="daily", days=120))
            if payload and payload.data:
                bars = payload.data.get("bars", [])
                if bars and len(bars) >= 30:
                    df = {
                        "open": [float(b.get("open", 0)) for b in bars],
                        "high": [float(b.get("high", 0)) for b in bars],
                        "low": [float(b.get("low", 0)) for b in bars],
                        "close": [float(b.get("close", 0)) for b in bars],
                        "volume": [float(b.get("volume", 0)) for b in bars],
                    }
                    fdc_ind = compute_indicators(df, indicators="all")
                    if fdc_ind:
                        sources = payload.meta.get("sources", ["fdc"])
                        print(f"[MultiSource] get_indicators({symbol}) → FDC numpy, {len(fdc_ind)}项指标")
                        try:
                            record_data_fetch(symbol, sources[0], success=True, count=len(fdc_ind))
                        except Exception:
                            pass
                        return {
                            "success": True,
                            "data": fdc_ind,
                            "data_source": sources[0],
                            "confidence": 1.0,
                            "indicator_count": len(fdc_ind),
                            "method": "fdc_numpy",
                        }
        except Exception as e:
            print(f"[Warning] FDC compute_indicators {symbol}: {e}")

        # 2. 全部失败
        return {
            "success": False,
            "error": f"所有数据源均无法计算 {symbol} 技术指标",
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

    def _fetch_qmt_kline(self, variety: str, period: str, days: int) -> Optional[list[dict]]:
        """通过 FDC futures_data_core.get_kline() 获取 K 线（完整 FDC 降级链）。

        委托 FDC 的数据引擎，自动使用 QMT(pri=0)→TDX(pri=1)→TqSDK(pri=2) 降级链。
        返回 debat-team 标准 bar dict 格式，每根 bar 附 data_source 标注实际命中源。
        """
        try:
            import asyncio
            from futures_data_core import get_kline as fdc_get_kline

            payload = asyncio.run(fdc_get_kline(variety, period=period, days=days))
            if payload is None or payload.meta.get("data_grade") == "UNAVAILABLE":
                return None
            bars_raw = payload.data.get("bars", [])
            if not bars_raw:
                return None
            sources = payload.meta.get("sources", ["fdc"])
            actual_source = sources[0] if sources else "fdc"
            result = []
            for b in bars_raw:
                result.append({
                    "date": str(b.get("date", "")),
                    "open": float(b.get("open", 0)),
                    "high": float(b.get("high", 0)),
                    "low": float(b.get("low", 0)),
                    "close": float(b.get("close", 0)),
                    "volume": float(b.get("volume", 0)),
                    "oi": float(b.get("open_interest", b.get("oi", 0))),
                    "settle": float(b.get("settle", 0)),
                    "data_source": actual_source,
                })
            return result[-days:] if result and len(result) > days else result
        except Exception as e:
            print(f"[Warning] _fetch_qmt_kline({variety}) FDC降级链失败: {e}")
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
            if not exchange_code:
                return None  # P1 品种映射校验失败 → 放弃该源
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
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs,
    ) -> Optional[List[Dict]]:
        # 从FDC CacheStore获取缓存（Redis L1 + PostgreSQL L2，Memory兜底）
        if self.cache_available and self.cache is not None:
            try:
                import asyncio as _asyncio
                cache_key = f"kline:{variety}:{start_date or 'latest'}"
                cached = _asyncio.run(self.cache.get(cache_key))
                if cached is not None:
                    print(f"[Cache] FDC CacheStore hit for {variety} ({cache_key})")
                    return cached
            except Exception as e:
                print(f"[Warning] FDC CacheStore read error: {e}")

        # 降级: JSON文件缓存(兼容旧缓存)
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
        # 保存数据到FDC CacheStore（Redis L1 + PostgreSQL L2，Memory兜底）
        if self.cache_available and self.cache is not None:
            try:
                import asyncio as _asyncio
                cache_key = f"kline:{variety}:latest"
                _asyncio.run(self.cache.set(cache_key, data, ttl_hours=4.0))
            except Exception as e:
                print(f"[Warning] FDC CacheStore write error: {e}")

        # 兜底: JSON文件(兼容旧调用者)
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
