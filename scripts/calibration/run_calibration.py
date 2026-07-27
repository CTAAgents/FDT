#!/usr/bin/env python3
"""
置信度校准独立入口 — 由 confidence-calibration Loop 调用。

用法:
    python scripts/calibration/run_calibration.py --symbol all
    python scripts/calibration/run_calibration.py --symbol RB

依赖: fdt_eval.feedback.parameter_tuner.ParameterTuner
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fdt_eval.feedback.parameter_tuner import ParameterTuner
from fdt_eval.feedback.config_store import ConfigStore


def _main() -> int:
    parser = argparse.ArgumentParser(description="置信度校准 — confidence-calibration Loop")
    parser.add_argument("--symbol", default="all", help="品种代码，默认 all")
    parser.add_argument("--followup", default=None, help="execution_followup.json 路径")
    args = parser.parse_args()

    store = ConfigStore()
    if not store.global_config.enabled:
        print("置信度校准已禁用 (global.enabled=False)")
        return 0

    tuner = ParameterTuner(store)
    calibrations = tuner.tune(followup_path=args.followup)

    if not calibrations:
        print("置信度校准: 无品种满足校准条件 (min_samples=20)")
        return 0

    if args.symbol != "all":
        calibrations = [c for c in calibrations if c.symbol.upper() == args.symbol.upper()]
        if not calibrations:
            print(f"品种 {args.symbol} 不在校准范围")
            return 0

    applied = sum(1 for c in calibrations if c.changes_applied)
    for c in calibrations:
        status = "✓" if c.changes_applied else "−"
        print(f"  {status} {c.symbol}: bias={c.confidence_bias:+.3f}, "
              f"offset={c.confidence_offset:+.3f}, "
              f"stop={c.old_stop_mult:.1f}→{c.new_stop_mult:.1f}, "
              f"target={c.old_target_mult:.1f}→{c.new_target_mult:.1f}")

    print(f"置信度校准: {len(calibrations)} 品种已分析, {applied} 品种有变更")
    store.save()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
