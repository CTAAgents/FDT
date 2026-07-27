"""
交易质量反馈闭环模块。

连接 verdict_backtest (测量) → 参数调整 (决策) → CTP signal_output (执行)。

核心链路:
    validate_verdicts.py 产出 validation_stats.json
        → position_tuner.py 计算每品种仓位系数
        → parameter_tuner.py 校准置信度 + 优化 stop/target
        → config_store.py 持久化调整参数
        → signal_output 读取 config_store 生成动态参数
"""
from __future__ import annotations

from fdt_eval.feedback.config_store import SymbolConfig, FeedbackConfig, ConfigStore
from fdt_eval.feedback.position_tuner import PositionTuner, PositionAdjustment
from fdt_eval.feedback.parameter_tuner import ParameterTuner, ParameterCalibration
