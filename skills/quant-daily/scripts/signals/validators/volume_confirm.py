"""V2 成交量确认验证器 + OI 持仓量联合增强 — 突破需放量（公开主流因子：量比）。

突破若无明显放量（量比低于正常下限），极可能是无量假突破。
阈值 VOL_MIN_RATIO 取自 CHANNEL_BREAKOUT_CONFIG.default.volume.normal_lower_ratio（默认 0.8）。

【增强】OI 量比联合判断：
- 量比 < 0.8 但 OI 暴增(>+15%) → 主力建仓，不降级
- 量比 > 1.5 但 OI 萎缩(<-10%) → 主力出货，降级
"""

from . import register_validator
from .base import demote

try:
    from config.settings import CHANNEL_BREAKOUT_CONFIG
    _VOL = CHANNEL_BREAKOUT_CONFIG.get("default", {}).get("volume", {})
    VOL_MIN_RATIO = float(_VOL.get("normal_lower_ratio", 0.8))
except Exception:
    VOL_MIN_RATIO = 0.8  # 兜底：低于此量比视为明显缩量

# ── OI 量比联合阈值（从 config/settings.py 集中读取） ──
try:
    from config.settings import ENHANCED_VALIDATOR_THRESHOLDS as _EVT
    OI_SURGE_THRESHOLD = float(_EVT.get("OI_SURGE_THRESHOLD", 15.0))
    OI_SHRINK_THRESHOLD = float(_EVT.get("OI_SHRINK_THRESHOLD", -10.0))
except Exception:
    OI_SURGE_THRESHOLD = 15.0
    OI_SHRINK_THRESHOLD = -10.0
VOL_HIGH_RATIO = 1.5         # 高量比阈值，配合 OI 萎缩判断


def _is_breakout_signal(signal_type: str) -> bool:
    """检查 signal_type 是否属突破类信号（v1 名称或 v2 命名空间前缀匹配）。"""
    breakout_prefixes = ("channel_breakout", "trend_following", "bb_squeeze")
    return any(signal_type.startswith(p) for p in breakout_prefixes)


def validate_volume_confirm(r, context):
    if not _is_breakout_signal(r.get("signal_type", "")):
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
    vol_ratio = last_vol / prior_avg if prior_avg > 0 else 0

    # ── OI 联合判断 ──
    oi_info = (context.extra or {}).get("oi_data", {}).get(sym, {})
    oi_change = oi_info.get("oi_change_pct", 0)

    # 量小但 OI 暴增 → 主力建仓（V1 已覆写，V2 不再重复处理）
    if vol_ratio < VOL_MIN_RATIO and oi_change > OI_SURGE_THRESHOLD:
        if not r.get("_oi_surge_reversal"):
            r["_oi_surge_reversal"] = True
        return

    # 量大但 OI 萎缩 → 主力出货，降级
    if vol_ratio > VOL_HIGH_RATIO and oi_change < OI_SHRINK_THRESHOLD:
        demote(r, f"放量(量比{vol_ratio:.2f})但OI萎缩({oi_change:+.1f}%)→出货假突破")
        return

    # 纯量比判断（OI 数据不存在或未触发联合条件时）
    if vol_ratio < VOL_MIN_RATIO:
        demote(r, f"突破无量(量比{vol_ratio:.2f}<{VOL_MIN_RATIO})疑似假突破")


register_validator("volume_confirm", validate_volume_confirm)
