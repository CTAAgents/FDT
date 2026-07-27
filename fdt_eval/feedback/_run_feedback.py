#!/usr/bin/env python3
"""
交易质量反馈触发脚本 — 由 master_graph node_run_validate_and_evolve 调用。

读取裁决回溯生成的 validation_stats.json 和 execution_followup.json，
运行 position_tuner + parameter_tuner，将调整写入 ConfigStore。

退出码: 0 = 成功 (含"无变更"), 1 = 错误

最后一行 stdout 作为 summary 被 master_graph 采集。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 默认数据路径 (与 validate_verdicts.py 产出路径对齐)
DEFAULT_STATS_PATH = PROJECT_ROOT / "memory" / "validations" / "validation_stats.json"
DEFAULT_FOLLOWUP_PATH = PROJECT_ROOT / "memory" / "validations" / "execution_followup.json"


def _main() -> int:
    # 检查输入文件是否存在
    stats_exists = DEFAULT_STATS_PATH.exists()
    followup_exists = DEFAULT_FOLLOWUP_PATH.exists()

    if not stats_exists and not followup_exists:
        print("数据文件不存在，跳过反馈调优（尚无历史裁决数据）")
        return 0

    # lazy import
    sys.path.insert(0, str(PROJECT_ROOT))
    from fdt_eval.feedback.position_tuner import PositionTuner
    from fdt_eval.feedback.parameter_tuner import ParameterTuner
    from fdt_eval.feedback.config_store import ConfigStore

    store = ConfigStore()
    if not store.global_config.enabled:
        print("反馈闭环已禁用 (global.enabled=False)")
        return 0

    parts: list[str] = []

    # 1. 仓位调整
    pos_tuner = PositionTuner(store)
    adjustments = pos_tuner.tune(stats_path=str(DEFAULT_STATS_PATH) if stats_exists else None)
    if adjustments:
        up = sum(1 for a in adjustments if a.direction == "up")
        down = sum(1 for a in adjustments if a.direction == "down")
        parts.append(f"仓位: {len(adjustments)}品种(↑{up} ↓{down})")

    # 2. 参数校准
    param_tuner = ParameterTuner(store)
    calibrations = param_tuner.tune(followup_path=str(DEFAULT_FOLLOWUP_PATH) if followup_exists else None)
    if calibrations:
        n_changed = sum(1 for c in calibrations if c.changes_applied)
        if n_changed:
            parts.append(f"参数: {n_changed}个品种有变更")

    # 3. 输出摘要
    if parts:
        summary = " | ".join(parts)
        print(summary)
    else:
        print("反馈调优: 无变更（数据不足或已最优）")

    # 持久化
    store.save()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
