"""
Eval 结果持久化 — SQLite 存储 + 趋势查询。

表结构:
    eval_results 表存储每次运行记录。
    eval_cache_manifest 表存储缓存清单。

用法:
    store = EvalStore()
    store.save(result)
    trends = store.trend("runtime.quality_inspector.p3_5", last=30)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fdt_eval.core.base import EvalResult, EvalMetric

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / ".eval_cache" / "eval_store.db"


class EvalStore:
    """Eval 结果 SQLite 存储。线程安全。"""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = Path(db_path or DEFAULT_DB_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    # ── 连接管理 ──

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS eval_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id     TEXT NOT NULL,
                trace_id    TEXT NOT NULL,
                stage       TEXT NOT NULL,
                status      TEXT NOT NULL,
                score       REAL NOT NULL,
                metrics     TEXT,
                detail      TEXT,
                duration_ms REAL,
                cache_hit   INTEGER DEFAULT 0,
                version     TEXT DEFAULT '1.0',
                profile     TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_case_trace ON eval_results(case_id, trace_id);
            CREATE INDEX IF NOT EXISTS idx_created ON eval_results(created_at);
            CREATE INDEX IF NOT EXISTS idx_stage_status ON eval_results(stage, status);
        """)
        self._conn.commit()

    # ── 写入 ──

    def save(self, result: EvalResult, profile: str = "") -> int:
        """保存一条 EvalResult，返回 id。"""
        metrics_json = json.dumps(
            [{"name": m.name, "value": m.value, "threshold": m.threshold, "unit": m.unit}
             for m in (result.metrics or [])],
            ensure_ascii=False,
        )
        cur = self._conn.execute(
            """INSERT INTO eval_results
               (case_id, trace_id, stage, status, score, metrics, detail,
                duration_ms, cache_hit, version, profile)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (result.case_id, result.trace_id, result.stage, result.status,
             result.score, metrics_json, result.detail,
             result.duration_ms, int(result.cache_hit), result.version, profile),
        )
        self._conn.commit()
        return cur.lastrowid

    # ── 趋势查询 ──

    def trend(self, case_id: str, last: int = 30) -> list[dict[str, Any]]:
        """查询某个 case 最近 N 次运行记录。

        Returns:
            [{"created_at": str, "status": str, "score": float, "detail": str}, ...]
        """
        rows = self._conn.execute(
            """SELECT created_at, status, score, detail, duration_ms, cache_hit
               FROM eval_results
               WHERE case_id = ?
               ORDER BY id DESC LIMIT ?""",
            (case_id, last),
        ).fetchall()
        return [dict(r) for r in rows]

    def trend_by_stage(self, stage: str, last_days: int = 7) -> list[dict[str, Any]]:
        """查询某个阶段最近 N 天的聚合数据。"""
        since = (datetime.now() - timedelta(days=last_days)).isoformat()
        rows = self._conn.execute(
            """SELECT case_id, status, COUNT(*) as cnt
               FROM eval_results
               WHERE stage = ? AND created_at >= ?
               GROUP BY case_id, status
               ORDER BY case_id""",
            (stage, since),
        ).fetchall()
        return [dict(r) for r in rows]

    def aggregate_score(self, last: int = 30) -> dict[str, Any]:
        """全引擎最近 N 次运行的聚合得分。"""
        rows = self._conn.execute(
            """SELECT stage, status, COUNT(*) as cnt
               FROM (SELECT stage, status FROM eval_results ORDER BY id DESC LIMIT ?)
               GROUP BY stage, status""",
            (last,),
        ).fetchall()
        total = sum(r["cnt"] for r in rows)
        passed = sum(r["cnt"] for r in rows if r["status"] == "PASS")
        return {
            "total": total,
            "passed": passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "breakdown": [dict(r) for r in rows],
        }

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
