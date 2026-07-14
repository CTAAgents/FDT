"""信号验证器注册表与编排 — 范式↔验证器 声明式框架核心。

架构：每个 signal_type 在 config.settings.SIGNAL_VALIDATOR_MAP 中声明它该跑哪些验证器。
调用约定（由注册位置决定，无需额外元数据）：
  - 普通 key（如 "channel_breakout"）下的验证器 → 对每条匹配记录调用 fn(r, context)（单记录验证器）
  - "__global__" 下的验证器（稳定性/拥挤度等列表级） → 对整个 all_ranked 调用 fn(all_ranked, context)

所有验证器只用公开主流因子（Donchian/Bollinger/ATR/Volume/MA/实体比例），无黑盒新因子。
设计哲学见 technical_debt.md §5 与 design/signal_paradigm_validator_framework.md。
"""

from config.settings import SIGNAL_VALIDATOR_MAP
from .base import ValidationContext, demote

VALIDATOR_REGISTRY = {}


def register_validator(vid: str, fn) -> None:
    VALIDATOR_REGISTRY[vid] = fn


def get_validator(vid: str):
    return VALIDATOR_REGISTRY.get(vid)


def run_signal_validators(all_ranked: list, context: ValidationContext) -> list:
    """按 SIGNAL_VALIDATOR_MAP 逐信号类型路由验证器。

    1) 逐 signal_type：对每条记录调用其声明的单记录验证器 fn(r, context)
    2) __global__：对整个列表调用列表级验证器 fn(all_ranked, context)
    返回（原地修改的）all_ranked。
    """
    # 1) 逐 signal_type 路由（单记录验证器）
    for r in all_ranked:
        st = r.get("signal_type", "")
        for vid in SIGNAL_VALIDATOR_MAP.get(st, []):
            fn = get_validator(vid)
            if fn is None:
                print(f"  ⚠️ [validator] 未注册: {vid}（跳过）")
                continue
            fn(r, context)

    # 2) 全局闸门（列表级验证器）
    for vid in SIGNAL_VALIDATOR_MAP.get("__global__", []):
        fn = get_validator(vid)
        if fn is None:
            print(f"  ⚠️ [validator] 未注册: {vid}（跳过）")
            continue
        fn(all_ranked, context)

    return all_ranked


# ── 导入即注册：确保 VALIDATOR_REGISTRY 填充 ──
from . import (  # noqa: E402
    p0_4_raw_kline,
    volume_confirm,
    atr_vol_timing,
    trend_direction,
    entity_quality,
    stability,
    crowding,
)

__all__ = [
    "VALIDATOR_REGISTRY",
    "register_validator",
    "get_validator",
    "run_signal_validators",
    "ValidationContext",
    "demote",
]
