"""
策略注册器 — 统一管理所有可打分策略。

用法:
    from strategies import get_strategy, list_strategies

    # 获取策略
    strat = get_strategy("layered_l1l4")
    result = strat.score(tech_list)

    # 查看全部
    for name, info in list_strategies().items():
        print(f"  {name}: {info['display']} {'(默认)' if info['default'] else ''}")
"""

_REGISTRY: dict[str, dict] = {}
_DEFAULT: str = "three_signal"  # 默认策略改为三层信号


def register_strategy(
    strategy_class,
    name: str = None,
    display_name: str = None,
    is_default: bool = False,
):
    """
    注册一个策略类到注册器。
    策略类必须实现 BaseStrategy 接口。

    参数:
        strategy_class: 策略类（非实例）
        name: 策略标识符。不传则取 strategy_class.name
        display_name: 中文名。不传则取 strategy_class.display_name
        is_default: 是否设为默认
    """
    instance = strategy_class()
    name = name or instance.name
    display = display_name or instance.display_name

    _REGISTRY[name] = {
        "class": strategy_class,
        "instance": instance,
        "display": display,
    }

    if is_default:
        global _DEFAULT
        _DEFAULT = name


def get_strategy(name: str = None):
    """
    获取策略实例。name=None 返回默认策略。

    参数:
        name: 策略名。None → 返回默认策略

    返回:
        BaseStrategy 实例

    抛出:
        KeyError: 策略未注册
    """
    if name is None:
        name = _DEFAULT
    entry = _REGISTRY.get(name)
    if entry is None:
        available = ", ".join(_REGISTRY.keys())
        raise KeyError(f"策略 '{name}' 未注册。可用策略: {available}")
    return entry["instance"]


def list_strategies() -> dict:
    """
    列出所有已注册的策略。

    返回:
        {name: {"display": 中文名, "default": 是否为默认}}
    """
    return {
        name: {
            "display": info["display"],
            "default": name == _DEFAULT,
        }
        for name, info in _REGISTRY.items()
    }


def get_default_strategy_name() -> str:
    """返回默认策略名"""
    return _DEFAULT


def set_default(name: str):
    """设置默认策略"""
    if name not in _REGISTRY:
        raise KeyError(f"策略 '{name}' 未注册")
    global _DEFAULT
    _DEFAULT = name


# 注册策略
# L1-L4和因子择时不再作为独立策略提供交易信号
# 它们的代码保留在strategies/目录下，通过data_interface供研究员import使用
from . import three_signal_strategy  # noqa: F401, E402
