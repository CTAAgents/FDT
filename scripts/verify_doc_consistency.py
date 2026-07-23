#!/usr/bin/env python3
r"""Harness 文档一致性校验脚本 (Layer 2 一致性自动化)

扫描 docs/harness/ 下的所有 .md 文件，解析其 ## 一致性元数据 章节中定义的
代码实体←→文档章节映射表格，提取「检验方式」字段作为 shell 命令执行，
验证文档声明的代码实体与实际代码一致，防止文档与代码漂移。

跨平台兼容: 使用纯 Python 实现 grep/ls/test 等命令的等价逻辑，
不依赖外部 shell 工具。

用法:
    python scripts/verify_doc_consistency.py
    python scripts/verify_doc_consistency.py --docs docs/harness/01-architecture.md

可导入:
    from scripts.verify_doc_consistency import run_checks
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = PROJECT_ROOT / "docs" / "harness"


# =============================================================================
# Markdown 表格解析（兼容 backtick 内的管道符）
# =============================================================================

def _split_markdown_row(row: str) -> List[str]:
    r"""分割 markdown 表格行，识别管道符内的反引号区域。

    markdown 中 `|` 出现在反引号内时不作为列分隔符。
    例如: | `grep -n "a\|b"` | -> 列内容为 `grep -n "a\|b"`
    """
    cells: List[str] = []
    current: List[str] = []
    in_backtick = False

    for ch in row:
        if ch == '`':
            in_backtick = not in_backtick
            current.append(ch)
        elif ch == '|' and not in_backtick:
            cells.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    cells.append(''.join(current).strip())
    return cells


def _is_separator_cell(cell: str) -> bool:
    """判断一个单元格是否为分隔符（如 :---, :--:, --- 等）。"""
    stripped = cell.strip()
    if not stripped:
        return False
    return all(c in ":- " for c in stripped)


def _strip_field(field: str) -> str:
    """清洗字段：去除首尾空白和包围的反引号。"""
    val = field.strip()
    # 去除包围的反引号（可能有多层）
    while val.startswith('`') and val.endswith('`') and len(val) >= 2:
        val = val[1:-1].strip()
    return val


def parse_consistency_table(content: str) -> List[Tuple[str, str, str]]:
    """从 markdown 内容中解析 ## 一致性元数据 表格。

    Returns:
        list of (code_ref, assertion, verification_command)
    """
    start = content.find("## 一致性元数据")
    if start == -1:
        return []

    rest = content[start + len("## 一致性元数据"):]

    # 找到第一个表格行（以 | 开头，且不止一个 |）
    lines = rest.splitlines()
    table_first = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|"):
            # 确保有至少 2 个 |
            parts = _split_markdown_row(stripped)
            if len(parts) >= 4:
                table_first = i
                break

    if table_first == -1:
        return []

    # 收集连续的表格行（遇到下一个 ## 或非表格空行后结束）
    table_lines: List[str] = []
    for line in lines[table_first:]:
        stripped = line.strip()
        if line.startswith("## "):
            break
        if not stripped:
            if table_lines:
                # 空行后检查是否还有表格行
                continue
            else:
                continue
        if stripped.startswith("|"):
            table_lines.append(stripped)
        elif table_lines:
            # 非表格行出现在表格后 → 表格结束
            break

    # 解析表格行
    results: List[Tuple[str, str, str]] = []
    data_started = False

    for line in table_lines:
        cells = _split_markdown_row(line)

        # 去掉首尾空单元格
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]

        if len(cells) < 4:
            continue

        # 检查表头行
        if "代码文件/函数" in cells[0]:
            continue

        # 检查分隔符行（所有非空单元格都是分隔符）
        non_empty = [c for c in cells if c.strip()]
        if non_empty and all(_is_separator_cell(c) for c in non_empty):
            data_started = True
            continue

        if not data_started:
            continue

        code_ref = _strip_field(cells[0])    # 代码文件/函数
        assertion = _strip_field(cells[2])   # 关键断言/可验证事实
        verification = _strip_field(cells[3])  # 检验方式

        if not code_ref and not assertion and not verification:
            continue

        results.append((code_ref, assertion, verification))

    return results


# =============================================================================
# 命令执行（纯 Python 实现，跨平台）
# =============================================================================

def _execute_grep(args: List[str], cwd: Path) -> Tuple[bool, str]:
    r"""Python 实现的 grep 命令等价逻辑。

    支持:
      grep -n "pattern"            -> 递归搜索
      grep -n "pattern" file       -> 指定文件
      grep -c "pattern" file       -> 计数
      grep -A5 "pattern" file      -> 上下文搜索
      grep "^version" pyproject.toml -> 行首锚定
      grep -n "pat1\|pat2" file    -> 多模式匹配
    """
    # 解析参数
    count_mode = False
    context_after = 0
    print_line_numbers = False
    pattern = ""
    files: List[str] = []

    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "-c":
            count_mode = True
        elif arg == "-n":
            print_line_numbers = True
        elif arg.startswith("-A"):
            if arg == "-A" and i + 1 < len(args):
                i += 1
                context_after = int(args[i])
            elif len(arg) > 2:
                context_after = int(arg[2:])
        elif arg.startswith("-"):
            pass  # 忽略其他未知参数
        else:
            if not pattern:
                pattern = arg
            else:
                files.append(arg)
        i += 1

    if not pattern:
        return False, "no pattern"

    # 去除模式中的引号
    pattern = pattern.strip("\"'")

    # 编译正则（处理 \| 作为 OR 操作符）
    # 将 grep 的 \| 转换为 Python 的 |
    py_pattern = pattern.replace("\\|", "|")
    try:
        regex = re.compile(py_pattern)
    except re.error as e:
        return False, f"invalid regex: {e}"

    # 确定搜索范围
    search_in: List[Path] = []
    if files:
        for f in files:
            p = cwd / f
            if p.exists():
                if p.is_dir():
                    search_in.extend(sorted(p.rglob("*")))
                else:
                    search_in.append(p)
            else:
                # 尝试 glob
                matches = list(cwd.glob(f))
                if matches:
                    search_in.extend(matches)
    else:
        # 递归搜索所有常见代码文件
        search_in = _find_searchable_files(cwd)

    if not search_in:
        return False, "no files to search"

    # 执行搜索
    match_count = 0
    matched_lines: List[str] = []

    for file_path in search_in:
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for line_num, line in enumerate(content.splitlines(), 1):
            if regex.search(line):
                match_count += 1
                rel_path = file_path.relative_to(cwd).as_posix()
                if print_line_numbers:
                    matched_lines.append(f"{rel_path}:{line_num}:{line}")
                else:
                    matched_lines.append(f"{rel_path}:{line}")

                # 上下文行
                if context_after > 0:
                    extra = content.splitlines()[line_num:line_num + context_after]
                    for el in extra:
                        matched_lines.append(f"  {el}")

    if count_mode:
        return True, f"{match_count}"

    if match_count > 0:
        output = "\n".join(matched_lines[:10])
        if len(matched_lines) > 10:
            output += f"\n... and {len(matched_lines) - 10} more"
        return True, output
    else:
        return False, f"pattern '{pattern}' not found in {len(search_in)} files"


def _find_searchable_files(root: Path) -> List[Path]:
    """递归查找可搜索的代码文件。"""
    # 要忽略的目录
    ignore_dirs = {".git", "__pycache__", "node_modules", ".venv", ".trae",
                   ".claude", "memory", "benchmarks"}
    result: List[Path] = []

    # 常见代码文件后缀
    code_extensions = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
                       ".java", ".yaml", ".yml", ".toml", ".json", ".md",
                       ".sql", ".sh", ".bat", ".ps1", ".cfg", ".ini",
                       ".txt", ".css", ".html"}

    for p in root.rglob("*"):
        relative = p.relative_to(root)
        parts = relative.parts
        if any(part in ignore_dirs for part in parts):
            continue
        if p.is_file() and p.suffix.lower() in code_extensions:
            result.append(p)

    return result


def _execute_ls(args: List[str], cwd: Path) -> Tuple[bool, str]:
    """Python 实现的 ls 命令等价逻辑。

    支持:
      ls file1 file2 file3 → 检查所有文件是否存在
      ls pattern/*.py      → glob 模式匹配
      ls pattern1 pattern2 → 多文件/模式检查
    """
    files = args[1:]  # 跳过 'ls'
    if not files:
        return False, "no files specified"

    missing: List[str] = []
    found: List[str] = []

    for f in files:
        # 检查 glob 模式
        if any(c in f for c in ("*", "?", "[")):
            matches = list(cwd.glob(f))
            if matches:
                found.append(f"{f} ({len(matches)} matches)")
            else:
                missing.append(f"{f} (no matches)")
        else:
            p = cwd / f
            if p.exists():
                found.append(f)
            else:
                missing.append(f)

    if not missing:
        output = ", ".join(found) if found else "all files exist"
        return True, output
    else:
        output = "missing: " + ", ".join(missing)
        return False, output


def _execute_test(args: List[str], cwd: Path) -> Tuple[bool, str]:
    """Python 实现的 test 命令等价逻辑。

    支持:
      test -f file → 文件存在性检查
    """
    if len(args) < 3:
        return False, "insufficient arguments"

    flag = args[1]
    target = args[2]

    p = cwd / target

    if flag == "-f":
        exists = p.is_file()
    elif flag == "-d":
        exists = p.is_dir()
    elif flag == "-e":
        exists = p.exists()
    else:
        return False, f"unknown test flag: {flag}"

    if exists:
        return True, f"{target} exists"
    else:
        return False, f"{target} not found"


def _execute_native(cmd: str, cwd: Path) -> Tuple[bool, str]:
    """用 subprocess 原生执行 shell 命令（跨平台 fallback）。"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = (result.stdout or result.stderr or "").strip()[:200]
            return True, output
        else:
            output = (result.stderr or result.stdout or "").strip()[:200]
            return False, output
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT (10s)"
    except Exception as e:
        return False, f"ERROR: {e}"


def execute_check(cmd: str, cwd: Path) -> Tuple[bool, str, str]:
    """执行一条检验命令。

    Returns:
        (passed, output_or_reason, exec_type)
    """
    if not cmd.strip():
        return False, "empty command", "NOT_EXECUTED"

    # 用 shlex 分词以支持引号包裹的参数
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return False, f"parse error: {e}", "NOT_EXECUTED"
    if not parts:
        return False, "empty command", "NOT_EXECUTED"

    tool = parts[0]

    try:
        if tool == "grep":
            passed, output = _execute_grep(parts, cwd)
            return passed, output, "EXECUTED"
        elif tool == "ls":
            passed, output = _execute_ls(parts, cwd)
            return passed, output, "EXECUTED"
        elif tool == "test":
            passed, output = _execute_test(parts, cwd)
            return passed, output, "EXECUTED"
        elif tool in ("python", "python3"):
            passed, output = _execute_native(cmd, cwd)
            return passed, output, "EXECUTED"
        else:
            # 未知命令 → 尝试原生 shell 执行
            passed, output = _execute_native(cmd, cwd)
            return passed, output, "EXECUTED"
    except Exception as e:
        return False, f"ERROR: {e}", "EXECUTED"


def _format_assertion(assertion: str, code_ref: str) -> str:
    """生成可读的断言描述。"""
    if assertion and len(assertion) > 2:
        return assertion
    if code_ref:
        if "::" in code_ref:
            return code_ref.split("::")[-1].replace("()", "") + " exists"
        return code_ref.split("/")[-1] + " exists"
    return "unknown assertion"


# =============================================================================
# 核心校验逻辑
# =============================================================================

def run_single_file(doc_path: Path) -> Tuple[int, int, int, int, List[str]]:
    """对单个文档文件执行一致性校验。

    Returns:
        (total, passed, failed, not_exec, report_lines)
    """
    passed = 0
    failed = 0
    not_exec = 0
    report_lines: List[str] = []

    try:
        content = doc_path.read_text(encoding="utf-8")
    except Exception as e:
        report_lines.append(f"  ⚠️  无法读取文件: {e}")
        return 0, 0, 0, 0, report_lines

    entries = parse_consistency_table(content)
    if not entries:
        report_lines.append("  ℹ️  未找到一致性元数据表格")
        return 0, 0, 0, 0, report_lines

    for code_ref, assertion, verification in entries:
        label = _format_assertion(assertion, code_ref)

        if not verification.strip():
            report_lines.append(
                f"  ⚪ NOT_EXECUTED: {label} (检验方式为空)"
            )
            not_exec += 1
            continue

        passed_flag, output, exec_type = execute_check(verification, PROJECT_ROOT)

        if exec_type == "NOT_EXECUTED":
            report_lines.append(
                f"  ⚪ NOT_EXECUTED: {label} ({verification[:80]})"
            )
            not_exec += 1
        elif passed_flag:
            report_lines.append(
                f"  ✅ PASS: {label} ({verification})"
            )
            passed += 1
        else:
            report_lines.append(
                f"  ❌ FAIL: {label} ({verification})"
            )
            failed += 1

    return passed + failed + not_exec, passed, failed, not_exec, report_lines


def run_checks(doc_paths: Optional[List[Path]] = None) -> int:
    """运行一致性校验。

    Args:
        doc_paths: 要检查的文档路径列表。为 None 时扫描 docs/harness/。

    Returns:
        0 全部通过，1 有失败项
    """
    if doc_paths is None:
        doc_paths = _find_all_harness_docs()

    if not doc_paths:
        print("❌ 未找到任何文档文件。")
        return 1

    # 统一解析为绝对路径
    doc_paths = [p.resolve() if not p.is_absolute() else p for p in doc_paths]

    # 过滤出包含 ## 一致性元数据 的文件
    valid_docs: List[Path] = []
    for p in doc_paths:
        try:
            content = p.read_text(encoding="utf-8")
            if "## 一致性元数据" in content:
                valid_docs.append(p)
        except Exception:
            pass

    if not valid_docs:
        print("❌ 未找到包含一致性元数据的文档。")
        return 1

    separator = "=" * 60
    print(separator)
    print("  Harness 文档一致性校验")
    print(separator)

    total_all = 0
    passed_all = 0
    failed_all = 0
    not_exec_all = 0

    for doc_path in valid_docs:
        rel_path = doc_path.relative_to(PROJECT_ROOT).as_posix()
        print(f"\n{rel_path}")
        tot, pas, fail, nexec, lines = run_single_file(doc_path)
        for line in lines:
            print(line)
        total_all += tot
        passed_all += pas
        failed_all += fail
        not_exec_all += nexec

    print(f"\n{separator}")
    print(f"  Summary: {total_all} total | {passed_all} PASS | "
          f"{failed_all} FAIL | {not_exec_all} NOT_EXECUTED")
    print(separator)

    if failed_all > 0:
        print("❌ 一致性校验未通过，请修复后重试。")
        return 1
    elif not_exec_all > 0:
        print("⚠️  部分检验方式未执行，请检查后重试。")
        return 0
    else:
        print("✅ 全部通过。")
        return 0


def _find_all_harness_docs() -> List[Path]:
    """递归扫描 docs/harness/ 下所有 .md 文件。"""
    if not HARNESS_DIR.is_dir():
        print(f"[WARN] 目录不存在: {HARNESS_DIR}", file=sys.stderr)
        return []
    return sorted(HARNESS_DIR.rglob("*.md"))


def main() -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="Harness 文档一致性校验 — 验证一致性元数据中的检验方式",
    )
    parser.add_argument(
        "--docs",
        nargs="+",
        type=str,
        help="要检查的文档文件路径（相对于项目根目录），"
             "如: docs/harness/01-architecture.md docs/harness/02-lifecycle.md",
    )
    args = parser.parse_args()

    if args.docs:
        doc_paths = [PROJECT_ROOT / p for p in args.docs]
        missing = [p for p in doc_paths if not p.exists()]
        if missing:
            for p in missing:
                print(f"❌ 文件不存在: {p}")
            return 1
    else:
        doc_paths = None

    return run_checks(doc_paths)


if __name__ == "__main__":
    sys.exit(main())
