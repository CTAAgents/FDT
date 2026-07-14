"""遗留 numpy 指标 — 已收编至 futures_data_core.indicators.legacy_numpy（FDC 单一真相源）。

本文件为兼容 shim：importer 常用的 ``_compute_indicators_numpy`` 经 re-export 透明转发；
``assess_trend_maturity`` 亦转发自 FDC（采用原 indicators_legacy 的 v2.17 超集版）。

原文件中已弃用的 ``identify_market_state`` / ``calculate_trend_score`` / ``compute_indicators``
为死代码且无外部调用方（全仓 grep 零引用），收编时不再保留，零外部破坏
（详见技术债 §1 收编记录 docs/design/tech_debt_s1_indicator_extraction_plan.md）。
"""

from futures_data_core.indicators.legacy_numpy import _compute_indicators_numpy
from futures_data_core.indicators import assess_trend_maturity

__all__ = ["_compute_indicators_numpy", "assess_trend_maturity"]
