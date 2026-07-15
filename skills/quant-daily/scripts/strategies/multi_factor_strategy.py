"""
多因子量化策略 — 四维因子加权打分，预测品种未来收益。

因子体系（40/30/20/10 加权）：
  量价 40%: momentum(动量), volatility(波动率), volume_flow(资金流), oi(持仓量变化)
  产业 30%: basis(基差), inventory_pct(库存分位), capacity(开工率 proxy)
  宏观 20%: macro_regime(宏观制度方向), rate(利率 proxy), pmi(景气度 proxy)
  另类 10%: position_rank(龙虎持仓集中度), warrant(仓单变化)

三模式：
  pure_momentum — 纯趋势多因子：量价权重提升至 60%
  long_short    — 强弱对冲：做多因子得分前 20%，做空后 20%
  neutral       — 行业中性：限制板块暴露偏差 ≤ 15%

数据来源：
  tech_list: momentum/volatility/volume_flow 从 K 线指标计算
  context.extra: {"oi_data": ..., "basis_data": ...} 来自 FDC 注入
  context.macro_signal: 宏观制度方向（bull/bear/neutral）
"""

from __future__ import annotations
from typing import Any
import math

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal


# ── 因子权重配置（标准模式） ──
FACTOR_WEIGHTS: dict[str, float] = {
    # 量价 40%
    "momentum": 0.15,
    "volatility_reversion": 0.10,
    "volume_flow": 0.08,
    "oi_change": 0.07,
    # 产业 30%
    "basis": 0.15,
    "inventory_pct": 0.10,
    "capacity": 0.05,
    # 宏观 20%
    "macro_regime": 0.12,
    "rate_proxy": 0.04,
    "pmi_proxy": 0.04,
    # 另类 10%
    "position_rank": 0.06,
    "warrant_change": 0.04,
}

# 纯趋势模式：量价权重提升至 60%
PURE_MOMENTUM_WEIGHTS: dict[str, float] = {
    "momentum": 0.25,
    "volatility_reversion": 0.15,
    "volume_flow": 0.12,
    "oi_change": 0.08,
    "basis": 0.12,
    "inventory_pct": 0.08,
    "capacity": 0.03,
    "macro_regime": 0.08,
    "rate_proxy": 0.02,
    "pmi_proxy": 0.02,
    "position_rank": 0.04,
    "warrant_change": 0.01,
}

SCORE_THRESHOLDS = {
    "STRONG": 40,
    "WATCH": 20,
    "WEAK": 10,
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def _calc_momentum(t: dict) -> float:
    """动量因子：综合价格变化率 + MA斜率 + MACD 交叉。返回 -1 ~ +1。"""
    chg = _safe_float(t.get("change_pct", 0))
    ma_slope = _safe_float(t.get("ma_slope", 0))
    macd = str(t.get("macd_cross", "none"))

    score = 0.0
    # 价格变化贡献 ±0.5
    score += max(-0.5, min(0.5, chg / 5.0))
    # MA斜率贡献 ±0.3
    score += max(-0.3, min(0.3, ma_slope * 3.0))
    # MACD交叉贡献 ±0.2
    if macd == "gold_cross":
        score += 0.2
    elif macd == "dead_cross":
        score -= 0.2

    return max(-1.0, min(1.0, score))


def _calc_volatility_reversion(t: dict) -> float:
    """波动率因子：高波动后回归预期。返回 -1 ~ +1。"""
    atr = _safe_float(t.get("atr", 0))
    price = _safe_float(t.get("price", 0))
    bb_width = _safe_float(t.get("bb_width", 0))
    bb = _safe_float(t.get("bb", 0.5))

    score = 0.0

    # 布林带位置贡献 ±0.5
    if 0 <= bb <= 1:
        # bb > 0.8 → 上轨附近 → 偏空
        # bb < 0.2 → 下轨附近 → 偏多
        score += (0.5 - bb) * 1.0  # bb=0 → +0.5, bb=1 → -0.5

    # 布林带宽度贡献 ±0.3（收窄后扩张预期）
    if bb_width > 0:
        # 宽幅带→回归概率增加
        score += max(-0.3, min(0.3, (0.05 - bb_width) * 5))

    # ATR/价格比贡献 ±0.2（高波动→回归预期）
    if price > 0 and atr > 0:
        atr_ratio = atr / price
        # atr_ratio > 0.03 → 高波动 → 偏回归做空（假设已涨）
        # atr_ratio < 0.005 → 低波动 → 中性
        score += max(-0.2, min(0.2, (0.02 - atr_ratio) * 10))

    return max(-1.0, min(1.0, score))


def _calc_volume_flow(t: dict) -> float:
    """资金流因子：成交量变化 + 持仓倾向。返回 -1 ~ +1。"""
    vol_ratio = _safe_float(t.get("vol_ratio", 1.0))
    price = _safe_float(t.get("price", 0))
    change = _safe_float(t.get("change_pct", 0))

    score = 0.0
    # 放量上涨 → 多头确认 +0.5
    # 放量下跌 → 空头确认 -0.5
    if vol_ratio > 1.3:
        if change > 0:
            score += 0.5
        elif change < 0:
            score -= 0.5
    # 缩量 → 趋势减弱 ±0.3
    elif vol_ratio < 0.7:
        score += (change / 5.0) * 0.3 if abs(change) > 0 else 0.0

    return max(-1.0, min(1.0, score))


def _calc_oi_change(t: dict, ctx_extra: dict | None) -> float:
    """持仓量变化因子：结合 OI 变化率判断多空意图。返回 -1 ~ +1。"""
    oi_data = (ctx_extra or {}).get("oi_data", {})
    sym = str(t.get("symbol", ""))
    oi_info = oi_data.get(sym, {})

    oi_ratio = _safe_float(oi_info.get("oi_ratio", 0))
    price = _safe_float(t.get("price", 0))
    change = _safe_float(t.get("change_pct", 0))

    score = 0.0
    if abs(oi_ratio) > 0.05:
        # OI增+价涨 → 多头进场趋势 +0.6
        if oi_ratio > 0.05 and change > 0:
            score += 0.6
        # OI增+价跌 → 空头进场趋势 -0.6
        elif oi_ratio > 0.05 and change < 0:
            score -= 0.6
        # OI减+价涨 → 空头离场 +0.3
        elif oi_ratio < -0.05 and change > 0:
            score += 0.3
        # OI减+价跌 → 多头离场 -0.3
        elif oi_ratio < -0.05 and change < 0:
            score -= 0.3

    return max(-1.0, min(1.0, score))


def _calc_basis(t: dict, ctx_extra: dict | None) -> float:
    """基差因子：期现价差方向。返回 -1 ~ +1。"""
    basis_data = (ctx_extra or {}).get("basis_data", {})
    sym = str(t.get("symbol", ""))
    basis_info = basis_data.get(sym, {})

    basis_val = _safe_float(basis_info.get("basis", 0))
    basis_pct = _safe_float(basis_info.get("basis_pct", 0))

    score = 0.0
    # 基差为正（期货升水）→ 偏空（交割回归）
    if basis_pct > 2.0:
        score += -0.6
    elif basis_pct > 1.0:
        score += -0.3
    # 基差为负（期货贴水）→ 偏多
    elif basis_pct < -2.0:
        score += 0.6
    elif basis_pct < -1.0:
        score += 0.3

    return max(-1.0, min(1.0, score))


def _calc_macro(t: dict, context: dict | None) -> float:
    """宏观因子：宏观制度方向。返回 -1 ~ +1。"""
    macro = str(context.get("macro_signal", "neutral") if context else "neutral")
    if macro == "bull":
        return 0.5
    elif macro == "bear":
        return -0.5
    return 0.0


def _calc_position_rank(t: dict, ctx_extra: dict | None) -> float:
    """龙虎持仓因子：持仓集中度变化。返回 -1 ~ +1。"""
    oi_data = (ctx_extra or {}).get("oi_data", {})
    sym = str(t.get("symbol", ""))
    oi_info = oi_data.get(sym, {})

    top5_ratio = _safe_float(oi_info.get("top5_ratio", 0))
    score = 0.0
    # 多头集中度上升 → 做多信号
    if top5_ratio > 0.4:
        score += 0.3
    elif top5_ratio > 0.3:
        score += 0.15
    # 空头集中度上升 → 做空信号
    if top5_ratio < -0.3:
        score -= 0.3
    elif top5_ratio < -0.2:
        score -= 0.15

    return max(-1.0, min(1.0, score))


def _calc_warrant_change(t: dict, ctx_extra: dict | None) -> float:
    """仓单变化因子：仓单增减反映可交割供应压力。返回 -1 ~ +1。

    仓单增（供应压力↑）→ 偏空；仓单减（库存紧张↑）→ 偏多。
    G27：数据来自 ``ctx_extra['warrant_data']``（FDC ``get_warrant``，真实全量源，
    覆盖 SHFE/DCE/CZCE/GFEX）。无仓单数据（含沙箱网络受限）时惰性返回 0.0。
    """
    w_data = (ctx_extra or {}).get("warrant_data", {})
    sym = str(t.get("symbol", ""))
    w = w_data.get(sym)
    if not w:
        return 0.0
    total = _safe_float(w.get("total"), 0)
    daily_change = _safe_float(w.get("daily_change"), 0)
    if total <= 0:
        return 0.0
    # 日变动占比归一化（±5% 触顶）：增→负(空) / 减→正(多)
    pct = daily_change / total
    return max(-1.0, min(1.0, -max(-1.0, min(1.0, pct * 5.0))))


def _calc_inventory(t: dict, ctx_extra: dict | None) -> float:
    """库存分位因子：期望输入为分位值（0~1 或百分比）。返回 -1 ~ +1。

    G27 数据源探查结论：FDC 库存缓存仅 CU/RB/AU 单点绝对值（无分位/无历史），
    无法计算有意义分位 → **惰性返回 0.0（不造假信号）**。待接入 Mysteel/隆众分位源
    或配置参考区间后，缓存一旦提供 ``pct``/``percentile`` 字段即自动激活。
    """
    inv_data = (ctx_extra or {}).get("inventory_data", {})
    sym = str(t.get("symbol", ""))
    inv = inv_data.get(sym)
    if not inv:
        return 0.0
    pct = inv.get("pct") or inv.get("percentile")
    if pct is not None:
        p = _safe_float(pct) / 100.0 if _safe_float(pct) > 1 else _safe_float(pct)
        # 库存分位高（累库）→ 偏空；低（去库）→ 偏多
        return max(-1.0, min(1.0, (0.5 - p) * 2.0))
    # 单点绝对值无分位语义 → 惰性 0（数据不可用，非信号）
    return 0.0


def _calc_capacity(t: dict, ctx_extra: dict | None) -> float:
    """开工率因子：开工率高（供应充裕）→ 偏空；低（供应收紧）→ 偏多。返回 -1 ~ +1。

    G27：FDC supply 缓存仅 CU/RB/AU 单点绝对值、无参考正常开工率区间 →
    **惰性返回 0.0（不造假信号）**。缓存提供 ``pct``/``utilization_pct`` 字段即激活。
    """
    sup_data = (ctx_extra or {}).get("supply_data", {})
    sym = str(t.get("symbol", ""))
    sup = sup_data.get(sym)
    if not sup:
        return 0.0
    pct = sup.get("pct") or sup.get("utilization_pct")
    if pct is not None:
        p = _safe_float(pct) / 100.0 if _safe_float(pct) > 1 else _safe_float(pct)
        return max(-1.0, min(1.0, (0.5 - p) * 2.0))
    return 0.0


class MultiFactorStrategy(BaseStrategyV2):
    """多因子量化：四维因子加权打分预测品种未来收益。"""

    def __init__(self, mode: str = "pure_momentum"):
        self._mode = mode
        self._weights = PURE_MOMENTUM_WEIGHTS if mode == "pure_momentum" else FACTOR_WEIGHTS

    @property
    def name(self) -> str:
        return "multi_factor"

    @property
    def display_name(self) -> str:
        mode_labels = {
            "pure_momentum": "纯趋势多因子",
            "long_short": "强弱对冲多因子",
            "neutral": "行业中性多因子",
        }
        return f"多因子量化({mode_labels.get(self._mode, self._mode)})"

    @property
    def signal_type(self) -> str:
        return f"multi_factor.{self._mode}"

    @property
    def validators(self) -> list[str]:
        return ["stability"]

    @property
    def weight(self) -> float:
        return 0.7

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        ctx_extra = (context or {}).get("extra", {})
        signals: list[RawSignal] = []

        for t in tech_list:
            sym = t.get("symbol", "")
            price = _safe_float(t.get("price", 0))
            if price <= 0:
                continue

            # 计算各因子得分
            factor_scores: dict[str, float] = {
                "momentum": _calc_momentum(t),
                "volatility_reversion": _calc_volatility_reversion(t),
                "volume_flow": _calc_volume_flow(t),
                "oi_change": _calc_oi_change(t, ctx_extra),
                "basis": _calc_basis(t, ctx_extra),
                "inventory_pct": _calc_inventory(t, ctx_extra),    # G27: FDC库存(惰性待分位源)
                "capacity": _calc_capacity(t, ctx_extra),           # G27: FDC开工率(惰性待参考区间)
                "macro_regime": _calc_macro(t, context),
                "rate_proxy": 0.0,         # 宏观利率因子占位
                "pmi_proxy": 0.0,          # 宏观PMI因子占位
                "position_rank": _calc_position_rank(t, ctx_extra),
                "warrant_change": _calc_warrant_change(t, ctx_extra),   # G27: FDC仓单(真实全量源)
            }

            # 加权总分
            total_score = sum(
                factor_scores[k] * self._weights.get(k, 0)
                for k in factor_scores
            )

            # 计算有效因子数
            active_factors = sum(1 for v in factor_scores.values() if abs(v) > 0.05)

            # 低于 3 个有效因子 → 信号质量不足
            if active_factors < 3:
                continue

            direction = "bull" if total_score > 0 else ("bear" if total_score < 0 else "neutral")
            if direction == "neutral":
                continue

            signals.append(RawSignal(
                symbol=sym,
                direction=direction,
                signal_type=f"{self.signal_type}.composite",
                raw_score=round(abs(total_score), 4),
                strategy_name=self.name,
                meta={
                    "factor_scores": factor_scores,
                    "active_factors": active_factors,
                    "mode": self._mode,
                    "price": price,
                },
            ))

        # 强弱对冲模式：做多得分前 20%，做空后 20%
        if self._mode == "long_short" and signals:
            signals.sort(key=lambda s: s.raw_score, reverse=True)
            top_n = max(1, len(signals) // 5)
            for i, s in enumerate(signals):
                if i < top_n:
                    s.direction = "bull"
                elif i >= len(signals) - top_n:
                    s.direction = "bear"
                else:
                    s.direction = "neutral"
            signals = [s for s in signals if s.direction != "neutral"]

        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)
            total = raw * 100 if s.direction == "bull" else -raw * 100

            # 等级判定
            abs_total = abs(total)
            if abs_total >= SCORE_THRESHOLDS["STRONG"]:
                grade = "STRONG"
            elif abs_total >= SCORE_THRESHOLDS["WATCH"]:
                grade = "WATCH"
            elif abs_total >= SCORE_THRESHOLDS["WEAK"]:
                grade = "WEAK"
            else:
                grade = "NOISE"

            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=round(total, 1),
                abs_score=round(raw * 100, 1),
                grade=grade,
                weight=self.weight,
            )
            ss.sub_scores = s.meta.get("factor_scores", {})
            ss.extra = dict(s.meta)
            result.append(ss)

        return result
