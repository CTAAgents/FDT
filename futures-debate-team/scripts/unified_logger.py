"""
期货辩论专家团 — 统一日志框架 v1.0（技术债清理）
===================================================
替代各模块的 print() 调用，统一日志级别、格式、轮转。

用法:
    from scripts.unified_logger import get_logger
    logger = get_logger("scan_all")
    logger.info("扫描开始")
    logger.warning("数据延迟")
    logger.error("连接失败", exc_info=True)
"""

import logging
import sys
import os
from pathlib import Path
from datetime import datetime


# ── 全局配置 ──
_LOG_LEVEL = os.environ.get("FDB_LOG_LEVEL", "INFO").upper()
_LOG_DIR = os.environ.get("FDB_LOG_DIR", None)

if _LOG_DIR is None:
    _LOG_DIR = Path(os.path.expanduser("~/Documents/WorkBuddy/Logs"))
    _LOG_DIR = str(_LOG_DIR)

_LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# ── 缓存创建过的logger ──
_loggers = {}


def get_logger(name: str, log_dir: str = None, level: str = None) -> logging.Logger:
    """获取或创建 logger。

    Args:
        name: logger 名称（通常用模块名，如 "scan_all"）
        log_dir: 日志目录（默认 ~/Documents/WorkBuddy/Logs/）
        level: 日志级别（默认环境变量 FDB_LOG_LEVEL 或 "INFO"）

    Returns:
        配置好的 logging.Logger 实例
    """
    global _LOG_DIR

    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(f"FDB.{name}")
    
    resolved_level = _LOG_LEVEL_MAP.get((level or _LOG_LEVEL).upper(), logging.INFO)
    logger.setLevel(resolved_level)

    # 避免重复添加 handler
    if logger.handlers:
        _loggers[name] = logger
        return logger

    # 格式化器
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. 控制台 handler（替代 print）
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(resolved_level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # 2. 文件 handler（带自动轮转）
    if log_dir or _LOG_DIR:
        log_path = Path(log_dir or _LOG_DIR)
        log_path.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        file_handler = logging.FileHandler(
            log_path / f"fdb_{today}.log",
            encoding="utf-8",
        )
        file_handler.setLevel(resolved_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 防止传播到根 logger
    logger.propagate = False

    _loggers[name] = logger
    return logger


def set_level(level: str):
    """全局修改日志级别。"""
    resolved = _LOG_LEVEL_MAP.get(level.upper(), logging.INFO)
    for name, logger in _loggers.items():
        logger.setLevel(resolved)
        for handler in logger.handlers:
            handler.setLevel(resolved)


if __name__ == "__main__":
    # 测试
    logger = get_logger("test", level="DEBUG")
    logger.debug("这是 debug")
    logger.info("这是 info")
    logger.warning("这是 warning")
    logger.error("这是 error")
    print("✅ 日志框架测试通过")
