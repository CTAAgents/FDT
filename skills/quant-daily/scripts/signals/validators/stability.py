"""V6 信号稳定性验证器 — 对比当前信号方向与最近 N 次扫描历史一致性（公开主流因子：方向一致率）。

迁移自 validate_signals.check_signal_stability，改为**单记录验证器**（按 signal_type 路由逐条调用）。
仅压 grade（不重定义 signal_type），与原逻辑一致。历史不足时跳过，绝不误伤。
"""

import json
import os

from . import register_validator
from .base import demote

N_STABILITY_LOOKBACK = 5       # 回顾最近 N 次扫描
MAX_INCONSISTENT_RATIO = 0.6   # 不一致比例超过此值则降级


def _load_training_data() -> list:
    """加载训练数据中的扫描记录（与原 validate_signals 同路径）。"""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "optimizer", "training_data.json"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _score_to_direction(total_score: float) -> str:
    if total_score > 5:
        return "bull"
    elif total_score < -5:
        return "bear"
    else:
        return "neutral"


def validate_stability(r: dict, context=None) -> None:
    """单记录稳定性验证：当前方向 vs 历史扫描一致率。"""
    sym = r.get("symbol", "")
    current_dir = _score_to_direction(r.get("total", 0))

    # 只对非 NOISE 且有明确方向的信号做稳定性检查
    if r.get("grade", "NOISE") == "NOISE" or current_dir == "neutral":
        return

    records = _load_training_data()
    if not records:
        return

    sym_records = [rec for rec in records
                   if rec.get("symbol", "").lower() == sym.lower()
                   and rec.get("record_type") == "scan"]
    sym_records.sort(key=lambda x: x.get("scan_time", ""), reverse=True)
    recent = sym_records[:N_STABILITY_LOOKBACK]

    if not recent or len(recent) < 3:
        return  # 历史不足，不判定

    consistent = sum(1 for rec in recent
                     if _score_to_direction(rec.get("total_score", 0)) == current_dir)
    inconsistent_ratio = 1 - (consistent / len(recent))
    if inconsistent_ratio > MAX_INCONSISTENT_RATIO:
        demote(r, f"信号不稳定(一致率{1 - inconsistent_ratio:.0%},回顾{len(recent)}次)",
               new_type=r.get("signal_type", "minor_signal"))
        r["_stability_note"] = f"信号不稳定(一致率{1 - inconsistent_ratio:.0%})"


register_validator("stability", validate_stability)
