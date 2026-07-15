"""波动率目标化 overlay（G32）。

执行/风险层缩放：读 tech 的 vol_target_scale / realized_vol，注入 ScoredSignal.extra，
供下游 trade_plan 缩放仓位。纯函数 + 轻量 overlay，零新数据源。

落点说明：Vol Targeting 是现代 CTA 趋势跟踪第二基石（与 TSMOM 并列），
但它缩放的是「仓位」而非「信号方向/强度」，故落于执行/风险 overlay 层
（Pipeline Phase 4.5），而非信号评分层。与 G34 Turtle 的 N 单位头寸管理共享
同一执行/风险语义。
"""

from __future__ import annotations

from typing import Any

from .base_v2 import ScoredSignal


class VolTargetingOverlay:
    """波动率目标化 overlay。

    对每个 ScoredSignal 注入：
      - extra["vol_target_scale"]: 仓位缩放系数（tech.VOL_SCALE，默认 1.0）
      - extra["realized_vol"]: 年化已实现波动率（默认 0.0）
      - extra["vol_target_note"]: 人读说明
    """

    def apply(self, signal: ScoredSignal, tech: dict) -> ScoredSignal:
        if not isinstance(tech, dict):
            tech = {}
        # tech 字段经 _FIELD_MAP 归一化为小写 vol_target_scale / realized_vol；
        # 同时兜底读取原始大写 VOL_SCALE / REALIZED_VOL。
        scale = float(tech.get("vol_target_scale", tech.get("VOL_SCALE", 1.0)) or 1.0)
        rv = float(tech.get("realized_vol", tech.get("REALIZED_VOL", 0.0)) or 0.0)
        signal.extra["vol_target_scale"] = round(scale, 3)
        signal.extra["realized_vol"] = round(rv, 4)
        if scale > 1.05:
            signal.extra["vol_target_note"] = f"低波动({rv:.1%})→加仓至{scale:.2f}x"
        elif scale < 0.95:
            signal.extra["vol_target_note"] = f"高波动({rv:.1%})→降仓至{scale:.2f}x"
        else:
            signal.extra["vol_target_note"] = f"波动中性({rv:.1%})→1.00x"
        return signal

    @staticmethod
    def compute_scale(realized_vol: float, target: float = 0.10,
                      floor: float = 0.2, cap: float = 3.0) -> float:
        """纯函数版缩放（供单测，与 tdx_compat.calculate_vol_target_scale 等价）。"""
        if realized_vol is None or not isinstance(realized_vol, (int, float)) or realized_vol <= 1e-6:
            return 1.0
        scale = target / float(realized_vol)
        return min(cap, max(floor, scale))
