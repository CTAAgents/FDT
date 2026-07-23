"""经验记录存储 — 读写 experience/records/ 目录"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..manager.schemas import CURRENT_SCHEMA_VERSION, ExperienceEntry, validate_schema

logger = logging.getLogger(__name__)


class ExperienceStore:
    """经验记录存储层"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self._records_dir = memory_dir / "experience" / "records"
        self._patterns_dir = memory_dir / "experience" / "patterns"
        self._index_path = memory_dir / "experience" / "INDEX.json"
        self._records_dir.mkdir(parents=True, exist_ok=True)

    # ── 读取 ──────────────────────────────────────

    def query(self, symbol: str) -> list[ExperienceEntry]:
        """查询某个品种的经验记录"""
        path = self._records_dir / f"{symbol}.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else [data]
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def list_symbols(self) -> list[str]:
        """列出所有有经验记录的品种"""
        if not self._records_dir.exists():
            return []
        return sorted(
            f.stem for f in self._records_dir.iterdir() if f.suffix == ".json"
        )

    # ── 写入 ──────────────────────────────────────

    def store(self, entry: ExperienceEntry) -> None:
        """写入经验记录（追加到品种文件）"""
        validate_schema(entry, "ExperienceEntry")

        symbol = entry.get("symbol", "")
        if not symbol:
            raise ValueError("ExperienceEntry requires 'symbol'")

        path = self._records_dir / f"{symbol}.json"
        existing = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        existing = existing if isinstance(existing, list) else [existing]

        entry["timestamp"] = entry.get("timestamp") or datetime.now(
            timezone.utc
        ).isoformat()
        entry["schema_version"] = CURRENT_SCHEMA_VERSION
        existing.append(entry)

        path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        self._update_index(symbol)
        logger.debug(f"Experience record for {symbol} stored")

    # ── 索引维护 ──────────────────────────────────

    def _update_index(self, symbol: str) -> None:
        """增量更新经验索引"""
        index = {"version": "2.0", "records": {}}
        if self._index_path.exists():
            try:
                index = json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        records = index.setdefault("records", {})
        records[symbol] = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "signal_quality": "actionable",
        }
        index["records"] = records
        self._index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── 迁移 ──────────────────────────────────────

    def migrate_from_legacy(self) -> int:
        """从旧格式迁移（检查并补全 schema_version）"""
        symbols = self.list_symbols()
        count = 0
        for sym in symbols:
            entries = self.query(sym)
            changed = False
            for entry in entries:
                if "schema_version" not in entry:
                    entry["schema_version"] = CURRENT_SCHEMA_VERSION
                    changed = True
            if changed:
                path = self._records_dir / f"{sym}.json"
                path.write_text(
                    json.dumps(entries, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                count += 1
        return count
