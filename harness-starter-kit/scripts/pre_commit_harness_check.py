#!/usr/bin/env python3
"""commit前Harness规范检查脚本 — v2: 从YAML规则文件加载检查项

v2 核心变化:
  1. 从 docs/harness/harness-rules.yaml 加载规则（优先，不再硬编码）
  2. 保留原有 rules.yaml 失败时的硬编码回退
  3. run_checks() 接收 changed_files 列表 → 遍历每条规则 → 检查 scope 文档
  4. 输出结构化 JSON（包含 check_id / status / message / severity / missing_docs）
  5. 兼容原有 CLI 接口（python pre_commit_harness_check.py 仍可工作）
"""
from __future__ import annotations

import os
import sys
import json
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

PROJECT_ROOT = Path(__file__).parent.parent


# =============================================================================
# JSON Schema for harness-rules.yaml 校验
# =============================================================================

RULES_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["version", "checks"],
    "properties": {
        "version": {"type": "string", "description": "规则文件版本号"},
        "description": {"type": "string", "description": "规则文件描述"},
        "checks": {
            "type": "array",
            "description": "检查规则列表",
            "items": {
                "type": "object",
                "required": ["id", "name", "severity", "type", "scope", "message"],
                "properties": {
                    "id": {
                        "type": "string",
                        "pattern": "^C\d{2}$",
                        "description": "规则唯一标识，如 C01"
                    },
                    "name": {
                        "type": "string",
                        "description": "规则名称"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["P0", "P1"],
                        "description": "严重等级: P0=必须, P1=建议"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["file_modified", "version_check", "gap_check"],
                        "description": "检查类型"
                    },
                    "scope": {
                        "type": "string",
                        "description": "文档路径，多个用 | 分隔"
                    },
                    "trigger_pattern": {
                        "type": ["string", "null"],
                        "description": "触发正则（匹配变更文件），null=总是触发"
                    },
                    "message": {
                        "type": "string",
                        "description": "检查不通过时的提示信息"
                    }
                }
            }
        }
    }
}


# =============================================================================
# 硬编码回退规则（通用版 — 与 harness-rules.yaml 通用模板内容一致）
# =============================================================================

FALLBACK_RULES: List[Dict[str, Any]] = [
    {
        "id": "C01",
        "name": "架构变更反映检查",
        "severity": "P0",
        "type": "file_modified",
        "scope": "docs/harness/01-architecture.md",
        "trigger_pattern": None,
        "message": "架构/数据流变更必须同步更新 01-architecture.md"
    },
    {
        "id": "C02",
        "name": "生命周期文档同步检查",
        "severity": "P0",
        "type": "file_modified",
        "scope": "docs/harness/02-lifecycle.md",
        "trigger_pattern": None,
        "message": "代码变更必须同步更新 02-lifecycle.md"
    },
    {
        "id": "C03",
        "name": "配置项更新检查",
        "severity": "P0",
        "type": "file_modified",
        "scope": "docs/harness/03-configuration.md",
        "trigger_pattern": None,
        "message": "新增/修改配置项必须更新 03-configuration.md"
    },
    {
        "id": "C04",
        "name": "降级/熔断路径检查",
        "severity": "P0",
        "type": "file_modified",
        "scope": "docs/harness/04-resilience.md",
        "trigger_pattern": None,
        "message": "降级/熔断逻辑变更必须更新 04-resilience.md"
    },
    {
        "id": "C05",
        "name": "可观测性文档检查",
        "severity": "P0",
        "type": "file_modified",
        "scope": "docs/harness/05-observability.md",
        "trigger_pattern": None,
        "message": "指标/日志/追踪变更必须更新 05-observability.md"
    },
    {
        "id": "C06",
        "name": "测试文档更新检查",
        "severity": "P1",
        "type": "file_modified",
        "scope": "docs/harness/06-testing.md",
        "trigger_pattern": None,
        "message": "测试文件变更时建议同步更新 06-testing.md"
    },
    {
        "id": "C07",
        "name": "版本号 bump 检查",
        "severity": "P0",
        "type": "version_check",
        "scope": "pyproject.toml",
        "trigger_pattern": None,
        "message": "任何代码变更后必须核对版本号是否需要 bump"
    },
    {
        "id": "C08",
        "name": "差距登记检查",
        "severity": "P1",
        "type": "gap_check",
        "scope": "docs/harness/08-gap-analysis.md",
        "trigger_pattern": None,
        "message": "重大变更应考虑在 08-gap-analysis.md 登记新差距"
    },
    {
        "id": "C09",
        "name": "晋级计划检查",
        "severity": "P1",
        "type": "file_modified",
        "scope": "docs/harness/09-advancement-plan.md",
        "trigger_pattern": None,
        "message": "里程碑变更必须更新 09-advancement-plan.md"
    },
    {
        "id": "C10",
        "name": "流程文档同步检查",
        "severity": "P1",
        "type": "file_modified",
        "scope": "docs/execution_modes_flowchart.md|docs/business_flow.md",
        "trigger_pattern": None,
        "message": "流程变更必须同步流程图文档"
    },
    {
        "id": "C11",
        "name": "角色职责文档检查",
        "severity": "P1",
        "type": "file_modified",
        "scope": "agents/*.md",
        "trigger_pattern": None,
        "message": "Agent 角色变更必须同步 agents/*.md"
    },
    {
        "id": "C12",
        "name": "README 快速参考检查",
        "severity": "P0",
        "type": "file_modified",
        "scope": "README.md",
        "trigger_pattern": None,
        "message": "README.md 必须同步更新，作为项目入口文档"
    },
]

def load_rules() -> List[Dict[str, Any]]:
    """从 harness-rules.yaml 加载规则，失败时回退到硬编码"""
    rules_path = PROJECT_ROOT / "docs" / "harness" / "harness-rules.yaml"
    if not rules_path.exists():
        print(f"\u26a0\ufe0f 规则文件不存在: {rules_path}，使用回退规则")
        return FALLBACK_RULES

    try:
        import yaml
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            print("\u26a0\ufe0f 规则文件格式错误（顶层非字典），使用回退规则")
            return FALLBACK_RULES

        checks = data.get("checks", [])
        if not checks or not isinstance(checks, list):
            print("\u26a0\ufe0f 规则文件未包含 checks 列表，使用回退规则")
            return FALLBACK_RULES

        # 基本字段校验
        valid_checks = []
        for c in checks:
            if all(k in c for k in ("id", "name", "severity", "type", "scope", "message")):
                valid_checks.append(c)

        if not valid_checks:
            print("\u26a0\ufe0f 规则文件中无合法检查项，使用回退规则")
            return FALLBACK_RULES

        print(f"\u2705 已加载 {len(valid_checks)} 条规则: {rules_path}")
        return valid_checks

    except ImportError:
        print("\u26a0\ufe0f pyyaml 未安装，使用回退规则（pip install pyyaml 安装）")
        return FALLBACK_RULES
    except yaml.YAMLError as e:
        print(f"\u26a0\ufe0f YAML 解析失败: {e}，使用回退规则")
        return FALLBACK_RULES
    except Exception as e:
        print(f"\u26a0\ufe0f 加载规则文件异常: {e}，使用回退规则")
        return FALLBACK_RULES


# =============================================================================
# Git 变更获取
# =============================================================================

def get_git_changes() -> List[str]:
    """获取git暂存区文件列表"""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT)
        )
        if result.returncode == 0 and result.stdout:
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return []
    except Exception as e:
        print(f"\u274c 获取git变更失败: {e}")
        return []


# =============================================================================
# 辅助判断函数
# =============================================================================

def has_code_changes(changes: List[str]) -> bool:
    """判断是否有代码变更"""
    return any(
        not f.startswith("docs/") and
        not f.startswith("tests/") and
        not f.startswith(".") and
        f.endswith((".py", ".yaml", ".json", ".toml"))
        for f in changes if f.strip()
    )


def check_doc_exists(doc_path: str) -> bool:
    """检查文档是否存在（支持 * 通配）"""
    path = PROJECT_ROOT / doc_path
    if "*" in doc_path:
        parent_str = doc_path.replace("*.md", "").rstrip("/\\")
        parent_dir = PROJECT_ROOT / parent_str
        if parent_dir.exists() and parent_dir.is_dir():
            return any(f.endswith(".md") for f in os.listdir(parent_dir))
        return False
    return path.exists()


def check_doc_modified(doc_path: str, changes: List[str]) -> bool:
    """检查文档是否被修改（支持 * 通配）"""
    if "*" in doc_path:
        prefix = doc_path.replace("*.md", "")
        normalized_prefix = prefix.replace("\\", "/").rstrip("/")
        return any(
            f.replace("\\", "/").startswith(normalized_prefix)
            for f in changes
        )
    return doc_path in changes


def _expand_scopes(scope: str) -> List[str]:
    """展开管道分隔的多个 scope 路径"""
    return [s.strip() for s in scope.split("|")]


def _scopes_any_exists(scopes: List[str]) -> bool:
    """任意一个 scope 文档存在"""
    return any(check_doc_exists(s) for s in scopes)


def _scopes_any_modified(scopes: List[str], changes: List[str]) -> bool:
    """任意一个 scope 文档被修改"""
    return any(check_doc_modified(s, changes) for s in scopes)


def _scopes_missing(scopes: List[str], changes: List[str]) -> List[str]:
    """返回未被修改的 scope 文档列表"""
    return [s for s in scopes if not check_doc_modified(s, changes)]


# =============================================================================
# 版本号验证
# =============================================================================

def validate_version() -> Tuple[bool, str]:
    """验证版本号"""
    version_path = PROJECT_ROOT / "pyproject.toml"
    if not version_path.exists():
        return False, "pyproject.toml不存在"

    with open(version_path, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        return False, "pyproject.toml中未找到version字段"

    version = match.group(1)
    if not version:
        return False, "版本号为空"

    return True, f"版本号: {version}"


# =============================================================================
# 核心检查逻辑
# =============================================================================

def _is_triggered(rule: Dict[str, Any], changed_files: List[str]) -> bool:
    """判断规则是否被触发"""
    pattern_str = rule.get("trigger_pattern")
    if pattern_str is None:
        # trigger_pattern=null 表示总是检查（只要有代码变更）
        return has_code_changes(changed_files) or True
    try:
        pattern = re.compile(pattern_str)
        return any(pattern.search(f) for f in changed_files)
    except re.error:
        # 正则无效时保守地触发
        return True


def run_checks(changed_files: List[str]) -> Dict[str, Any]:
    """运行所有检查

    遍历每条规则，检查 scope 文档是否需要更新。
    返回结构化 JSON（包含 check_id / status / message / severity / missing_docs）
    """
    rules = load_rules()
    check_results = []

    has_code = has_code_changes(changed_files)

    for rule in rules:
        check_id = rule["id"]
        name = rule["name"]
        severity = rule["severity"]
        rule_type = rule["type"]
        scope = rule["scope"]
        message = rule["message"]

        scopes = _expand_scopes(scope)
        entry = {
            "check_id": check_id,
            "name": name,
            "status": "pass",
            "message": message,
            "severity": severity,
            "missing_docs": [],
        }

        # ---- 类型: version_check ----------------------------------------------------
        if rule_type == "version_check":
            if not has_code:
                entry["status"] = "skip"
                entry["message"] = "无代码变更，跳过版本号检查"
            else:
                valid, version_msg = validate_version()
                if not valid:
                    entry["status"] = "fail"
                    entry["message"] = version_msg
                else:
                    entry["status"] = "pass"
                    entry["message"] = f"版本号校验通过: {version_msg}"
            check_results.append(entry)
            continue

        # ---- 类型: gap_check --------------------------------------------------------
        if rule_type == "gap_check":
            if not has_code:
                entry["status"] = "skip"
                entry["message"] = "无代码变更，跳过差距登记检查"
            elif not _scopes_any_exists(scopes):
                entry["status"] = "fail"
                entry["missing_docs"] = scopes
                entry["message"] = message
            elif not _scopes_any_modified(scopes, changed_files):
                entry["status"] = "warning"
                entry["missing_docs"] = _scopes_missing(scopes, changed_files)
                entry["message"] = message
            else:
                entry["status"] = "pass"
                entry["message"] = f"\u2713 {name}"
            check_results.append(entry)
            continue

        # ---- 类型: file_modified ----------------------------------------------------
        triggered = _is_triggered(rule, changed_files)
        if not triggered:
            entry["status"] = "skip"
            entry["message"] = "未触发检查条件"
            check_results.append(entry)
            continue

        # 检查文档存在性
        doc_exists = _scopes_any_exists(scopes)
        if not doc_exists:
            entry["status"] = "fail"
            entry["missing_docs"] = scopes
            entry["message"] = message + "（文档不存在）"
            check_results.append(entry)
            continue

        # 检查文档是否在变更中
        doc_modified = _scopes_any_modified(scopes, changed_files)
        if not doc_modified:
            if severity == "P0":
                entry["status"] = "fail"
            else:
                entry["status"] = "warning"
            entry["missing_docs"] = _scopes_missing(scopes, changed_files)
            entry["message"] = message
        else:
            entry["status"] = "pass"
            entry["message"] = f"\u2713 {name}"

        check_results.append(entry)

    # 构建输出
    passed = [c for c in check_results if c["status"] == "pass"]
    failed = [c for c in check_results if c["status"] == "fail"]
    warnings_list = [c for c in check_results if c["status"] == "warning"]
    skipped = [c for c in check_results if c["status"] == "skip"]

    return {
        "checks": check_results,
        "summary": {
            "total": len(check_results),
            "passed": len(passed),
            "failed": len(failed),
            "warnings": len(warnings_list),
            "skipped": len(skipped),
            "compliant": len(failed) == 0,
        }
    }


# =============================================================================
# 结果输出
# =============================================================================

def print_results(results: Dict[str, Any]) -> None:
    """打印检查结果"""
    checks = results.get("checks", [])
    summary = results.get("summary", {})

    print("\n" + "=" * 70)
    print("   Harness 工程规范 — commit 前检查")
    print("=" * 70)

    changes = get_git_changes()
    print(f"\n变更文件: {len(changes)} 个")

    passed = [c for c in checks if c["status"] == "pass"]
    failed = [c for c in checks if c["status"] == "fail"]
    warnings_list = [c for c in checks if c["status"] == "warning"]
    skipped = [c for c in checks if c["status"] == "skip"]

    if passed:
        print("\n\u2705 通过的检查:")
        for item in passed:
            print(f"  \u2713 [{item['check_id']}] {item['name']}")

    if warnings_list:
        print("\n\u26a0\ufe0f 建议更新:")
        for item in warnings_list:
            print(f"  \u26a0\ufe0f [{item['check_id']}] {item['message']}")
            if item["missing_docs"]:
                for d in item["missing_docs"]:
                    print(f"       \u2192 缺少: {d}")

    if failed:
        print("\n\u274c 未通过的检查:")
        for item in failed:
            print(f"  \u274c [{item['check_id']}] {item['message']}")
            if item["missing_docs"]:
                for d in item["missing_docs"]:
                    print(f"       \u2192 缺少: {d}")

    if skipped:
        print(f"\n\u23ed\ufe0f  跳过的检查: {len(skipped)} 项")

    print("\n" + "-" * 70)
    print(f"  总结: {summary.get('passed', 0)}/{summary.get('total', 0)} 通过"
          f"  ({summary.get('failed', 0)} 失败, "
          f"{summary.get('warnings', 0)} 建议, "
          f"{summary.get('skipped', 0)} 跳过)")
    if summary.get("compliant", True):
        print("  \u2705 全部检查通过，可以提交")
    else:
        print("  \u274c 检查未通过，请修复后再提交")
    print("-" * 70)


# =============================================================================
# README 版本号自动同步
# =============================================================================

def auto_update_readme() -> None:
    """自动更新 README.md 中的版本号（从 pyproject.toml 同步）"""
    readme_path = PROJECT_ROOT / "README.md"
    version_path = PROJECT_ROOT / "pyproject.toml"
    if not readme_path.exists() or not version_path.exists():
        return

    with open(version_path, "r", encoding="utf-8") as f:
        vcontent = f.read()
    match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', vcontent)
    if not match:
        return
    version = match.group(1)

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    content = re.sub(r'\*\*v\d+\.\d+\.\d+\*\*', f'**v{version}**', content, count=1)

    if content != original:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(content)
        try:
            import subprocess
            subprocess.run(["git", "add", "README.md"], cwd=str(PROJECT_ROOT),
                           capture_output=True, text=True)
        except Exception:
            pass


# =============================================================================
# CLI 入口
# =============================================================================

def main() -> None:
    # 自动同步 README 版本号
    auto_update_readme()

    changes = get_git_changes()

    if not changes:
        print("\u26a0\ufe0f 没有暂存的文件，跳过检查")
        sys.exit(0)

    results = run_checks(changes)
    print_results(results)

    if not results["summary"]["compliant"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
