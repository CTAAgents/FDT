"""TDX 兼容指标计算 — 已收编至 futures_data_core.indicators（FDC 单一真相源）。

本文件为兼容 shim：所有 ``calculate_*`` / ``detect_*`` / ``analyze_metal`` 符号经
re-export 透明转发自 ``futures_data_core.indicators``，importer 无需改动。
指标计算逻辑零变更（见技术债 §1 收编记录）。
"""

from futures_data_core.indicators import *  # noqa: F401,F403
from futures_data_core.indicators import __all__ as _fdc_all  # noqa: F401

__all__ = list(_fdc_all)
