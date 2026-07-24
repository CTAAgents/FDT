"""
合约桥接层 — 从 skills/futures-trading-analysis/contracts/ 重新导出所有模型和迁移函数。

用法:
    from contracts import BullOutput, BearOutput, RiskOutput, apply_migration, ...
"""

import importlib.util
import sys
from pathlib import Path

_real = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "futures-trading-analysis"
    / "contracts"
)

# ── 注册为 contracts._impl 子包，相对导入可正确解析 ──────
spec = importlib.util.spec_from_file_location(
    "contracts._impl",
    _real / "__init__.py",
    submodule_search_locations=[str(_real)],
)
_mod = importlib.util.module_from_spec(spec)
_mod.__package__ = "contracts._impl"
sys.modules["contracts._impl"] = _mod
spec.loader.exec_module(_mod)

# ── 重新导出所有公开符号 ─────────────────────────────────
_exported = []
for _attr in dir(_mod):
    if not _attr.startswith("_"):
        globals()[_attr] = getattr(_mod, _attr)
        _exported.append(_attr)

__all__ = _exported
