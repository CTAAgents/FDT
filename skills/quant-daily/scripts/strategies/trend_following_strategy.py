"""
趋势跟踪策略 v2 — DC20/DC55/BB 通道突破（纯简版）。

复用 scan_all 指标管线已有的技术字段，零新采集。
与 v1 ChannelBreakoutStrategy 的核心逻辑一致但精简，
直接实现 BaseStrategyV2 接口。
"""

from __future__ import annotations
from statistics import mean, stdev
from typing import Any

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal


def _score_dc20(close: float, dc20_high: float, dc20_low: float) -> tuple[float, str]:
    """DC20 打分：价格相对通道位置。返回 (score_0_1, direction)。"""
    if dc20_high <= 0 or dc20_low <= 0 or dc20_high <= dc20_low:
        return 0.0, "neutral"
    pos = (close - dc20_low) / (dc20_high - dc20_low)
    if pos > 0.95:
        return (pos - 0.95) / 0.05, "bull"
    if pos < 0.05:
        return (0.05 - pos) / 0.05, "bear"
    return 0.0, "neutral"


def _score_dc55(close: float, dc55_high: float, dc55_low: float) -> tuple[float, str]:
    """DC55 打分：趋势方向确认。"""
    if dc55_high <= 0 or dc55_low <= 0 or dc55_high <= dc55_low:
        return 0.0, "neutral"
    pos = (close - dc55_low) / (dc55_high - dc55_low)
    if pos > 0.80:
        return (pos - 0.80) / 0.20, "bull"
    if pos < 0.20:
        return (0.20 - pos) / 0.20, "bear"
    return 0.0, "neutral"


def _score_bb(bb: float) -> tuple[float, str]:
    """布林带 %b 打分。"""
    if not isinstance(bb, (int, float)):
        return 0.0, "neutral"
    if bb > 0.95:
        return (bb - 0.95) / 0.05, "bull"
    if bb < 0.05:
        return (0.05 - bb) / 0.05, "bear"
    return 0.0, "neutral"


class TrendFollowingStrategy(BaseStrategyV2):
    """趋势跟踪：DC20/DC55 + 布林带通道突破（v2 精简版）。"""

    @property
    def name(self) -> str:
        return "trend_following"

    @property
    def display_name(self) -> str:
        return "趋势跟踪(通道突破v2)"

    @property
    def signal_type(self) -> str:
        return "trend_following"

    @property
    def validators(self) -> list[str]:
        return ["p0_4_raw_kline", "volume_confirm", "atr_vol_timing"]

    @property
    def weight(self) -> float:
        return 1.0  # 趋势信号权重最高

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        signals: list[RawSignal] = []
        for t in tech_list:
            sym = t.get("symbol", "")
            close = float(t.get("price", 0))
            if close <= 0:
                continue

            dc20_h = float(t.get("dc20_high", t.get("dc20_max", 0)))
            dc20_l = float(t.get("dc20_low", t.get("dc20_min", 0)))
            dc55_h = float(t.get("dc55_high", t.get("dc55_max", 0)))
            dc55_l = float(t.get("dc55_low", t.get("dc55_min", 0)))
            bb_val = t.get("bb", 0.5)
            adx = float(t.get("adx", 0))

            # 三层打分
            s20, d20 = _score_dc20(close, dc20_h, dc20_l)
            s55, d55 = _score_dc55(close, dc55_h, dc55_l)
            sbb, dbb = _score_bb(bb_val)

            # 方向投票：DC20(3票) + DC55(2票) + BB(1票)
            votes: dict[str, float] = {"bull": 0.0, "bear": 0.0}
            for d, s in [(d20, s20), (d55, s55), (dbb, sbb)]:
                if d != "neutral":
                    votes[d] += s
            if votes["bull"] == 0 and votes["bear"] == 0:
                continue

            direction = "bull" if votes["bull"] > votes["bear"] else "bear"
            raw = max(votes["bull"], votes["bear"])

            # 子类型
            sub = []
            if s20 > 0:
                sub.append("dc20")
            if s55 > 0:
                sub.append("dc55")
            if sbb > 0:
                sub.append("bb")
            signal_type = f"{self.signal_type}.{'+'.join(sub) if sub else 'mixed'}"

            signals.append(RawSignal(
                symbol=sym,
                direction=direction,
                signal_type=signal_type,
                raw_score=round(raw, 3),
                strategy_name=self.name,
                meta={
                    "dc20_score": round(s20, 3),
                    "dc55_score": round(s55, 3),
                    "bb_score": round(sbb, 3),
                    "adx": adx,
                    "close": close,
                },
            ))
        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)
            # raw ∈ [0, 1];  映射到绝対分
            total = raw * 100 if s.direction == "bull" else -raw * 100
            abs_score = raw * 100
            grade = "STRONG" if raw > 0.75 else "WATCH" if raw > 0.5 else "WEAK" if raw > 0.2 else "NOISE"
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=round(total, 1),
                abs_score=round(abs_score, 1),
                grade=grade,
                weight=self.weight,
            )
            ss.sub_scores = {
                "dc20": s.meta.get("dc20_score", 0),
                "dc55": s.meta.get("dc55_score", 0),
                "bb": s.meta.get("bb_score", 0),
            }
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
