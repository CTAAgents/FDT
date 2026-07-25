#!/usr/bin/env python3
"""
准入评估自动化脚本 — G17 修复

执行 4 步准入检查并输出 JSON 准入报告：
1. Shadow: 检查当前迭代轮数 ≥ 5
2. Golden Tasks: 运行金标准测试集，要求全部通过
3. Validator Quality: 检查漏放率 ≈ 0%，误杀率 < 20%
4. Canary: 检查金丝雀运行时长 ≥ 24h

用法:
    python scripts/advancement_check.py                         # 完整 4 步检查
    python scripts/advancement_check.py --phase shadow          # 单步
    python scripts/advancement_check.py --output report.json    # 输出到文件
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def check_shadow() -> dict:
    """Step 1: 影子模式 — 检查迭代轮数 ≥ 5"""
    result = {"phase": "shadow", "passed": False, "detail": "", "metrics": {}}
    debate_log = Path("memory/debate_journal.json")
    if not debate_log.exists():
        result["detail"] = "memory/debate_journal.json 不存在，影子模式未运行"
        return result

    try:
        with open(debate_log, "r", encoding="utf-8") as f:
            entries = [line for line in f if line.strip()]
        rounds = len(entries)
        result["metrics"]["total_rounds"] = rounds
        if rounds >= 5:
            result["passed"] = True
            result["detail"] = f"影子模式已运行 {rounds} 轮 (≥5 ✅)"
        else:
            result["detail"] = f"影子模式仅运行 {rounds} 轮 (<5 ⚠️)"
    except Exception as e:
        result["detail"] = f"读取辩论日志失败: {e}"

    return result


def check_golden_tasks() -> dict:
    """Step 2: 金标准任务集 — 运行金标准测试并检查全部通过"""
    result = {"phase": "golden_tasks", "passed": False, "detail": "", "metrics": {}}
    golden_dir = Path("tests/golden")
    if not golden_dir.exists():
        result["detail"] = "tests/golden/ 目录不存在，未定义金标准任务集"
        return result

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/golden/", "-q", "--tb=short"],
            capture_output=True, text=True, timeout=120,
        )
        result["metrics"]["output"] = proc.stdout.strip() + proc.stderr.strip()
        result["metrics"]["return_code"] = proc.returncode

        # 解析 "N passed" 或 "N failed"
        out = proc.stdout + proc.stderr
        if "failed" in out and "passed" not in out:
            lines = out.strip().splitlines()
            for line in lines:
                if "failed" in line:
                    result["detail"] = f"金标准测试失败: {line.strip()}"
                    return result

        if proc.returncode == 0:
            result["passed"] = True
            result["detail"] = "金标准任务集全部通过 ✅"
        else:
            result["detail"] = f"金标准任务集未通过 (exit={proc.returncode})"
    except subprocess.TimeoutExpired:
        result["detail"] = "金标准测试超时 (120s)"
    except FileNotFoundError:
        result["detail"] = "pytest 未安装或无 tests/golden/ 目录"

    return result


def check_validator_quality() -> dict:
    """Step 3: 验证器质量度量 — 检查漏放率 ≈ 0%，误杀率 < 20%"""
    result = {"phase": "validator_quality", "passed": False, "detail": "", "metrics": {}}
    quality_log = Path("memory/validator_quality.json")
    if not quality_log.exists():
        result["detail"] = "validator_quality.json 不存在，运行 --collect 收集数据"
        return result

    try:
        with open(quality_log, "r", encoding="utf-8") as f:
            data = json.load(f)
        fp = data.get("false_pass_rate", 1.0)
        fb = data.get("false_block_rate", 1.0)
        total = data.get("total_checks", 0)
        result["metrics"]["false_pass_rate"] = fp
        result["metrics"]["false_block_rate"] = fb
        result["metrics"]["total_checks"] = total

        issues = []
        if total < 10:
            issues.append(f"检查样本不足 ({total})")
        if fp > 0.0:
            issues.append(f"漏放率 {fp:.1%} > 0%")
        if fb >= 0.2:
            issues.append(f"误杀率 {fb:.1%} ≥ 20%")
        if not issues and total >= 10 and fp <= 0.0 and fb < 0.2:
            result["passed"] = True
            result["detail"] = f"验证器质量达标: 漏放率={fp:.1%}, 误杀率={fb:.1%} ✅"
        else:
            result["detail"] = " | ".join(issues) if issues else "数据不足"
    except (json.JSONDecodeError, KeyError) as e:
        result["detail"] = f"质量日志解析失败: {e}"

    return result


def check_canary(result_dir: str = "reports") -> dict:
    """Step 4: 金丝雀 — 检查小范围放量时长 ≥ 24h"""
    result = {"phase": "canary", "passed": False, "detail": "", "metrics": {}}
    reports_dir = Path(result_dir)
    if not reports_dir.exists():
        result["detail"] = f"{result_dir}/ 目录不存在"
        return result

    html_reports = sorted(reports_dir.glob("debate_report_*.html"))
    if not html_reports:
        result["detail"] = "未找到辩论报告，金丝雀未运行"
        return result

    try:
        # 取最早和最晚报告时间
        timestamps = []
        for rp in html_reports:
            mtime = datetime.fromtimestamp(rp.stat().st_mtime)
            timestamps.append(mtime)

        first = min(timestamps)
        last = max(timestamps)
        duration_h = (last - first).total_seconds() / 3600
        report_count = len(html_reports)

        result["metrics"]["first_report"] = first.isoformat()
        result["metrics"]["last_report"] = last.isoformat()
        result["metrics"]["duration_hours"] = round(duration_h, 1)
        result["metrics"]["report_count"] = report_count

        if duration_h >= 24:
            result["passed"] = True
            result["detail"] = f"金丝雀运行 {duration_h:.1f}h (≥24h ✅)，产出 {report_count} 份报告"
        else:
            result["detail"] = f"金丝雀仅运行 {duration_h:.1f}h (<24h ⚠️)，产出 {report_count} 份报告"
    except Exception as e:
        result["detail"] = f"检查金丝雀失败: {e}"

    return result


def main():
    parser = argparse.ArgumentParser(description="FDT 准入评估自动化")
    parser.add_argument("--phase", choices=["shadow", "golden", "validator", "canary", "all"],
                        default="all", help="指定检查阶段")
    parser.add_argument("--output", type=str, default="",
                        help="输出报告到 JSON 文件")
    parser.add_argument("--result-dir", type=str, default="reports",
                        help="报告目录（金丝雀检查用）")
    args = parser.parse_args()

    phase_map = {
        "shadow": check_shadow,
        "golden": check_golden_tasks,
        "validator": check_validator_quality,
        "canary": lambda: check_canary(args.result_dir),
    }

    phases = list(phase_map.keys()) if args.phase == "all" else [args.phase]
    results = []

    print("=" * 60)
    print("  FDT 准入评估")
    print("=" * 60)
    print()

    for phase in phases:
        print(f"▶ Step {phases.index(phase) + 1}: {phase}...")
        r = phase_map[phase]()
        results.append(r)
        status = "✅ 通过" if r["passed"] else "❌ 未通过"
        print(f"  {status}: {r['detail']}")
        print()

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    report = {
        "generated_at": datetime.now().isoformat(),
        "total_steps": total_count,
        "passed_steps": passed_count,
        "all_passed": passed_count == total_count,
        "results": results,
    }

    print("-" * 60)
    if report["all_passed"]:
        print(f"  🎉 全部 {total_count} 步准入检查通过")
    else:
        print(f"  ⚠️ {passed_count}/{total_count} 步通过，{total_count - passed_count} 步未通过")
    print("-" * 60)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {out_path}")

    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
