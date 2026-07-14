"""V3 ATR 波动率择时验证器 + 基差联合增强 — 低波动震荡市突破易假（公开主流因子：ATR%）。

期货实证：ATR 择时可 +91% 收益 / -79% 回撤，震荡市（低 ATR%）突破可靠性显著下降。
低波动（atr% < ATR_PCT_LOW）突破 → 降级；高波动（atr% > ATR_PCT_HIGH）仅标记不拦。

【增强】基差+低波联合判断：
- ATR% < 0.5% 但基差走阔(basis_pct > +2%) → 弹簧压缩，不降级
- ATR% > 4.0% 且 Contango 加深 → 过热，降级
"""

from . import register_validator
from .base import demote

ATR_PCT_LOW = 0.5   # 低波动阈值(%)，低于则震荡市突破可靠性低 → 降级
ATR_PCT_HIGH = 4.0  # 高波动阈值(%)，高于则失控，仅标记供下游参考

# ── 基差联合阈值 ──
BASIS_WIDEN_THRESHOLD = 2.0   # 基差走阔 %（正=现货更强），低波+基差走阔=弹簧压缩
BASIS_SHRINK_THRESHOLD = -2.0 # 基差收缩 %，高波+基差收缩=过热迹象


def validate_atr_vol_timing(r, context):
    if r.get("signal_type") not in ("channel_breakout", "bb_squeeze_prebreakout", "near_breakout", "minor_signal"):
        return
    atr = r.get("atr", 0)
    price = r.get("price", 0)
    if not (atr and price):
        return
    atr_pct = atr / price * 100
    
    # ── 基差联合判断 ──
    basis_info = (context.extra or {}).get("basis_data", {}).get(r.get("symbol", "").upper(), {})
    basis_pct = basis_info.get("basis_pct", 0)

    # 低波 + 基差走阔 → 弹簧压缩（V1 已覆写，V3 不再重复处理）
    if atr_pct < ATR_PCT_LOW and basis_pct > BASIS_WIDEN_THRESHOLD:
        if not r.get("_strangle_compressed"):
            r["_strangle_compressed"] = True
            r["_override_reason"] = f"基差走阔(basis_pct={basis_pct:+.2f}%)弹簧压缩覆写降级"
        return
    
    # 高波 + 基差收缩 → 过热，降级
    if atr_pct > ATR_PCT_HIGH and basis_pct < BASIS_SHRINK_THRESHOLD:
        demote(r, f"高波({atr_pct:.2f}%)+基差收缩(basis_pct={basis_pct:+.2f}%)→过热信号")
        return

    if atr_pct < ATR_PCT_LOW:
        demote(r, f"低波动震荡(atr%={atr_pct:.2f}<{ATR_PCT_LOW})突破可靠性低")
    elif atr_pct > ATR_PCT_HIGH:
        r["_atr_hot"] = True  # 高波动不拦，标记供下游


register_validator("atr_vol_timing", validate_atr_vol_timing)
