"""
Eval 缓存管理器 — Manifest 文件的读取、写入、命中判断。

缓存命中规则:
    cache_hit = cache_ttl > 0
                AND (now - last_run) < cache_ttl
                AND all(depends_on 文件 hash 未变)
"""
from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from typing import Any

from fdt_eval.core.base import EvalCase

CACHE_DIR = Path(__file__).resolve().parent.parent / ".eval_cache"
MANIFEST_PATH = CACHE_DIR / "manifest.json"


def _hash_file(glob_pattern: str) -> str | None:
    """计算符合 glob 模式的第一个文件的 sha256 前 12 位。

    Returns:
        hash string 或 None（文件不存在）
    """
    from glob import glob
    matches = glob(glob_pattern, recursive=True)
    if not matches:
        return None
    try:
        h = hashlib.sha256()
        with open(matches[0], "rb") as f:
            h.update(f.read(8192))  # 只读前 8KB
        return h.hexdigest()[:12]
    except OSError:
        return None


def _load_manifest() -> dict[str, Any]:
    """加载 manifest.json，不存在时返回空 dict。"""
    if MANIFEST_PATH.exists():
        try:
            with open(MANIFEST_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_manifest(manifest: dict[str, Any]) -> None:
    """写入 manifest.json。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def check_cache(case: EvalCase) -> bool:
    """检查缓存是否命中。

    Args:
        case: EvalCase 实例

    Returns:
        True 表示缓存命中（应跳过执行）
    """
    if case.cache_ttl <= 0:
        return False

    manifest = _load_manifest()
    entry = manifest.get(case.case_id)
    if entry is None:
        return False

    # TTL 检查
    last_run = entry.get("last_run", 0)
    if (time.time() - last_run) > case.cache_ttl:
        return False

    # 依赖文件 hash 检查
    for dep in (case.depends_on or []):
        cached_hash = entry.get("depends_on", {}).get(dep)
        current_hash = _hash_file(dep)
        if cached_hash != current_hash:
            return False

    return True


def update_cache(case: EvalCase) -> None:
    """执行后更新 manifest 缓存记录。"""
    manifest = _load_manifest()
    entry = manifest.get(case.case_id, {})
    entry["last_run"] = time.time()
    entry["cache_ttl"] = case.cache_ttl
    dep_hashes = {}
    for dep in (case.depends_on or []):
        dep_hashes[dep] = _hash_file(dep)
    entry["depends_on"] = dep_hashes
    manifest[case.case_id] = entry
    _save_manifest(manifest)


def clear_cache(case_id: str | None = None) -> None:
    """清除缓存。

    Args:
        case_id: 指定清除某个 case，None 时清除全部
    """
    if case_id:
        manifest = _load_manifest()
        manifest.pop(case_id, None)
        _save_manifest(manifest)
    else:
        if MANIFEST_PATH.exists():
            MANIFEST_PATH.unlink()
