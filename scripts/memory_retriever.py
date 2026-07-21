#!/usr/bin/env python3
"""
memory_retriever.py — 记忆召回策略 (D5 Memory Phase 3)
========================================================
功能:
  1. 基于品种相似度的上下文自动注入
  2. 基于区制匹配的历史案例召回
  3. Top-K 召回 + 强制负样本
  4. 记忆排序与评分

用法:
  from scripts.memory_retriever import MemoryRetriever
  retriever = MemoryRetriever()
  results = retriever.retrieve(symbol="RB", top_k=5)
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = PROJECT_ROOT / "memory" / "retriever_cache"


class MemoryRetriever:
    """记忆召回引擎"""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or DEFAULT_STORAGE
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "retriever_cache.db"

    def retrieve(
        self,
        symbol: str = "",
        regime: str = "",
        top_k: int = 5,
        require_negative: bool = True,
        days: int = 90,
    ) -> list[dict]:
        """
        召回历史记忆

        Args:
            symbol: 品种
            regime: 区制
            top_k: 返回数量
            require_negative: 是否强制包含负样本
            days: 历史天数

        Returns:
            按相关度排序的记忆列表
        """
        results = self._query_local(symbol, regime, top_k * 2, days)
        scored = self._score_results(results, symbol, regime)
        scored.sort(key=lambda x: x.get("_score", 0), reverse=True)

        selected = scored[:top_k]

        # 强制注入负样本
        if require_negative:
            negatives = [r for r in scored if not r.get("is_positive", True)]
            if negatives:
                # 将最高分的负样本替换最后一个正样本
                for i, r in enumerate(selected):
                    if r.get("is_positive", True):
                        selected[i] = negatives[0]
                        break

        return selected

    def _query_local(self, symbol: str, regime: str, limit: int, days: int) -> list[dict]:
        """从本地存储查询"""
        return []  # 本地存储占位, 集成vector_memory后使用

    def _score_results(self, results: list[dict], symbol: str, regime: str) -> list[dict]:
        """对结果进行评分"""
        for r in results:
            score = 0.5
            if r.get("symbol") == symbol:
                score += 0.3
            if r.get("regime") == regime and regime:
                score += 0.2
            r["_score"] = score
        return results

    def store_debate_result(self, symbol: str, direction: str, confidence: float, is_profitable: bool):
        """存储辩论结果用于未来召回"""
        record = {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "is_positive": is_profitable,
            "timestamp": datetime.now().isoformat(),
        }
        self._store_local(record)
        return record

    def _store_local(self, record: dict):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS debate_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                direction TEXT,
                confidence REAL,
                is_positive INTEGER,
                timestamp TEXT
            )
        """)
        conn.execute(
            "INSERT INTO debate_memory (symbol, direction, confidence, is_positive, timestamp) VALUES (?,?,?,?,?)",
            (record["symbol"], record["direction"], record["confidence"],
             int(record["is_positive"]), record["timestamp"]),
        )
        conn.commit()
        conn.close()

    def get_stats(self) -> dict:
        """获取统计"""
        conn = sqlite3.connect(str(self.db_path))
        try:
            total = conn.execute("SELECT COUNT(*) FROM debate_memory").fetchone()[0]
            positive = conn.execute("SELECT COUNT(*) FROM debate_memory WHERE is_positive=1").fetchone()[0]
        except Exception:
            total, positive = 0, 0
        conn.close()
        return {"total": total, "positive": positive, "negative": total - positive}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="记忆召回工具")
    parser.add_argument("action", choices=["retrieve", "store", "stats"])
    parser.add_argument("--symbol", "-s", help="品种")
    parser.add_argument("--direction", "-d", help="方向")
    parser.add_argument("--confidence", "-c", type=float, default=0.5, help="置信度")
    parser.add_argument("--profitable", "-p", action="store_true", help="是否盈利")
    args = parser.parse_args()

    retriever = MemoryRetriever()
    if args.action == "store":
        retriever.store_debate_result(args.symbol or "?", args.direction or "?", args.confidence, args.profitable)
        print("Stored")
    elif args.action == "stats":
        print(json.dumps(retriever.get_stats(), ensure_ascii=False, indent=2))
    else:
        results = retriever.retrieve(symbol=args.symbol or "")
        print(f"Retrieved {len(results)} results")


if __name__ == "__main__":
    main()
