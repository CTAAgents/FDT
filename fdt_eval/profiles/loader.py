"""Profile YAML 加载器。

从 fdt_eval/profiles/*.yaml 加载 profile 配置。
支持 includes/excludes glob 模式 + options 覆盖。
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

PROFILES_DIR = Path(__file__).resolve().parent


def _try_load_yaml(path: Path) -> dict | None:
    """尝试用 YAML 加载，兜底用 JSON。"""
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        pass
    except Exception:
        pass
    try:
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_profile(name: str) -> dict[str, Any] | None:
    """按名称加载 profile 配置。

    Args:
        name: profile 名称 (dev/ci/nightly/release)

    Returns:
        dict 包含 includes/excludes/options，或 None（未找到）
    """
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        # 尝试 .json
        path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        return None

    raw = _try_load_yaml(path)
    if raw is None:
        return None

    return {
        "includes": raw.get("includes", ["*"]),
        "excludes": raw.get("excludes", []),
        "options": raw.get("options", {}),
    }


def resolve_case_ids(
    profile_name: str,
    all_case_ids: list[str],
) -> list[str] | None:
    """解析 profile 配置，返回匹配的 case_id 列表。

    Returns:
        None if profile not found
    """
    cfg = load_profile(profile_name)
    if cfg is None:
        return None

    matched = set()
    for pattern in cfg["includes"]:
        matched.update(fnmatch.filter(all_case_ids, pattern))

    for pattern in cfg["excludes"]:
        matched.difference_update(fnmatch.filter(all_case_ids, pattern))

    # 按阶段排序
    stage_order = {"runtime": 0, "gate": 1, "meta": 2, "post_hoc": 3, "evolution": 4}
    return sorted(matched, key=lambda c: stage_order.get(c.split(".")[0], 99))


def get_profile_options(name: str) -> dict[str, Any]:
    """获取 profile 的选项配置，不存在时返回空 dict。"""
    cfg = load_profile(name)
    return cfg.get("options", {}) if cfg else {}
