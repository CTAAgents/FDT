#!/usr/bin/env python3
"""
明鉴秋资源检查器 — 在 spawn 每批 Agent 前调用，输出清晰的操作指引。

用法:
  python scripts/spawn_resource_check.py --phase phase2 --base 6

输出:
  {"safe_concurrent": 4, "risk_level": "green", "recommendation": "proceed",
   "reason": "CPU 45%, 内存 62%, 建议并发4",
   "phase": "phase2", "advice": "✅ 资源充足，按计划spawn，建议并发4"}

明鉴秋使用方式:
  phase=phase2, base=6 → 调用本脚本
  risk_level=red → 停止spawn，等资源释放后重试
  risk_level=yellow → 降并发数到 safe_concurrent
  risk_level=green → 按 safe_concurrent 或 base 中较小的值执行
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 导入资源看门狗
_WATCHDOG = Path(__file__).resolve().parent / "resource_watchdog.py"


def pre_spawn_check(phase: str, base_concurrent: int) -> dict:
    """明鉴秋在 spawn 前调用，获取资源感知的并发建议。

    Args:
        phase: 执行阶段（phase0-phase7 或角色名）
        base_concurrent: 该阶段计划并发数

    Returns:
        包含 safe_concurrent / risk_level / advice 的 dict
    """
    import subprocess
    cmd = [
        sys.executable, str(_WATCHDOG),
        "--phase", phase,
        "--active", "0",  # 明鉴秋在调用时手动传入实际活跃数
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return _fallback(phase, base_concurrent, "看门狗异常")
        result = json.loads(r.stdout)
    except Exception as e:
        return _fallback(phase, base_concurrent, str(e))

    safe = result.get("safe_concurrent", base_concurrent)
    risk = result.get("risk_level", "green")
    recommendation = result.get("recommendation", "proceed")
    reason = result.get("reason", "")
    final_safe = min(safe, base_concurrent)

    # 生成操作建议
    if risk == "red":
        advice = (
            f"⛔ 资源红色警戒（{reason}）。"
            f"建议停止 spawn，检查系统负载，等待资源释放后重试"
        )
        final_safe = 0
    elif risk == "yellow":
        advice = (
            f"⚠️ 资源黄色预警（{reason}）。"
            f"降低并发至 {final_safe}，并监控后续阶段"
        )
    else:
        advice = (
            f"✅ 资源充足（{reason}）。"
            f"按计划 spawn，并发上限 {final_safe}"
        )

    return {
        "safe_concurrent": final_safe,
        "risk_level": risk,
        "recommendation": recommendation,
        "reason": reason,
        "phase": phase,
        "base_concurrent": base_concurrent,
        "advice": advice,
    }


def _fallback(phase: str, base: int, err: str) -> dict:
    """看门狗不可用时的保守回退。"""
    safe = max(1, base // 2)
    return {
        "safe_concurrent": safe,
        "risk_level": "yellow",
        "recommendation": "cautious",
        "reason": f"看门狗不可用（{err}），保守降半并发={safe}",
        "phase": phase,
        "base_concurrent": base,
        "advice": f"⚠️ 看门狗不可用，保守执行，并发 {safe}",
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="明鉴秋资源检查器")
    parser.add_argument("--phase", required=True,
                        help="执行阶段名（phase0-phase7 或角色名）")
    parser.add_argument("--base", type=int, default=5,
                        help="该阶段计划并发数")
    parser.add_argument("--active", type=int, default=0,
                        help="当前活跃 Agent 数")
    args = parser.parse_args()

    result = pre_spawn_check(args.phase, args.base)
    # 支持覆盖活跃数
    if args.active > 0:
        result["active_count"] = args.active
    print(json.dumps(result, ensure_ascii=False))
    # 同时打印可读版本
    print(f"\n📊 {result['advice']}", file=sys.stderr)
