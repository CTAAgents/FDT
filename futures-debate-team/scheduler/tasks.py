"""
scheduler/tasks.py — 预注册任务

每个任务是一个无参数的异步函数（或同步函数），返回 TaskResult。
通过 `@register_task` 注册到任务注册表，供发动机调度。
"""

import json
import os
import sys
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


# ─── 任务注册表 ─────────────────────────────────────────

_task_registry: dict[str, Callable] = {}


def register_task(name: str):
    """装饰器：注册任务到注册表"""
    def wrapper(func):
        _task_registry[name] = func
        return func
    return wrapper


def get_task(name: str) -> Callable | None:
    return _task_registry.get(name)


def list_tasks() -> list[str]:
    return list(_task_registry.keys())


# ─── 任务结果 ───────────────────────────────────────────

@dataclass
class TaskResult:
    task_name: str
    success: bool
    started_at: str = ""
    finished_at: str = ""
    summary: str = ""
    error: str = ""
    details: dict = field(default_factory=dict)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def _run_script(script_rel: str, *args: str, timeout: int = 300) -> tuple[bool, str]:
    """运行项目内的脚本"""
    root = _project_root()
    script_path = root / script_rel
    if not script_path.exists():
        return False, f"脚本不存在: {script_path}"

    venv_python = str(root / "venv" / "Scripts" / "python.exe")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    cmd = [venv_python, str(script_path)] + list(args)
    _log(f"运行: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace"
        )
        if result.returncode == 0:
            # 取最后一行非空输出作为摘要
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            summary = lines[-1] if lines else "完成"
            return True, summary
        else:
            error = result.stderr.strip()[:200] if result.stderr.strip() else "未知错误"
            return False, error
    except subprocess.TimeoutExpired:
        return False, f"超时({timeout}s)"
    except Exception as e:
        return False, str(e)


# ─── 任务实现 ───────────────────────────────────────────

@register_task("daily_debate")
def daily_debate() -> TaskResult:
    """日常辩论 — 全量扫描62品种"""
    start = datetime.now()
    _log("📊 开始日常辩论全量扫描")

    # 模式一实战辩论比POC复杂，先做POC简化版：只做扫描+汇总
    success, summary = _run_script(
        "skills/quant-daily/scripts/scan_all.py",
        "--dual",
        timeout=180,
    )

    # 记录到debate_journal（简化版只记录触发）
    journal_path = _project_root() / "memory" / "debate_journal.json"
    entry = {
        "triggered_at": start.strftime("%Y-%m-%d %H:%M"),
        "type": "daily_debate",
        "scan_result": "ok" if success else "failed",
    }
    try:
        if journal_path.exists():
            with open(journal_path) as f:
                journal = json.load(f)
        else:
            journal = {"entries": []}
        journal["entries"].append(entry)
        with open(journal_path, "w") as f:
            json.dump(journal, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return TaskResult(
        task_name="daily_debate",
        success=success,
        started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        error="" if success else summary,
    )


@register_task("auto_publish")
def auto_publish() -> TaskResult:
    """自动发布 — 版本号自增 + Git推送"""
    start = datetime.now()
    _log("📦 开始自动发布")

    sync_script = _project_root().parent.parent.parent.parent / "quant-bare" / "sync_experts_to_github.py"
    if not sync_script.exists():
        sync_script = Path("C:/Users/yangd/quant-bare/sync_experts_to_github.py")

    if sync_script.exists():
        success, summary = _run_script(str(sync_script.relative_to(_project_root().parent)), timeout=120)
    else:
        success, summary = False, "sync脚本不存在"

    return TaskResult(
        task_name="auto_publish",
        success=success,
        started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        error="" if success else summary,
    )


@register_task("update_dominant_mapping")
def update_dominant_mapping() -> TaskResult:
    """更新主力合约映射"""
    start = datetime.now()
    _log("🔄 更新主力合约映射")

    # 主力映射在 scan_all.py 中自动完成，此处作为显式触发入口
    # 执行主力映射更新脚本（略：目前集成在scan_all中，独立为占位）
    return TaskResult(
        task_name="update_dominant_mapping",
        success=True,
        started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary="主力映射集成在scan_all中，自动完成",
    )


@register_task("validate_and_evolve")
def validate_and_evolve() -> TaskResult:
    """验证裁决 → 校准 → 进化（自循环P0）"""
    start = datetime.now()
    _log("🔬 开始验证→校准→进化管道")

    steps = [
        ("scripts/validate_verdicts.py", [], "验证历史裁决", 120),
        ("scripts/calibrate_weights.py", [], "校准评分权重", 60),
        ("scripts/evolve_agents.py", [], "进化Agent参数", 60),
        ("ml/trainer.py", [], "ML训练检查", 180),
    ]

    results = {}
    all_ok = True
    for script_path, args, label, timeout in steps:
        exists = (_project_root() / script_path).exists()
        if not exists:
            results[label] = "跳过（脚本不存在）"
            continue
        ok, msg = _run_script(script_path, *args, timeout=timeout)
        results[label] = "✅" if ok else f"❌ {msg}"
        if not ok:
            all_ok = False

    summary = " | ".join(f"{k}: {v}" for k, v in results.items())
    return TaskResult(
        task_name="validate_and_evolve",
        success=all_ok,
        started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        details=results,
    )


@register_task("ml_training_check")
def ml_training_check() -> TaskResult:
    """ML训练检查 — TrainingOrchestrator"""
    start = datetime.now()
    _log("🧠 检查ML训练条件")

    trainer_path = _project_root() / "ml" / "trainer.py"
    if not trainer_path.exists():
        return TaskResult(
            task_name="ml_training_check",
            success=True,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary="跳过（trainer.py不存在）",
        )

    # 通过脚本运行
    success, summary = _run_script("ml/trainer.py", "--check", timeout=120)

    return TaskResult(
        task_name="ml_training_check",
        success=success,
        started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        error="" if success else summary,
    )


# ─── 直接运行（模拟调度） ──────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        task = get_task(sys.argv[1])
        if task:
            result = task()
            print(f"\n{'✅' if result.success else '❌'} {result.task_name}")
            print(f"  {result.summary}")
            if result.error:
                print(f"  错误: {result.error}")
        else:
            print(f"未知任务: {sys.argv[1]}")
            print(f"可用任务: {', '.join(list_tasks())}")
    else:
        print(f"可用任务 ({len(_task_registry)}):")
        for name in sorted(_task_registry.keys()):
            print(f"  {name}")
