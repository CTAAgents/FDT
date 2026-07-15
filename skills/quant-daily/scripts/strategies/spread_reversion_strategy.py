"""
跨期价差 OU 均值回归策略 — Spread Reversion（G35 Phase 2）。

期货特有的「做空均值回归」第二维度：同一品种**近月 vs 远月**价差回归。
当近远月价差偏离历史均值达到 OU 过程的触发出场边界时，顺应均值回复方向交易：
  - 价差偏高（近月高估）→ 做空近月 + 做多远月
  - 价差偏低（近月低估）→ 做多近月 + 做空远月
两腿独立 RawSignal，**天然双向做空**。

数据通路（Phase 0 探查结论）：
  - FDC ``get_spread`` / ``term_structure`` 仅返回**当前快照**（无历史序列），无法直接 OU 拟合；
  - FDC ``get_kline`` 采集器 ``_resolve_contract`` 将品种映射到**主力/首月合约**，取不到指定近/远月历史；
  - 故 provider ``fetch_spread_history`` 复用 FDC ``_resolve_contracts``（xtquant 合约链，可注入）
    取近/远月代码，经 xtquant ``get_market_data_ex``（与 FDC qmt 采集器同源引擎）拉历史→对齐建价差序列。
  - 策略 ``compute`` 仅消费预采集的 ``ctx["spread_history"]``（scan_all 受保护注入），**零网络依赖**；
    离线（无 spread_history）时优雅无操作。

零新数据源：复用 FDC ``_resolve_contracts`` + xtquant ``get_market_data_ex``（与 FDC qmt 采集器同一底层）。
"""

from __future__ import annotations
from typing import Any, Callable, Optional

import numpy as np

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal


# ── 阈值配置 ──
Z_ENTRY = 2.0             # 价差 z-score 绝对值超过 → 出信号
MIN_BARS = 60             # OU 拟合/ Z 所需最小历史 bar 数
HALF_LIFE_MAX = 120.0     # OU 半衰期上限（日），超过视为弱回归不放大权重
HALF_LIFE_MIN = 2.0       # OU 半衰期下限（日），过短视为噪声不交易
SPREAD_WINDOW = 20        # 滚动 z 窗口


# ── 统计工具（纯 numpy，策略自包含） ──

def _build_spread_series(near: np.ndarray, far: np.ndarray) -> np.ndarray:
    """对齐构建近远月价差序列（spread = near - far），按最短长度截断。"""
    n = min(len(near), len(far))
    if n < 1:
        return np.array([])
    return np.asarray(near[-n:], dtype=float) - np.asarray(far[-n:], dtype=float)


def _rolling_z(values: list[float], window: int) -> float:
    """滚动 Z-score（取末值相对窗口均值/标准差的偏离）。"""
    if len(values) < window:
        window = len(values)
    if window < 2:
        return 0.0
    w = np.array(values[-window:], dtype=float)
    mu = float(np.mean(w))
    sd = float(np.std(w))
    if sd <= 1e-9:
        return 0.0
    return float((values[-1] - mu) / sd)


def _fit_ou_half_life(spread: np.ndarray) -> float:
    """OU 过程半衰期：spread[t]-spread[t-1] = a + b*spread[t-1] → hl = -ln(2)/b。

    b >= 0（无均值回复，含随机游走/趋势）→ inf；样本不足 → inf。
    """
    r = np.asarray(spread, dtype=float)
    if len(r) < 10:
        return float("inf")
    dy = np.diff(r)
    ylag = r[:-1]
    if np.var(ylag) <= 1e-12:
        return float("inf")
    b = np.cov(ylag, dy)[0, 1] / np.var(ylag)
    if b >= 0:
        return float("inf")
    return float(-np.log(2) / b)


# ════════════════════════════════════════════════════════════
# Provider：构建跨期价差历史（受 scan_all 调用，可注入 mock 测试）
# ════════════════════════════════════════════════════════════

# 合约链 & K 线 provider：sync callable（测试 mock / scan_all 同步上下文）
ContractsProvider = Callable[[str], Optional[list[dict]]]
KlinesProvider = Callable[[list[str], int], Optional[dict[str, list[float]]]]


def fetch_spread_history(
    symbol: str,
    days: int = 120,
    *,
    fetch_contracts: Optional[ContractsProvider] = None,
    fetch_klines: Optional[KlinesProvider] = None,
) -> Optional[dict]:
    """获取某品种跨期价差历史序列（受保护，失败返回 None）。

    先经 ``fetch_contracts``（缺省走 ``asyncio.run(FDC _resolve_contracts)`` → xtquant 合约链）
    取近/远月合约代码；再经 ``fetch_klines``（缺省走 xtquant ``get_market_data_ex``）拉两端历史
    → 对齐建价差序列。任一环节失败 → 返回 None（scan_all 侧按空处理，策略无操作）。

    Args:
        symbol: 品种代码（如 ``"CU"``）。
        days: 回溯交易日数。
        fetch_contracts: 可注入 sync 合约链 provider（测试 mock）。
        fetch_klines: 可注入 sync K 线 provider（测试 mock）。

    Returns:
        ``{"near_contract", "far_contract", "spread": [...], "dates": [...],
        "spread_pct": [...]}`` 或 ``None``。
    """
    # ── 1. 解析近/远月合约 ──
    if fetch_contracts is not None:
        contracts = fetch_contracts(symbol)
    else:
        try:
            from futures_data_core.f10.spread import _resolve_contracts as _rc
            import asyncio
            contracts = asyncio.run(_rc(symbol, None))
        except Exception:
            return None

    if not contracts or len(contracts) < 2:
        return None

    def _key(c: dict) -> str:
        return str(c.get("month") or c.get("contract") or "")

    sorted_c = sorted(contracts, key=_key)
    near, far = sorted_c[0], sorted_c[1]
    near_code = near.get("contract")
    far_code = far.get("contract")
    if not near_code or not far_code:
        return None

    # ── 2. 拉两端历史 ──
    if fetch_klines is not None:
        klines = fetch_klines([near_code, far_code], days)
    else:
        klines = _fetch_klines_xtquant([near_code, far_code], days)
    if not klines:
        return None

    near_series = klines.get(near_code)
    far_series = klines.get(far_code)
    if not near_series or not far_series:
        return None

    near_arr = np.asarray(near_series, dtype=float)
    far_arr = np.asarray(far_series, dtype=float)
    spread = _build_spread_series(near_arr, far_arr)
    if len(spread) < MIN_BARS:
        return None

    # 对齐日期（若有长度差异，取尾部）
    n = len(spread)
    dates = [str(i) for i in range(n)]
    far_tail = float(far_arr[-n]) if far_arr[-n] != 0 else 1.0
    spread_pct = [float(s) / far_tail * 100.0 for s in spread]

    return {
        "near_contract": near_code,
        "far_contract": far_code,
        "spread": [float(x) for x in spread],
        "dates": dates,
        "spread_pct": [float(x) for x in spread_pct],
    }


def _fetch_klines_xtquant(contract_codes: list[str], days: int) -> Optional[dict[str, list[float]]]:
    """生产路径：经 xtquant ``get_market_data_ex`` 拉多合约收盘历史（与 FDC qmt 采集器同源）。

    任何异常（xtquant 不可用 / 网络）返回 None → 上层按空处理。
    """
    try:
        from xtquant import xtdata
    except Exception:
        return None
    try:
        count = int(days) + 5
        df = xtdata.get_market_data_ex(
            field_list=["close"],
            stock_list=contract_codes,
            period="1d",
            count=count,
            dividend_type="none",
        )
        if not isinstance(df, dict):
            return None
        out: dict[str, list[float]] = {}
        for code in contract_codes:
            series = df.get(code)
            if series is None or not isinstance(series, dict):
                continue
            closes = series.get("close")
            if closes is None:
                continue
            vals = [float(c) for c in closes if c is not None]
            if vals:
                out[code] = vals
        return out if out else None
    except Exception:
        return None


# ════════════════════════════════════════════════════════════
# 策略类
# ════════════════════════════════════════════════════════════

class SpreadReversionStrategy(BaseStrategyV2):
    """跨期价差 OU 均值回归：近月高估做空近月+做多远月，反之亦然。"""

    @property
    def name(self) -> str:
        return "spread_reversion"

    @property
    def display_name(self) -> str:
        return "跨期价差OU均值回归(做空回归)"

    @property
    def signal_type(self) -> str:
        return "spread_reversion"

    @property
    def validators(self) -> list[str]:
        return ["atr_vol_timing", "stability"]

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        signals: list[RawSignal] = []
        ctx = context or {}
        sh = ctx.get("spread_history") or {}
        if not sh:
            return signals  # 离线（无价差历史）→ 优雅无操作

        for sym, info in sh.items():
            spread_raw = info.get("spread")
            if not spread_raw or len(spread_raw) < MIN_BARS:
                continue
            spread = np.asarray(spread_raw, dtype=float)

            # ── OU 半衰期门禁：必须可均值回复且半衰期在可交易区间 ──
            hl = _fit_ou_half_life(spread)
            if not np.isfinite(hl) or hl > HALF_LIFE_MAX or hl < HALF_LIFE_MIN:
                continue

            # ── 滚动 z 偏离 ──
            z = _rolling_z(list(spread), SPREAD_WINDOW)
            if abs(z) < Z_ENTRY:
                continue

            near_code = info.get("near_contract", f"{sym}?N")
            far_code = info.get("far_contract", f"{sym}?F")

            # 价差偏高（近月高估）→ 做空近月 + 做多远月
            # 价差偏低（近月低估）→ 做多近月 + 做空远月
            if z > 0:
                near_dir, far_dir = "bear", "bull"
            else:
                near_dir, far_dir = "bull", "bear"
            raw = min(1.0, abs(z) / 3.0)

            meta = {
                "variety": str(sym),
                "near_contract": near_code,
                "far_contract": far_code,
                "z_score": round(z, 2),
                "half_life": round(hl, 1),
                "spread": round(float(spread[-1]), 2),
                "spread_pct": round(float(info.get("spread_pct", [0])[-1]), 4)
                if info.get("spread_pct") else None,
                "type": "spread_reversion",
            }

            signals.append(RawSignal(
                symbol=near_code, direction=near_dir,
                signal_type=f"{self.signal_type}.near.{near_code}",
                raw_score=raw, strategy_name=self.name,
                meta={**meta, "leg": "near"},
            ))
            signals.append(RawSignal(
                symbol=far_code, direction=far_dir,
                signal_type=f"{self.signal_type}.far.{far_code}",
                raw_score=raw, strategy_name=self.name,
                meta={**meta, "leg": "far"},
            ))

        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)
            total = raw * 100 if s.direction == "bull" else -raw * 100
            grade = "WATCH" if raw > 0.8 else "WEAK" if raw > 0.4 else "NOISE"
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=round(total, 1),
                abs_score=round(raw * 100, 1),
                grade=grade,
                weight=0.7,
            )
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
