"""quant-daily 统一指标引擎 — 已迁移至 data_adapter.indicators（FDC 已退役）。

本文件为兼容 shim：``assess_trend_maturity`` 转发自 ``indicators_legacy``。
其余计算函数已不再维护（FDC 退役），导入时直接引用 data_adapter.indicators.compute_indicators。
"""

from indicators.indicators_legacy import assess_trend_maturity

__all__ = ["assess_trend_maturity"]
