"""V1 原始K线重校验门禁 (P0-4) + 基差方向校验 — 防御伪造突破的最后闸门。

迁移自 scan_all._revalidate_breakouts，改为**单记录验证器**（按 signal_type 路由逐条调用）。
逻辑逐字保留：末根 high/close 是否真实穿越前 20 根极值；穿越幅度 >50% 视为 spike 伪造 → 降级 NOISE。

【Phase 2 增强】基差方向校验：
- 突破方向与基差方向冲突时标记 _basis_conflict，不降级仅告警
  （多头突破但基差负值=Contango，空头突破但基差正值=Backwardation）
- 供闫判官辩论时参考，也供 V2/V3 的 undemote 权衡
"""

from . import register_validator
from .base import demote

_SPIKE_RETURN_CAP = 0.5  # 与 multi_source_adapter._SPIKE_RETURN_CAP 一致
_BREAKOUT_SIGNALS = {"channel_breakout", "trend_confirmation", "bb_squeeze_prebreakout"}
# v2 命名空间前缀（trend_following.dc20 等）
_V2_TREND_PREFIXES = ("trend_following",)
# ── G43 类别错误修复（2026-07-16）──
# P0-4 校验语义 = 「末根 high/low/close 是否真实穿越前 20 根唐奇安极值」，
# 仅对**真正的唐奇安通道突破**子信号成立。去融合（G41）后 trend_following 拆成
# 10 个独立子信号，其中 supertrend/sar/chandelier/macd/tsmom/dual_thrust/bb/
# keltner 均**非** 20 根极值突破，若一律套用此门禁会把它们误判为「伪突破」并降级
# 为 total=0（实测 supertrend/sar/macd/tsmom 各 52/63、chandelier 25/33 被误降）。
# 故 v2 命名空间下仅 dc20/dc55 两个唐奇安突破子信号进入 P0-4 重校验。
_V2_BREAKOUT_SUFFIXES = ("dc20", "dc55")

def _is_v2_breakout(sig: str) -> bool:
    if not any(sig.startswith(p) for p in _V2_TREND_PREFIXES):
        return False
    return sig.rsplit(".", 1)[-1] in _V2_BREAKOUT_SUFFIXES

# ── 基差方向冲突阈值（从 config/settings.py 集中读取） ──
try:
    from config.settings import ENHANCED_VALIDATOR_THRESHOLDS as _EVT
    BASIS_CONFLICT_THRESHOLD = float(_EVT.get("BASIS_CONFLICT_THRESHOLD", 2.0))
except Exception:
    BASIS_CONFLICT_THRESHOLD = 2.0


def validate_p0_4_raw_kline(r: dict, context) -> None:
    sig = r.get("signal_type", "")
    if sig not in _BREAKOUT_SIGNALS and not _is_v2_breakout(sig):
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
        # ── 多因子覆写检查：即使在 V1 看来是伪突破，若 OI/基差数据支持则覆写 ──
        _oi_info = (context.extra or {}).get("oi_data", {}).get(sym.upper(), {})
        _basis_info = (context.extra or {}).get("basis_data", {}).get(sym.upper(), {})
        _oi_change = _oi_info.get("oi_change_pct", 0)
        _basis_pct = _basis_info.get("basis_pct", 0)
        
        _overridden = False
        if _oi_change > 15.0:
            # OI 暴增 >15% → 主力建仓，即使价格没破极值也不降级
            _overridden = True
            r["_oi_surge_reversal"] = True
            r["_override_reason"] = f"OI暴增({_oi_change:+.1f}%)主力建仓覆写伪突破拦截"
            print(f"  ✅ [P0-4] {sym} OI暴增({_oi_change:+.1f}%)覆写伪突破降级")
        elif _basis_pct > 2.0:
            # 基差走阔 >2% → 现货驱动，价格虽未破极值但基本面支持
            _overridden = True
            r["_strangle_compressed"] = True
            r["_override_reason"] = f"基差走阔(basis_pct={_basis_pct:+.2f}%)弹簧压缩覆写伪突破降级"
            print(f"  ✅ [P0-4] {sym} 基差走阔({_basis_pct:+.2f}%)覆写伪突破降级")
        
        if not _overridden:
            demote(r, reason)
            # 保留原 P0-4 的追溯键，兼容下游读者
            r["_breakout_revalidated"] = False
            r["_revalidate_reason"] = reason
            print(f"  ⛔ [P0-4] {sym} 突破信号被重校验拦截: {reason} → 降级NOISE")
        return  # 已处理，无需继续

    # ── Phase 2 增强：基差方向校验（突破已通过 V1 但方向与基座冲突）──
    basis_info = (context.extra or {}).get("basis_data", {}).get(sym.upper(), {})
    basis_pct = basis_info.get("basis_pct", 0)
    if basis_pct == 0:
        return  # 无基差数据，跳过
    conflict = False
    conflict_reason = ""
    if direction == "bull" and basis_pct < -BASIS_CONFLICT_THRESHOLD:
        conflict = True
        conflict_reason = f"多头突破但基差负值(basis_pct={basis_pct:+.2f}%)资金驱动非基本面驱动"
    elif direction == "bear" and basis_pct > BASIS_CONFLICT_THRESHOLD:
        conflict = True
        conflict_reason = f"空头突破但基差正值(basis_pct={basis_pct:+.2f}%)现货支撑空头风险高"
    if conflict:
        r["_basis_conflict"] = True
        r["_basis_conflict_reason"] = conflict_reason
        r["_basis_basis_pct"] = basis_pct
        print(f"  ⚠️ [P0-4] {sym} 基差方向冲突: {conflict_reason}")


register_validator("p0_4_raw_kline", validate_p0_4_raw_kline)
