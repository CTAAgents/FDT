"""V3 ATR 波动率择时验证器 — 低波动震荡市突破易假（公开主流因子：ATR% = atr / price）。

期货实证：ATR 择时可 +91% 收益 / -79% 回撤，震荡市（低 ATR%）突破可靠性显著下降。
低波动（atr% < ATR_PCT_LOW）突破 → 降级；高波动（atr% > ATR_PCT_HIGH）仅标记不拦（趋势市可能真突破）。
"""

from . import register_validator
from .base import demote

ATR_PCT_LOW = 0.5   # 低波动阈值(%)，低于则震荡市突破可靠性低 → 降级
ATR_PCT_HIGH = 4.0  # 高波动阈值(%)，高于则失控，仅标记供下游参考


def validate_atr_vol_timing(r, context):
    if r.get("signal_type") not in ("channel_breakout", "bb_squeeze_prebreakout", "near_breakout", "minor_signal"):
        return
    atr = r.get("atr", 0)
    price = r.get("price", 0)
    if not (atr and price):
        return
    atr_pct = atr / price * 100
    if atr_pct < ATR_PCT_LOW:
        demote(r, f"低波动震荡(atr%={atr_pct:.2f}<{ATR_PCT_LOW})突破可靠性低")
    elif atr_pct > ATR_PCT_HIGH:
        r["_atr_hot"] = True  # 高波动不拦，标记供下游


register_validator("atr_vol_timing", validate_atr_vol_timing)
