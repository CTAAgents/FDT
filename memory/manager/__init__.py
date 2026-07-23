"""MemoryManager 核心 — memory/ 目录的唯一读写入口"""

from .manager import MemoryManager

_global_memory: MemoryManager | None = None


def get_memory() -> MemoryManager:
    """获取全局单例"""
    assert _global_memory is not None, "MemoryManager not initialized"
    return _global_memory


def init_memory(base_dir: str | None = None) -> MemoryManager:
    """初始化全局单例（在 fdt_cli.py 入口处调用）"""
    import os

    from .manager import MemoryManager

    global _global_memory
    _global_memory = MemoryManager(base_dir or os.getcwd())
    return _global_memory
