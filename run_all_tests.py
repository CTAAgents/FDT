#!/usr/bin/env python3
"""隔离测试 runner — 按技能目录分别 subprocess 执行，规避跨技能 top-level 包名碰撞。

背景（方案1）：多个技能在各自 skills/<x>/scripts/ 下携带同名顶层包
（scripts/signals/pipeline/debate/ml）。在单个 pytest 会话内合并运行时，
Python 会按会话内首次出现顺序缓存该 namespace，导致某技能内部
`from scripts.xxx import` 命中错误技能的 scripts 包 → ImportError。

对策：每个测试目录在**独立子进程**中运行 pytest（各自全新解释器 = 全新
sys.modules），从根上消除会话级 namespace 碰撞；再把各目录结果聚合成一份
全量报告。零测试代码改动、零回归风险。

用法：
    python run_all_tests.py            # 跑全部自动发现的测试目录
    python run_all_tests.py -k         # 保留原样透传给 pytest 的额外参数
"""

import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS_ROOT = os.path.join(PROJECT_ROOT, "tests")

# pytest 退出码：0=全过 1=有失败 2=中断 3=内部错误 4=用法错误 5=未收集到用例
_NO_TESTS = 5

# 摘要行数量提取：形如 "1 failed, 4 passed, 2 warnings in 0.5s"
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped)")


def discover_test_dirs():
    """自动发现 tests/ 下所有含 conftest.py 或 test_*.py 的直接子目录（排序）。

    避免硬编码列表随目录新增而漂移（历史 bug：曾漏掉 6 个目录）。
    """
    dirs = []
    for name in sorted(os.listdir(TESTS_ROOT)):
        d = os.path.join(TESTS_ROOT, name)
        if not os.path.isdir(d) or name.startswith("__"):
            continue
        has_conftest = os.path.isfile(os.path.join(d, "conftest.py"))
        has_tests = any(
            f.startswith("test_") and f.endswith(".py") for f in os.listdir(d)
        )
        if has_conftest or has_tests:
            dirs.append(f"tests/{name}")
    return dirs


def parse_summary(stdout):
    """从 pytest 输出解析 passed/failed/error/skipped 计数（取最后一条摘要行）。"""
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    summary_line = ""
    for line in stdout.splitlines():
        s = line.strip()
        if (" in " in s) and any(
            k in s for k in ("passed", "failed", "error", "skipped", "no tests ran")
        ):
            summary_line = s  # 保留最后一条（pytest 摘要在末尾）
    for num, kind in _COUNT_RE.findall(summary_line):
        key = "error" if kind.startswith("error") else kind
        counts[key] += int(num)
    return counts, summary_line


def main():
    extra_args = sys.argv[1:]  # 透传给 pytest（如 -k / -x / -q）
    test_dirs = discover_test_dirs()
    python = sys.executable

    results = []  # (dir, counts, summary_line, returncode)
    for td in test_dirs:
        test_path = os.path.join(PROJECT_ROOT, td)
        print(f"\n{'=' * 64}")
        print(f"▶ {td}")
        print(f"{'=' * 64}")
        proc = subprocess.run(
            [python, "-m", "pytest", test_path, "--tb=short", "-q", *extra_args],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        counts, summary = parse_summary(proc.stdout)
        results.append((td, counts, summary, proc.returncode))

        if proc.returncode == _NO_TESTS:
            print("  ⏭ 未收集到用例")
        elif summary:
            print(f"  {summary}")
        else:
            print(f"  (无摘要, exit={proc.returncode})")
        # 真实失败/错误时打印简短尾部诊断
        if proc.returncode not in (0, _NO_TESTS):
            tail = [l for l in proc.stdout.splitlines()[-12:] if l.strip()]
            for l in tail:
                print(f"    │ {l}")
            for l in proc.stderr.splitlines()[-4:]:
                if l.strip():
                    print(f"    ⚠ {l.strip()}")

    # ── 聚合报告 ────────────────────────────────────────────────
    tot = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    hard_fail = False
    print(f"\n{'=' * 64}\n📊 聚合报告\n{'=' * 64}")
    for td, c, _summary, rc in results:
        for k in tot:
            tot[k] += c[k]
        if rc not in (0, _NO_TESTS):
            hard_fail = True
        status = (
            "⏭ 空"
            if rc == _NO_TESTS
            else ("✅" if (c["failed"] == 0 and c["error"] == 0 and rc == 0) else "❌")
        )
        print(
            f"  {status} {td:<38} "
            f"pass={c['passed']:<4} fail={c['failed']:<3} "
            f"err={c['error']:<3} skip={c['skipped']:<3}"
        )
    print(f"{'-' * 64}")
    print(
        f"  合计: passed={tot['passed']}  failed={tot['failed']}  "
        f"error={tot['error']}  skipped={tot['skipped']}  "
        f"| 目录={len(results)}"
    )
    ok = (tot["failed"] == 0 and tot["error"] == 0 and not hard_fail)
    print(f"  {'✅ 全部通过' if ok else '⚠️ 存在失败/错误'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
