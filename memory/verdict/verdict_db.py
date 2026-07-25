"""裁决结果记录存储 — JSON 文件存储 + 按品种/方向/置信度区间查询"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..manager.schemas import VerdictRecord

logger = logging.getLogger(__name__)


class VerdictDB:
    """裁决数据库 — 存储每轮辩论的裁决结果与事后走势配对

    文件布局:
      memory/verdict/records/{symbol}/{trace_id}.json
    """

    def __init__(self, memory_dir: Path):
        self._records_dir = memory_dir / "verdict" / "records"
        self._records_dir.mkdir(parents=True, exist_ok=True)

    def store(self, record: VerdictRecord) -> str:
        """存储一条裁决记录

        Returns:
            记录 trace_id
        """
        trace_id = record["trace_id"]
        symbol = record.get("symbol", "unknown").upper()
        sym_dir = self._records_dir / symbol
        sym_dir.mkdir(parents=True, exist_ok=True)

        path = sym_dir / f"{trace_id}.json"
        record.setdefault("schema_version", "2.1")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        logger.debug(f"VerdictRecord stored: {symbol}/{trace_id}")
        return trace_id

    def get(self, symbol: str, trace_id: str) -> Optional[VerdictRecord]:
        """读取单个裁决记录"""
        path = self._records_dir / symbol.upper() / f"{trace_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return None

    def query(
        self,
        symbol: Optional[str] = None,
        direction: Optional[str] = None,
        confidence_low: float = 0.0,
        confidence_high: float = 100.0,
        limit: int = 200,
    ) -> list[VerdictRecord]:
        """按条件查询裁决记录

        Args:
            symbol: 品种代码，None 表示全部
            direction: 方向过滤
            confidence_low/confidence_high: 置信度区间 [0, 100]
            limit: 最大返回数
        """
        results: list[VerdictRecord] = []

        if symbol:
            sym_dir = self._records_dir / symbol.upper()
            paths = list(sym_dir.glob("*.json")) if sym_dir.exists() else []
        else:
            paths = list(self._records_dir.rglob("*.json"))

        for p in paths:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    rec: VerdictRecord = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                continue

            if direction and rec.get("direction") != direction:
                continue

            conf = rec.get("confidence", 0)
            if isinstance(conf, (int, float)):
                if conf < confidence_low or conf > confidence_high:
                    continue

            results.append(rec)

        # 按时间倒序
        results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return results[:limit]

    def list_symbols(self) -> list[str]:
        """返回有裁决记录的品种列表"""
        symbols = []
        for d in self._records_dir.iterdir():
            if d.is_dir() and any(d.glob("*.json")):
                symbols.append(d.name)
        return sorted(symbols)

    def count(self) -> int:
        """返回总记录数"""
        return len(list(self._records_dir.rglob("*.json")))

    def migrate_from_legacy(self) -> int:
        """从 JournalEntry 迁移历史裁决记录（占位 — 需人工确认 N 日走势后批量回填）"""
        count = 0
        logger.info("VerdictDB legacy migration: pending manual outcome pairing")
        return count
