"""
FDT 测试统一路径工具 — 所有 conftest 从此导入
============================================

用法:
    from fdt_test_helpers import add_fdt_paths
    add_fdt_paths(__file__)
"""
import os
import sys


def add_fdt_paths(test_file: str, *extra_dirs: str) -> None:
    """将 FDT 项目根加入 sys.path，使 `from scripts.xxx` 可解析。

    Args:
        test_file: 传入 __file__
        extra_dirs: 额外路径（如 skills/xxx/scripts/），相对于项目根
    """
    # tests/<module>/conftest.py → tests/ → FDT_ROOT
    fdt_root = os.path.dirname(os.path.dirname(os.path.abspath(test_file)))
    
    to_add = [fdt_root]  # FDT_ROOT 优先
    for d in extra_dirs:
        p = os.path.join(fdt_root, d)
        if os.path.isdir(p):
            to_add.append(p)
    
    for p in reversed(to_add):
        if p not in sys.path:
            sys.path.insert(0, p)
