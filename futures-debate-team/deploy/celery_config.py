# Futures-Debate-Team 分布式部署配置（P2-3）
# =============================================
# 使用 Celery 作为任务队列，支持多节点并行执行。
# 
# 启动方式:
#   celery -A deploy.celery_app worker --concurrency=4
#
# 多节点:
#   节点1: celery worker (信号扫描+辩论)
#   节点2: celery worker (回测+报告)
#   节点3: celery beat (定时任务调度)

# ── Celery 配置 ──
CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/1"

# ── 任务路由 ──
TASK_ROUTES = {
    "scan.tasks.run_dual_scan": {"queue": "scanning"},
    "debate.tasks.run_debate_pipeline": {"queue": "debate"},
    "backtest.tasks.run_backtest": {"queue": "backtest"},
    "report.tasks.generate_daily": {"queue": "report"},
}

# ── 节点配置 ──
NODE_CONFIG = {
    "scanning": {
        "concurrency": 4,
        "prefetch_multiplier": 1,
        "max_tasks_per_child": 50,
    },
    "debate": {
        "concurrency": 2,
        "prefetch_multiplier": 1,
    },
    "backtest": {
        "concurrency": 1,
        "prefetch_multiplier": 2,
    },
}

# ── 定时任务 ──
BEAT_SCHEDULE = {
    "daily_scan": {
        "task": "scan.tasks.run_daily_scan",
        "schedule": "0 8 * * 1-5",  # 工作日 8:00
    },
    "daily_report": {
        "task": "report.tasks.generate_daily_report",
        "schedule": "0 17 * * 1-5",  # 工作日 17:00
    },
}
