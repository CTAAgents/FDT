#!/usr/bin/env python3
"""commit前Harness规范检查脚本 — 强制执行12项检查清单"""

import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Tuple

PROJECT_ROOT = Path(__file__).parent.parent

CHECKLIST = [
    {"id": 1, "name": "数据流/架构变更", "doc": "docs/harness/01-architecture.md", "required": True},
    {"id": 2, "name": "阶段/文件名/产出物", "doc": "docs/harness/02-lifecycle.md", "required": True},
    {"id": 3, "name": "新配置项", "doc": "docs/harness/03-configuration.md", "required": False},
    {"id": 4, "name": "降级/熔断/超时路径", "doc": "docs/harness/04-resilience.md", "required": True},
    {"id": 5, "name": "新指标/日志", "doc": "docs/harness/05-observability.md", "required": False},
    {"id": 6, "name": "测试文件和用例数", "doc": "docs/harness/06-testing.md", "required": True},
    {"id": 7, "name": "版本号和版本历史", "doc": "docs/harness/07-operations.md", "required": True},
    {"id": 8, "name": "差距登记/关闭", "doc": "docs/harness/08-gap-analysis.md", "required": False},
    {"id": 9, "name": "晋级里程碑", "doc": "docs/harness/09-advancement-plan.md", "required": False},
    {"id": 10, "name": "流程文档", "doc": "execution_modes_flowchart.md", "required": False},
    {"id": 11, "name": "角色MD职责", "doc": "agents/*.md", "required": False},
    {"id": 12, "name": "README快速参考", "doc": "README.md", "required": True},
]


def get_git_changes() -> List[str]:
    """获取git暂存区文件列表"""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip().split("\n")
        return []
    except Exception as e:
        print(f"❌ 获取git变更失败: {e}")
        return []


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
    """检查文档是否存在"""
    path = PROJECT_ROOT / doc_path
    if "*" in doc_path:
        pattern = doc_path.replace("*.md", "")
        return any(f.startswith(pattern) for f in os.listdir(PROJECT_ROOT / pattern[:-1]) if f.endswith(".md"))
    return path.exists()


def check_doc_modified(doc_path: str, changes: List[str]) -> bool:
    """检查文档是否被修改"""
    if "*" in doc_path:
        pattern = doc_path.replace("*.md", "")
        return any(f.startswith(pattern) for f in changes if f.strip())
    return doc_path in changes


def validate_version() -> Tuple[bool, str]:
    """验证版本号"""
    version_path = PROJECT_ROOT / "pyproject.toml"
    if not version_path.exists():
        return False, "pyproject.toml不存在"
    
    with open(version_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    import re
    match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        return False, "pyproject.toml中未找到version字段"
    
    version = match.group(1)
    if not version:
        return False, "版本号为空"
    
    return True, f"版本号: {version}"


def run_checks(changes: List[str]) -> Dict:
    """运行所有检查"""
    results = {
        "passed": [],
        "failed": [],
        "warnings": [],
        "summary": {
            "total": len(CHECKLIST),
            "passed": 0,
            "failed": 0,
            "warnings": 0,
            "compliant": True
        }
    }
    
    has_code = has_code_changes(changes)
    
    for item in CHECKLIST:
        doc_exists = check_doc_exists(item["doc"])
        doc_modified = check_doc_modified(item["doc"], changes)
        
        status = "pass"
        message = ""
        
        if not doc_exists:
            status = "fail"
            message = f"文档不存在: {item['doc']}"
        elif has_code and item["required"] and not doc_modified:
            status = "fail"
            message = f"代码变更未同步更新: {item['doc']}"
        elif has_code and not item["required"] and not doc_modified:
            status = "warning"
            message = f"建议更新: {item['doc']}"
        else:
            status = "pass"
            message = f"✓ {item['name']}"
        
        if status == "pass":
            results["passed"].append({"id": item["id"], "name": item["name"], "doc": item["doc"]})
        elif status == "fail":
            results["failed"].append({"id": item["id"], "name": item["name"], "doc": item["doc"], "message": message})
        else:
            results["warnings"].append({"id": item["id"], "name": item["name"], "doc": item["doc"], "message": message})
    
    version_valid, version_msg = validate_version()
    if not version_valid:
        results["failed"].append({"id": 0, "name": "版本号验证", "doc": "pyproject.toml", "message": version_msg})
    else:
        results["passed"].append({"id": 0, "name": "版本号验证", "doc": "pyproject.toml", "message": version_msg})
    
    results["summary"]["passed"] = len(results["passed"])
    results["summary"]["failed"] = len(results["failed"])
    results["summary"]["warnings"] = len(results["warnings"])
    results["summary"]["compliant"] = len(results["failed"]) == 0
    
    return results


def print_results(results: Dict):
    """打印检查结果"""
    print("\n" + "=" * 70)
    print("   FDT Harness工程规范 — commit前检查")
    print("=" * 70)
    
    print(f"\n检查文件: {len(get_git_changes())} 个")
    
    if results["passed"]:
        print("\n✅ 通过的检查:")
        for item in results["passed"]:
            if item["id"] == 0:
                print(f"  ✓ {item['name']}: {item['message']}")
            else:
                print(f"  ✓ [{item['id']}] {item['name']} → {item['doc']}")
    
    if results["warnings"]:
        print("\n⚠️ 建议更新:")
        for item in results["warnings"]:
            print(f"  ⚠️ [{item['id']}] {item['message']}")
    
    if results["failed"]:
        print("\n❌ 未通过的检查:")
        for item in results["failed"]:
            print(f"  ❌ [{item['id']}] {item['name']}: {item['message']}")
    
    print("\n" + "-" * 70)
    print(f"  总结: {results['summary']['passed']}/{results['summary']['total']} 通过")
    
    if results["summary"]["compliant"]:
        print("  ✅ 全部检查通过，可以提交")
    else:
        print("  ❌ 检查未通过，请修复后再提交")
    print("-" * 70)


def main():
    changes = get_git_changes()
    
    if not changes:
        print("⚠️ 没有暂存的文件，跳过检查")
        sys.exit(0)
    
    results = run_checks(changes)
    print_results(results)
    
    if not results["summary"]["compliant"]:
        sys.exit(1)


if __name__ == "__main__":
    main()