"""
RHI 全局 Harness CLI — 任何项目都可以使用的 Harness 自优化工具。

安装:
  python scripts/rhi_global_cli.py install    # 自动安装到 PATH

用法:
  python scripts/rhi_global_cli.py init [--project PATH]
  python scripts/rhi_global_cli.py status [--project PATH]
  python scripts/rhi_global_cli.py step [--project PATH] [--max-iters 3]
  python scripts/rhi_global_cli.py history [--project PATH]

原理:
  将项目的 CLAUDE.md 作为 Harness prompt，每次迭代比较当前版本与上一版本的
  输出质量评分 (四维: 覆盖度/完整性/一致性/清晰度)，决定是否保留更新。

参考:
  RHI: Recursive Harness Self-Improvement, arXiv:2607.15524
  MemoHarness: Agent Harnesses That Learn from Experience, arXiv:2607.14159
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# 全局存储目录（用户级）
GLOBAL_RHI_DIR = Path(os.environ.get("RHI_GLOBAL_DIR", str(Path.home() / ".rhi-global")))

# HARMMON 模板（无项目时创建的最小模板）
STARTER_TEMPLATE = """# RHI 全局 Harness — 项目 {project_name}

> 自动部署于 {deploy_time}
> 参考: RHI (arXiv:2607.15524) + MemoHarness (arXiv:2607.14159)

## 项目背景
{project_desc}

## 全局规则（RHI 可迭代优化以下内容）

### 1. 核心约束
- 文档先行：改代码前先改对应文档
- 契约优先：先定义 Schema 再实现
- 测试随重构：测试全绿才能进入下一阶段

### 2. 通信规则
- 信息传递必须明确契约
- 禁止绕过约定的接口直接访问内部状态

### 3. 验收门禁
- 变更后运行回归测试
- 关键路径必须有独立验证

### 4. RHI 自改进状态
- 上次优化: 尚未运行
- 当前评分: 待评估
- 迭代次数: 0
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("rhi-global")


# ─── 工具函数 ───


def _get_project_root(path: str | None = None) -> Path:
    """获取项目根目录。优先取 path 参数，否则从 CWD 开始向上找 CLAUDE.md。"""
    if path:
        return Path(path).resolve()
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / "CLAUDE.md").exists() or (parent / ".git").exists():
            return parent
    return cwd


def _get_rhi_dir(project_root: Path) -> Path:
    """获取项目级 RHI 存储目录。"""
    return project_root / ".rhi"


def _score_claude_md(claude_path: Path) -> dict:
    """对 CLAUDE.md 进行四维质量评分。

    维度:
      - memory_coverage (0.30): 是否引用项目记忆 / 知识库
      - rule_completeness (0.30): 检查清单和反模式是否齐全
      - consistency (0.20): 与 harness/docs 的引用正确
      - clarity (0.20): 文件长度适度 (< 300 行最佳)

    Returns:
        {"score": float, "breakdown": dict}
    """
    if not claude_path.exists():
        return {"score": 0.0, "breakdown": {}}

    content = claude_path.read_text(encoding="utf-8")
    scores = {}

    # 记忆覆盖度
    has_memory = "project_memory" in content or "memory" in content
    has_knowledge = "Knowledge" in content or "knowledge" in content
    scores["memory_coverage"] = 1.0 if (has_memory and has_knowledge) else (0.5 if (has_memory or has_knowledge) else 0.0)

    # 规则完整性
    has_checklist = any(k in content for k in ["检查清单", "checklist", "Checklist", "12项"])
    has_antipattern = any(k in content for k in ["反模式", "anti-pattern", "AP01"])
    scores["rule_completeness"] = 1.0 if (has_checklist and has_antipattern) else (0.5 if (has_checklist or has_antipattern) else 0.0)

    # 一致性
    has_harness = "Harness" in content
    has_docs = any(d in content for d in ["docs/", "CLAUDE.md", "README"])
    scores["consistency"] = 1.0 if (has_harness and has_docs) else (0.5 if (has_harness or has_docs) else 0.0)

    # 清晰度
    total_lines = len(content.splitlines())
    scores["clarity"] = 1.0 if total_lines < 300 else (0.5 if total_lines < 500 else 0.2)

    weights = {"memory_coverage": 0.30, "rule_completeness": 0.30, "consistency": 0.20, "clarity": 0.20}
    total = sum(scores[k] * weights[k] for k in weights)

    return {"score": round(total, 4), "breakdown": scores}


def _load_history(project_root: Path) -> dict:
    """加载项目的 RHI 历史。"""
    rhi_dir = _get_rhi_dir(project_root)
    history_file = rhi_dir / "history.json"
    if history_file.exists():
        try:
            return json.loads(history_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"versions": [], "preferences": [], "improvement_rate": 0.0, "best_version": 0, "converged": False}


def _save_history(project_root: Path, history: dict) -> None:
    """保存项目的 RHI 历史。"""
    rhi_dir = _get_rhi_dir(project_root)
    rhi_dir.mkdir(parents=True, exist_ok=True)
    history_file = rhi_dir / "history.json"
    history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 子命令实现 ───


def cmd_init(args: argparse.Namespace) -> int:
    """初始化项目级 RHI Harness。

    如果项目没有 CLAUDE.md，创建最小模板。
    如果已有，记录版本快照。
    """
    project_root = _get_project_root(args.project)
    claude_path = project_root / "CLAUDE.md"

    if not claude_path.exists():
        # 创建最小模板
        name = project_root.name
        claude_path.write_text(
            STARTER_TEMPLATE.format(
                project_name=name,
                deploy_time=datetime.now().isoformat(),
                project_desc=args.desc or f"项目 {name} 的 Harness 规范",
            ),
            encoding="utf-8",
        )
        logger.info(f"[init] 创建 CLAUDE.md: {claude_path}")
    else:
        logger.info(f"[init] CLAUDE.md 已存在: {claude_path}")

    # 记录首版本快照
    score = _score_claude_md(claude_path)
    history = _load_history(project_root)
    if not history["versions"]:
        history["versions"].append({
            "version": 0,
            "timestamp": datetime.now().isoformat(),
            "score": score["score"],
            "breakdown": score["breakdown"],
            "content_length": len(claude_path.read_text(encoding="utf-8")),
        })
        _save_history(project_root, history)
        logger.info(f"[init] 首版本评分: {score['score']:.3f}")
    else:
        logger.info(f"[init] 已有 {len(history['versions'])} 个版本记录")

    print("\n=== ✅ RHI Harness 初始化完成 ===")
    print(f"  项目: {project_root}")
    print(f"  评分: {score['score']:.3f}")
    print(f"  文件: {claude_path}")
    print(f"  历史: {_get_rhi_dir(project_root) / 'history.json'}")
    print()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """显示当前项目 Harness 状态。"""
    project_root = _get_project_root(args.project)
    claude_path = project_root / "CLAUDE.md"
    history = _load_history(project_root)

    score = _score_claude_md(claude_path) if claude_path.exists() else {"score": 0.0, "breakdown": {}}
    versions = history.get("versions", [])
    prefs = history.get("preferences", [])

    print("\n=== 📊 RHI Harness 状态 ===")
    print(f"  项目: {project_root}")
    print(f"  CLAUDE.md: {'✅ 存在' if claude_path.exists() else '❌ 不存在'}")
    print(f"  当前评分: {score['score']:.3f}")
    print(f"  版本记录: {len(versions)} 个")
    print(f"  偏好历史: {len(prefs)} 次")
    print(f"  改进率: {history.get('improvement_rate', 0):.3f}")
    print(f"  最优版本: #{history.get('best_version', 0)}")
    print(f"  收敛状态: {'✅ 已收敛' if history.get('converged') else '⏳ 进行中'}")
    print()
    print("  评分明细:")
    for dim, val in score["breakdown"].items():
        bar = "█" * int(val * 20) + "░" * (20 - int(val * 20))
        print(f"    {dim:25s} {bar} {val:.2f}")
    print()
    return 0


def cmd_step(args: argparse.Namespace) -> int:
    """执行一轮 RHI Harness 自改进。

    评分当前 CLAUDE.md，与上一版本比较，记录偏好。
    这是 RHI Algorithm 1 在全局 Harness 层面的适配。
    """
    project_root = _get_project_root(args.project)
    claude_path = project_root / "CLAUDE.md"

    if not claude_path.exists():
        logger.error("[step] CLAUDE.md 不存在，请先运行 init")
        return 1

    history = _load_history(project_root)
    versions = history.get("versions", [])
    preferences = history.get("preferences", [])
    max_iters = args.max_iters or 3
    iter_num = len(versions)

    if iter_num >= max_iters:
        history["converged"] = True
        _save_history(project_root, history)
        logger.info(f"[step] 已达最大轮次 {max_iters}，标记为收敛")
        return 0

    current_content = claude_path.read_text(encoding="utf-8")
    current_score = _score_claude_md(claude_path)

    # 与上一版本比较
    if versions:
        prev = versions[-1]
        prev_score = prev.get("score", 0)
        delta = current_score["score"] - prev_score

        if delta > 0.02:
            preference = "improve"
        elif delta < -0.02:
            preference = "regress"
        else:
            preference = "tie"

        rationale = f"评分 {delta:+.3f} (cur={current_score['score']:.3f}, prev={prev_score:.3f})"
        preferences.append({
            "iteration": iter_num,
            "preference": preference,
            "score_current": current_score["score"],
            "score_previous": prev_score,
            "score_breakdown": {"current": current_score["breakdown"], "previous": prev.get("breakdown", {})},
            "rationale": rationale,
            "key_diffs": [],
        })
    else:
        preferences.append({
            "iteration": 0,
            "preference": "tie",
            "score_current": current_score["score"],
            "score_previous": 0.0,
            "score_breakdown": {"current": current_score["breakdown"], "previous": {}},
            "rationale": "首轮基准评分",
            "key_diffs": [],
        })

    # 记录版本
    versions.append({
        "version": iter_num,
        "timestamp": datetime.now().isoformat(),
        "score": current_score["score"],
        "breakdown": current_score["breakdown"],
        "content_length": len(current_content),
    })

    # 改进率
    try:
        sys.path.insert(0, str(HERE.parent))
        from scripts.rhi_pairwise_eval import compute_improvement_rate
    except ImportError:
        # 回退: 手动计算
        def compute_improvement_rate(prefs):
            if not prefs:
                return 0.0
            improves = sum(1 for p in prefs if p.get("preference") == "improve")
            return improves / len(prefs)
    s_i = compute_improvement_rate(preferences)
    history["versions"] = versions
    history["preferences"] = preferences
    history["improvement_rate"] = s_i
    history["best_version"] = max(range(len(versions)), key=lambda i: versions[i].get("score", 0))

    # 停止检查
    if s_i < 0.3 and len(preferences) >= 2:
        history["converged"] = True
    elif iter_num >= max_iters - 1:
        history["converged"] = True

    _save_history(project_root, history)

    last_pref = preferences[-1]
    icon = {"improve": "✅", "regress": "❌", "tie": "➡️"}.get(last_pref["preference"], "➡️")

    print(f"\n=== {'🔄 RHI 迭代完成' if not history['converged'] else '🎯 RHI 已收敛'} ===")
    print(f"  轮次: #{iter_num}")
    print(f"  偏好: {icon} {last_pref['preference']}")
    print(f"  评分: {last_pref['score_current']:.3f} (vs {last_pref['score_previous']:.3f})")
    print(f"  改进率: {s_i:.3f}")
    print(f"  原因: {last_pref.get('rationale', '')}")
    print()

    if history["converged"]:
        print(f"  停止原因: s_i={s_i:.3f} < 0.3 或达最大轮次")
        best = history["versions"][history["best_version"]]
        print(f"  最优版本: #{history['best_version']} (评分 {best['score']:.3f})")
        print()

    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """显示 RHI 优化历史。"""
    project_root = _get_project_root(args.project)
    history = _load_history(project_root)
    versions = history.get("versions", [])
    preferences = history.get("preferences", [])

    if not versions:
        print("\n📭 无 RHI 历史记录\n")
        return 0

    print("\n=== 📜 RHI Harness 优化历史 ===")
    for v in versions:
        ts = v.get("timestamp", "")[:19]
        score = v.get("score", 0)
        length = v.get("content_length", 0)
        pref = next((p for p in preferences if p.get("iteration") == v.get("version")), {})
        icon = {"improve": "✅", "regress": "❌", "tie": "➡️"}.get(pref.get("preference", "tie"), "➡️")
        print(f"  #{v['version']} {icon} {ts} | 评分 {score:.3f} | {length} chars")
    print(f"\n  总版本数: {len(versions)}")
    print(f"  改进率: {history.get('improvement_rate', 0):.3f}")
    print(f"  最优版本: #{history.get('best_version', 0)}")
    print(f"  收敛: {'✅' if history.get('converged') else '⏳ 否'}")
    print()
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """安装 rhi-global 到用户 PATH。

    创建 `rhi-global` 脚本到 ~/.local/bin (Unix) 或 %USERPROFILE%\\.rhi-global\\bin (Windows)。
    """
    if sys.platform == "win32":
        bin_dir = GLOBAL_RHI_DIR / "bin"
    else:
        bin_dir = Path.home() / ".local" / "bin"

    bin_dir.mkdir(parents=True, exist_ok=True)

    # 创建入口脚本
    entry_path = bin_dir / ("rhi-global.bat" if sys.platform == "win32" else "rhi-global")
    entry_content = f"""@echo off
python "{HERE / 'rhi_global_cli.py'}" %*
""" if sys.platform == "win32" else f"""#!/bin/bash
python3 "{HERE / 'rhi_global_cli.py'}" "$@"
"""
    entry_path.write_text(entry_content, encoding="utf-8")
    if sys.platform != "win32":
        entry_path.chmod(0o755)

    print("\n=== 📦 RHI Global CLI 已安装 ===")
    print(f"  入口: {entry_path}")
    print(f"  存储: {GLOBAL_RHI_DIR}")
    print()
    print("  用法: rhi-global init [--project PATH]")
    print("        rhi-global status [--project PATH]")
    print("        rhi-global step [--project PATH]")
    print("        rhi-global history [--project PATH]")
    print()

    # 提示添加 PATH
    if sys.platform == "win32":
        if str(bin_dir) not in os.environ.get("PATH", ""):
            print("  ℹ️ 请将以下目录添加到 PATH:")
            print(f"     {bin_dir}")
            print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RHI 全局 Harness CLI — 任何项目的递归 Harness 自改进",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  rhi-global init                         # 初始化当前项目
  rhi-global init --project /path/to/proj # 指定项目
  rhi-global status                       # 查看状态
  rhi-global step                         # 执行一轮优化
  rhi-global history                      # 查看历史
  rhi-global install                      # 安装到 PATH
""",
    )
    parser.add_argument("--project", "-p", help="项目根目录（默认从 CWD 自动检测）")
    parser.add_argument("--max-iters", "-n", type=int, default=3, help="最大迭代轮次（默认 3）")
    parser.add_argument("--desc", "-d", help="项目描述（init 时使用）")
    parser.add_argument("command", nargs="?", default="status",
                        choices=["init", "status", "step", "history", "install"],
                        help="子命令")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "step": cmd_step,
        "history": cmd_history,
        "install": cmd_install,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
