"""品种知识存储 — 读写 knowledge/ 目录"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..manager.schemas import CURRENT_SCHEMA_VERSION, KnowledgeEntry, validate_schema

logger = logging.getLogger(__name__)


class KnowledgeStore:
    """品种知识存储层"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self._knowledge_dir = memory_dir / "knowledge"
        self._variety_index_path = self._knowledge_dir / "variety_index.json"

    # ── 读取 ──────────────────────────────────────

    def query(self, symbol: str) -> KnowledgeEntry | None:
        """查询单个品种知识"""
        symbol_dir = self._knowledge_dir / symbol
        if not symbol_dir.exists():
            return None

        entry: KnowledgeEntry = {
            "symbol": symbol,
            "last_updated": "",
            "total_debates": 0,
            "drivers": [],
            "patterns": [],
            "key_levels": {},
            "data_quality": {},
        }

        profile_path = symbol_dir / "profile.json"
        if profile_path.exists():
            try:
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
                entry["total_debates"] = profile.get("total_debates", 0)
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        drivers_path = symbol_dir / "drivers.md"
        if drivers_path.exists():
            entry["last_updated"] = datetime.fromtimestamp(
                drivers_path.stat().st_mtime
            ).isoformat()

        patterns_path = symbol_dir / "patterns.json"
        if patterns_path.exists():
            try:
                entry["patterns"] = json.loads(
                    patterns_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        key_levels_path = symbol_dir / "key_levels.json"
        if key_levels_path.exists():
            try:
                entry["key_levels"] = json.loads(
                    key_levels_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        data_quality_path = symbol_dir / "data_quality.json"
        if data_quality_path.exists():
            try:
                entry["data_quality"] = json.loads(
                    data_quality_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        return entry

    def list_symbols(self) -> list[str]:
        """列出所有有知识目录的品种"""
        if not self._knowledge_dir.exists():
            return []
        return sorted(
            d.name for d in self._knowledge_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_") and d.name != "strategies"
        )

    # ── 写入 ──────────────────────────────────────

    def store(self, entry: KnowledgeEntry) -> None:
        """写入品种知识（支持增量更新）"""
        validate_schema(entry, "KnowledgeEntry")

        symbol = entry.get("symbol", "")
        if not symbol:
            raise ValueError("KnowledgeEntry requires 'symbol'")

        symbol_dir = self._knowledge_dir / symbol
        symbol_dir.mkdir(parents=True, exist_ok=True)

        timestamp = entry.get("last_updated") or datetime.now(timezone.utc).isoformat()

        # drivers → drivers.md
        if "drivers" in entry and entry["drivers"]:
            drivers_content = f"# {symbol} 核心驱动因子\n\n最后更新: {timestamp}\n\n"
            for d in entry["drivers"]:
                drivers_content += (
                    f"- **{d.get('name', '?')}**"
                    f" (权重: {d.get('weight', 0)})\n"
                )
            (symbol_dir / "drivers.md").write_text(
                drivers_content, encoding="utf-8"
            )

        # patterns → patterns.json
        if "patterns" in entry and entry["patterns"]:
            existing = []
            patterns_path = symbol_dir / "patterns.json"
            if patterns_path.exists():
                try:
                    existing = json.loads(patterns_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, FileNotFoundError):
                    pass
            merged = existing + entry["patterns"]
            (symbol_dir / "patterns.json").write_text(
                json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        # key_levels
        if "key_levels" in entry and entry["key_levels"]:
            (symbol_dir / "key_levels.json").write_text(
                json.dumps(entry["key_levels"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        # data_quality
        if "data_quality" in entry and entry["data_quality"]:
            (symbol_dir / "data_quality.json").write_text(
                json.dumps(entry["data_quality"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        # 更新 variety_index.json
        self._update_variety_index(symbol, entry)

        logger.info(f"Knowledge for {symbol} stored")

    # ── 索引维护 ──────────────────────────────────

    def _update_variety_index(self, symbol: str, entry: KnowledgeEntry) -> None:
        """更新品种索引（增量）"""
        index = {}
        if self._variety_index_path.exists():
            try:
                index = json.loads(
                    self._variety_index_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        current = index.get(symbol, {"total_debates": 0, "effective_patterns": 0})
        current["total_debates"] = current.get("total_debates", 0) + (
            1 if entry.get("total_debates", 0) > 0 else 0
        )
        current["drivers_updated"] = (
            entry.get("last_updated") if "drivers" in entry else current.get("drivers_updated")
        )
        current["patterns_updated"] = (
            entry.get("last_updated") if "patterns" in entry else current.get("patterns_updated")
        )
        index[symbol] = current

        self._variety_index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── 迁移 ──────────────────────────────────────

    def migrate_from_legacy(self) -> int:
        """检查旧格式并补充索引"""
        symbols = self.list_symbols()
        index = {}
        if self._variety_index_path.exists():
            try:
                index = json.loads(
                    self._variety_index_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        count = 0
        for sym in symbols:
            if sym not in index:
                index[sym] = {"total_debates": 0, "effective_patterns": 0}
                count += 1

        if count > 0:
            self._variety_index_path.write_text(
                json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return count
