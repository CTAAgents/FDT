"""运行模式检测。

整个模块的数据管道分为三种运行模式：

- ``INDEPENDENT``：纯 Python 代码，零 LLM 依赖，任意环境可运行。
- ``LLM_ENHANCED``：核心逻辑独立，LLM 可选增强。
- ``LLM_DRIVEN``：必须通过 LLM 上下文执行。
- ``UNAVAILABLE``：所需数据源/环境当前不可用。
"""

from __future__ import annotations

import os
from enum import Enum


class RuntimeMode(str, Enum):
    """数据管道运行模式。"""

    INDEPENDENT = "independent"
    LLM_ENHANCED = "llm_enhanced"
    LLM_DRIVEN = "llm_driven"
    UNAVAILABLE = "unavailable"

    def __str__(self) -> str:  # pragma: no cover - 仅用于友好展示
        return self.value


def _has_websearch() -> bool:
    """检测当前环境是否具备 LLM WebSearch 能力。

    WorkBuddy 等 LLM 环境会注入 ``WORKBUDDY_LLM_CONTEXT`` 环境变量；
    独立 Python 环境返回 ``False``。
    """
    return bool(os.environ.get("WORKBUDDY_LLM_CONTEXT"))


def detect_llm_capability() -> dict:
    """探测当前环境每项功能的可运行模式。

    Returns:
        映射 ``功能名 -> RuntimeMode 值`` 的字典。
    """
    has_llm = _has_websearch()
    return {
        "kline": RuntimeMode.INDEPENDENT.value,
        "indicators": RuntimeMode.INDEPENDENT.value,
        "term_structure": RuntimeMode.INDEPENDENT.value,
        "spread": RuntimeMode.INDEPENDENT.value,
        "basis": RuntimeMode.INDEPENDENT.value,
        "warrant": RuntimeMode.INDEPENDENT.value,
        "fundamental_supply": (
            RuntimeMode.LLM_ENHANCED.value if has_llm else RuntimeMode.INDEPENDENT.value
        ),
        "fundamental_demand": (
            RuntimeMode.LLM_ENHANCED.value if has_llm else RuntimeMode.INDEPENDENT.value
        ),
        "search_fundamental_llm": (
            RuntimeMode.LLM_DRIVEN.value if has_llm else RuntimeMode.UNAVAILABLE.value
        ),
    }


def current_environment() -> str:
    """返回当前环境描述。"""
    return "llm" if _has_websearch() else "independent_python"
