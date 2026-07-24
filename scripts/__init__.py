"""scripts/ — FDT 工具集（按职责划分为4个子包）。

子包结构：
  scripts/core/       核心基础设施：日志、追踪、版本、LLM 客户端
  scripts/analysis/   分析引擎：因子、归因、知识提取、模式蒸馏
  scripts/ops/        运维自动化：调度、监控、告警、资源管理
  scripts/reporting/  报告与输出：裁判记录、信号验证、质量校验

新功能应创建在上述子包中，而非直接放在 scripts/ 根目录。
向后兼容：根目录的旧文件保留为重导出存根，新代码应直接引用子包路径。
"""
# ── 自优化增强模块（向后兼容导出） ──
from scripts.analyze_trajectory import FaultAttributor, TrajectoryAnalyzer
from scripts.embodiskill_reflect import EmbodiSkillReflector
from scripts.skillevolver_evolution import SkillEvolver
from scripts.verify_evolution import EvolutionVerifier

__all__ = [
    "TrajectoryAnalyzer",
    "FaultAttributor",
    "SkillEvolver",
    "EmbodiSkillReflector",
    "EvolutionVerifier",
]
