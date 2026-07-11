"""
FDT 统一链路追踪 — Trace ID 模块 v1.0
=======================================

为每一轮辩论（或每次流水线运行）生成唯一 trace_id，
贯穿 P1-P6 所有阶段，注入日志、文件名和子进程环境变量，
实现完整链路可追踪。

用法:
    from scripts.trace_id import new_trace, current_trace, TraceLogAdapter

    # 流水线入口
    trace_id = new_trace()
    logger.info(f"Trace ID: {trace_id}")

    # 子模块中
    tid = current_trace()  # 自动从环境变量/线程上下文获取

    # 子进程透传
    env = inject_trace_to_env()
    subprocess.run(cmd, env=env)
"""

import os
import threading
import uuid
from datetime import datetime
from typing import Optional

# ── 线程局部存储 ──
_trace_context = threading.local()
_ENV_KEY = "FDT_TRACE_ID"


def new_trace(prefix: str = "") -> str:
    """生成新的 trace_id 并设置为当前上下文。

    trace_id 格式: {YYYYMMDD}-{8位hex}
    子进程通过环境变量 FDT_TRACE_ID 继承。

    Args:
        prefix: 可选的 trace 前缀（如 "daily", "adhoc"）

    Returns:
        trace_id 字符串
    """
    date_str = datetime.now().strftime("%Y%m%d")
    short_id = uuid.uuid4().hex[:8]
    if prefix:
        tid = f"{prefix}-{date_str}-{short_id}"
    else:
        tid = f"{date_str}-{short_id}"

    _trace_context.id = tid
    os.environ[_ENV_KEY] = tid
    return tid


def current_trace() -> str:
    """获取当前 trace_id。

    优先级: 线程上下文 > 环境变量 > 默认值

    Returns:
        当前 trace_id，或 "no-trace" 表示未初始化
    """
    # 1. 线程上下文
    tid = getattr(_trace_context, "id", None)
    if tid:
        return tid

    # 2. 环境变量（子进程继承）
    tid = os.environ.get(_ENV_KEY)
    if tid:
        _trace_context.id = tid  # 回填到线程上下文
        return tid

    return "no-trace"


def set_trace(trace_id: str) -> None:
    """显式设置当前 trace_id（用于子进程恢复）。"""
    _trace_context.id = trace_id
    os.environ[_ENV_KEY] = trace_id


def inject_trace_to_env(extra_env: Optional[dict] = None) -> dict:
    """生成包含 trace_id 的环境变量字典，用于子进程透传。

    Args:
        extra_env: 额外的环境变量

    Returns:
        合并后的环境变量字典
    """
    env = os.environ.copy()
    env[_ENV_KEY] = current_trace()
    if extra_env:
        env.update(extra_env)
    return env


class TraceLogAdapter:
    """在日志消息前自动附加 [trace_id] 前缀。"""

    def __init__(self, logger, trace_getter=None):
        self._logger = logger
        self._getter = trace_getter or current_trace

    def _prepend(self, msg):
        return f"[{self._getter()}] {msg}"

    def debug(self, msg, *args, **kwargs):
        self._logger.debug(self._prepend(msg), *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._logger.info(self._prepend(msg), *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._logger.warning(self._prepend(msg), *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._logger.error(self._prepend(msg), *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._logger.critical(self._prepend(msg), *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self._logger.exception(self._prepend(msg), *args, **kwargs)


def trace_file_name(base: str, ext: str = "json") -> str:
    """生成带 trace_id 的文件名。

    Args:
        base: 基础文件名（如 "debate_results"）
        ext: 扩展名（默认 "json"）

    Returns:
        "{base}_{trace_id}.{ext}"
    """
    tid = current_trace()
    if tid == "no-trace":
        return f"{base}.{ext}"
    return f"{base}_{tid}.{ext}"


if __name__ == "__main__":
    tid = new_trace("test")
    assert tid.startswith("test-"), f"Unexpected trace_id format: {tid}"
    assert current_trace() == tid, "current_trace mismatch"
    print(f"✅ Trace ID 模块测试通过: {tid}")
