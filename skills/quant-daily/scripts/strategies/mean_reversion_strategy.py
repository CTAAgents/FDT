"""
均值回归策略 — RSI/CCI/布林带极端反转。

数据来源：全部来自 scan_all 指标管线已有的 tech_list 字段
  (rsi, cci, bb, adx)，零新采集。
"""

from __future__ import annotations
from typing import Any

import numpy as np

from .base_v2 import BaseStrategyV2, RawSignal, ScoredSignal, format_reason
from .spread_reversion_strategy import kalman_filter_ou


# ── 阈值配置 ──
RSI_OVERSOLD = 25        # RSI 低于此值 → 超卖做多
RSI_OVERBOUGHT = 75      # RSI 高于此值 → 超买做空
CCI_OVERSOLD = -200      # CCI 低于此值 → 极度超卖
CCI_OVERBOUGHT = 200     # CCI 高于此值 → 极度超买
BB_LOWER_THRESHOLD = 0.1  # 布林带 %b 低于此 → 下轨外做多
BB_UPPER_THRESHOLD = 0.9  # 布林带 %b 高于此 → 上轨外做空
ADX_MAX = 25             # ADX 低于此 → 震荡市（反转策略偏好）
KF_Z_MAX = 2.5           # KF 自适应 z 超过此值 → 均值加速偏移 → 压制回归信号 (G37 Phase 3)
KF_MIN_BARS = 20         # KF 所需最小 bar 数
BB_BANDWIDTH_MIN = 0.03  # 布林带带宽下限（< 3% = 极度压缩 → 反转高概率；G39）


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

        # ── 从 kline_data 建立收盘价索引（供 KF 制度过滤使用）──
        kline_map: dict[str, np.ndarray] = {}
        for _sym, (_name, _bars) in (kline_data or {}).items():
            _closes = [float(b.get("close", 0)) for b in _bars if b.get("close")]
            if len(_closes) >= KF_MIN_BARS:
                kline_map[str(_sym).upper()] = np.array(_closes, dtype=float)

        for t in tech_list:
            sym = t.get("symbol", "")
            adx = float(t.get("adx", 0))
            rsi = float(t.get("rsi", 50))
            cci = float(t.get("cci", 0))
            bb = t.get("bb", 0)
            price = float(t.get("price", 0))
            bb_width = float(t.get("bb_width", 1.0))  # 1.0 缺省（可接受）

            # ── KF 制度过滤器（G37 Phase 3）：均值加速偏移 → 压制回归信号 ──
            kf_z = 0.0
            kf_regime_ok = True
            _closes = kline_map.get(str(sym).upper())
            if _closes is not None and len(_closes) >= KF_MIN_BARS:
                kf = kalman_filter_ou(_closes)
                kf_z = abs(kf["z_score"])
                if kf_z > KF_Z_MAX:
                    kf_regime_ok = False

            # 趋势市不做反转（ADX > 25 或 KF 检测到均值加速偏移）
            in_ranging = (adx == 0 or adx < ADX_MAX) and kf_regime_ok
            # 布林带带宽门禁（G39）：带宽极低 → 压缩态 → 反转高概率窗口
            bb_bandwidth_ok = bb_width < BB_BANDWIDTH_MIN or bb_width <= 0.10
            # 若无 bb_width 数据（缺省 1.0）→ 不压制信号
            in_ranging = in_ranging and (bb_width >= 1.0 or bb_bandwidth_ok)

            # ── 各子信号独立产出（v8.1.8 去融合：不投票、不坍缩）──
            # 每个子信号各自产一条 RawSignal，signal_type 带子类型命名空间
            # （mean_reversion.rsi / .cci / .bb），辩论环节据 signal_type 可见
            # 是哪个子信号触发，绝不被投票合并成一条 .reversal。

            def _emit(sub: str, strength: float, direction: str) -> None:
                signals.append(RawSignal(
                    symbol=sym,
                    direction=direction,
                    signal_type=f"{self.signal_type}.{sub}",
                    raw_score=round(strength, 3),
                    strategy_name=self.name,
                    meta={
                        "sub_type": sub,
                        "rsi": rsi, "cci": cci, "bb": bb,
                        "adx": adx, "price": price,
                        "kf_z_score": round(kf_z, 2),
                        "kf_suppressed": not kf_regime_ok,
                        "bb_width": round(bb_width, 4) if bb_width != 1.0 else None,
                    },
                ))

            # 1. RSI 极端反转
            if in_ranging and 0 < rsi < RSI_OVERSOLD:
                _emit("rsi", (RSI_OVERSOLD - rsi) / RSI_OVERSOLD, "bull")
            elif in_ranging and rsi > RSI_OVERBOUGHT:
                _emit("rsi", (rsi - RSI_OVERBOUGHT) / (100 - RSI_OVERBOUGHT), "bear")

            # 2. CCI 极值回归
            if in_ranging and cci < CCI_OVERSOLD and cci > -999:
                _emit("cci", min(1.0, (CCI_OVERSOLD - cci) / 200), "bull")
            elif in_ranging and cci > CCI_OVERBOUGHT:
                _emit("cci", min(1.0, (cci - CCI_OVERBOUGHT) / 200), "bear")

            # 3. 布林带反转（bb 须在 0-1 有效范围内）
            if isinstance(bb, (int, float)) and 0 <= bb <= 1:
                if in_ranging and bb < BB_LOWER_THRESHOLD and bb > 0:
                    _emit("bb", (BB_LOWER_THRESHOLD - bb) / BB_LOWER_THRESHOLD, "bull")
                elif in_ranging and bb > BB_UPPER_THRESHOLD:
                    _emit("bb", (bb - BB_UPPER_THRESHOLD) / (1 - BB_UPPER_THRESHOLD), "bear")

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
            # reason：子策略身份 + 关键条件，供辩论环节识别"为什么选这个信号"
            _m = s.meta
            _metrics = {}
            if _m.get("rsi"):
                _metrics["RSI"] = round(_m["rsi"], 1)
            if _m.get("cci"):
                _metrics["CCI"] = round(_m["cci"], 1)
            if _m.get("bb") is not None:
                _metrics["BB%b"] = round(_m["bb"], 2)
            if _m.get("adx"):
                _metrics["ADX"] = round(_m["adx"], 1)
            _note = "KF压制(均值加速偏移)" if _m.get("kf_suppressed") else ""
            ss.reason = format_reason(
                s.signal_type, s.direction, grade,
                metrics=_metrics or None,
                strength=round(raw, 2),
                note=_note,
            )
            ss.extra = dict(s.meta)
            result.append(ss)
        return result
