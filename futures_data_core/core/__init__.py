"""核心层：降级链、缓存、新鲜度、品种注册、归一化数据载体。"""

from futures_data_core.core.symbol_registry import (
    get_symbol,
    is_known,
    list_exchanges,
    list_symbols,
    reload,
)
from futures_data_core.core.data_freshness import (
    data_grade_from_age,
    evaluate,
)
from futures_data_core.core.data_quality import (
    evaluate_symbol as evaluate_data_quality,
    evaluate_f10_data,
    evaluate_indicators,
    evaluate_jin10_context,
)
from futures_data_core.core.types import (
    KlineBar,
    KlineData,
    QuoteData,
    RolloverEvent,
    DominantMap,
)
from futures_data_core.core.field_normalizer import (
    CanonicalField,
    normalize_kline_row,
    normalize_kline_list,
    normalize_signal_row,
    normalize_signal_list,
    normalize_verdict as normalize_verdict_n,
    normalize_risk_check as normalize_risk_check_n,
    normalize_direction_raw,
    normalize_direction_to_signal,
)

__all__ = [
    "get_symbol",
    "is_known",
    "list_exchanges",
    "list_symbols",
    "reload",
    "data_grade_from_age",
    "evaluate",
    "evaluate_f10_data",
    "evaluate_indicators",
    "evaluate_jin10_context",
    "KlineBar",
    "KlineData",
    "QuoteData",
    "RolloverEvent",
    "DominantMap",
    "CanonicalField",
    "normalize_kline_row",
    "normalize_kline_list",
    "normalize_signal_row",
    "normalize_signal_list",
    "normalize_direction_raw",
    "normalize_direction_to_signal",
]
