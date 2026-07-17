#!/usr/bin/env python3
"""
FDT daily automation runner
"""

import os
import sys
import subprocess
import shutil

FDT_ROOT = r"D:\Programs\FDT"
REPORT_ROOT = r"D:\FDTWorkspace"

sys.path.insert(0, FDT_ROOT)

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
    source_dir = os.path.join(
        os.path.expanduser("~"),
        "Documents",
        "WorkBuddy",
        "Commodities",
        "Reports",
        "商品期货深度分析",
        DATE_STR,
    )
    target_dir = os.path.join(REPORT_ROOT, DATE_STR)
    os.makedirs(target_dir, exist_ok=True)

    # 按文件类型分类存放：html 放 html/ 子目录，json 放 json/ 子目录
    html_dir = os.path.join(target_dir, "html")
    json_dir = os.path.join(target_dir, "json")
    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)

    if os.path.exists(source_dir):
        for item in os.listdir(source_dir):
            src = os.path.join(source_dir, item)
            if os.path.isfile(src):
                if item.endswith(".html"):
                    dst = os.path.join(html_dir, item)
                elif item.endswith(".json"):
                    dst = os.path.join(json_dir, item)
                else:
                    dst = os.path.join(target_dir, item)
                shutil.copy2(src, dst)
        print(f"Report copied to: {target_dir}")
        return target_dir

    print(f"Source report dir not found: {source_dir}")
    return None


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