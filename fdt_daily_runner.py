#!/usr/bin/env python3
"""
FDT daily automation runner

Pipeline 模块通过 subprocess 调用（fdt_daily_runner.py → pipeline/runner.py），
不在 Python 导入图中可见。以下顶级导入建立显式依赖边以供工具分析和审计。
"""
import os
import sys
import subprocess
import shutil

FDT_ROOT = r"D:\Programs\FDT"
REPORT_ROOT = r"D:\FDTWorkspace"

sys.path.insert(0, FDT_ROOT)

# 显式依赖边：pipeline.runner 在运行时通过 subprocess 调用
import pipeline.runner  # noqa: E402, F401 — 建立 import 图可见性

from datetime import datetime

today = datetime.now()
DATE_STR = today.strftime("%Y-%m-%d")
DATE_COMPACT = today.strftime("%Y%m%d")


def configure_strategies():
    settings_path = os.path.join(
        FDT_ROOT, "skills", "quant-daily", "scripts", "config", "settings.py"
    )
    with open(settings_path, "r", encoding="utf-8") as f:
        content = f.read()

    import re

    content = re.sub(
        r'DISABLED_STRATEGIES: set\[str\] = \{[^}]*\}',
        """DISABLED_STRATEGIES: set[str] = {
    "multi_factor",
    "ml_signal",
    "event_driven",
    "arbitrage",
    "mean_reversion",
    "pairs_reversion",
    "spread_reversion",
    "basis_reversion",
    "macro_regime",
}""",
        content,
    )

    content = re.sub(r"DEBATE_ENTRY_MIN_ABS = \d+", "DEBATE_ENTRY_MIN_ABS = 40", content)

    with open(settings_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("Configured: trend_following only, debate threshold 40, filter ON")


def run_pipeline():
    env = os.environ.copy()
    env["FDT_USE_LANGGRAPH"] = "true"
    # FDT_SCAN_MODE removed → default filter ON
    env["FDT_STRATEGIES"] = "trend_following"
    env["FDT_DAILY_WORKSPACE"] = REPORT_ROOT

    pipeline_script = os.path.join(FDT_ROOT, "pipeline", "runner.py")
    result = subprocess.run(
        [sys.executable, pipeline_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        cwd=FDT_ROOT,
        env=env,
    )

    print(result.stdout)
    if result.stderr:
        print(f"stderr: {result.stderr}")

    return result.returncode == 0, result.stdout


def copy_report():
    """将 LangGraph 产出整理到 html/ 和 json/ 子目录。

    LangGraph 已直接写入 REPORT_ROOT/{date}/，本函数仅按类型分类。
    始终用最新产出覆盖子目录。
    """
    target_dir = os.path.join(REPORT_ROOT, DATE_STR)
    html_dir = os.path.join(target_dir, "html")
    json_dir = os.path.join(target_dir, "json")
    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)

    if not os.path.exists(target_dir):
        print(f"LangGraph output dir not found: {target_dir}")
        return None

    moved = 0
    for item in os.listdir(target_dir):
        src = os.path.join(target_dir, item)
        if not os.path.isfile(src):
            continue
        if item in ("html", "json"):
            continue
        if item.endswith(".html"):
            dst = os.path.join(html_dir, item)
        elif item.endswith(".json"):
            dst = os.path.join(json_dir, item)
        else:
            continue
        shutil.copy2(src, dst)
        moved += 1

        label = "html" if moved > 0 else "no new"
    print(f"Report organized at: {target_dir} ({label} files organized)")
    return target_dir


def main():
    print("=" * 60)
    print("FDT Daily Automation")
    print(f"Date: {DATE_STR}")
    print("=" * 60)

    configure_strategies()
    success, output = run_pipeline()
    report_dir = copy_report()

    if success:
        print("FDT Daily Automation Complete")
        if report_dir:
            html_path = os.path.join(report_dir, "html")
            if os.path.exists(html_path):
                html_files = [f for f in os.listdir(html_path) if f.endswith(".html")]
                if html_files:
                    print(f"HTML Reports: {', '.join(html_files)}")
        return 0
    else:
        print("FDT Daily Automation Failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())