"""
FDT 测试统一路径工具 — 所有 conftest 从此导入
============================================

用法:
    from fdt_test_helpers import add_fdt_paths
    add_fdt_paths(__file__)
"""
import os
import sys


def add_fdt_paths(test_file: str, *extra_dirs, skip_root: bool = False) -> None:
    """将 FDT 项目根加入 sys.path，使 `from scripts.xxx` 可解析。

    Args:
        test_file: 传入 __file__
        extra_dirs: 额外路径列表或字符串，相对于项目根
        skip_root: 为True时不加FDT_ROOT（用于技能级scripts与项目级scripts冲突时）
    """
    # tests/<module>/conftest.py → tests/<module>/ → tests/ → FDT_ROOT
    fdt_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(test_file))))

    # Flatten: conftest calls may pass a list as single arg
    dirs = []
    for d in extra_dirs:
        if isinstance(d, (list, tuple)):
            dirs.extend(d)
        else:
            dirs.append(d)

    to_add = [fdt_root] if not skip_root else []
    for d in dirs:
        p = os.path.join(fdt_root, d)
        if os.path.isdir(p):
            to_add.append(p)

    for p in reversed(to_add):
        if p not in sys.path:
            sys.path.insert(0, p)
