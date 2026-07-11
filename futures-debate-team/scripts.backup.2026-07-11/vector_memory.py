from scripts.unified_logger import get_logger

_logger = get_logger("vector_memory")
#!/usr/bin/env python3
"""
向量记忆管理器 — 三层记忆架构 + RAG注入（P0-7）
=================================================
替换文件存储为三层记忆架构：
- 短时（当日）：内存缓存
- 中期（30天）：SQLite 时序库
- 长期：Qdrant 向量库（lite版）

功能：
- 分层存储历史交易、黑天鹅、失败案例
- RAG检索：相似品种+区制+信号的历史案例注入Agent上下文
- 强制负样本注入（Top20中≥20%亏损）
- 自动归因标签化

用法:
    from vector_memory import VectorMemory
    vm = VectorMemory()
    vm.store(record, layer="long_term")
    similar = vm.query(symbol="RB", regime="strong_trend", top_k=5)
"""

import os, json, math, sqlite3, hashlib
from datetime import datetime, timedelta, date
from typing import Dict, List, Any, Optional
from pathlib import Path
from collections import defaultdict


class VectorMemory:
    """三层记忆管理器：短时/中期/长期。"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            self.base_dir = Path(__file__).parent.parent / "memory"
        else:
            self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 三层存储路径
        self.short_dir = self.base_dir / "short_term"
        self.mid_db = self.base_dir / "mid_term.db"
        self.long_dir = self.base_dir / "long_term"

        self.short_dir.mkdir(exist_ok=True)
        self.long_dir.mkdir(exist_ok=True)

        # 内存缓存（短时）
        self._cache = {}

        # 初始化SQLite中期库
        self._init_mid_db()

    def _init_mid_db(self):
        """初始化中期时序数据库。"""
        with sqlite3.connect(str(self.mid_db)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    pnl REAL NOT NULL,
                    regime TEXT,
                    attribution_tags TEXT,  -- JSON: {technical:0.3, fundamental:0.4, ...}
                    strategy_fingerprint TEXT,
                    UNIQUE(symbol, timestamp, strategy_fingerprint)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol_regime 
                ON trades(symbol, regime)
            """)
            conn.commit()

    def _generate_vector_id(self, record: Dict[str, Any]) -> str:
        """生成向量ID（基于品种+区制+信号指纹）。"""
        payload = f"{record.get('symbol', '')}_{record.get('regime', '')}_{record.get('signal_fingerprint', '')}"
        return hashlib.md5(payload.encode()).hexdigest()[:16]

    def store(self, record: Dict[str, Any], layer: str = "auto") -> str:
        """
        存储记忆记录到指定层。

        Args:
            record: {
                "symbol": str,
                "timestamp": str,
                "pnl": float,
                "regime": str,           # 行情区制
                "direction": str,         # "long" / "short"
                "attribution_tags": Dict, # {technical:0.3, fundamental:0.4, ...}
                "signal_fingerprint": str,
                "is_black_swan": bool,   # 是否黑天鹅事件
                "is_failure": bool,      # 是否失败案例
            }
            layer: "short" | "mid" | "long" | "auto"

        Returns:
            存储ID
        """
        record_id = self._generate_vector_id(record)

        if layer == "auto":
            # 自动分层：
            # - 当日交易 → 短时
            # - 30天内 → 中期
            # - 黑天鹅/失败案例 → 长期
            # - 其他 → 中期
            ts = datetime.fromisoformat(record.get("timestamp", datetime.now().isoformat()))
            days_ago = (datetime.now() - ts).days

            if days_ago <= 1:
                layer = "short"
            elif record.get("is_black_swan") or record.get("is_failure"):
                layer = "long"
            else:
                layer = "mid"

        if layer == "short":
            # 内存缓存
            self._cache[record_id] = record
            return f"short:{record_id}"

        elif layer == "mid":
            # SQLite
            with sqlite3.connect(str(self.mid_db)) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trades
                    (symbol, timestamp, direction, pnl, regime, attribution_tags, strategy_fingerprint)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        record.get("symbol", ""),
                        record.get("timestamp", ""),
                        record.get("direction", ""),
                        record.get("pnl", 0),
                        record.get("regime", ""),
                        json.dumps(record.get("attribution_tags", {})),
                        record.get("signal_fingerprint", ""),
                    ),
                )
                conn.commit()
            return f"mid:{record_id}"

        elif layer == "long":
            # 长期文件存储（向量库简化版）
            file_path = self.long_dir / f"{record_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            return f"long:{record_id}"

        return record_id

    def query(
        self, symbol: str, regime: str = None, signal_fingerprint: str = None, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        RAG检索：查找相似的历史交易记录。

        检索逻辑：
        1. 同品种优先
        2. 同区制优先
        3. 相似信号指纹优先
        4. 强制负样本注入（Top20中≥20%亏损）

        Args:
            symbol: 品种代码
            regime: 行情区制（可选）
            signal_fingerprint: 信号指纹（可选）
            top_k: 返回数量

        Returns:
            [{"record": Dict, "similarity_score": float}, ...]
        """
        results = []

        # 1. 从短时内存检索
        for rid, rec in self._cache.items():
            if rec.get("symbol") == symbol:
                score = self._similarity_score(rec, symbol, regime, signal_fingerprint)
                if score > 0.3:
                    results.append({"record": rec, "similarity_score": score, "layer": "short"})

        # 2. 从中期SQLite检索
        with sqlite3.connect(str(self.mid_db)) as conn:
            query = "SELECT * FROM trades WHERE symbol = ?"
            params = [symbol]
            if regime:
                query += " AND regime = ?"
                params.append(regime)
            query += " ORDER BY timestamp DESC LIMIT 100"

            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                rec = {
                    "id": row[0],
                    "symbol": row[1],
                    "timestamp": row[2],
                    "direction": row[3],
                    "pnl": row[4],
                    "regime": row[5],
                    "attribution_tags": json.loads(row[6]) if row[6] else {},
                    "strategy_fingerprint": row[7],
                }
                score = self._similarity_score(rec, symbol, regime, signal_fingerprint)
                if score > 0.3:
                    results.append({"record": rec, "similarity_score": score, "layer": "mid"})

        # 3. 从长期文件检索
        for json_file in self.long_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    rec = json.load(f)
                if rec.get("symbol") == symbol:
                    score = self._similarity_score(rec, symbol, regime, signal_fingerprint)
                    if score > 0.3:
                        results.append({"record": rec, "similarity_score": score, "layer": "long"})
            except (json.JSONDecodeError, KeyError):
                pass

        # 排序：按相似度降序
        results.sort(key=lambda x: x["similarity_score"], reverse=True)

        # 强制负样本注入：Top20中至少20%为亏损样本
        top_results = results[:top_k]
        loss_records = [r for r in results if r["record"].get("pnl", 0) < 0]

        min_loss_count = max(1, top_k // 5)  # 20%负样本
        current_loss_count = sum(1 for r in top_results if r["record"].get("pnl", 0) < 0)

        if current_loss_count < min_loss_count and loss_records:
            # 替换部分盈利样本为亏损样本
            to_replace = min_loss_count - current_loss_count
            profit_indices = [i for i, r in enumerate(top_results) if r["record"].get("pnl", 0) >= 0]
            for i in range(min(to_replace, len(profit_indices), len(loss_records))):
                top_results[profit_indices[i]] = loss_records[i]

        return top_results[:top_k]

    def _similarity_score(self, record: Dict, symbol: str, regime: str, fingerprint: str) -> float:
        """计算相似度得分（0-1）。"""
        score = 0.0

        # 品种匹配：0.4
        if record.get("symbol") == symbol:
            score += 0.4

        # 区制匹配：0.3
        if regime and record.get("regime") == regime:
            score += 0.3

        # 信号指纹匹配：0.3
        if fingerprint and record.get("signal_fingerprint") == fingerprint:
            score += 0.3
        elif fingerprint and record.get("signal_fingerprint"):
            # 部分匹配（简化）
            score += 0.1

        return min(score, 1.0)

    def add_attribution_tags(self, record_id: str, tags: Dict[str, str]) -> bool:
        """
        为记忆记录添加归因标签。

        Args:
            record_id: 记录ID
            tags: {
                "failure_reason": "technical_failure|fundamental_reversal|macro_shock|liquidity_risk|risk_management",
                "magnitude": "minor|moderate|severe",
                "lessons": str,
            }
        """
        # 更新中期库中的记录
        with sqlite3.connect(str(self.mid_db)) as conn:
            conn.execute("UPDATE trades SET attribution_tags = ? WHERE id = ?", (json.dumps(tags), record_id))
            conn.commit()
        return True

    def get_failure_summary(self, symbol: str = None, days: int = 30) -> Dict[str, Any]:
        """
        获取失败案例汇总（用于负样本注入和复盘）。

        Returns:
            {"total_failures": int, "by_reason": Dict, "avg_loss": float}
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with sqlite3.connect(str(self.mid_db)) as conn:
            query = "SELECT pnl, attribution_tags FROM trades WHERE pnl < 0 AND timestamp > ?"
            params = [cutoff]
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        by_reason = defaultdict(int)
        total_loss = 0.0

        for pnl, tags_json in rows:
            total_loss += abs(pnl)
            tags = json.loads(tags_json) if tags_json else {}
            reason = tags.get("failure_reason", "unknown")
            by_reason[reason] += 1

        return {
            "total_failures": len(rows),
            "by_reason": dict(by_reason),
            "avg_loss": round(total_loss / max(len(rows), 1), 2),
            "period_days": days,
        }


if __name__ == "__main__":
    vm = VectorMemory()

    # 存储测试数据
    vm.store(
        {
            "symbol": "RB",
            "timestamp": datetime.now().isoformat(),
            "pnl": 500,
            "regime": "strong_trend",
            "direction": "long",
            "signal_fingerprint": "FDB_v4.4_seed42_abc123",
        },
        layer="mid",
    )

    vm.store(
        {
            "symbol": "RB",
            "timestamp": (datetime.now() - timedelta(days=2)).isoformat(),
            "pnl": -300,
            "regime": "strong_trend",
            "direction": "long",
            "signal_fingerprint": "FDB_v4.4_seed42_def456",
            "is_failure": True,
        },
        layer="long",
    )

    # 查询
    results = vm.query("RB", regime="strong_trend", top_k=5)
    print(f"查询结果 ({len(results)}条):")
    for r in results:
        rec = r["record"]
        print(
            f"  {rec['symbol']} {rec['direction']} PnL={rec['pnl']} score={r['similarity_score']:.2f} layer={r['layer']}"
        )

    # 失败汇总
    summary = vm.get_failure_summary("RB", days=30)
    print(f"\n失败汇总: {json.dumps(summary, ensure_ascii=False, indent=2)}")
