"""
套利策略 — 跨期价差 + 跨品种配对 + 期现基差。

依赖：
  - FDC f10/spread.py: compute_spread() + get_spread()
  - FDC f10/term_structure.py: analyze_term_structure()
  - 100ppi 现货价（通过 scan_all 的 _collect_basis_data_sync 注入 context）
"""

from __future__ import annotations
import asyncio
from statistics import mean, stdev
from typing import Any

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal, format_reason


# ── 跨品种配对表（hardcoded，产业链逻辑） ──
# pair: (leg_a, leg_b, ratio)  ratio=leg_a/leg_b 的合理比率
# 信号：比率偏离合理区间时做多弱势品种+做空强势品种
CROSS_VARIETY_PAIRS: dict[str, dict] = {
    "RB-HC": {"a": "RB", "b": "HC", "ratio": 1.05, "z_window": 20,
              "name": "螺卷价差"},
    "I-J":  {"a": "I", "b": "J", "ratio": 0.40, "z_window": 20,
             "name": "矿焦比"},
    "TA-EG": {"a": "TA", "b": "EG", "ratio": 2.5, "z_window": 20,
              "name": "PTA-乙二醇"},
    "M-RM": {"a": "M", "b": "RM", "ratio": 1.3, "z_window": 20,
             "name": "豆粕-菜粕"},
    "Y-OI": {"a": "Y", "b": "OI", "ratio": 1.0, "z_window": 20,
             "name": "豆油-菜油"},
    "SA-FG": {"a": "SA", "b": "FG", "ratio": 1.2, "z_window": 20,
              "name": "纯碱-玻璃"},
}


# ── 内部辅助 ──
def _pair_key(a: str, b: str) -> str:
    return f"{a}-{b}".upper()


def _compute_zscore(values: list[float], current: float) -> float:
    """滚动 Z-score。数据不足时返回 0。"""
    if len(values) < 5:
        return 0.0
    mu = mean(values)
    sigma = stdev(values)
    return (current - mu) / sigma if sigma > 0 else 0.0


async def _fetch_calendar_spread(symbol: str) -> dict[str, Any]:
    """异步获取跨期价差（FDC f10/spread.py）。"""
    from futures_data_core.f10.spread import get_spread
    try:
        payload = await get_spread(symbol)
        if payload and payload.data:
            return payload.data
    except Exception:
        pass
    return {}


def _fetch_calendar_spread_sync(symbol: str) -> dict[str, Any]:
    """同步包装器。"""
    try:
        return asyncio.run(_fetch_calendar_spread(symbol))
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════
# 策略类
# ════════════════════════════════════════════════════════════

class ArbitrageStrategy(BaseStrategyV2):
    """套利策略：跨期价差 + 跨品种配对 + 期现基差。"""

    @property
    def name(self) -> str:
        return "arbitrage"

    @property
    def display_name(self) -> str:
        return "套利(跨期+跨品种+基差)"

    @property
    def signal_type(self) -> str:
        return "arbitrage"

    @property
    def validators(self) -> list[str]:
        return ["atr_vol_timing", "stability"]

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        signals: list[RawSignal] = []
        ctx = context or {}
        basis_data = ctx.get("extra", {}).get("basis_data", {})

        # 1. 期现基差信号（每个品种）
        for t in tech_list:
            sym = t.get("symbol", "").upper()
            bd = basis_data.get(sym, {})
            bp = bd.get("basis_pct", 0)
            if abs(bp) > 3.0:
                direction = "bull" if bp > 0 else "bear"
                signals.append(RawSignal(
                    symbol=sym,
                    direction=direction,
                    signal_type=f"{self.signal_type}.basis",
                    raw_score=abs(bp),
                    strategy_name=self.name,
                    meta={"basis_pct": bp, "type": "basis"},
                ))

        # 2. 跨品种配对信号
        price_map = {t.get("symbol", "").upper(): t.get("price", 0) for t in tech_list}
        for pk, pair in CROSS_VARIETY_PAIRS.items():
            pa, pb = pair["a"].upper(), pair["b"].upper()
            if pa not in price_map or pb not in price_map:
                continue
            pa_price, pb_price = price_map[pa], price_map[pb]
            if pb_price <= 0:
                continue
            current_ratio = pa_price / pb_price
            z = (current_ratio - pair["ratio"]) / (pair["ratio"] * 0.05)  # 简化 z
            if abs(z) > 1.0:
                # 比率偏高 → 做空强势品种(a)，做多弱势品种(b)
                direction = "bear" if z > 0 else "bull"
                signals.append(RawSignal(
                    symbol=f"{pk}",
                    direction=direction,
                    signal_type=f"{self.signal_type}.pair",
                    raw_score=abs(z),
                    strategy_name=self.name,
                    meta={
                        "pair_a": pa, "pair_b": pb,
                        "current_ratio": round(current_ratio, 4),
                        "target_ratio": pair["ratio"],
                        "z_score": round(z, 2),
                        "type": "pair",
                    },
                ))

        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        tech_map = {t.get("symbol", "").upper(): t for t in tech_list}
        for s in filtered_signals:
            raw = abs(s.raw_score)
            total = raw if s.direction == "bull" else -raw
            # grade: 强信号直接给 WATCH
            grade = "WATCH" if raw > 2.0 else "WEAK"
            sig_type = s.meta.get("type", "unknown")
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=total,
                abs_score=raw,
                grade=grade,
                weight=0.7,
            )
            # reason：子信号身份 + 关键条件，供辩论环节识别"为什么选这个信号"
            _m = s.meta
            _metrics = {}
            if _m.get("basis_pct") is not None:
                _metrics["basis_pct"] = round(_m["basis_pct"], 2)
            if _m.get("z_score") is not None:
                _metrics["z"] = round(_m["z_score"], 2)
            if _m.get("pair_a"):
                _metrics["pair"] = f"{_m['pair_a']}-{_m['pair_b']}"
            ss.reason = format_reason(
                s.signal_type, s.direction, grade,
                metrics=_metrics or None, strength=round(raw, 2))
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
