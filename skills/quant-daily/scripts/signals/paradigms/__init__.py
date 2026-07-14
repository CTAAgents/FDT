"""信号计算范式注册表 — 范式↔验证器 框架的「范式」侧。

范式 = 「一类信号怎么算」的模板。FDT 当前主力是 P1 通道突破（计算实体已存在于
strategies/channel_breakout_strategy.py），此处仅做范式注册与元信息，不重写其计算。
P3/P4 为未来聚焦位（填 Bollinger %B / OLS 残差等公开主流因子实现）。

范式与验证器的关联通过 config.settings.SIGNAL_VALIDATOR_MAP 声明（signal_type → [validator_id]），
本注册表提供「范式元信息 + 它覆盖哪些 signal_type / 该配哪些验证器」的可读索引。
"""

PARADIGM_REGISTRY = {}


def register_paradigm(pid: str, cls) -> None:
    PARADIGM_REGISTRY[pid] = cls


# ── 导入即注册 ──
from . import breakout, mean_reversion, regression  # noqa: E402

__all__ = ["PARADIGM_REGISTRY", "register_paradigm"]
