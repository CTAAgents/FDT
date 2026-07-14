"""V2 成交量确认验证器 — 突破需放量（公开主流因子：量比 = 末根量 / 前 20 根均量）。

突破若无明显放量（量比低于正常下限），极可能是无量假突破。
阈值 VOL_MIN_RATIO 取自 CHANNEL_BREAKOUT_CONFIG.default.volume.normal_lower_ratio（默认 0.8），
与打分层缩量判定口径一致，集中可调。
"""

from . import register_validator
from .base import demote

try:
    from config.settings import CHANNEL_BREAKOUT_CONFIG
    _VOL = CHANNEL_BREAKOUT_CONFIG.get("default", {}).get("volume", {})
    VOL_MIN_RATIO = float(_VOL.get("normal_lower_ratio", 0.8))
except Exception:
    VOL_MIN_RATIO = 0.8  # 兜底：低于此量比视为明显缩量


def validate_volume_confirm(r, context):
    if r.get("signal_type") not in ("channel_breakout", "bb_squeeze_prebreakout"):
        return
    sym = r.get("symbol", "")
    dlist = (context.kline_data.get(sym) or (None, []))[1]
    if len(dlist) < 21:
        return
    last = dlist[-1]
    prior = dlist[-21:-1]
    try:
        last_vol = float(last.get("volume", 0))
        prior_avg = sum(float(x.get("volume", 0)) for x in prior) / len(prior)
    except (ValueError, TypeError):
        return
    if prior_avg > 0 and last_vol / prior_avg < VOL_MIN_RATIO:
        demote(r, f"突破无量(量比{last_vol / prior_avg:.2f}<{VOL_MIN_RATIO})疑似假突破")


register_validator("volume_confirm", validate_volume_confirm)
