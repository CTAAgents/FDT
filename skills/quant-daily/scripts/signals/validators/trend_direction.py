"""V4 趋势方向零参数验证器 — 逆高周期趋势的突破疑似假（公开主流因子：高周期 Donchian/MA 方向）。

期货实证：趋势方向零参数过滤是最优过滤器（+53% profit-to-drawdown，零过拟合）。
高周期方向由 context.higher_tf 提供（扫描时预计算，或读 ma_align/ma_slope 作代理）。
未提供（"neutral" 或缺失）时自动跳过，绝不误伤。预留 provider 接口，不在此硬算。
"""

from . import register_validator
from .base import demote


def validate_trend_direction(r, context):
    if r.get("signal_type") not in ("channel_breakout", "trend_confirmation"):
        return
    sym = r.get("symbol", "")
    ht = context.higher_tf.get(sym, "neutral")  # "bull" / "bear" / "neutral"
    if ht == "neutral":
        return
    if ht != r.get("direction", ""):
        demote(r, f"逆高周期趋势(ht={ht})突破疑似假")


register_validator("trend_direction", validate_trend_direction)
