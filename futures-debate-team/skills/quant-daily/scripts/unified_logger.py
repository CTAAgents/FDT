"""统一的日志打印与模块级时间戳缓存"""

import logging


def get_logger(name: str = None) -> logging.Logger:
    """获取统一的logger实例"""
    _logger = logging.getLogger(name or __name__)
    if not _logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
        _logger.addHandler(handler)
        _logger.setLevel(logging.WARNING)
    return _logger
