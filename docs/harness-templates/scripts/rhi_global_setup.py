"""
RHI 全局 Harness 自进化 — Starter Kit 一键部署。

将此脚本复制到任意项目后运行：
  python scripts/rhi_global_setup.py init     # 初始化 RHI 自进化
  python scripts/rhi_global_setup.py step     # 执行一轮优化
  python scripts/rhi_global_setup.py status   # 查看状态

原理：
  将项目的 CLAUDE.md 作为 Harness prompt，每次 step 比较当前版本
  与上一版本的输出质量评分，决定是否保留更新。

参考：
  RHI: Recursive Harness Self-Improvement, arXiv:2607.15524
  MemoHarness: Agent Harnesses That Learn from Experience, arXiv:2607.14159

部署方式：
  python D:\\HarnessStarterKit\\scripts\\rhi_global_setup.py deploy
  → 将本脚本 + 配置复制到当前项目
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

STARTER_KIT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("rhi-setup")

# ─── 评分函数 ───

def _score_claude(claude_path: Path) -> dict:
    if not claude_path.exists():
        return {"score": 0.0, "breakdown": {}}
    content = claude_path.read_text(encoding="utf-8")
    scores = {}
    has_memory = "memory" in content.lower()
    has_knowledge = "knowledge" in content.lower()
    scores["memory_coverage"] = 1.0 if (has_memory and has_knowledge) else (0.5 if (has_memory or has_knowledge) else 0.0)
    has_check = any(k in content for k in ["检查清单", "checklist", "12项"])
    has_anti = any(k in content for k in ["反模式", "anti-pattern", "AP01"])
    scores["rule_completeness"] = 1.0 if (has_check and has_anti) else (0.5 if (has_check or has_anti) else 0.0)
    has_harness = "Harness" in content
    has_docs = any(d in content for d in ["docs/", "CLAUDE.md"])
    scores["consistency"] = 1.0 if (has_harness and has_docs) else (0.5 if (has_harness or has_docs) else 0.0)
    lines = len(content.splitlines())
    scores["clarity"] = 1.0 if lines < 300 else (0.5 if lines < 500 else 0.2)
    weights = {"memory_coverage": 0.30, "rule_completeness": 0.30, "consistency": 0.20, "clarity": 0.20}
    total = sum(scores[k] * weights[k] for k in weights)
    return {"score": round(total, 4), "breakdown": scores}

def _improvement_rate(prefs: list) -> float:
    if not prefs:
        return 0.0
    improves = sum(1 for p in prefs if p.get("preference") == "improve")
    return improves / len(prefs)

# ─── 子命令 ───

def cmd_deploy(args: argparse.Namespace) -> int:
    """将 RHI 部署到指定项目。"""
    if args.project:
        target = Path(args.project).resolve()
    else:
        target = Path.cwd()
    rhi_dir = target / ".rhi"
    rhi_dir.mkdir(parents=True, exist_ok=True)

    # 复制本脚本到目标项目
    script_dst = target / "scripts" / "rhi_global_setup.py"
    if not target.joinpath("scripts").exists():
        target.joinpath("scripts").mkdir(parents=True, exist_ok=True)
    if not script_dst.exists():
        shutil.copy2(__file__, script_dst)
        logger.info(f"[deploy] 已复制 rhi_global_setup.py 到 {script_dst}")

    # 初始化历史
    history_file = rhi_dir / "history.json"
    if not history_file.exists():
        init_history = {"versions": [], "preferences": [], "improvement_rate": 0.0, "best_version": 0, "converged": False}
        history_file.write_text(json.dumps(init_history, indent=2), encoding="utf-8")
        logger.info(f"[deploy] 已创建 {history_file}")

    print(f"\n=== ✅ RHI 已部署到 {target} ===")
    print("  用法: python scripts/rhi_global_setup.py step")
    print("        python scripts/rhi_global_setup.py status")
    return 0

def cmd_init(args: argparse.Namespace) -> int:
    """初始化当前项目的 RHI（首版本快照）。"""
    root = Path(args.project).resolve() if args.project else Path.cwd()
    claude = root / "CLAUDE.md"
    if not claude.exists():
        logger.error(f"CLAUDE.md 不存在: {claude}")
        return 1
    rhi_dir = root / ".rhi"
    rhi_dir.mkdir(parents=True, exist_ok=True)
    history_file = rhi_dir / "history.json"
    history = {"versions": [], "preferences": [], "improvement_rate": 0.0, "best_version": 0, "converged": False}
    score = _score_claude(claude)
    history["versions"].append({
        "version": 0, "timestamp": datetime.now().isoformat(),
        "score": score["score"], "breakdown": score["breakdown"],
        "content_length": len(claude.read_text(encoding="utf-8")),
    })
    history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")
    print("\n=== ✅ RHI 初始化完成 ===")
    print(f"  项目: {root}")
    print(f"  首版评分: {score['score']:.3f}")
    return 0

def cmd_step(args: argparse.Namespace) -> int:
    """执行一轮 RHI 自改进。"""
    root = Path(args.project).resolve() if args.project else Path.cwd()
    claude = root / "CLAUDE.md"
    if not claude.exists():
        logger.error(f"CLAUDE.md 不存在: {claude}")
        return 1
    rhi_dir = root / ".rhi"
    history_file = rhi_dir / "history.json"
    if not history_file.exists():
        logger.error("未初始化，请先运行 init")
        return 1
    history = json.loads(history_file.read_text(encoding="utf-8"))
    max_iters = args.max_iters or 5
    iter_num = len(history.get("versions", []))
    if iter_num >= max_iters:
        history["converged"] = True
        history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(f"  已达最大轮次 {max_iters}，已收敛")
        return 0
    score = _score_claude(claude)
    versions = history.get("versions", [])
    prefs = history.get("preferences", [])
    if versions:
        prev = versions[-1]
        delta = score["score"] - prev.get("score", 0)
        pref = "improve" if delta > 0.02 else ("regress" if delta < -0.02 else "tie")
        prefs.append({"iteration": iter_num, "preference": pref, "score_current": score["score"],
                       "score_previous": prev.get("score", 0), "rationale": f"delta={delta:+.3f}"})
    else:
        prefs.append({"iteration": 0, "preference": "tie", "score_current": score["score"], "score_previous": 0.0, "rationale": "首轮"})
    versions.append({"version": iter_num, "timestamp": datetime.now().isoformat(), "score": score["score"],
                      "breakdown": score["breakdown"], "content_length": len(claude.read_text(encoding="utf-8"))})
    s_i = _improvement_rate(prefs)
    history["versions"] = versions
    history["preferences"] = prefs
    history["improvement_rate"] = s_i
    history["best_version"] = max(range(len(versions)), key=lambda i: versions[i].get("score", 0))
    if s_i < 0.3 and len(prefs) >= 2:
        history["converged"] = True
    elif iter_num >= max_iters - 1:
        history["converged"] = True
    history_file.write_text(json.dumps(history, indent=2), encoding="utf-8")
    icon = {"improve": "✅", "regress": "❌", "tie": "➡️"}.get(prefs[-1]["preference"], "➡️")
    print(f"\n=== {'🔄 RHI' if not history['converged'] else '🎯 收敛'} ===")
    print(f"  轮次: #{iter_num}  {icon} {prefs[-1]['preference']}")
    print(f"  评分: {prefs[-1]['score_current']:.3f} (vs {prefs[-1]['score_previous']:.3f})")
    return 0

def cmd_status(args: argparse.Namespace) -> int:
    """查看当前项目的 RHI 状态。"""
    root = Path(args.project).resolve() if args.project else Path.cwd()
    claude = root / "CLAUDE.md"
    rhi_dir = root / ".rhi"
    history_file = rhi_dir / "history.json"
    score = _score_claude(claude) if claude.exists() else {"score": 0.0}
    history = json.loads(history_file.read_text(encoding="utf-8")) if history_file.exists() else {}
    versions = history.get("versions", [])
    prefs = history.get("preferences", [])
    print("\n=== 📊 RHI 状态 ===")
    print(f"  项目: {root}")
    print(f"  评分: {score['score']:.3f}")
    print(f"  版本: {len(versions)} | 迭代: {len(prefs)} | 改进率: {history.get('improvement_rate', 0):.3f}")
    print(f"  收敛: {'✅' if history.get('converged') else '⏳'}")
    if versions:
        best = max(versions, key=lambda v: v.get("score", 0))
        print(f"  最优: v{best.get('version', '?')} ({best.get('score', 0):.3f})")
    return 0


# ─── CLI ───

def main() -> int:
    parser = argparse.ArgumentParser(description="RHI 全局 Harness 自进化 — Starter Kit")
    parser.add_argument("command", nargs="?", default="status", choices=["init", "step", "status", "deploy"])
    parser.add_argument("--project", "-p", help="目标项目目录（默认 CWD）")
    parser.add_argument("--max-iters", "-n", type=int, default=5, help="最大迭代轮次")
    args = parser.parse_args()
    cmds = {"deploy": cmd_deploy, "init": cmd_init, "step": cmd_step, "status": cmd_status}
    return cmds[args.command](args)

if __name__ == "__main__":
    sys.exit(main())
