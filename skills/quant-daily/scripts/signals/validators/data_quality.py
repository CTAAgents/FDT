"""V8 数据质量闸门 — 低质量数据自动降权/阻断（Data Governance Phase 2）。

当信号依赖的数据质量不足时：
  - overall=D → 直接降级 NOISE（数据不可靠）
  - overall=C → 不降级但标记 _dq_score_penalty，供下游参考
  - 数据源为 web_fallback → 标记 _web_search_flag（低优先级）
  - 数据源为 cache → 标记 _cached_data_flag（新鲜度不足）

注册为 __global__ 列表级验证器，对所有信号统一生效。
"""

from . import register_validator
from .base import demote

# C/D 等级的门槛值
DQ_DEMOTE_GRADES = {"D"}       # 直接降级
DQ_PENALTY_GRADES = {"C"}      # 标记扣分但不降级
LOW_PRIORITY_SOURCES = {"web_fallback"}


def validate_data_quality(all_ranked: list, context=None) -> None:
    """列表级数据质量闸门。"""
    for r in all_ranked:
        dq = r.get("data_quality", {})
        if not dq or not dq.get("available", False):
            continue

        overall = dq.get("overall", "N/A")
        source = dq.get("source", "unknown")
        issues = dq.get("issues", [])
        sym = r.get("symbol", "")

        # ── D级 → 直接降级 NOISE ──
        if overall in DQ_DEMOTE_GRADES:
            demote(r, f"数据质量D级({'; '.join(issues)})", new_type=r.get("signal_type", "minor_signal"))
            r["_dq_demoted"] = True
            r["_dq_reason"] = f"数据质量D级（源={source}）"
            print(f"  ⛔ [数据质量] {sym} 数据质量D级 → 降级NOISE ({'; '.join(issues)})")
            continue

        # ── 非NOISE信号加标记 ──
        if r.get("grade", "NOISE") == "NOISE":
            continue

        # ── C级 → 扣分标记 ──
        if overall in DQ_PENALTY_GRADES:
            r["_dq_grade"] = overall
            r["_dq_penalty"] = True
            r["_dq_reason"] = f"数据质量C级（源={source}）"
            print(f"  ⚠️ [数据质量] {sym} 数据质量C级（源={source}）— 信号保留但可靠性存疑")

        # ── web_fallback 源 → 低优先级标记 ──
        if source in LOW_PRIORITY_SOURCES:
            r["_dq_web_fallback"] = True
            r["_dq_reason"] = r.get("_dq_reason", "") + " [Web兜底源]"
            if overall == "D":  # 已在上面处理
                pass
            elif overall == "C":
                print(f"  ⚠️ [数据质量] {sym} Web兜底源(C级) — 存在数据可靠性风险")

        # ── CACHED 数据 → 新鲜度标记 ──
        confidence = dq.get("confidence", "")
        if confidence == "CACHED":
            r["_cached_data_flag"] = True
            r["_dq_cached"] = True


register_validator("data_quality", validate_data_quality)
