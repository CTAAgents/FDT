"""辩论日志存储 — 读写 debate_journal.json + SQLite 双写"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..manager.schemas import CURRENT_SCHEMA_VERSION, JournalEntry, validate_schema

logger = logging.getLogger(__name__)


class JournalStore:
    """辩论日志存储层"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self._journal_path = memory_dir / "journal" / "debate_journal.json"
        self._index_path = memory_dir / "journal" / "index.json"
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 读取 ──────────────────────────────────────

    def load_all(self) -> list[dict]:
        """读取全部 journal 条目"""
        if not self._journal_path.exists():
            return []
        try:
            with open(self._journal_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"Failed to read {self._journal_path}, returning empty")
            return []

    def query(self, symbol: str | None = None,
              limit: int = 10) -> list[JournalEntry]:
        """按品种查询辩论历史"""
        entries = self.load_all()
        if symbol:
            entries = [e for e in entries if e.get("symbol") == symbol]
        entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return entries[:limit]

    # ── 写入 ──────────────────────────────────────

    def store(self, entry: JournalEntry) -> str:
        """写入一条 journal 条目，返回 trace_id"""
        validate_schema(entry, "JournalEntry")

        timestamp = entry.get("timestamp") or datetime.now(timezone.utc).isoformat()
        entry["timestamp"] = timestamp
        entry["schema_version"] = CURRENT_SCHEMA_VERSION
        trace_id = entry.get("trace_id") or f"journal-{datetime.now().timestamp():.0f}"
        entry["trace_id"] = trace_id

        # 双写: JSON + SQLite
        self._append_json(entry)
        self._append_sqlite(entry)

        return trace_id

    def store_schedule(self, task: str, state: dict) -> None:
        """持久化调度状态到 schedule_state.json"""
        path = self.memory_dir / "state" / "schedule_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        data[task] = {
            **state,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ── 迁移 ──────────────────────────────────────

    def migrate_from_legacy(self) -> int:
        """从旧格式迁移到新 Schema（添加 schema_version）"""
        entries = self.load_all()
        count = 0
        for entry in entries:
            if "schema_version" not in entry:
                entry["schema_version"] = CURRENT_SCHEMA_VERSION
                count += 1
        if count > 0:
            with open(self._journal_path, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
        return count

    # ── 内部方法 ──────────────────────────────────

    def _append_json(self, entry: dict) -> None:
        """追加写入 JSON 文件"""
        entries = self.load_all()
        entries.append(entry)
        # 限容：超出 journal_max_entries 时裁剪
        max_entries = getattr(self, "_max_entries", 1000)
        if len(entries) > max_entries:
            entries = entries[-max_entries:]
        with open(self._journal_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        logger.debug(f"Journal entry {entry.get('trace_id')} appended to JSON")

    def _append_sqlite(self, entry: dict) -> None:
        """备份写入 SQLite"""
        db_path = self.memory_dir / "state" / "mid_term.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                """CREATE TABLE IF NOT EXISTS debate_journal (
                    trace_id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    round_id TEXT,
                    symbol TEXT,
                    direction TEXT,
                    confidence REAL,
                    grade TEXT,
                    verdict TEXT,
                    risk TEXT,
                    pnl REAL,
                    outcome TEXT,
                    schema_version TEXT
                )"""
            )
            conn.execute(
                """INSERT OR REPLACE INTO debate_journal
                (trace_id, timestamp, round_id, symbol, direction,
                 confidence, grade, verdict, risk, pnl, outcome, schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.get("trace_id"),
                    entry.get("timestamp"),
                    entry.get("round_id"),
                    entry.get("symbol"),
                    entry.get("direction"),
                    entry.get("confidence"),
                    entry.get("grade"),
                    json.dumps(entry.get("verdict", {})),
                    json.dumps(entry.get("risk", {})),
                    entry.get("pnl"),
                    entry.get("outcome"),
                    entry.get("schema_version"),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"SQLite journal write failed (non-fatal): {e}")
