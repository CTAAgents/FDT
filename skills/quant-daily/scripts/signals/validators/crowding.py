"""V7 信号拥挤度验证器 — 全局闸门（列表级），对所有活跃信号只保留前 K 名（公开主流因子：活跃数上限）。

迁移自 validate_signals.crowding_filter，改为**列表级验证器**（注册于 SIGNAL_VALIDATOR_MAP["__global__"]），
在整个 all_ranked 上跑一次。仅压 grade（不重定义 signal_type），与原逻辑一致。
"""

from . import register_validator

MAX_SIGNALS_TOTAL = 20   # 拥挤度上限：活跃信号数超过此值触发压制
CROWDING_KEEP_TOP = 15   # 拥挤时保留前 K 名


def validate_crowding(all_ranked: list, context=None) -> None:
    """列表级拥挤度压制：非 NOISE 信号数 > 上限时，仅保留总分前 K 名。"""
    active = [(i, r) for i, r in enumerate(all_ranked)
              if r.get("grade", "NOISE") not in ("NOISE",)]
    if len(active) <= MAX_SIGNALS_TOTAL:
        return

    active_sorted = sorted(active, key=lambda x: abs(x[1].get("total", 0)), reverse=True)
    keep_indices = set(idx for idx, _ in active_sorted[:CROWDING_KEEP_TOP])

    for idx, r in active:
        if idx not in keep_indices:
            r["grade"] = "NOISE"
            r["_crowding_note"] = (f"信号拥挤({len(active)}>"
                                   f"{MAX_SIGNALS_TOTAL}), 总分排名靠后被压制")
            r["_raw_total"] = r.get("total", 0)  # 保留原始总分
            r["total"] = 0


register_validator("crowding", validate_crowding)
