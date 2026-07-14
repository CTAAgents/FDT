"""
均值回归策略 — RSI/CCI/布林带极端反转。

数据来源：全部来自 scan_all 指标管线已有的 tech_list 字段
  (rsi, cci, bb, adx)，零新采集。
"""

from __future__ import annotations
from typing import Any

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal


# ── 阈值配置 ──
RSI_OVERSOLD = 25        # RSI 低于此值 → 超卖做多
RSI_OVERBOUGHT = 75      # RSI 高于此值 → 超买做空
CCI_OVERSOLD = -200      # CCI 低于此值 → 极度超卖
CCI_OVERBOUGHT = 200     # CCI 高于此值 → 极度超买
BB_LOWER_THRESHOLD = 0.1  # 布林带 %b 低于此 → 下轨外做多
BB_UPPER_THRESHOLD = 0.9  # 布林带 %b 高于此 → 上轨外做空
ADX_MAX = 25             # ADX 低于此 → 震荡市（反转策略偏好）


class MeanReversionStrategy(BaseStrategyV2):
    """均值回归：RSI/CCI/BB 极端值回归。"""

    @property
    def name(self) -> str:
        return "mean_reversion"

    @property
    def display_name(self) -> str:
        return "均值回归(RSI+CCI+布林带)"

    @property
    def signal_type(self) -> str:
        return "mean_reversion"

    @property
    def validators(self) -> list[str]:
        return ["atr_vol_timing", "stability"]

    def compute(self, tech_list: list[dict], kline_data: dict,
                context: dict | None = None) -> list[RawSignal]:
        signals: list[RawSignal] = []

        for t in tech_list:
            sym = t.get("symbol", "")
            adx = float(t.get("adx", 0))
            rsi = float(t.get("rsi", 50))
            cci = float(t.get("cci", 0))
            bb = t.get("bb", 0)
            price = float(t.get("price", 0))

            # 趋势市不做反转（ADX > 25）
            in_ranging = adx == 0 or adx < ADX_MAX

            sub_signals: list[tuple[str, float, str]] = []

            # 1. RSI 极端反转
            if in_ranging and 0 < rsi < RSI_OVERSOLD:
                strength = (RSI_OVERSOLD - rsi) / RSI_OVERSOLD
                sub_signals.append(("rsi", strength, "bull"))
            elif in_ranging and rsi > RSI_OVERBOUGHT:
                strength = (rsi - RSI_OVERBOUGHT) / (100 - RSI_OVERBOUGHT)
                sub_signals.append(("rsi", strength, "bear"))

            # 2. CCI 极值回归
            if in_ranging and cci < CCI_OVERSOLD and cci > -999:
                strength = min(1.0, (CCI_OVERSOLD - cci) / 200)
                sub_signals.append(("cci", strength, "bull"))
            elif in_ranging and cci > CCI_OVERBOUGHT:
                strength = min(1.0, (cci - CCI_OVERBOUGHT) / 200)
                sub_signals.append(("cci", strength, "bear"))

            # 3. 布林带反转（bb 须在 0-1 有效范围内）
            if isinstance(bb, (int, float)) and 0 <= bb <= 1:
                if in_ranging and bb < BB_LOWER_THRESHOLD and bb > 0:
                    strength = (BB_LOWER_THRESHOLD - bb) / BB_LOWER_THRESHOLD
                    sub_signals.append(("bb", strength, "bull"))
                elif in_ranging and bb > BB_UPPER_THRESHOLD:
                    strength = (bb - BB_UPPER_THRESHOLD) / (1 - BB_UPPER_THRESHOLD)
                    sub_signals.append(("bb", strength, "bear"))

            # 融合：多个子信号投票决定方向
            if sub_signals:
                bull_strength = sum(s for _, s, d in sub_signals if d == "bull")
                bear_strength = sum(s for _, s, d in sub_signals if d == "bear")
                if bull_strength > bear_strength:
                    direction = "bull"
                    raw = bull_strength
                elif bear_strength > bull_strength:
                    direction = "bear"
                    raw = bear_strength
                else:
                    continue

                signals.append(RawSignal(
                    symbol=sym,
                    direction=direction,
                    signal_type=f"{self.signal_type}.reversal",
                    raw_score=round(raw, 3),
                    strategy_name=self.name,
                    meta={
                        "rsi": rsi, "cci": cci, "bb": bb,
                        "adx": adx, "price": price,
                        "sub_types": [s[0] for s in sub_signals],
                    },
                ))

        return signals

    def score(self, filtered_signals: list[RawSignal],
              tech_list: list[dict],
              context: dict | None = None) -> list[ScoredSignal]:
        result: list[ScoredSignal] = []
        for s in filtered_signals:
            raw = abs(s.raw_score)
            # 强度映射：>0.6 → WATCH, >0.3 → WEAK, 其余 NOISE
            grade = "WATCH" if raw > 0.5 else "WEAK" if raw > 0.2 else "NOISE"
            total = raw * 100 if s.direction == "bull" else -raw * 100
            ss = ScoredSignal(
                symbol=s.symbol,
                direction=s.direction,
                signal_type=s.signal_type,
                strategy_name=self.name,
                total=round(total, 1),
                abs_score=round(raw * 100, 1),
                grade=grade,
                weight=0.6,
            )
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
