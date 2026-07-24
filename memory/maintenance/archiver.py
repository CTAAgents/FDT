"""归档 + 压缩 — 维护层"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class Archiver:
    """记忆归档器"""

    def __init__(self, memory_dir: Path):
        self._memory_dir = memory_dir
        self._archive_dir = memory_dir / "archive"
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._journal_path = memory_dir / "journal" / "debate_journal.json"

    def archive(self) -> int:
        """压缩 debate_journal.json（保留最近 100 条），返回归档数"""
        if not self._journal_path.exists():
            return 0

        try:
            with open(self._journal_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return 0

        if not isinstance(entries, list) or len(entries) <= 100:
            return 0

        # 前 N-100 条归档
        cutoff = len(entries) - 100
        to_archive = entries[:cutoff]
        kept = entries[cutoff:]

        # 写入归档文件
        archive_file = (
            self._archive_dir / f"debate_journal_archive_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(to_archive, f, indent=2, ensure_ascii=False)

        # 截断主文件
        with open(self._journal_path, "w", encoding="utf-8") as f:
            json.dump(kept, f, indent=2, ensure_ascii=False)

        logger.info(
            f"Archived {len(to_archive)} journal entries to {archive_file.name}"
        )
        return len(to_archive)
