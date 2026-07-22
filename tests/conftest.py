"""Root test conftest — 添加 FDT 核心模块路径，预加载 config 包避免命名空间冲突。"""
import sys
import os
import importlib.util

_ROOT = os.path.dirname(os.path.abspath(__file__))

# ── 1. sys.path 设置 ──
_PATHS = [
    os.path.join(_ROOT, "..", "scripts"),
    os.path.join(_ROOT, "..", "skills", "quant-daily", "scripts"),
    os.path.join(_ROOT, ".."),
]
for p in _PATHS:
    rp = os.path.realpath(p)
    if rp not in sys.path:
        sys.path.insert(0, rp)

# ── 2. 预加载 config 包 ──
# 根 config/ 目录无 __init__.py，成为 PEP 420 命名空间，导致 config.settings 找不到。
_SKILL_CONFIG = os.path.realpath(os.path.join(_ROOT, "..", "skills", "quant-daily", "scripts", "config"))
if os.path.isdir(_SKILL_CONFIG) and os.path.isfile(os.path.join(_SKILL_CONFIG, "__init__.py")):
    spec = importlib.util.spec_from_file_location(
        "config", os.path.join(_SKILL_CONFIG, "__init__.py"),
        submodule_search_locations=[_SKILL_CONFIG]
    )
    if spec and "config" not in sys.modules:
        config_mod = importlib.util.module_from_spec(spec)
        sys.modules["config"] = config_mod
        spec.loader.exec_module(config_mod)
