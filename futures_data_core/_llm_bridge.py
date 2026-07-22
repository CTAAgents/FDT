"""LLM 调用桥接层（集中管理）。

设计原则：
    - 所有 LLM 调用集中在此模块，不在业务代码中散落。
    - 每个 LLM 调用方法都有清晰的 INDEPENDENT 兜底。
    - LLM 调用失败时静默降级（返回 ``None`` + 警告），不抛异常。

运行模式：``search_fundamental_llm`` 等属于 ``[LLM-DRIVEN]``，
必须在支持 WebSearch 的 LLM 上下文（如 LLM 平台）中执行；
独立 Python 环境调用将返回 ``None`` 或抛出 :class:`LlmContextNotAvailableError`。
"""

from __future__ import annotations

import os
import warnings


class LlmContextNotAvailableError(RuntimeError):
    """LLM 上下文不可用时抛出。"""

    def __init__(self, message: str = "当前环境不支持 LLM 调用") -> None:
        super().__init__(message)


def _has_websearch() -> bool:
    """检测当前环境是否有 WebSearch 能力。"""
    return bool(os.environ.get("WORKBUDDY_LLM_CONTEXT"))


def assert_llm_context(func_name: str) -> None:
    """断言当前具备 LLM 上下文，否则抛 :class:`LlmContextNotAvailableError`。

    Args:
        func_name: 调用方函数名，用于错误提示。

    Raises:
        LlmContextNotAvailableError: 当前环境无 LLM 能力。
    """
    if not _has_websearch():
        raise LlmContextNotAvailableError(
            f"{func_name} 需要在支持 WebSearch 的 LLM 上下文（如 LLM 平台）中执行。"
        )


async def llm_websearch(query: str) -> "str | None":
    """调用 LLM WebSearch（如果可用）。

    运行模式: ``[LLM-DRIVEN]``。

    Args:
        query: 搜索查询字符串。

    Returns:
        str: 搜索结果文本；或 ``None``（LLM 不可用，已降级）。
    """
    if not _has_websearch():
        warnings.warn(
            "WebSearch 在当前环境中不可用，已降级为独立模式。",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    # 实际的 WebSearch 调用由 LLM 桥接层注入；此处为占位实现。
    # 在 LLM 环境中会被替换为真实实现。
    return None


async def llm_enhance(text: str) -> "str | None":
    """LLM 润色（如果可用），用于 F10 报告增强。

    运行模式: ``[LLM-ENHANCED]``。

    Args:
        text: 待润色文本。

    Returns:
        str: 润色后文本；或 ``None``（LLM 不可用）。
    """
    if not _has_websearch():
        return None
    return text
