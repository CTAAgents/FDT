"""技术指标层：纯 numpy 计算（FDC 单一真相源）。

收编技术债 §1：原分散于 quant-daily/scripts/indicators/ 的指标副本
（calc_core / indicators_legacy / core 内的 assess_trend_maturity）统一收编至此包内：
- ``core``           ：FDC 原生基础指标（MA/EMA/RSI/MACD/BOLL/KDJ/ATR/CCI/...）
- ``tdx_compat``     ：TDX 100% 对齐的 calculate_* 兼容指标（原 calc_core.py）
- ``legacy_numpy``   ：_compute_indicators_numpy（原 indicators_legacy.py）
- ``trend_maturity`` ：assess_trend_maturity（采用 v2.17 超集版，原 indicators_legacy.py）

quant-daily 侧的 calc_core / core / indicators_legacy 现为 re-export shim，importer 无需改动。
指标计算逻辑零变更。
"""

from futures_data_core.indicators.core import (
    INDICATOR_NAMES,
    compute_indicators,
)
from futures_data_core.indicators.tdx_compat import *  # noqa: F401,F403
from futures_data_core.indicators.legacy_numpy import _compute_indicators_numpy  # noqa: F401
from futures_data_core.indicators.trend_maturity import assess_trend_maturity  # noqa: F401
import futures_data_core.indicators.tdx_compat as _tdx_compat

__all__ = (
    ["INDICATOR_NAMES", "compute_indicators", "_compute_indicators_numpy", "assess_trend_maturity"]
    + list(_tdx_compat.__all__)
)
