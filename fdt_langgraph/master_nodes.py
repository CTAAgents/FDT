"""
master_nodes.py — Master Orchestrator 节点函数

纯 Python datetime 调度判断，零第三方依赖。
覆盖老 scheduler/triggers.py 全部 13 个任务的调度与执行。

调度类型:
  - time:  按星期+时间窗口判断（check_time 中判定）
  - data:  按数据阈值触发，冷却期去重（节点内部做实际阈值检查）
  - debate_record:  辩论轮次去重计数触发，冷却期去重
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 持久触发状态文件（与老 scheduler 同文件，保障平滑过渡）
_TRIGGER_STATE_PATH = "memory/schedule_state.json"


# ═══════════════════════════════════════════════════════
#  持久化触发状态（读/写 memory/schedule_state.json）
# ═══════════════════════════════════════════════════════

def _load_json(rel_path: str) -> dict:
    """读取项目根下相对路径的 JSON 文件。返回 {} 如果文件不存在或解析失败。"""
    fp = PROJECT_ROOT / rel_path
    if not fp.exists():
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        return {}


def _get_trigger_state() -> dict:
    """读取触发状态（记录各任务上次触发时间，用于冷却期去重）。"""
    state = _load_json(_TRIGGER_STATE_PATH)
    if not state:
        state = {"last_triggered": {}, "last_heartbeat": ""}
    return state


def _set_triggered(task_name: str):
    """记录任务已触发。"""
    state = _get_trigger_state()
    state["last_triggered"][task_name] = datetime.now().strftime("%Y-%m-%d %H:%M")
    state["last_heartbeat"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fp = PROJECT_ROOT / _TRIGGER_STATE_PATH
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _count_json_data(data: dict, count_key: str) -> int:
    """估算 JSON 数据中指定 key 的条目数。"""
    if isinstance(data, dict) and count_key in data:
        val = data[count_key]
        if isinstance(val, list):
            return len(val)
        if isinstance(val, (int, float)):
            return int(val)
    return 0


# ═══════════════════════════════════════════════════════
#  脚本运行工具
# ═══════════════════════════════════════════════════════

def _run_script(script_rel: str, *args: str, timeout: int = 300) -> tuple[bool, str]:
    """运行项目脚本并返回 (success, summary)。"""
    script_path = PROJECT_ROOT / script_rel
    if not script_path.exists():
        return False, f"脚本不存在: {script_path}"
    candidates = [
        str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
        str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe"),
    ]
    venv_python = sys.executable
    for c in candidates:
        if Path(c).exists():
            venv_python = c
            break
    cmd = [venv_python, str(script_path)] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                encoding="utf-8", errors="replace")
        if result.returncode == 0:
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            return True, lines[-1] if lines else "完成"
        return False, result.stderr.strip()[:200]
    except subprocess.TimeoutExpired:
        return False, f"超时({timeout}s)"
    except Exception as e:
        return False, str(e)


def _task_key(state: dict, task_name: str) -> str:
    """生成任务当天的运行 key，用于判断是否已运行。"""
    today = date.today().isoformat()
    return f"{task_name}_{today}"


# ═══════════════════════════════════════════════════════
#  通用脚本节点工厂（减少样板代码）
# ═══════════════════════════════════════════════════════

def _make_script_node(task_name: str, script_path: str, *args: str,
                      timeout: int = 300, description: str = ""):
    """生成一个简单的脚本包装节点函数。"""
    def node_fn(state: dict) -> dict:
        state["current_task"] = task_name
        started = datetime.now().isoformat()
        ok, msg = _run_script(script_path, *args, timeout=timeout)
        state.setdefault("task_results", {})[task_name] = {
            "success": ok, "summary": msg, "started_at": started,
            "completed_at": datetime.now().isoformat(),
        }
        _set_triggered(task_name)
        state["task_index"] = state.get("task_index", 0) + 1
        state["phase"] = "dispatch"
        logger.info(f"[Master] {task_name}: {'✅' if ok else '❌'} {msg[:80]}")
        return state
    node_fn.__name__ = f"node_run_{task_name}"
    node_fn.__qualname__ = node_fn.__name__
    node_fn.__doc__ = f"运行 {task_name} — {description}"
    return node_fn


def _make_data_threshold_node(task_name: str, script_path: str, *args: str,
                              timeout: int = 300, description: str = ""):
    """生成数据阈值节点 — 先检查数据量，达标才运行脚本，否则跳过。"""
    def node_fn(state: dict) -> dict:
        state["current_task"] = task_name
        started = datetime.now().isoformat()
        sched = state.get("schedules", {}).get(task_name, {})
        data = _load_json(sched.get("data_path", ""))
        count = _count_json_data(data, sched.get("count_key", "entries"))
        threshold = sched.get("threshold", 50)
        if count < threshold:
            msg = f"数据量{count}<{threshold}，跳过"
            ok = True
            logger.info(f"[Master] {task_name}: ⏭ {msg}")
        else:
            ok, msg = _run_script(script_path, *args, timeout=timeout)
        state.setdefault("task_results", {})[task_name] = {
            "success": ok, "summary": msg, "started_at": started,
            "completed_at": datetime.now().isoformat(),
        }
        _set_triggered(task_name)
        state["task_index"] = state.get("task_index", 0) + 1
        state["phase"] = "dispatch"
        logger.info(f"[Master] {task_name}: {'✅' if ok else '❌'} {msg[:80]}")
        return state
    node_fn.__name__ = f"node_run_{task_name}"
    node_fn.__qualname__ = node_fn.__name__
    node_fn.__doc__ = f"数据阈值触发 {task_name} — {description}"
    return node_fn


# ═══════════════════════════════════════════════════════
#  Step 1: 检查时间/数据条件 — 标记到期任务
# ═══════════════════════════════════════════════════════

def node_check_time(state: dict) -> dict:
    """检查当前时间与数据条件，将所有到期任务加入队列。"""
    state["phase"] = "check_time"
    now = datetime.now()  # naive local time, 与 _set_triggered 存储格式一致
    today_weekday = now.weekday()
    task_queue = []
    last_runs = state.setdefault("last_runs", {})

    # 读取持久化触发状态（冷却期判断用）
    trigger_state = _get_trigger_state()
    last_triggered = trigger_state.get("last_triggered", {})

    for task_name, sched in state.get("schedules", {}).items():
        trigger_type = sched.get("trigger_type", "time")

        if trigger_type == "time":
            # ── 时间触发：星期 + 5 分钟窗口 ──
            wk = sched.get("weekdays", [0, 1, 2, 3, 4, 5, 6])
            if today_weekday not in wk:
                continue
            current_minutes = now.hour * 60 + now.minute
            target_minutes = sched.get("hour", 0) * 60 + sched.get("minute", 0)
            if not (target_minutes - 5 <= current_minutes <= target_minutes + 5):
                continue
            run_key = _task_key(state, task_name)
            if last_runs.get(run_key):
                continue
            task_queue.append(task_name)

        elif trigger_type in ("data", "debate_record"):
            # ── 数据触发：冷却期去重 ──
            cooldown = sched.get("cooldown_minutes", 1440)
            last_ts = last_triggered.get(task_name, "")
            if last_ts:
                try:
                    last_dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M")
                    elapsed = (now - last_dt).total_seconds() / 60
                    if elapsed < cooldown:
                        continue  # 仍在冷却期
                except ValueError:
                    pass
            task_queue.append(task_name)

    state["task_queue"] = task_queue
    state["task_index"] = 0
    logger.info(f"[Master] 检查完成: now={now.strftime('%H:%M')}, "
                f"到期任务={task_queue}")
    return state


# ═══════════════════════════════════════════════════════
#  Step 2: 调度分发
# ═══════════════════════════════════════════════════════

def node_dispatch(state: dict) -> dict:
    """从任务队列取出下一个任务。G18: 调度权代码层强制 — 仅 team_lead 可调度。"""
    # G18 调度权断言: 仅明鉴秋(team_lead)可触发调度
    caller = state.get("caller", "master_graph")
    assert caller in ("team_lead", "master_graph"), \
        f"G18 调度权越界: caller={caller}, 仅 team_lead/master_graph 可调度"
    queue = state.get("task_queue", [])

    # G-6D-07: ToolMetrics 反哺调度 — 跳过成功率 < 50% 的任务
    try:
        from scripts.tool_metrics import ToolMetrics
        tm = ToolMetrics()
        stats = tm.get_tool_stats()
        filtered = []
        for task in queue:
            ts = stats.get(task, {})
            sr = ts.get("success_rate", 100.0)
            if sr < 50.0:
                logger.warning(f"[G-6D-07] 跳过 {task}: 成功率 {sr:.0f}% < 50%")
                continue
            filtered.append(task)
        if len(filtered) != len(queue):
            state["task_queue"] = filtered
            queue = filtered
    except Exception:
        pass

    idx = state.get("task_index", 0)
    if idx < len(queue):
        state["current_task"] = queue[idx]
        state["phase"] = "task_running"
        logger.info(f"[Master] 调度: {state['current_task']} ({idx+1}/{len(queue)})")
    else:
        state["current_task"] = ""
        state["phase"] = "done"
        logger.info("[Master] 所有到期任务已完成")
    return state


# ═══════════════════════════════════════════════════════
#  Step 3: 各任务执行节点
# ═══════════════════════════════════════════════════════

# ── 3a. 简单脚本包装任务（使用 _make_script_node） ──

node_run_cluster_failures = _make_script_node(
    "cluster_failures", "scripts/cluster_failures.py",
    description="失败模式聚类（Telescope 层）",
)

node_run_self_optimize_analysis = _make_data_threshold_node(
    "self_optimize_analysis", "scripts/self_improve.py", "--mode=analyze",
    description="SkillAdaptor 归因分析",
)

node_run_self_optimize_evolve = _make_script_node(
    "self_optimize_evolve", "scripts/skillevolver_evolution.py",
    timeout=180,
    description="Skillevolver 技能层进化",
)

node_run_self_optimize_verify = _make_script_node(
    "self_optimize_verify", "scripts/verify_evolution.py", "--ab-test",
    description="自优化验证 Autoresearch A/B",
)

node_run_discipline_enforce = _make_script_node(
    "discipline_enforce", "scripts/enforce_discipline.py",
    description="D4 纪律钳制（仓位上限校正）",
)

node_run_auto_publish = _make_script_node(
    "auto_publish", "scripts/auto_publish.py",
    description="自动发布",
)


# ── 3b. 有特殊逻辑的任务节点 ──

def node_run_data_collection(state: dict) -> dict:
    """数据采集: 更新主力合约映射（内联 — 委托给 node_run_update_dominant_mapping）。"""
    state["current_task"] = "data_collection"
    started = datetime.now().isoformat()
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
            ok, msg = False, "TDX 数据源不可用，跳过"
        else:
            mapping = resolver.refresh_all(collector)
            loop.close()
            switch_count = len([v for v in mapping.values() if v.get("switched")])
            ok, msg = True, f"已更新 {len(mapping)} 品种, {switch_count} 换月事件"
    except Exception as exc:
        ok, msg = False, str(exc)

    state.setdefault("task_results", {})["data_collection"] = {
        "success": ok, "summary": msg, "started_at": started,
        "completed_at": datetime.now().isoformat(),
    }
    _set_triggered("data_collection")
    state["task_index"] = state.get("task_index", 0) + 1
    state["phase"] = "dispatch"
    logger.info(f"[Master] data_collection: {'✅' if ok else '❌'} {msg[:80]}")
    return state


def node_run_update_dominant_mapping(state: dict) -> dict:
    """更新主力合约映射（内联 Python — 对应老 scheduler/tasks.py）。"""
    state["current_task"] = "update_dominant_mapping"
    started = datetime.now().isoformat()
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
            ok, msg = False, "TDX 数据源不可用，跳过"
        else:
            mapping = resolver.refresh_all(collector)
            loop.close()
            switch_count = len([v for v in mapping.values() if v.get("switched")])
            ok, msg = True, f"已更新 {len(mapping)} 品种, {switch_count} 换月事件"
    except Exception as exc:
        ok, msg = False, str(exc)

    state.setdefault("task_results", {})["update_dominant_mapping"] = {
        "success": ok, "summary": msg, "started_at": started,
        "completed_at": datetime.now().isoformat(),
    }
    _set_triggered("update_dominant_mapping")
    state["task_index"] = state.get("task_index", 0) + 1
    state["phase"] = "dispatch"
    logger.info(f"[Master] update_dominant_mapping: {'✅' if ok else '❌'} {msg[:80]}")
    return state


def node_run_daily_debate(state: dict) -> dict:
    """日常辩论: 运行辩论图 + 自进化。"""
    state["current_task"] = "daily_debate"
    started = datetime.now().isoformat()

    os.environ["FDT_RUN_EVOLUTION"] = "true"

    from fdt_langgraph.state import create_initial_state
    from fdt_langgraph.graph import build_debate_graph_no_checkpoint as build_debate_graph
    from fdt_langgraph.evolution_graph import run_evolution

    trace_id = f"master-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        initial = create_initial_state(trace_id, "default")
        graph = build_debate_graph(mode="default")
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(graph.ainvoke(initial))
        loop.close()
        debate_ok = True
        debate_msg = f"辩论完成, phases={result.get('completed_phases', [])}"
        logger.info(f"[Master] 辩论完成: trace_id={trace_id}")

        # 自动触发进化
        ev_state = run_evolution(source_trace_id=trace_id)
        if ev_state:
            ev_steps = list(ev_state.get("step_results", {}).keys())
            logger.info(f"[Master] 自进化完成: steps={ev_steps}")
            debate_msg += f" → 进化: {ev_steps}"
        else:
            logger.warning(f"[Master] 自进化返回 None，跳过进化步骤")
            debate_msg += " → 进化: None"

    except Exception as e:
        debate_ok = False
        debate_msg = str(e)
        logger.error(f"[Master] 辩论失败: {e}")

    state.setdefault("task_results", {})["daily_debate"] = {
        "success": debate_ok, "summary": debate_msg, "started_at": started,
        "completed_at": datetime.now().isoformat(),
    }
    _set_triggered("daily_debate")
    state["task_index"] = state.get("task_index", 0) + 1
    state["phase"] = "dispatch"
    return state


def node_run_apm_scorecard(state: dict) -> dict:
    """APM 评分卡。"""
    state["current_task"] = "apm_scorecard"
    started = datetime.now().isoformat()
    ok, msg = _run_script("scripts/apm_scorecard.py", timeout=120)
    state.setdefault("task_results", {})["apm_scorecard"] = {
        "success": ok, "summary": msg, "started_at": started,
        "completed_at": datetime.now().isoformat(),
    }
    _set_triggered("apm_scorecard")
    state["task_index"] = state.get("task_index", 0) + 1
    state["phase"] = "dispatch"
    logger.info(f"[Master] apm_scorecard: {'✅' if ok else '❌'} {msg}")
    return state


def node_run_validate_and_evolve(state: dict) -> dict:
    """验证→校准→进化（多步管道）。"""
    state["current_task"] = "validate_and_evolve"
    started = datetime.now().isoformat()

    steps = [
        ("scripts/validate_verdicts.py", [], "验证历史裁决", 120),
        ("scripts/calibrate_weights.py", [], "校准评分权重", 60),
        ("scripts/evolve_agents.py", [], "进化Agent参数", 60),
        ("ml/trainer.py", [], "ML训练检查", 180),
    ]
    results = {}
    all_ok = True
    for script_path, args, label, timeout in steps:
        ok, msg = _run_script(script_path, *args, timeout=timeout)
        results[label] = "✅" if ok else f"❌ {msg}"
        if not ok:
            all_ok = False
    summary = " | ".join(f"{k}: {v}" for k, v in results.items())

    state.setdefault("task_results", {})["validate_and_evolve"] = {
        "success": all_ok, "summary": summary, "started_at": started,
        "completed_at": datetime.now().isoformat(),
        "details": results,
    }
    _set_triggered("validate_and_evolve")
    state["task_index"] = state.get("task_index", 0) + 1
    state["phase"] = "dispatch"
    logger.info(f"[Master] validate_and_evolve: {'✅' if all_ok else '⚠️'} {summary[:80]}")
    return state


def node_run_ml_training_check(state: dict) -> dict:
    """ML 训练检查 — 数据阈值判断 + 脚本执行。"""
    state["current_task"] = "ml_training_check"
    started = datetime.now().isoformat()

    # 先检查数据量
    sched = state.get("schedules", {}).get("ml_training_check", {})
    data = _load_json(sched.get("data_path", "memory/debate_journal.json"))
    count = _count_json_data(data, sched.get("count_key", "entries"))
    threshold = sched.get("threshold", 50)

    if count < threshold:
        ok, msg = True, f"数据量{count}<{threshold}，跳过"
    else:
        trainer_path = PROJECT_ROOT / "ml" / "trainer.py"
        if not trainer_path.exists():
            ok, msg = True, "跳过（trainer.py 不存在）"
        else:
            ok, msg = _run_script("ml/trainer.py", "--check", timeout=120)

    state.setdefault("task_results", {})["ml_training_check"] = {
        "success": ok, "summary": msg, "started_at": started,
        "completed_at": datetime.now().isoformat(),
    }
    _set_triggered("ml_training_check")
    state["task_index"] = state.get("task_index", 0) + 1
    state["phase"] = "dispatch"
    logger.info(f"[Master] ml_training_check: {'✅' if ok else '❌'} {msg[:80]}")
    return state


def node_run_vibench_baseline(state: dict) -> dict:
    """ViBench 基线更新 — 数据阈值判断后运行 benchmark。"""
    state["current_task"] = "vibench_baseline"
    started = datetime.now().isoformat()

    sched = state.get("schedules", {}).get("vibench_baseline", {})
    data = _load_json(sched.get("data_path", "benchmarks/test_cases.json"))
    count = _count_json_data(data, sched.get("count_key", "total_cases"))
    threshold = sched.get("threshold", 30)

    if count < threshold:
        ok, msg = True, f"案例数{count}<{threshold}，跳过"
    else:
        ok, msg = _run_script("scripts/run_benchmark.py", "--run", timeout=180)

    state.setdefault("task_results", {})["vibench_baseline"] = {
        "success": ok, "summary": msg, "started_at": started,
        "completed_at": datetime.now().isoformat(),
    }
    _set_triggered("vibench_baseline")
    state["task_index"] = state.get("task_index", 0) + 1
    state["phase"] = "dispatch"
    logger.info(f"[Master] vibench_baseline: {'✅' if ok else '❌'} {msg[:80]}")
    return state


def node_run_d3_auto_light(state: dict) -> dict:
    """D3 Composure 自动点亮 — 辩论轮次去重计数≥threshold 触发评分卡重算。"""
    state["current_task"] = "d3_auto_light"
    started = datetime.now().isoformat()

    sched = state.get("schedules", {}).get("d3_auto_light", {})
    data = _load_json(sched.get("data_path", "memory/debate_journal.json"))
    threshold = sched.get("threshold", 5)

    # 从 journal 中提取去重辩论轮次
    recs = [e for e in data.get("entries", []) if e.get("action") == "debate_record"]
    rounds = set(r.get("round_id") for r in recs if r.get("round_id"))
    round_count = len(rounds)

    if round_count < threshold:
        ok, msg = True, f"辩论轮次{round_count}<{threshold}，不点亮 D3"
    else:
        ok, msg = _run_script("scripts/apm_scorecard.py", timeout=120)

    state.setdefault("task_results", {})["d3_auto_light"] = {
        "success": ok, "summary": msg, "started_at": started,
        "completed_at": datetime.now().isoformat(),
    }
    _set_triggered("d3_auto_light")
    state["task_index"] = state.get("task_index", 0) + 1
    state["phase"] = "dispatch"
    logger.info(f"[Master] d3_auto_light: {'✅' if ok else '❌'} {msg[:80]}")
    return state


# ═══════════════════════════════════════════════════════
#  路由函数
# ═══════════════════════════════════════════════════════

# 任务名 → 节点名 映射表
_TASK_NODE_MAP: dict[str, str] = {
    "daily_debate": "run_debate",
    "data_collection": "run_data_collection",
    "update_dominant_mapping": "run_update_dominant_mapping",
    "apm_scorecard": "run_apm",
    "auto_publish": "run_publish",
    "validate_and_evolve": "run_validate_and_evolve",
    "ml_training_check": "run_ml_training_check",
    "cluster_failures": "run_cluster_failures",
    "self_optimize_analysis": "run_self_optimize_analysis",
    "self_optimize_evolve": "run_self_optimize_evolve",
    "self_optimize_verify": "run_self_optimize_verify",
    "discipline_enforce": "run_discipline_enforce",
    "vibench_baseline": "run_vibench_baseline",
    "d3_auto_light": "run_d3_auto_light",
}


def route_after_dispatch(state: dict) -> str:
    """根据 current_task 路由到对应执行节点。"""
    task = state.get("current_task", "")
    return _TASK_NODE_MAP.get(task, "done")


def route_after_task(state: dict) -> str:
    """任务完成后回到 dispatch 取下一个。"""
    idx = state.get("task_index", 0)
    queue = state.get("task_queue", [])
    if idx < len(queue):
        return "dispatch"
    return "done"
