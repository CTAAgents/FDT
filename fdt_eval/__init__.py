"""
FDT Eval Framework — 统一评估系统。

将所有散落的 eval 逻辑统一为 fdt_eval 包，提供：
  - 统一的 EvalResult 契约
  - 装饰器注册体系
  - Profile 驱动的运行器（dev/ci/nightly/release）
  - SQLite 结果持久化 + 趋势查询
  - Eval-to-Action 闭环（阻断/告警/登记差距）

用法:
    python -m fdt_eval run --profile ci
    python -m fdt_eval trend --case runtime.quality_inspector.p3_5 --last 30
    python -m fdt_eval list
"""

__version__ = "1.0.0"
__all__ = ["EvalCase", "EvalResult", "EvalContext", "EvalMetric", "EvalAction",
           "eval_registry", "EvalRunner", "EvalStore"]

from fdt_eval.core.base import EvalCase, EvalResult, EvalContext, EvalMetric, EvalAction
from fdt_eval.core.registry import eval_registry
from fdt_eval.core.runner import EvalRunner
from fdt_eval.core.store import EvalStore
