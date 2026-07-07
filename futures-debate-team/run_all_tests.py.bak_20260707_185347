#!/usr/bin/env python3
"""运行所有测试 — 分目录执行避免 conftest.py sys.path 冲突"""

import subprocess, sys, os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TEST_DIRS = [
    "tests/quant-daily",
    "tests/commodity-chain",
    "tests/debate-argument-builder",
    "tests/debate-risk-manager",
    "tests/fundamental-data-collector",
    "tests/technical-analysis",
    "tests/contracts",
]

python = sys.executable
all_ok = True
total_passed = 0
total_failed = 0

for td in TEST_DIRS:
    test_path = os.path.join(PROJECT_ROOT, td)
    if not os.path.isdir(test_path):
        print(f"  ⏭ {td} (目录不存在)")
        continue
    print(f"\n{'=' * 60}")
    print(f"▶ 运行: {td}")
    print(f"{'=' * 60}")
    result = subprocess.run(
        [python, "-m", "pytest", test_path, "--tb=short"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    # 提取摘要
    for line in result.stdout.split("\n"):
        if "passed" in line and "failed" in line and "in" in line:
            print(f"  {line.strip()}")
            if "failed" in line:
                n_failed = int([x for x in line.split() if x.isdigit()][1])
                total_failed += n_failed
            break
    if result.returncode != 0:
        all_ok = False
        for line in result.stderr.split("\n")[-5:]:
            if line.strip():
                print(f"  ⚠ {line.strip()}")

print(f"\n{'=' * 60}")
print(f"{'✅ 全部通过' if all_ok else '⚠️ 存在失败'} | 测试目录: {len(TEST_DIRS)}")
sys.exit(0 if all_ok else 1)
