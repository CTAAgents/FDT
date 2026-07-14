"""
FDT 合约版本迁移工具 — 顶层重新导出桥。

实现 `apply_migration()` / `MIGRATION_REGISTRY` / `VERSION_MATRIX` 的顶层入口。

真实实现在 skills/futures-trading-analysis/contracts/migrations.py，
本文件作为 re-export shim 提供 `from contracts.migrations import apply_migration` 路径。

用法:
    from contracts.migrations import apply_migration, MIGRATION_REGISTRY, VERSION_MATRIX
"""

import sys
import importlib.util
from pathlib import Path

# skills/futures-trading-analysis/contracts/migrations.py 的绝对路径
_impl_path = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "futures-trading-analysis"
    / "contracts"
    / "migrations.py"
)

if _impl_path.exists():
    spec = importlib.util.spec_from_file_location(
        "contracts._impl_migrations",
        str(_impl_path),
    )
    _mod = importlib.util.module_from_spec(spec)
    _mod.__package__ = "contracts._impl_migrations"
    sys.modules["contracts._impl_migrations"] = _mod
    spec.loader.exec_module(_mod)

    # re-export 所有公开符号
    for _attr in dir(_mod):
        if not _attr.startswith("_"):
            globals()[_attr] = getattr(_mod, _attr)

    __all__ = [a for a in dir(_mod) if not a.startswith("_")]
else:
    # fallback: 空桩（不应在生产到达此分支）
    MIGRATION_REGISTRY = {}
    VERSION_MATRIX = {}

    def apply_migration(skill_type: str, data: dict, target_version: str) -> dict:
        raise NotImplementedError("migrations.py 未找到 — 请检查 skills/futures-trading-analysis/contracts/migrations.py")
