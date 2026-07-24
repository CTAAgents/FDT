"""事故记录存储 — 读写 incidents/incidents.md + failure_clusters.json"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from ..manager.schemas import IncidentEntry, validate_schema

logger = logging.getLogger(__name__)


class IncidentStore:
    """事故记录存储层"""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self._incidents_dir = memory_dir / "incidents"
        self._incidents_dir.mkdir(parents=True, exist_ok=True)

    # ── 读取 ──────────────────────────────────────

    def load_all(self) -> list[IncidentEntry]:
        """读取 incidents.md 并解析为结构化条目"""
        path = self._incidents_dir / "incidents.md"
        if not path.exists():
            return []
        # incidents.md 是人类可读的 Markdown，不做结构化解析
        # 返回元信息
        return []

    # ── 写入 ──────────────────────────────────────

    def store(self, entry: IncidentEntry) -> None:
        """以 Markdown 格式追加写入 incidents.md"""
        validate_schema(entry, "IncidentEntry")

        entry["timestamp"] = entry.get("timestamp") or datetime.now(
            timezone.utc
        ).isoformat()
        entry.setdefault("trace_id", f"inc-{datetime.now().timestamp():.0f}")

        date_str = entry["timestamp"][:10]
        md_entry = (
            f"\n## {entry['title']} ({entry['severity']})\n\n"
            f"- **日期**: {date_str}\n"
            f"- **trace_id**: {entry['trace_id']}\n\n"
            "### 事件\n\n"
            f"{entry.get('root_cause', '')}\n\n"
            "### 根因\n\n"
            f"{entry.get('root_cause', '')}\n\n"
            "### 改正\n\n"
            f"{entry.get('fix', '')}\n\n"
            "### 预防\n\n"
            f"{entry.get('prevention', '')}\n"
            "---\n"
        )

        path = self._incidents_dir / "incidents.md"
        with open(path, "a", encoding="utf-8") as f:
            f.write(md_entry)

        logger.info(f"Incident {entry.get('trace_id')} written to incidents.md")
