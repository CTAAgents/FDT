# scripts/__init__.py — 注册自优化增强模块
from scripts.analyze_trajectory import TrajectoryAnalyzer, FaultAttributor
from scripts.skillevolver_evolution import SkillEvolver
from scripts.embodiskill_reflect import EmbodiSkillReflector
from scripts.verify_evolution import EvolutionVerifier

__all__ = [
    "TrajectoryAnalyzer",
    "FaultAttributor",
    "SkillEvolver",
    "EmbodiSkillReflector",
    "EvolutionVerifier",
]
