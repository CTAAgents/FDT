"""记忆缺口检查器 — check_memory_gaps.py 的最终实现

用于检测：
1. 缺少 session_memory 的日期
2. learned 字段不完整的记录
3. 超过 30 天未更新的品种知识
4. 可能废弃的文件
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..manager.schemas import GapReport

logger = logging.getLogger(__name__)

# TRAE IDE 记忆目录
TRAE_MEMORY_DIR = (
    Path.home() / ".trae-cn" / "memory" / "projects" / "-d-Programs-FDT"
)


class Checker:
    """记忆缺口检查器"""

    def __init__(self, memory_dir: Path):
        self._memory_dir = memory_dir
        self._knowledge_dir = memory_dir / "knowledge"
        self._session_dir = TRAE_MEMORY_DIR

    def run(self) -> GapReport:
        """执行全面的记忆缺口检查"""
        report: GapReport = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "missing_sessions": self._check_missing_sessions(),
            "incomplete_learned": self._check_incomplete_learned(),
            "stale_knowledge": self._check_stale_knowledge(),
            "unreferenced_files": self._check_unreferenced_files(),
        }

        if any(report.values()):
            logger.warning(f"Memory gaps found: {report}")
        else:
            logger.info("No memory gaps detected")

        return report

    def _check_missing_sessions(self) -> list[str]:
        """检查 TRAE IDE session_memory 是否缺失"""
        if not self._session_dir.exists():
            return ["trae_memory_dir_not_found"]

        missing = []
        # 检查最近 3 个日期目录
        date_dirs = sorted(
            d for d in self._session_dir.iterdir()
            if d.is_dir() and d.name.isdigit()
        )[-3:]

        for date_dir in date_dirs:
            has_session = any(
                f.name.startswith("session_memory_") and f.suffix == ".jsonl"
                for f in date_dir.iterdir()
                if f.is_file()
            )
            if not has_session:
                missing.append(date_dir.name)

        return missing

    def _check_incomplete_learned(self) -> list[str]:
        """检查 session_memory 中 learned 字段是否完整"""
        if not self._session_dir.exists():
            return []

        incomplete = []
        for date_dir in sorted(self._session_dir.iterdir()):
            if not date_dir.is_dir() or not date_dir.name.isdigit():
                continue
            for f in sorted(date_dir.iterdir()):
                if not f.name.startswith("session_memory_") or f.suffix != ".jsonl":
                    continue
                try:
                    for line in f.read_text(encoding="utf-8").strip().split("\n"):
                        if not line.strip():
                            continue
                        entry = json.loads(line)
                        learned = entry.get("learned", [])
                        if not learned:
                            incomplete.append(f"{date_dir.name}/{f.name}")
                        elif isinstance(learned, list):
                            has_tag = any(
                                str(item).startswith("【") for item in learned
                            )
                            if not has_tag:
                                incomplete.append(f"{date_dir.name}/{f.name}")
                except (json.JSONDecodeError, OSError):
                    continue
        return incomplete

    def _check_stale_knowledge(self) -> list[str]:
        """检查超过 30 天未更新的品种知识"""
        if not self._knowledge_dir.exists():
            return []

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stale = []
        for symbol_dir in self._knowledge_dir.iterdir():
            if not symbol_dir.is_dir() or symbol_dir.name.startswith("_"):
                continue
            drivers_path = symbol_dir / "drivers.md"
            if not drivers_path.exists():
                continue
            try:
                mtime = datetime.fromtimestamp(drivers_path.stat().st_mtime)
                if (now - mtime).days > 30:
                    stale.append(symbol_dir.name)
            except OSError:
                continue
        return stale

    def _check_unreferenced_files(self) -> list[str]:
        """扫描可能废弃的零散文件"""
        unreferenced = []
        root_items = [p for p in self._memory_dir.iterdir() if p.is_file()]
        for item in root_items:
            if item.name not in ("index.md",):
                unreferenced.append(str(item.relative_to(self._memory_dir)))
        return unreferenced
