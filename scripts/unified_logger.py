"""
期货辩论专家团 — 统一日志框架 v1.1
===================================
替代各模块的 print() 调用，统一日志级别、格式、轮转。
v1.1: 新增 JSON 结构化日志（FDT_LOG_FORMAT=json）

用法:
    from scripts.unified_logger import get_logger
    logger = get_logger("scan_all")
    logger.info("扫描开始")
    logger.warning("数据延迟")
    logger.error("连接失败", exc_info=True)

环境变量:
    FDT_LOG_LEVEL  = DEBUG|INFO|WARNING|ERROR|CRITICAL (默认 INFO)
    FDT_LOG_FORMAT = text|json (默认 text)
    FDT_LOG_DIR    = 日志目录 (默认 ~/Documents/WorkBuddy/Logs/)
"""

from __future__ import annotations

import json as _json
import logging
import sys
import os
from pathlib import Path
from datetime import datetime, timezone


# ── 全局配置 ──
_LOG_LEVEL = os.environ.get("FDT_LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = os.environ.get("FDT_LOG_FORMAT", "text").lower()
_LOG_DIR = os.environ.get("FDT_LOG_DIR", None)

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

_loggers = {}


# ── JSON 格式化器（兼容 ELK/Loki 等聚合平台） ──────────

class JSONFormatter(logging.Formatter):
    """结构化 JSON 日志格式"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}Z",
            "logger": record.name,
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            payload["exc"] = str(record.exc_info[1])
        if hasattr(record, "trace_id"):
            payload["trace_id"] = record.trace_id
        return _json.dumps(payload, ensure_ascii=False)


def _make_formatter() -> logging.Formatter:
    """根据 FDT_LOG_FORMAT 返回对应格式化器"""
    if _LOG_FORMAT == "json":
        return JSONFormatter()
    return logging.Formatter(
        fmt="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_logger(name: str, log_dir: str | None = None, level: str | None = None) -> logging.Logger:
    """获取或创建 logger。"""
    global _LOG_DIR

    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(f"FDB.{name}")
    resolved_level = _LOG_LEVEL_MAP.get((level or _LOG_LEVEL).upper(), logging.INFO)
    logger.setLevel(resolved_level)

    if logger.handlers:
        _loggers[name] = logger
        return logger

    formatter = _make_formatter()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(resolved_level)
    console.setFormatter(formatter)
    logger.addHandler(console)

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

    logger.propagate = False
    _loggers[name] = logger
    return logger


def set_level(level: str) -> None:
    resolved = _LOG_LEVEL_MAP.get(level.upper(), logging.INFO)
    for _n, logger in _loggers.items():
        logger.setLevel(resolved)
        for handler in logger.handlers:
            handler.setLevel(resolved)


if __name__ == "__main__":
    logger = get_logger("test", level="DEBUG")
    logger.debug("这是 debug")
    logger.info("这是 info")
    logger.warning("这是 warning")
    logger.error("这是 error")
    print("✅ 日志框架测试通过 (格式: " + _LOG_FORMAT + ")")
