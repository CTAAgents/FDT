"""V1 原始K线重校验门禁 (P0-4) — 防御伪造突破的最后闸门。

迁移自 scan_all._revalidate_breakouts，改为**单记录验证器**（按 signal_type 路由逐条调用）。
逻辑逐字保留：末根 high/close 是否真实穿越前 20 根极值；穿越幅度 >50% 视为 spike 伪造 → 降级 NOISE。
全程使用公开、可解释的价格极值因子，无黑盒。
"""

from . import register_validator
from .base import demote

_SPIKE_RETURN_CAP = 0.5  # 与 multi_source_adapter._SPIKE_RETURN_CAP 一致
_BREAKOUT_SIGNALS = {"channel_breakout", "trend_confirmation", "bb_squeeze_prebreakout"}


def validate_p0_4_raw_kline(r: dict, context) -> None:
    sig = r.get("signal_type", "")
    if sig not in _BREAKOUT_SIGNALS:
        return
    sym = r.get("symbol", "")
    dlist = (context.kline_data.get(sym) or (None, []))[1]
    if len(dlist) < 21:
        return
    prior = dlist[-21:-1]  # 前 20 根（排除候选突破根本身）
    last = dlist[-1]
    try:
        last_high = float(last.get("high", 0))
        last_low = float(last.get("low", 0))
        last_close = float(last.get("close", 0))
        prior_max_h = max(float(x.get("high", 0)) for x in prior)
        prior_min_l = min(float(x.get("low", 0)) for x in prior)
        prior_max_c = max(float(x.get("close", 0)) for x in prior)
        prior_min_c = min(float(x.get("close", 0)) for x in prior)
    except (ValueError, TypeError):
        return
    direction = r.get("direction", "")
    forged = False
    reason = ""
    if direction == "bull":
        broke = (last_high > prior_max_h) or (last_close > prior_max_c)
        if not broke:
            forged = True
            reason = "末根high/close均未超前20根极值(伪突破)"
        elif prior_max_h > 0 and (last_high / prior_max_h - 1.0) > _SPIKE_RETURN_CAP:
            forged = True
            reason = f"末根high超前期{(last_high / prior_max_h - 1) * 100:.0f}%>50%(疑似spike伪造)"
    elif direction == "bear":
        broke = (last_low < prior_min_l) or (last_close < prior_min_c)
        if not broke:
            forged = True
            reason = "末根low/close均未破前20根极值(伪突破)"
        elif prior_min_l > 0 and (prior_min_l / last_low - 1.0) > _SPIKE_RETURN_CAP:
            forged = True
            reason = f"末根low破前期{(prior_min_l / last_low - 1) * 100:.0f}%>50%(疑似spike伪造)"
    if forged:
        demote(r, reason)
        # 保留原 P0-4 的追溯键，兼容下游读者
        r["_breakout_revalidated"] = False
        r["_revalidate_reason"] = reason
        print(f"  ⛔ [P0-4] {sym} 突破信号被重校验拦截: {reason} → 降级NOISE")


register_validator("p0_4_raw_kline", validate_p0_4_raw_kline)
