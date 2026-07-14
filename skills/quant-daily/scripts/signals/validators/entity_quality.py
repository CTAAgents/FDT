"""V5 实体质量验证器 — 长影线十字突破不可靠（公开主流因子：实体/振幅比）。

实体/振幅比 = |close-open| / (high-low)。比值过低（< BODY_RATIO_MIN）即长上/下影线十字，
说明突破被快速打回，信号质量差。主要用于 minor_signal 这类弱信号。
"""

from . import register_validator
from .base import demote

BODY_RATIO_MIN = 0.3  # 实体/振幅 < 0.3 视为长影线十字，突破不可靠


def validate_entity_quality(r, context):
    if r.get("signal_type") not in ("minor_signal",):
        return
    sym = r.get("symbol", "")
    dlist = (context.kline_data.get(sym) or (None, []))[1]
    if not dlist:
        return
    last = dlist[-1]
    try:
        o, h, l, c = (float(last.get(k, 0)) for k in ("open", "high", "low", "close"))
    except (ValueError, TypeError):
        return
    rng = h - l
    if rng > 0 and abs(c - o) / rng < BODY_RATIO_MIN:
        demote(r, f"长影线十字(实体比{abs(c - o) / rng:.2f}<{BODY_RATIO_MIN})信号不可靠")


register_validator("entity_quality", validate_entity_quality)
