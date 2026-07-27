"""评估用例自动发现。"""

from pathlib import Path
import importlib
import pkgutil


def _discover_cases() -> None:
    """导入所有 case 模块以触发装饰器注册。"""
    pkg_dir = Path(__file__).parent
    for importer, module_name, is_pkg in pkgutil.walk_packages(
        path=[str(pkg_dir)],
        prefix="fdt_eval.cases.",
    ):
        try:
            importlib.import_module(module_name)
        except Exception:
            pass  # 空模块占位


_discover_cases()
