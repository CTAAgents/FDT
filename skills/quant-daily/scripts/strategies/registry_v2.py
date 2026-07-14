"""
v2 策略注册表 — 自动发现 + 手动注册。

用法:
    from strategies.registry_v2 import get_pipeline, register_v2
    register_v2(MyStrategy())
    pipeline = get_pipeline()
    result = pipeline.run(tech_list, kline_data, context)
"""

from __future__ import annotations
from typing import Optional

from .base_v2 import BaseStrategyV2
from .pipeline import StrategyPipeline, StrategyFusion

# ── v2 策略注册表 ──
_V2_REGISTRY: dict[str, BaseStrategyV2] = {}


def register_v2(strategy: BaseStrategyV2, replace: bool = False) -> None:
    """注册一个 v2 策略实例。同名策略默认不覆盖（需 replace=True）。"""
    if strategy.name in _V2_REGISTRY and not replace:
        return
    _V2_REGISTRY[strategy.name] = strategy


def unregister_v2(name: str) -> None:
    _V2_REGISTRY.pop(name, None)


def list_v2_strategies() -> dict[str, str]:
    return {name: s.display_name for name, s in _V2_REGISTRY.items()}


def clear_v2() -> None:
    _V2_REGISTRY.clear()


def get_pipeline(strategy_names: Optional[list[str]] = None,
                 fusion_method: str = StrategyFusion.WEIGHTED_MAX
                 ) -> StrategyPipeline:
    """获取 StrategyPipeline 实例。

    Args:
        strategy_names: 指定策略名列表。None = 全部已注册策略。
        fusion_method: 融合模式。

    Returns:
        配置好的 StrategyPipeline 实例。
    """
    if strategy_names:
        strategies = [_V2_REGISTRY[n] for n in strategy_names if n in _V2_REGISTRY]
    else:
        strategies = list(_V2_REGISTRY.values())
    if not strategies:
        raise ValueError("No v2 strategies registered")
    fusion = StrategyFusion(fusion_method)
    return StrategyPipeline(strategies, fusion=fusion)


# ── 已支持的策略自动注册 ──
# 导入即注册，v2 策略文件在 import 时调用 register_v2()
# 取消注释下面几行以启用对应策略:

# from .arbitrage_strategy import ArbitrageStrategy
# from .mean_reversion_strategy import MeanReversionStrategy
# from .macro_regime_strategy import MacroRegimeStrategy
# from .event_driven_strategy import EventDrivenStrategy
# from .ml_signal_strategy import MlSignalStrategy
