"""Turtle 完整系统 overlay（G34）。

执行/风险层纪律：读 tech 的 DC20/55 突破状态 + turtle_n，注入 ScoredSignal.extra，
供下游 trade_plan 缩放仓位（单位预算）与执行系统读取加仓/止损阶梯。
纯函数 + 轻量 overlay，零新数据源。

落点说明：Turtle 法则（Dennis/Eckhardt 1983）含 N 单位头寸 + 金字塔加仓 + 2N 退出，
属执行/风险管理，故落于执行/风险 overlay 层（Pipeline Phase 4.6），接在 G32 Vol
Targeting 之后，与 G32 共享同一执行/风险语义。信号评分层（DC20/55 突破）已由 G30 覆盖。
"""

from __future__ import annotations

from typing import Any

from .base_v2 import ScoredSignal


def _fnum(tech: dict, *keys, default: float = 0.0) -> float:
    """从 tech 按优先级取第一个存在的数值键，转 float；缺失/非数返回 default。"""
    for k in keys:
        v = tech.get(k)
        if v is not None and isinstance(v, (int, float)):
            return float(v)
    return default


class TurtleSystemOverlay:
    """Turtle 完整系统 overlay。

    对每个 ScoredSignal 注入：
      - extra["turtle_system"]: 激活系统（"S1"=DC20 / "S2"=DC55 / "none"）
      - extra["turtle_n"]: N 值（波动率基准，默认 0.0）
      - extra["turtle_units"]: 计划头寸单位数（1-4，由 abs_score 决定，默认 1）
      - extra["turtle_add_steps"]: 金字塔加仓价格阶梯（list[float]，默认空）
      - extra["turtle_stop_2n"]: 2N 退出止损价（默认 0.0）
      - extra["turtle_note"]: 人读说明
    """

    def apply(self, signal: ScoredSignal, tech: dict) -> ScoredSignal:
        if not isinstance(tech, dict):
            tech = {}
        direction = getattr(signal, "direction", "neutral")

        # 无方向信号：注入中性 turtle 元数据，不缩放
        if direction not in ("bull", "bear"):
            signal.extra["turtle_system"] = "none"
            signal.extra["turtle_units"] = 1
            signal.extra["turtle_n"] = _fnum(tech, "turtle_n", "TURTLE_N")
            signal.extra["turtle_add_steps"] = []
            signal.extra["turtle_stop_2n"] = 0.0
            signal.extra["turtle_note"] = "无方向：turtle 纪律不激活"
            return signal

        n = _fnum(tech, "turtle_n", "TURTLE_N")
        close = _fnum(tech, "last_price", "close", "LAST_PRICE")

        # 系统选择：S1=DC20 突破；S2=DC55 突破
        dc20_h = _fnum(tech, "dc20_high", "DC20_UPPER")
        dc20_l = _fnum(tech, "dc20_low", "DC20_LOWER")
        dc55_h = _fnum(tech, "dc55_high", "DC55_UPPER")
        dc55_l = _fnum(tech, "dc55_low", "DC55_LOWER")
        s1 = "bull" if (dc20_h > 0 and close > dc20_h) else ("bear" if (dc20_l > 0 and close < dc20_l) else "none")
        s2 = "bull" if (dc55_h > 0 and close > dc55_h) else ("bear" if (dc55_l > 0 and close < dc55_l) else "none")
        if s2 != "none":
            system = "S2"
        elif s1 != "none":
            system = "S1"
        else:
            system = "none"

        # 单位数：由信号强度（abs_score）决定（turtle 加仓阶梯的预算）
        _abs = abs(float(getattr(signal, "abs_score", getattr(signal, "total", 0.0)) or 0.0))
        if system == "none":
            units = 1
        elif _abs >= 92:
            units = 4
        elif _abs >= 85:
            units = 3
        elif _abs >= 75:
            units = 2
        else:
            units = 1

        sdir = 1.0 if direction == "bull" else -1.0
        add_steps: list = []
        if n > 0 and units > 1 and system != "none":
            for k in range(1, units):
                add_steps.append(round(close + sdir * 0.5 * n * k, 2))
        stop_2n = round(close - sdir * 2.0 * n, 2) if n > 0 else 0.0

        signal.extra["turtle_system"] = system
        signal.extra["turtle_units"] = units
        signal.extra["turtle_n"] = round(n, 4)
        signal.extra["turtle_add_steps"] = add_steps
        signal.extra["turtle_stop_2n"] = stop_2n
        if system == "none" or n <= 0:
            note = "turtle 未触发（无 DC 突破 / N 无效）"
        else:
            note = (
                f"{system} {direction}：N={n:.2f}，计划{units}单位，"
                f"加仓阶={add_steps}，2N止损={stop_2n:.2f}"
            )
        signal.extra["turtle_note"] = note
        return signal
