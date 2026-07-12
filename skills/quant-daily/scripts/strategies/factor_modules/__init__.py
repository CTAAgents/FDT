"""
因子模块 — 子模块包
factor_timing.py(1358行) 拆分方案（技术债清理）：

factor_definitions.py  — 因子定义、配置、CONFIG
factor_scoring.py      — 评分逻辑、投票机制、分组
factor_timing.py       — 主入口（精简为编排层）
"""

from .factor_definitions import CONFIG, get_factor_config
from .factor_scoring import calc_decile_vote, apply_g1_g10

__all__ = ["CONFIG", "get_factor_config", "calc_decile_vote", "apply_g1_g10"]
