"""P3 均值回归范式（骨架）— 未来聚焦位：填 Bollinger %B / 价格 Z-Score 公开主流因子实现。

当前 FDT 的均值回归信号（minor_signal / bb_squeeze_prebreakout 部分）由 ChannelBreakoutStrategy
的 BB 评分承担，本范式仅声明元信息与验证器映射。RSI 阈值属过拟合陷阱，仅作辅助，不进核心。
"""

from . import register_paradigm


class MeanReversionParadigm:
    id = "mean_reversion"
    label = "均值回归 (Bollinger %B / 价格 Z-Score)"
    signal_types = ["minor_signal", "bb_squeeze_prebreakout"]
    validators = ["entity_quality", "atr_vol_timing", "stability"]
    note = "骨架：计算逻辑由 channel_breakout_strategy 的 BB 评分承担，本范式仅声明元信息与验证器映射。"


register_paradigm("mean_reversion", MeanReversionParadigm)
