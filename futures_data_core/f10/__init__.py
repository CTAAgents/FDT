"""f10 基本面与衍生品数据模块公开 API。

所有函数均为 ``[INDEPENDENT]`` 或显式标注的 ``[LLM-ENHANCED]`` / ``[LLM-DRIVEN]``，
无隐藏 LLM 依赖。返回值为 :class:`~futures_data_core._a2a.A2APayload`。
"""

from futures_data_core.f10.basis import (
    PpiSpotFetcher,
    compute_basis,
    get_basis,
    get_basis_batch,
)
from futures_data_core.f10.exchange_scraper import (
    EXCHANGE_ENDPOINTS,
    fetch_exchange_page,
    fmt_of,
    get_exchange_url,
    parse_daily_rows,
)
from futures_data_core.f10.fundamentals import get_fundamental
from futures_data_core.f10.huishang import HuishangFetcher, get_huishang_fundamental
from futures_data_core.f10.position import get_position_ranking
from futures_data_core.f10.spread import compute_spread, get_spread
from futures_data_core.f10.term_structure import analyze_term_structure, get_term_structure
from futures_data_core.f10.warrant import get_warrant, summarize_warrant
from futures_data_core.f10.web_collector import search_fundamental_llm
from futures_data_core.f10.sentiment import get_sentiment
from futures_data_core.f10.macro import get_macro_pmi, get_macro_rate

__all__ = [
    # term structure
    "analyze_term_structure",
    "get_term_structure",
    # spread
    "compute_spread",
    "get_spread",
    # basis
    "compute_basis",
    "get_basis",
    "get_basis_batch",
    "PpiSpotFetcher",
    # exchange scraper
    "get_exchange_url",
    "fmt_of",
    "fetch_exchange_page",
    "parse_daily_rows",
    "EXCHANGE_ENDPOINTS",
    # warrant
    "get_warrant",
    "summarize_warrant",
    # huishang
    "get_huishang_fundamental",
    "HuishangFetcher",
    # fundamentals
    "get_fundamental",
    # web collector
    "search_fundamental_llm",
    # sentiment
    "get_sentiment",
    # position ranking
    "get_position_ranking",
    # macro
    "get_macro_pmi",
    "get_macro_rate",
]
