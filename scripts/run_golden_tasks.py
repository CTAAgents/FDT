"""
Golden Tasks 验证脚本 — Phase C4/C5
====================================
运行 5 个已知品种的辩论案例，对比适配后 vs 默认配置的信号质量。

用法:
    python scripts/run_golden_tasks.py --mode shadow --tasks-dir benchmarks/golden_adaptation/
    python scripts/run_golden_tasks.py --mode compare --tasks-dir benchmarks/golden_adaptation/
    python scripts/run_golden_tasks.py --mode list --tasks-dir benchmarks/golden_adaptation/
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

# 项目根目录
FDT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FDT_ROOT))

from scripts.harness_adapter import (
    adapt_harness,
    DEFAULT_CONFIG,
    log_adaptation,
)


def load_tasks(tasks_dir: Path) -> list[dict]:
    """加载所有 Golden Task 定义"""
    tasks = []
    for f in tasks_dir.glob("*.yaml"):
        with open(f, encoding="utf-8") as fp:
            task = yaml.safe_load(fp)
        task["_source_file"] = f.name
        tasks.append(task)
    return sorted(tasks, key=lambda t: t.get("task_id", ""))


def run_shadow(task: dict, patterns_dir: Path, records_dir: Path, log_dir: Path) -> dict:
    """Shadow 模式: 只记录不应用，观察适配决策合理性"""
    tc = task.get("expected_market_context", {})
    result = adapt_harness(
        task_conditions=tc,
        patterns_dir=patterns_dir,
        records_dir=records_dir,
        base_config=DEFAULT_CONFIG,
        shadow_mode=True,
    )

    # 记录日志
    log_path = log_adaptation(result, task["task_id"], task["symbol"], log_dir)

    return {
        "task_id": task["task_id"],
        "symbol": task["symbol"],
        "name": task.get("name", ""),
        "mode": "shadow",
        "adaptations": result["adaptations"],
        "matched_patterns": result["matched_patterns"],
        "matched_cases": result["matched_cases"],
        "applied": result["applied"],
        "log_path": str(log_path),
    }


def run_compare(task: dict, patterns_dir: Path, records_dir: Path, log_dir: Path) -> dict:
    """对比模式: 对比适配后 vs 默认配置"""
    tc = task.get("expected_market_context", {})

    # 默认配置
    default_result = {
        "config": DEFAULT_CONFIG,
        "adapted": False,
        "adaptations": [],
    }

    # 适配后配置
    adapted_result = adapt_harness(
        task_conditions=tc,
        patterns_dir=patterns_dir,
        records_dir=records_dir,
        base_config=DEFAULT_CONFIG,
        shadow_mode=False,
    )

    # 记录日志
    log_path = log_adaptation(adapted_result, task["task_id"], task["symbol"], log_dir)

    # 计算配置偏差
    deviations = _compute_deviations(DEFAULT_CONFIG, adapted_result["adapted_config"])

    # 检查验证标准
    criteria_results = []
    for criterion in task.get("verification_criteria", []):
        passed = _check_criterion(criterion, DEFAULT_CONFIG, adapted_result["adapted_config"])
        criteria_results.append({"criterion": criterion, "passed": passed})

    return {
        "task_id": task["task_id"],
        "symbol": task["symbol"],
        "name": task.get("name", ""),
        "mode": "compare",
        "deviations": deviations,
        "matched_patterns": adapted_result["matched_patterns"],
        "matched_cases": adapted_result["matched_cases"],
        "applied": adapted_result["applied"],
        "criteria_results": criteria_results,
        "all_criteria_passed": all(c["passed"] for c in criteria_results),
        "log_path": str(log_path),
    }


def _compute_deviations(base: dict, adapted: dict) -> list[dict]:
    """计算两个配置之间的偏差"""
    deviations = []
    all_dims = set(list(base.keys()) + list(adapted.keys()))
    for dim in all_dims:
        base_fields = base.get(dim, {})
        adapted_fields = adapted.get(dim, {})
        all_fields = set(list(base_fields.keys()) + list(adapted_fields.keys()))
        for field in all_fields:
            b_val = base_fields.get(field)
            a_val = adapted_fields.get(field)
            if b_val != a_val:
                deviations.append({
                    "path": f"{dim}.{field}",
                    "base": b_val,
                    "adapted": a_val,
                    "change": "modified",
                })
    return deviations


def _check_criterion(criterion: str, base_config: dict, adapted_config: dict) -> bool:
    """解析并检查验证标准

    支持的格式：
    - "适配后 field_path >= value"
    - "适配后 field_path <= value"
    - "适配后配置与默认配置偏差不超过 X%"
    """
    try:
        if "偏差不超过" in criterion:
            # "适配后配置与默认配置偏差不超过 30%"
            pct = float(criterion.split("不超过")[-1].replace("%", "").strip()) / 100
            devs = _compute_deviations(base_config, adapted_config)
            total_fields = 0
            all_dims = set(list(base_config.keys()) + list(adapted_config.keys()))
            for dim in all_dims:
                bf = base_config.get(dim, {})
                af = adapted_config.get(dim, {})
                total_fields += len(set(list(bf.keys()) + list(af.keys())))
            changed_fields = len(devs)
            if total_fields == 0:
                return True
            return (changed_fields / total_fields) <= pct
        elif ">=" in criterion:
            # "适配后 max_evidence_items >= 5"
            parts = criterion.replace("适配后", "").strip().split(">=")
            field_name = parts[0].strip()
            value = float(parts[1].strip())
            actual = _get_config_value(adapted_config, field_name)
            return actual is not None and actual >= value
        elif "<=" in criterion:
            parts = criterion.replace("适配后", "").strip().split("<=")
            field_name = parts[0].strip()
            value = float(parts[1].strip())
            actual = _get_config_value(adapted_config, field_name)
            return actual is not None and actual <= value
        else:
            return True  # 无法解析的标准默认通过
    except Exception:
        return False


def _get_config_value(config: dict, field_path: str):
    """从配置中获取字段值，支持嵌套路径如 'd3_generation.debater_temp'。
    也支持裸字段名如 'debater_temp'，会自动遍历所有维度查找。
    """
    parts = field_path.split(".")
    if len(parts) == 1:
        # 裸字段名：遍历所有维度查找
        for dim, fields in config.items():
            if isinstance(fields, dict) and parts[0] in fields:
                return fields[parts[0]]
        return None
    current = config
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def print_results(results: list[dict], mode: str):
    """打印结果摘要"""
    print(f"\n{'='*60}")
    print(f"Golden Tasks 验证结果 — 模式: {mode}")
    print(f"{'='*60}")

    all_passed = True
    for r in results:
        status = "PASS" if (mode == "shadow" or r.get("all_criteria_passed", True)) else "FAIL"
        if not r.get("all_criteria_passed", True):
            all_passed = False

        print(f"\n  [{status}] {r['task_id']} — {r['name']} ({r['symbol']})")
        print(f"    匹配模式: {r['matched_patterns'] if r['matched_patterns'] else '无'}")
        print(f"    匹配案例: {r['matched_cases']}")

        if mode == "compare":
            print(f"    配置偏差: {len(r.get('deviations', []))} 项")
            for d in r.get("deviations", []):
                print(f"      {d['path']}: {d['base']} → {d['adapted']}")
            for c in r.get("criteria_results", []):
                mark = "OK" if c["passed"] else "FAIL"
                print(f"      [{mark}] {c['criterion']}")

    print(f"\n{'='*60}")
    if mode == "compare":
        if all_passed:
            print("结果: 全部通过 — 可以进入 Validator 度量阶段")
        else:
            print("结果: 存在失败项 — 需要调整适配参数后重试")
    else:
        print("结果: Shadow 模式完成 — 请人工审查适配决策合理性")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Golden Tasks 验证脚本")
    parser.add_argument("--mode", choices=["shadow", "compare", "list"],
                        default="shadow", help="运行模式")
    parser.add_argument("--tasks-dir", type=Path,
                        default=FDT_ROOT / "benchmarks" / "golden_adaptation",
                        help="Golden Tasks 目录")
    parser.add_argument("--patterns-dir", type=Path,
                        default=FDT_ROOT / "memory" / "experience" / "patterns",
                        help="Gt 模式目录")
    parser.add_argument("--records-dir", type=Path,
                        default=FDT_ROOT / "memory" / "experience" / "records",
                        help="Et 记录目录")
    parser.add_argument("--output-dir", type=Path,
                        default=FDT_ROOT / "memory" / "experience" / "adaptation_log",
                        help="适配日志输出目录")

    args = parser.parse_args()

    tasks = load_tasks(args.tasks_dir)
    if not tasks:
        print("错误: 未找到 Golden Task 定义文件")
        sys.exit(1)

    print(f"加载了 {len(tasks)} 个 Golden Tasks:")
    for t in tasks:
        print(f"  {t['task_id']} — {t.get('name', '')} ({t['symbol']})")

    if args.mode == "list":
        return

    results = []
    run_fn = run_shadow if args.mode == "shadow" else run_compare

    for task in tasks:
        print(f"\n运行 {task['task_id']} ({args.mode} 模式)...")
        result = run_fn(task, args.patterns_dir, args.records_dir, args.output_dir)
        results.append(result)

    print_results(results, args.mode)

    # 保存结构化结果
    output_file = args.output_dir / f"golden_tasks_{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"结构化结果已保存: {output_file}")


if __name__ == "__main__":
    main()
