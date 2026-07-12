"""
scheduler — 专家团内建心跳引擎

替代平台automation，让专家团自主决策"什么时候做什么"。
由 bootstrap.py 启动，可运行在前台（交互）或后台（守护）模式。
"""
from .engine import SchedulerEngine, run_once
from .tasks import (
    daily_debate,
    auto_publish,
    update_dominant_mapping,
    validate_and_evolve,
    ml_training_check,
)

__all__ = [
    "SchedulerEngine",
    "run_once",
    "daily_debate",
    "auto_publish",
    "update_dominant_mapping",
    "validate_and_evolve",
    "ml_training_check",
]
