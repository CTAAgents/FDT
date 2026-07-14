"""Root test conftest — 添加 FDT 核心模块路径。"""
import sys, os

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PATHS = [
    os.path.join(_ROOT, "..", "scripts"),
    os.path.join(_ROOT, "..", "skills", "quant-daily", "scripts"),
]
for p in _PATHS:
    rp = os.path.realpath(p)
    if rp not in sys.path:
        sys.path.insert(0, rp)
