"""
master_state.py — Master Orchestrator 状态定义

Master Graph 是 FDT 的统一编排层，管理所有自动化任务的时间调度与执行。
所有任务节点均运行在 LangGraph 框架内，零第三方依赖。

调度类型:
  - time:  按星期+时间触发（5 分钟窗口），对应老 scheduler 的 TimeTrigger
  - data:  按数据量阈值触发（冷却期去重），对应老 scheduler 的 DataTrigger
  - debate_record:  辩论轮次计数触发，对应老 scheduler 的 DebateRecordTrigger
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def create_master_state(loop_id: str = "") -> dict:
    """创建 Master Orchestrator 初始状态。"""
    now = datetime.now(timezone.utc).astimezone()
    return {
        "loop_id": loop_id,
        "phase": "idle",
        "current_task": "",
        "task_queue": [],
        "task_index": 0,
        "schedules": _get_default_schedules(),
        "last_runs": {},
        "task_results": {},
        "errors": [],
        "started_at": now.isoformat(),
        "completed_at": "",
    }


def _get_default_schedules() -> dict:
    """返回默认调度注册表 — 覆盖老 scheduler/triggers.py 全部 13 个任务。

    时间触发型任务由 check_time 按星期+时间窗口判断；
    数据触发型任务由 check_time 按冷却期判断，在节点内部做实际阈值检查。
    """
    return {
        # ── P6 日常辩论 ───────────────────────────────────
        "daily_debate": {
            "trigger_type": "time",
            "weekdays": [0, 1, 2, 3, 4],  # 工作日
            "hour": 19, "minute": 15,
            "description": "日常辩论 + 自进化闭环",
        },
        # ── 主力合约映射更新 ──────────────────────────────
        "update_dominant_mapping": {
            "trigger_type": "time",
            "weekdays": [0, 1, 2, 3, 4],  # 工作日收盘后
            "hour": 15, "minute": 30,
            "description": "主力合约映射更新（TDX）",
        },
        # ── 自动发布 ─────────────────────────────────────
        "auto_publish": {
            "trigger_type": "time",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],  # 每天
            "hour": 23, "minute": 5,
            "description": "自动发布（版本自增 + Git 推送）",
        },
        # ── APM 评分卡 ────────────────────────────────────
        "apm_scorecard": {
            "trigger_type": "time",
            "weekdays": [0],  # 仅周一
            "hour": 8, "minute": 30,
            "description": "APM-CS 五轴评分卡",
        },
        # ── 失败模式聚类 ─────────────────────────────────
        "cluster_failures": {
            "trigger_type": "time",
            "weekdays": [0],  # 仅周一
            "hour": 8, "minute": 0,
            "description": "失败模式聚类（Telescope 层）",
        },
        # ── D4 纪律钳制 ──────────────────────────────────
        "discipline_enforce": {
            "trigger_type": "time",
            "weekdays": [0],  # 仅周一
            "hour": 8, "minute": 45,
            "description": "D4 纪律钳制（仓位上限校正）",
        },
        # ── 自优化-技能层进化 ────────────────────────────
        "self_optimize_evolve": {
            "trigger_type": "time",
            "weekdays": [0, 1, 2, 3, 4],  # 工作日
            "hour": 15, "minute": 35,
            "description": "Skillevolver 技能层进化",
        },
        # ── 自优化-A/B验证 ──────────────────────────────
        "self_optimize_verify": {
            "trigger_type": "time",
            "weekdays": [0],  # 仅周一
            "hour": 8, "minute": 50,
            "description": "自优化验证（Autoresearch A/B）",
        },
        # ── 验证→校准→进化（数据触发） ─────────────────
        "validate_and_evolve": {
            "trigger_type": "data",
            "data_path": "memory/execution_followup.json",
            "count_key": "records",
            "threshold": 1,
            "cooldown_minutes": 1440,
            "description": "验证 → 校准 → 进化管道",
        },
        # ── ML 训练检查（数据触发） ──────────────────────
        "ml_training_check": {
            "trigger_type": "data",
            "data_path": "memory/debate_journal.json",
            "count_key": "entries",
            "threshold": 50,
            "cooldown_minutes": 4320,
            "description": "ML 训练条件检查",
        },
        # ── SkillAdaptor 归因分析（数据触发） ───────────
        "self_optimize_analysis": {
            "trigger_type": "data",
            "data_path": "memory/debate_journal.json",
            "count_key": "entries",
            "threshold": 1,
            "cooldown_minutes": 360,
            "description": "SkillAdaptor 归因分析",
        },
        # ── ViBench 基线更新（数据触发） ────────────────
        "vibench_baseline": {
            "trigger_type": "data",
            "data_path": "benchmarks/test_cases.json",
            "count_key": "total_cases",
            "threshold": 30,
            "cooldown_minutes": 10080,
            "description": "ViBench 基线指标更新",
        },
        # ── D3 Composure 自动点亮（辩论轮次数据触发） ──
        "d3_auto_light": {
            "trigger_type": "debate_record",
            "data_path": "memory/debate_journal.json",
            "threshold": 5,
            "cooldown_minutes": 1440,
            "description": "D3 Composure 自动点亮（轮次≥5）",
        },
        # ── 记忆系统维护（时间触发） ─────────────────────
        "memory_maintenance": {
            "trigger_type": "time",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "hour": 4, "minute": 0,
            "cooldown_minutes": 1440,
            "description": "记忆系统维护（清理+归档+知识老化）",
        },
    }
