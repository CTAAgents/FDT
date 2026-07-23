"""
期货辩论专家团 — 统一日志框架 v1.2
===================================
替代各模块的 print() 调用，统一日志级别、格式、轮转、归档。

v1.2 变更:
  - 默认日志路径从 ~/Documents/FDT/Logs → FDT_ROOT/memory/logs/
  - 新增 RotatingFileHandler (10MB/文件, 保留5个备份)
  - 新增 30 天自动清理过期日志
  - 新增 trace_id 注入支持

用法:
    from scripts.unified_logger import get_logger
    logger = get_logger("scan_all")
    logger.info("扫描开始")
    logger.warning("数据延迟")
    logger.error("连接失败", exc_info=True)

环境变量:
    FDT_LOG_LEVEL  = DEBUG|INFO|WARNING|ERROR|CRITICAL (默认 INFO)
    FDT_LOG_FORMAT = text|json (默认 text)
    FDT_LOG_DIR    = 日志目录 (默认 FDT_ROOT/memory/logs/)
"""

from __future__ import annotations

import json as _json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta


# ── 自动检测 FDT 根目录 ──

def _detect_fdt_root() -> str | None:
    """从 __file__ 位置向上找到 FDT 根目录。"""
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        if (parent / "memory").is_dir() and (parent / "scripts").is_dir():
            return str(parent)
    return None


_FDT_ROOT = _detect_fdt_root()

# ── 全局配置 ──
_LOG_LEVEL = os.environ.get("FDT_LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = os.environ.get("FDT_LOG_FORMAT", "text").lower()
_LOG_DIR = os.environ.get("FDT_LOG_DIR", None)

if _LOG_DIR is None and _FDT_ROOT:
    _LOG_DIR = os.path.join(_FDT_ROOT, "memory", "logs")
elif _LOG_DIR is None:
    _LOG_DIR = str(Path.home() / "Documents" / "FDT" / "Logs")

_LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_loggers = {}
_cleanup_lock = False


# ── 日志轮转配置 ──

_MAX_BYTES = 10 * 1024 * 1024   # 10 MB 轮转
_BACKUP_COUNT = 5                # 保留 5 个备份
_RETENTION_DAYS = 30             # 日志保留 30 天


def _cleanup_old_logs(log_dir: str) -> None:
    """删除超过 RETENTION_DAYS 天的旧日志文件。"""
    global _cleanup_lock
    if _cleanup_lock:
        return
    _cleanup_lock = True
    try:
        cutoff = time.time() - _RETENTION_DAYS * 86400
        for f in Path(log_dir).glob("fdb_*.log*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                except OSError:
                    pass
    finally:
        _cleanup_lock = False


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
        fmt="[%(asctime)s] [%(name)s] [%(levelname)s] [%(trace_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class TraceIDFilter(logging.Filter):
    """将 trace_id 注入 LogRecord（text 格式可用）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


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

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(resolved_level)
    console.setFormatter(formatter)
    console.addFilter(TraceIDFilter())
    logger.addHandler(console)

    # File handler with rotation
    log_path = Path(log_dir or _LOG_DIR)
    log_path.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    file_handler = logging.handlers.RotatingFileHandler(
        log_path / f"fdb_{today}.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(resolved_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(TraceIDFilter())
    logger.addHandler(file_handler)

    # 清理过期日志（每日首次调用）
    _cleanup_old_logs(str(log_path))

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
    print("✅ 日志框架 v1.2 测试通过 (格式: " + _LOG_FORMAT + ")")
