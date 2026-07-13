"""信号验证管道 — 辩论前的最后一道过滤。

两个阶段:
  1. 信号稳定性检查: 对比当前信号方向与最近 N 次扫描的方向一致性
     连续不一致 → 降级 NOISE
  2. 信号拥挤度压制: 如果总信号数超过阈值, 只保留总分前 K 名
     排名靠后的 weak 信号跳过辩论

集成位置: scan_all.py run_scan() 中, 在 score() 之后、写入 JSON / 启动辩论之前。
"""

import json
import os
from datetime import datetime
from typing import Any

# ── 默认阈值 (可由 scan_all.py 注入覆盖) ──
N_STABILITY_LOOKBACK = 5         # 回顾最近 N 次扫描
MAX_INCONSISTENT_RATIO = 0.6     # 不一致比例超过此值则降级
MAX_SIGNALS_TOTAL = 20           # 拥挤度上限
CROWDING_KEEP_TOP = 15           # 拥挤时保留前 K 名


def _load_training_data() -> list:
    """加载训练数据中的扫描记录"""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "optimizer", "training_data.json"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _score_to_direction(total_score: float) -> str:
    """总分 → 方向"""
    if total_score > 5:
        return "bull"
    elif total_score < -5:
        return "bear"
    else:
        return "neutral"


def check_signal_stability(
    all_ranked: list[dict],
    n_lookback: int = N_STABILITY_LOOKBACK,
    max_inconsistent_ratio: float = MAX_INCONSISTENT_RATIO,
) -> tuple[list[dict], int]:
    """检查每个品种当前信号方向与历史扫描的一致性。

    Args:
        all_ranked: scan_all.py 产出的排名列表 (含 {symbol, total, grade, ...})
        n_lookback: 回顾最近 N 次扫描记录
        max_inconsistent_ratio: 不一致比例 > 此值则降级

    Returns:
        (filtered_all_ranked, demoted_count)
    """
    records = _load_training_data()
    if not records:
        return all_ranked, 0

    demoted = 0
    result = []
    for r in all_ranked:
        sym = r.get("symbol", "")
        current_dir = _score_to_direction(r.get("total", 0))

        # 只对非 NOISE 且有明确方向的信号做稳定性检查
        grade = r.get("grade", "NOISE")
        if grade == "NOISE" or current_dir == "neutral":
            result.append(r)
            continue

        # 找该品种最近的 N 次扫描记录
        sym_records = [rec for rec in records
                       if rec.get("symbol", "").lower() == sym.lower()
                       and rec.get("record_type") == "scan"]
        sym_records.sort(key=lambda x: x.get("scan_time", ""), reverse=True)
        recent = sym_records[:n_lookback]

        if not recent or len(recent) < 3:
            # 历史不足, 不判定
            result.append(r)
            continue

        # 计算方向一致比例
        consistent = 0
        for rec in recent:
            hist_dir = _score_to_direction(rec.get("total_score", 0))
            if hist_dir == current_dir:
                consistent += 1

        inconsistent_ratio = 1 - (consistent / len(recent))
        if inconsistent_ratio > max_inconsistent_ratio:
            r["grade"] = "NOISE"
            r["_stability_note"] = f"信号不稳定(一致率{1-inconsistent_ratio:.0%}, 回顾{len(recent)}次)"
            r["total"] = 0
            demoted += 1

        result.append(r)

    return result, demoted


def crowding_filter(
    all_ranked: list[dict],
    max_signals: int = MAX_SIGNALS_TOTAL,
    keep_top: int = CROWDING_KEEP_TOP,
) -> tuple[list[dict], int]:
    """信号拥挤度压制: 如果非 NOISE 信号数 > max_signals, 只保留前 keep_top 名。

    Args:
        all_ranked: 排名列表 (已按 total 绝对值排序)
        max_signals: 触发拥挤压制的信号数阈值
        keep_top: 拥挤时保留的前 K 名

    Returns:
        (filtered_all_ranked, suppressed_count)
    """
    # 识别非 NOISE 的信号
    active = [(i, r) for i, r in enumerate(all_ranked)
              if r.get("grade", "NOISE") not in ("NOISE",)]
    if len(active) <= max_signals:
        return all_ranked, 0

    # 按总分绝对值排序（取前 keep_top）
    active_sorted = sorted(active, key=lambda x: abs(x[1].get("total", 0)), reverse=True)
    keep_indices = set(idx for idx, _ in active_sorted[:keep_top])

    suppressed = 0
    for idx, r in active:
        if idx not in keep_indices:
            r["grade"] = "NOISE"
            r["_crowding_note"] = (f"信号拥挤({len(active)}>"
                                   f"{max_signals}), 总分排名靠后被压制")
            r["total"] = 0
            suppressed += 1

    return all_ranked, suppressed


def validate_all(
    all_ranked: list[dict],
    stability_kwargs: dict | None = None,
    crowding_kwargs: dict | None = None,
) -> tuple[list[dict], dict]:
    """完整信号验证管道: 稳定性检查 → 拥挤度压制。

    Args:
        all_ranked: scan_all.py 产出的排名列表
        stability_kwargs: 传递给 check_signal_stability 的额外参数
        crowding_kwargs: 传递给 crowding_filter 的额外参数

    Returns:
        (filtered_all_ranked, stats_dict)
        stats_dict = {
            "stability_demoted": int,
            "crowding_suppressed": int,
            "total_suppressed": int,
            "active_signals_before": int,
            "active_signals_after": int,
        }
    """
    active_before = sum(1 for r in all_ranked
                        if r.get("grade", "NOISE") not in ("NOISE",))

    ranked, stability_demoted = check_signal_stability(
        all_ranked, **(stability_kwargs or {})
    )
    ranked, crowding_suppressed = crowding_filter(
        ranked, **(crowding_kwargs or {})
    )

    active_after = sum(1 for r in ranked
                       if r.get("grade", "NOISE") not in ("NOISE",))

    stats = {
        "stability_demoted": stability_demoted,
        "crowding_suppressed": crowding_suppressed,
        "total_suppressed": stability_demoted + crowding_suppressed,
        "active_signals_before": active_before,
        "active_signals_after": active_after,
    }
    return ranked, stats
