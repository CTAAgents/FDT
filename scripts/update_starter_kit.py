"""
更新 D:\HarnessStarterKit\ 模板项目，部署 RHI 自进化能力。
"""
import os
from pathlib import Path

KIT = Path(r"D:\HarnessStarterKit")

def update_claude_md():
    path = KIT / "CLAUDE.md"
    content = path.read_text(encoding="utf-8")

    rhi_section = """
## RHI 递归 Harness 自进化（v9.22.0+）

本项目的 CLAUDE.md 支持 RHI 自优化。将 CLAUDE.md 作为可迭代的 Harness prompt，
每次 step 比较当前版本与上一版本的输出质量评分。

使用方式：
```bash
python scripts/rhi_global_setup.py init     # 首版快照
python scripts/rhi_global_setup.py step     # 执行一轮自优化
python scripts/rhi_global_setup.py status   # 查看评分与收敛状态
```

评分维度：memory_coverage(0.30) + rule_completeness(0.30) + consistency(0.20) + clarity(0.20)
改进率低于 0.3 或达最大轮次后自动收敛。

参考：
- RHI: Recursive Harness Self-Improvement, arXiv:2607.15524
- MemoHarness: Agent Harnesses That Learn from Experience, arXiv:2607.14159
"""

    if "RHI 递归 Harness 自进化" in content:
        print("[--] CLAUDE.md 已有 RHI 章节，跳过")
    else:
        # 在文件末尾前插入（保留末尾引用行）
        content = content.replace(
            "> 项目根目录的 CLAUDE.md 可在此基础之上扩展项目专属内容（如 Agent 列表、项目流程等）。",
            rhi_section.strip() + "\n\n> 项目根目录的 CLAUDE.md 可在此基础之上扩展项目专属内容（如 Agent 列表、项目流程等）。"
        )
        path.write_text(content, encoding="utf-8")
        print("[OK] CLAUDE.md 已添加 RHI 章节")


def update_deploy_harness():
    path = KIT / "scripts" / "deploy_harness.py"
    content = path.read_text(encoding="utf-8")

    if "rhi_global_setup.py" in content:
        print("[--] deploy_harness.py 已有 rhi_global_setup.py，跳过")
        return

    # 在脚本列表中添加 rhi_global_setup.py
    old = "def deploy(project_root):"
    insert = """
def deploy(project_root):
    # 确保 rhi_global_setup.py 也在部署范围内
    _rhi_setup_src = os.path.join(STARTER_KIT, "scripts", "rhi_global_setup.py")
    _rhi_setup_dst = os.path.join(project_root, "scripts", "rhi_global_setup.py")
    if os.path.exists(_rhi_setup_src) and not os.path.exists(_rhi_setup_dst):
        os.makedirs(os.path.join(project_root, "scripts"), exist_ok=True)
        shutil.copy2(_rhi_setup_src, _rhi_setup_dst)
        result.setdefault("deployed_files", []).append("scripts/rhi_global_setup.py")
"""
    content = content.replace(old, insert)
    path.write_text(content, encoding="utf-8")
    print("[OK] deploy_harness.py 已添加 RHI 部署")


def update_harness_readme():
    path = KIT / "docs" / "harness" / "README.md"
    content = path.read_text(encoding="utf-8")

    if "RHI" in content:
        print("[--] docs/harness/README.md 已有 RHI，跳过")
        return

    new_line = "| 13 | [scripts/rhi_global_setup.py](../../scripts/rhi_global_setup.py) | RHI 递归 Harness 自进化（v9.22.0+） |\n"
    content = content.rstrip() + "\n" + new_line
    path.write_text(content, encoding="utf-8")
    print("[OK] docs/harness/README.md 已添加 RHI 条目")


def update_root_readme():
    path = KIT / "README.md"
    content = path.read_text(encoding="utf-8")

    if "rhi_global_setup.py" in content:
        print("[--] README.md 已有 RHI，跳过")
        return

    # 更新目录结构
    old_tree = """└── scripts\\
    ├── deploy_harness.py        # 手动部署脚本
    └── pre_commit_harness_check.py  # commit 前自动检查脚本"""
    new_tree = """└── scripts\\
    ├── deploy_harness.py        # 手动部署脚本
    ├── pre_commit_harness_check.py  # commit 前自动检查脚本
    └── rhi_global_setup.py      # RHI 递归 Harness 自进化（v9.22.0+）"""

    content = content.replace(old_tree, new_tree)

    # 添加使用说明
    rhi_usage = """

## RHI 递归 Harness 自进化（v9.22.0+）

RHI 让 CLAUDE.md 能自我优化：

```bash
python scripts/rhi_global_setup.py init     # 首版快照
python scripts/rhi_global_setup.py step     # 执行一轮优化
python scripts/rhi_global_setup.py status   # 查看状态
```

每次 step 从四维评分 CLAUDE.md，记录 pairwise 偏好，改进率低于 0.3 时收敛。
参考：RHI (arXiv:2607.15524) + MemoHarness (arXiv:2607.14159)
"""

    content = content.rstrip() + rhi_usage
    path.write_text(content, encoding="utf-8")
    print("[OK] README.md 已更新")


if __name__ == "__main__":
    print("=== 更新 HarnessStarterKit ===\n")
    update_claude_md()
    update_deploy_harness()
    update_harness_readme()
    update_root_readme()
    print("\n✅ 全部完成")
