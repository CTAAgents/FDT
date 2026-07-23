"""知识老化 — 维护层：封装 extract_knowledge.run_decay()"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Decay:
    """知识老化执行器"""

    def __init__(self, memory_dir: Path):
        self._memory_dir = memory_dir

    def run(self, days_without_update: int = 60) -> list[str]:
        """执行知识老化，返回 deprecated 的模式名列表"""
        return self._fallback_decay(days_without_update)

    def _fallback_decay(self, days_without_update: int) -> list[str]:
        """简易老化逻辑：扫描 knowledge/ 目录，60 天未辩论的品种标记"""
        knowledge_dir = self._memory_dir / "knowledge"
        if not knowledge_dir.exists():
            return []

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff = days_without_update * 86400
        decayed = []

        for symbol_dir in knowledge_dir.iterdir():
            if not symbol_dir.is_dir() or symbol_dir.name.startswith("_"):
                continue
            # 检查 drivers.md 的最后修改时间
            drivers_path = symbol_dir / "drivers.md"
            if not drivers_path.exists():
                continue
            try:
                mtime = datetime.fromtimestamp(drivers_path.stat().st_mtime)
                age = (now - mtime).total_seconds()
                if age > cutoff:
                    logger.info(
                        f"Knowledge decay: {symbol_dir.name} "
                        f"({age / 86400:.0f} days without update)"
                    )
                    decayed.append(symbol_dir.name)
            except OSError:
                continue

        if decayed:
            logger.info(
                f"Decay check complete: {len(decayed)} symbols stale "
                f"(>{days_without_update}d)"
            )
        return decayed
