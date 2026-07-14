"""结构化日志 [INDEPENDENT]。

``setup_logging(date)`` 在保留既有 print 输出的前提下，额外把日志镜像到
``logs/fdt_{date}.log``（文件 + 控制台双 handler）。

首版策略：**只加镜像，不删 print**。避免破坏任何其他依赖 stdout 解析的脚本。
所有关键节点逐步从 print 迁到 logger（本文件仅为基础设施）。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

__all__ = ["setup_logging", "get_logger"]

_LOGGER_NAME = "fdt"


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def setup_logging(date_str: str | None = None, level: int = logging.INFO) -> logging.Logger:
    """配置 FDT 根 logger：控制台 + 文件双输出。幂等（重复调用不叠加 handler）。"""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    if logger.handlers:
        return logger  # 已配置，避免重复 handler

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 控制台
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    # 文件
    try:
        log_dir = _root() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        d = date_str or date.today().strftime("%Y-%m-%d")
        fh = logging.FileHandler(str(log_dir / f"fdt_{d}.log"), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass  # 文件日志不可用时不阻断
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
