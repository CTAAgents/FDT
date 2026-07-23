"""TTL 清理 + 存储限容 — 维护层"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class Cleaner:
    """过期记忆清理器"""

    def __init__(self, memory_dir: Path):
        self._memory_dir = memory_dir
        self._journal_path = memory_dir / "journal" / "debate_journal.json"

    def clean(self, max_age_days: int = 30) -> int:
        """清理超过 max_age_days 的 journal 记录，返回清理数"""
        if not self._journal_path.exists():
            return 0

        try:
            with open(self._journal_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return 0

        if not isinstance(entries, list):
            return 0

        now = datetime.now(timezone.utc)
        cutoff = max_age_days * 86400  # seconds
        kept = []
        removed = 0
        for entry in entries:
            ts = entry.get("timestamp", "")
            try:
                entry_time = datetime.fromisoformat(ts)
                if (now - entry_time).total_seconds() > cutoff:
                    removed += 1
                    continue
            except (ValueError, TypeError):
                pass
            kept.append(entry)

        if removed > 0:
            with open(self._journal_path, "w", encoding="utf-8") as f:
                json.dump(kept, f, indent=2, ensure_ascii=False)
            logger.info(f"Cleaned {removed} old journal entries (>{max_age_days}d)")

        return removed

    def enforce_storage_limit(self, max_mb: int = 100) -> float:
        """检查并清理存储超过限额的部分"""
        total_bytes = sum(
            f.stat().st_size
            for f in self._memory_dir.rglob("*")
            if f.is_file() and f.suffix in (".json", ".db", ".md")
        )
        total_mb = total_bytes / (1024 * 1024)
        if total_mb > max_mb:
            logger.warning(
                f"Storage {total_mb:.1f}MB exceeds limit {max_mb}MB. "
                "Manual cleanup recommended."
            )
        return total_mb
