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
    """FDT_ROOT（futures-debate-team 包根）。本文件位于 FDT_ROOT/scheduler/，故上溯两级。
    全文件路径基准：_run_script(rel)、root/'skills'、root/'scripts'、root/'ml'、root/'memory' 均以此为根。
    ⚠️ 勿改回单层 .parent（会退回 scheduler/，令所有相对脚本路径失效）。"""
    return Path(__file__).resolve().parent.parent


# 品种代码列表（与 scan_all 保持一致），供三生产者统一扫描范围
try:
    import sys as _sys
    _sys.path.insert(0, str(_project_root() / "skills" / "quant-daily" / "scripts"))
    from config.symbols import ALL_SYMBOLS
    ALL_SYMBOL_CODES = [s[0] for s in ALL_SYMBOLS]
except Exception:
    ALL_SYMBOL_CODES = []


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def _run_script(script_rel: str, *args: str, timeout: int = 300) -> tuple[bool, str]:
    """运行项目内的脚本"""
    root = _project_root()
    script_path = root / script_rel
    if not script_path.exists():
        return False, f"脚本不存在: {script_path}"

    # 脚本的父目录作为工作目录（很多脚本用相对路径如 ./reports/）
    script_cwd = str(script_path.parent)

    # Python路径探测：优先使用有依赖的Python
    candidates = [
        str(root / ".venv" / "Scripts" / "python.exe"),  # 项目venv
        str(root / "venv" / "Scripts" / "python.exe"),           # 项目venv
    ]
    venv_python = sys.executable
    for c in candidates:
        if os.path.exists(c):
            venv_python = c
            break

    cmd = [venv_python, str(script_path)] + list(args)
    _log(f"运行: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd, cwd=script_cwd, capture_output=True, text=True,  # ← 使用脚本目录作为cwd
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
    """
    日常辩论 — 完整全量管道

    流程:
      Step 1: 数技源 channel_breakout 扫描
      Step 2: 查找最新summary + 链分析 → assemble_intermediate_data.py
      Step 3: phase3_generate_report.py → HTML报告
      Step 4: 复制报告到 Commodities/
    """
    start = datetime.now()
    _log("📊 日常辩论 — 全量管道启动")
    steps = []

    # ── 报告目录与日期（供三生产者统一落地） ──
    root = _project_root()
    date_str = datetime.now().strftime("%Y%m%d")
    date_str_hy = datetime.now().strftime("%Y-%m-%d")
    scan_report_dir = Path(os.path.expanduser("~")) / "Documents" / "Commodities" / "Reports" / "商品期货深度分析" / date_str_hy
    os.makedirs(scan_report_dir, exist_ok=True)

    # ── Step 1: 通道突破扫描 ──
    _log("  Step 1/4: 通道突破扫描")
    sym_codes = ",".join(ALL_SYMBOL_CODES) if ALL_SYMBOL_CODES else ""

    # 数技源: 通道突破（默认 channel_breakout）
    ok_cb, msg_cb = _run_script(
        "skills/quant-daily/scripts/scan_all.py",
        "-o", str(scan_report_dir), "-p", "full_scan_summary",
        timeout=300,
    )
    steps.append(
        f"扫描: 通道突破{'✅' if ok_cb else '❌'}"
    )

    # 至少通道突破汇总须存在，否则后续无数据可用
    if not (scan_report_dir / f"full_scan_summary_{date_str}.json").exists():
        return TaskResult(
            task_name="daily_debate", success=False,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary="扫描失败: 通道突破汇总未生成", error=msg_cb,
        )

    # ── Step 2: 查找最新产出，准备报告数据 ──
    _log("  Step 2/4: 准备报告数据")

    # 查找最新的 summary JSON（优先查scan默认输出目录）
    if scan_report_dir.exists():
        summary_files = sorted(scan_report_dir.glob(f"full_scan_summary_{date_str}*.json"))
    else:
        summary_files = []

    if not summary_files:
        # 降级到 quant-daily/reports/
        reports_dir = root / "skills" / "quant-daily" / "reports"
        summary_files = sorted(reports_dir.glob(f"full_scan_summary_{date_str}*.json"))
    if not summary_files:
        summary_files = sorted(reports_dir.glob("full_scan_summary_*.json"))
    if not summary_files:
        steps.append("数据: ❌ 未找到summary")
        return TaskResult(
            task_name="daily_debate", success=False,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary="未找到扫描结果", error="summary未生成",
        )

    latest_summary = str(summary_files[-1])
    _log(f"  summary: {latest_summary}")
    steps.append(f"数据: ✅ {Path(latest_summary).name}")

    # ── Step 3: 运行phase3报告生成 ──
    phase3_script = str(root / "skills" / "futures-trading-analysis" / "scripts" / "phase3_generate_report.py")

    if Path(phase3_script).exists():
        ok3, msg3 = _run_script(
            "skills/futures-trading-analysis/scripts/phase3_generate_report.py",
            timeout=120,
        )
        steps.append(f"报告: {'✅' if ok3 else '❌'} {msg3[:60]}")
    else:
        steps.append("报告: ⏭ 脚本不存在")
        ok3, msg3 = False, "phase3_generate_report.py not found"

    # ── Step 4: 复制报告到工作空间 Commodities/ ──
    _log("  Step 4/4: 复制报告到工作空间")
    # phase3 输出在 scan_report_dir，复制到 Signal/Commodities/
    html_files = list(scan_report_dir.glob("debate_report_*.html")) if scan_report_dir.exists() else []

    commodity_dir = Path(os.path.expanduser("~")) / "Documents" / "Signal" / "Commodities"
    copied = []
    if commodity_dir.exists():
        import shutil
        for hf in html_files:
            dest = commodity_dir / hf.name
            shutil.copy2(str(hf), str(dest))
            copied.append(str(dest))
        _log(f"  已复制 {len(html_files)} 个报告到 {commodity_dir}")

    if copied:
        steps.append(f"输出: ✅ {copied[0]}")
    else:
        steps.append("输出: ⚠️ 目标目录不存在")

    # ── 记录日志 ──
    journal_path = root / "memory" / "debate_journal.json"
    entry = {
        "triggered_at": start.strftime("%Y-%m-%d %H:%M"),
        "type": "daily_debate_full",
        "steps": steps,
        "report_count": len(html_files),
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

    summary_line = " | ".join(steps)
    return TaskResult(
        task_name="daily_debate",
        success=ok3,
        started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary_line,
    )


@register_task("auto_publish")
def auto_publish() -> TaskResult:
    """自动发布 — 版本号自增 + Git推送"""
    start = datetime.now()
    _log("📦 开始自动发布")

    # quant-bare 位于用户主目录（FDT 包外），用 expanduser 便携解析；保留硬编码兜底
    sync_script = Path(os.path.expanduser("~")) / "quant-bare" / "sync_experts_to_github.py"
    if not sync_script.exists():
        sync_script = Path("C:/Users/yangd/quant-bare/sync_experts_to_github.py")

    if sync_script.exists():
        # sync_script 在 FDT 包外，传绝对路径（_run_script 的 root/abs 会取绝对路径，避免 relative_to ValueError）
        success, summary = _run_script(str(sync_script), timeout=120)
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
    """更新主力合约映射 — 使用 DominantResolver 刷新所有品种主力映射表。"""
    start = datetime.now()
    _log("🔄 更新主力合约映射")

    try:
        from futures_data_core.core.dominant_resolver import DominantResolver
        from futures_data_core.collectors.tdx import TDXCollector

        resolver = DominantResolver()
        collector = TDXCollector()
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        available = loop.run_until_complete(collector.check_available())
        if not available:
            loop.close()
            return TaskResult(
                task_name="update_dominant_mapping",
                success=False,
                started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                summary="TDX 数据源不可用，跳过",
                error="TDXCollector.check_available() 返回 False",
            )
        mapping = resolver.refresh_all(collector)
        loop.close()
        count = len(mapping)
        switch_count = len(
            [v for v in mapping.values() if v.get("switched")]
        )
        _log(f"  ✅ 主力映射更新完成: {count} 品种, {switch_count} 换月事件")
        return TaskResult(
            task_name="update_dominant_mapping",
            success=True,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary=f"已更新 {count} 品种主力映射, 检测到 {switch_count} 个换月事件",
        )
    except Exception as exc:
        _log(f"  ❌ 主力映射更新失败: {exc}")
        return TaskResult(
            task_name="update_dominant_mapping",
            success=False,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary=f"更新失败: {exc}",
            error=str(exc),
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


# ─── 自优化增强：四技能流水线任务 ────────────────────


@register_task("self_optimize_analysis")
def self_optimize_analysis() -> TaskResult:
    """SkillAdaptor 归因分析 —— 解析 debate_results.json → 步级故障归因"""
    start = datetime.now()
    _log("🔍 自优化分析（SkillAdaptor 归因）")

    success, summary = _run_script(
        "scripts/self_improve.py", "--mode=analyze", timeout=120
    )

    return TaskResult(
        task_name="self_optimize_analysis",
        success=success,
        started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        error="" if success else summary,
    )


@register_task("self_optimize_evolve")
def self_optimize_evolve() -> TaskResult:
    """Skillevolver 技能层进化 —— 高置信度故障 → Agent MD 补丁"""
    start = datetime.now()
    _log("🧬 自优化进化（Skillevolver 技能层）")

    success, summary = _run_script(
        "scripts/skillevolver_evolution.py", timeout=180
    )

    return TaskResult(
        task_name="self_optimize_evolve",
        success=success,
        started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        error="" if success else summary,
    )


@register_task("self_optimize_verify")
def self_optimize_verify() -> TaskResult:
    """Autoresearch A/B 验证 —— 对比 baseline vs evolved"""
    start = datetime.now()
    _log("✅ 自优化验证（Autoresearch A/B）")

    success, summary = _run_script(
        "scripts/verify_evolution.py", "--ab-test", timeout=120
    )

    return TaskResult(
        task_name="self_optimize_verify",
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
