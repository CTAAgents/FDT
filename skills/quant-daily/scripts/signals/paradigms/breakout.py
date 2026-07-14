"""P1 通道突破范式 — 计算实体 = 既有 ChannelBreakoutStrategy，此处仅注册为范式。

不重写任何计算逻辑：ChannelBreakoutStrategy 已是 FDT 主力信号引擎，范式层只声明
它覆盖哪些 signal_type、该配哪些验证器（与 SIGNAL_VALIDATOR_MAP 中 channel_breakout 等条目对应）。
未来聚焦：调 DC20/DC55/BB/ATR 等公开因子的权重与阈值（在 config/settings.py）。
"""

from . import register_paradigm


class BreakoutParadigm:
    id = "breakout"
    label = "通道突破 (Donchian DC20/DC55 + Bollinger + ATR)"
    # 覆盖的 signal_type（与 ChannelBreakoutStrategy 产出一致）
    signal_types = ["channel_breakout", "trend_confirmation", "bb_squeeze_prebreakout", "near_breakout"]
    # 该配的验证器（与 SIGNAL_VALIDATOR_MAP 对应）
    validators = ["p0_4_raw_kline", "volume_confirm", "atr_vol_timing", "trend_direction"]
    # 计算实体（既有策略，不重写）
    engine_path = "strategies.channel_breakout_strategy.ChannelBreakoutStrategy"


register_paradigm("breakout", BreakoutParadigm)
