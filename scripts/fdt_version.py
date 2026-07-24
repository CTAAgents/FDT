"""FDT 版本号 —— 单一真相源。

所有硬编码版本号必须替换为此函数调用。
"""
from __future__ import annotations

import re
from pathlib import Path


def get_fdt_version() -> str:
    """从 pyproject.toml 读取版本号"""
    root = Path(__file__).resolve().parent.parent
    pp = root / "pyproject.toml"
    if not pp.exists():
        return "未知"

    try:
        text = pp.read_text(encoding="utf-8")
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else "未知"
    except Exception:
        return "未知"


def get_fdt_version_tag() -> str:
    """返回带 v 前缀的版本号"""
    return f"v{get_fdt_version()}"
