"""补丁记忆存储层 — patches.jsonl 的读写 + 域-补丁倒排索引"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..manager.schemas import PatchEntry

logger = logging.getLogger(__name__)


class PatchStore:
    """补丁记忆的持久化存储。

    - 按日期分片存储至 _session_memory/{YYYYMMDD}/patches.jsonl
    - 维护全局倒排索引 _session_memory/patches_index.json
    """

    def __init__(self, memory_dir: Path):
        self._session_dir = memory_dir / "_session_memory"
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._session_dir / "patches_index.json"
        self._patch_counter = 0

    # ── 写入 ────────────────────────────────────────

    def store(self, entry: PatchEntry) -> str:
        """写入一条补丁记录。

        Returns:
            patch_id（自动生成或使用 entry 中已有的）。
        """
        # 自动生成 patch_id
        if not entry.get("patch_id"):
            self._patch_counter += 1
            today = datetime.now().strftime("%Y%m%d")
            entry["patch_id"] = f"patch-{today}-{self._patch_counter:03d}"

        patch_id = entry["patch_id"]

        # 按日期分片
        date_str = entry.get("conditions", {}).get("valid_from", datetime.now().strftime("%Y-%m-%d"))
        date_dir = date_str.replace("-", "")
        patch_dir = self._session_dir / date_dir
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_file = patch_dir / "patches.jsonl"

        # 追加写入
        with open(patch_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # 更新倒排索引
        self._update_index(entry)

        logger.info("[PatchStore] 已写入补丁: %s (domain=%s)", patch_id, entry.get("domain"))
        return patch_id

    # ── 检索 ────────────────────────────────────────

    def query_by_domain(self, domain: str) -> list[PatchEntry]:
        """按域标签检索补丁链。

        Args:
            domain: 域标签前缀（如 "生猪" 匹配所有 "生猪|*" 补丁）。

        Returns:
            匹配的补丁列表（按 valid_from 降序）。
        """
        index = self._load_index()
        matched_ids: list[str] = []

        for idx_domain, ids in index.items():
            if idx_domain == domain or idx_domain.startswith(f"{domain}|") or domain.startswith(idx_domain):
                matched_ids.extend(ids)

        if not matched_ids:
            return []

        # 去重后加载完整条目
        matched_ids = list(set(matched_ids))
        patches = self._load_by_ids(matched_ids)

        # 按 valid_from 降序
        patches.sort(
            key=lambda p: p.get("conditions", {}).get("valid_from", ""),
            reverse=True,
        )
        return patches

    def query_by_version(self, domain: str, as_of: str | None = None) -> list[PatchEntry]:
        """按版本区间检索相关补丁。

        Args:
            domain: 域标签前缀。
            as_of: 截止日期 YYYY-MM-DD（None=当前日期）。

        Returns:
            在指定日期前有效的补丁列表（降序）。
        """
        as_of = as_of or datetime.now().strftime("%Y-%m-%d")
        patches = self.query_by_domain(domain)

        # 过滤在 as_of 日期前生效的补丁
        result = []
        for p in patches:
            cond = p.get("conditions", {})
            valid_from = cond.get("valid_from", "2000-01-01")
            valid_until = cond.get("valid_until")
            if valid_from <= as_of:
                if valid_until is None or valid_until >= as_of:
                    result.append(p)
        return result

    def resolve_conflict(self, domain: str) -> dict:
        """检查某域是否存在矛盾补丁。

        Returns:
            {"has_conflict": bool, "conflicts": [...], "resolution": "..."}
        """
        patches = self.query_by_domain(domain)
        active = [p for p in patches if p.get("conditions", {}).get("valid_until") is None]

        conflicts = []
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                # 同一域内两条长期有效的补丁如果 rationale 冲突则标记
                if a.get("rationale", "").strip() and b.get("rationale", "").strip():
                    a_dir = a.get("post_state", "")[:30]
                    b_dir = b.get("post_state", "")[:30]
                    if a_dir and b_dir and a_dir != b_dir:
                        conflicts.append({
                            "patch_a": a.get("patch_id"),
                            "patch_b": b.get("patch_id"),
                            "summary": f"冲突: [{a.get('domain')}] {a_dir} vs {b_dir}",
                        })

        if conflicts:
            return {
                "has_conflict": True,
                "conflicts": conflicts,
                "resolution": "需要人工复核 — 两条长期有效的补丁存在方向性矛盾",
            }
        return {"has_conflict": False, "conflicts": [], "resolution": "无矛盾"}

    # ── 内部方法 ────────────────────────────────────

    def _update_index(self, entry: PatchEntry) -> None:
        """更新域→补丁ID 倒排索引。"""
        index = self._load_index()
        domain = entry.get("domain", "unknown")
        patch_id = entry["patch_id"]

        if domain not in index:
            index[domain] = []
        if patch_id not in index[domain]:
            index[domain].append(patch_id)

        self._write_index(index)

    def _load_index(self) -> dict[str, list[str]]:
        """加载倒排索引。"""
        if not self._index_path.exists():
            return {}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_index(self, index: dict) -> None:
        """写入倒排索引。"""
        self._index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_by_ids(self, patch_ids: list[str]) -> list[PatchEntry]:
        """按 patch_id 列表加载完整条目（全量扫描 patches.jsonl）。"""
        id_set = set(patch_ids)
        result: list[PatchEntry] = []

        for patch_file in self._session_dir.rglob("patches.jsonl"):
            if not patch_file.is_file():
                continue
            with open(patch_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("patch_id") in id_set:
                            result.append(entry)
                            id_set.discard(entry["patch_id"])
                    except json.JSONDecodeError:
                        continue

        return result

    def load_all(self) -> list[PatchEntry]:
        """加载全部补丁（用于迁移/统计）。"""
        result: list[PatchEntry] = []
        for patch_file in self._session_dir.rglob("patches.jsonl"):
            if not patch_file.is_file():
                continue
            with open(patch_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        result.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return result
