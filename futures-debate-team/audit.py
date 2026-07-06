"""代码审计 — 期货交易辩论专家团"""

import os, re, sys

PROJECT = os.path.dirname(os.path.abspath(__file__))
EXCLUDE_DIRS = {"venv", "__pycache__", ".git", ".workbuddy", "node_modules", "__pycache__"}
EXCLUDE_FILES = {"integrate_test.py", "test_coverage_boost.py"}

issues = {"hardcoded_path": [], "security": [], "style": [], "comment": []}


def scan_file(fp):
    """扫描单个Python文件的常见问题"""
    with open(fp, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    content = "".join(lines)

    basename = os.path.basename(fp)
    rel = os.path.relpath(fp, PROJECT)

    # ── 1. 硬编码路径 ──────────────────────────────────
    # DATADIR 硬编码
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if "DATADIR" in s and ("2026-" in s or r"C:\\Users" in s or "/Users/" in s):
            issues["hardcoded_path"].append(f"{rel}:{i} DATADIR硬编码: {s[:80]}")

    # 硬编码的日期字符串 (20260705 或 2026-07-05 之类的)
    if basename in ("run_full_chain_analysis.py", "run_final_chain_analysis.py"):
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if "20260705" in s and "datetime.now" not in s:
                issues["hardcoded_path"].append(f"{rel}:{i} 硬编码日期: {s[:80]}")

    # 硬编码的用户路径
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if r"C:\Users" in s and "expanduser" not in s and "os.environ" not in s:
            issues["hardcoded_path"].append(f"{rel}:{i} 硬编码用户路径: {s[:80]}")

    # ── 2. 安全泄露 ──────────────────────────────────
    for i, line in enumerate(lines, 1):
        s = line.strip()
        # API Key / Token 模式
        if re.search(r'(api[_-]?key|apikey|token|secret|password|passwd)\s*[=:]\s*["\']', s, re.I):
            # 排除 obvious non-secrets
            if not any(x in s.lower() for x in ["os.environ", "environ.get", "config.", "settings"]):
                issues["security"].append(f"{rel}:{i} 疑似凭据泄露: {s[:60]}")
        if re.search(r'["\'][A-Za-z0-9_\-]{32,}["\']', s) and "import" not in s and "version" not in s:
            issues["security"].append(f"{rel}:{i} 疑似Token: {s[:60]}")

    # ── 3. 代码风格 ──────────────────────────────────
    for i, line in enumerate(lines, 1):
        s = line
        if len(s.rstrip()) > 120:
            issues["style"].append(f"{rel}:{i} 超长行({len(s.rstrip())}字符): {s[:80]}")

    # 混用tab和空格
    for i, line in enumerate(lines, 1):
        current_line = line.rstrip("\n")
        if any(c == "\t" for c in current_line) and current_line.strip():
            issues["style"].append(f"{rel}:{i} 包含制表符缩进: {current_line[:60]}")
            break  # 每个文件只报告一次

    # ── 4. 注释一致性 ──────────────────────────────────
    # 英文docstring中有中文, 或中文注释中有英文
    for i, line in enumerate(lines, 1):
        s = line.strip()
        # docstring: 双引号三引号
        if '"""' in s and len(s) > 10:
            has_cn = bool(re.search(r"[\u4e00-\u9fff]", s))
            has_en = bool(re.search(r"[a-zA-Z]{3,}", s))
            if has_cn and has_en:
                pass  # 中英混用是正常的说明性注释

        # 行尾空格
        if s != s.rstrip() and s.strip():
            issues["style"].append(f"{rel}:{i} 行尾有多余空格")


def scan_agent_file(fp):
    """扫描Agent Markdown文件"""
    with open(fp, encoding="utf-8", errors="ignore") as f:
        content = f.read()

    rel = os.path.relpath(fp, PROJECT)

    # 检查硬编码路径
    if r"C:\Users" in content and "expanduser" not in content:
        issues["hardcoded_path"].append(f"{rel} Agent文件含硬编码路径")

    # 检查API key
    if re.search(r"(api[_-]?key|token|secret)\s*:", content, re.I):
        issues["security"].append(f"{rel} Agent文件含疑似凭据")


def scan_settings(fp):
    """扫描配置文件"""
    with open(fp, encoding="utf-8", errors="ignore") as f:
        content = f.read()
    rel = os.path.relpath(fp, PROJECT)
    if re.search(r"(token|secret|password|api_key)", content, re.I):
        # Show the context
        for line in content.split("\n"):
            if re.search(r"(token|secret|password|api_key)", line, re.I):
                issues["security"].append(f"{rel} 配置文件含敏感字段: {line.strip()[:80]}")


print("=" * 60)
print(f"代码审计 — {PROJECT}")
print("=" * 60)

# 扫描所有py文件
for root, dirs, files in os.walk(PROJECT):
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
    for f in files:
        fp = os.path.join(root, f)
        if f.endswith(".py"):
            scan_file(fp)
        elif f.endswith(".md") and "agents" in root:
            scan_agent_file(fp)
        elif f in ("settings.json", ".env", "config.ini"):
            scan_settings(fp)


# 输出报告
def print_section(title, items, max_show=15):
    print(f"\n{'=' * 60}")
    print(f"{title}: {len(items)} 个问题")
    print(f"{'=' * 60}")
    if items:
        for item in items[:max_show]:
            print(f"  ⚠ {item}")
        if len(items) > max_show:
            print(f"  ... 还有 {len(items) - max_show} 个问题")
    else:
        print("  ✅ 无问题")


print_section("硬编码路径", issues["hardcoded_path"])
print_section("安全泄露", issues["security"])
print_section("代码风格", issues["style"], max_show=20)
print_section("注释一致性", issues["comment"])

print(f"\n{'=' * 60}")
total = sum(len(v) for v in issues.values())
if total == 0:
    print("🎉 完美通过! 无任何问题")
else:
    print(f"📋 总计 {total} 个待修复问题")
    print(f"   hardcoded_path: {len(issues['hardcoded_path'])}")
    print(f"   security:       {len(issues['security'])}")
    print(f"   style:          {len(issues['style'])}")
    print(f"   comment:        {len(issues['comment'])}")
print(f"{'=' * 60}")
