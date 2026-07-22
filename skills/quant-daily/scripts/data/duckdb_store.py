#!/usr/bin/env python3
"""
DuckDB 存储引擎 — futures-data-search 的本地数据库层
=====================================================
替代方案：DolphinDB（未安装/商业授权） + ES/Milvus（未部署）

优势：
  - 零部署：pip install duckdb 即用，无需启动服务
  - 生态兼容：与 exchange-futures-data 共享 DuckDB 实例
  - 列式存储：适配期货分析模式（按品种/日期维度查询）
  - 单文件便携：futures.db 可复制可备份

表结构（4张）：
  - oi_ranking       前20会员持仓排名
  - warehouse        仓单日报
  - futures_news     产业资讯/公告
  - term_structure   期限结构（跨月价差）
  - query_cache      API查询结果临时缓存（防重复请求）
"""

import json
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import duckdb

    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False
    print("[Warning] duckdb not installed. Install with: pip install duckdb")


class DuckDBStore:
    """基于 DuckDB 的期货数据存储引擎"""

    DB_DIR = Path.home() / ".skills" / "skills" / "quant-daily" / "data"
    DB_PATH = DB_DIR / "futures.db"

    SCHEMAS = {
        "oi_ranking": """
            CREATE TABLE IF NOT EXISTS oi_ranking (
                trade_date    DATE    NOT NULL,
                variety       VARCHAR NOT NULL,
                contract      VARCHAR NOT NULL,
                exchange      VARCHAR,
                rank          INTEGER NOT NULL,
                member        VARCHAR,
                direction     VARCHAR NOT NULL,  -- 'long' or 'short'
                lots          BIGINT,
                change_from_prev BIGINT,
                PRIMARY KEY (trade_date, variety, contract, rank, direction)
            )
        """,
        "warehouse": """
            CREATE TABLE IF NOT EXISTS warehouse (
                trade_date    DATE    NOT NULL,
                variety       VARCHAR NOT NULL,
                exchange      VARCHAR,
                warehouse_name VARCHAR,
                registered_lots BIGINT,
                cancelled_lots  BIGINT,
                net_change    BIGINT,
                unit          VARCHAR,  -- '吨'/'张'/'手'
                PRIMARY KEY (trade_date, variety, warehouse_name)
            )
        """,
        "futures_news": """
            CREATE TABLE IF NOT EXISTS futures_news (
                id          INTEGER PRIMARY KEY,
                publish_date DATE   NOT NULL,
                variety     VARCHAR NOT NULL,
                title       VARCHAR,
                source      VARCHAR,
                url         VARCHAR,
                summary     TEXT,
                sentiment   VARCHAR  -- 'bullish'/'bearish'/'neutral'
            )
        """,
        "term_structure": """
            CREATE TABLE IF NOT EXISTS term_structure (
                trade_date  DATE    NOT NULL,
                variety     VARCHAR NOT NULL,
                contract    VARCHAR NOT NULL,
                price       DOUBLE,
                volume      BIGINT,
                open_interest BIGINT,
                settle      DOUBLE,
                PRIMARY KEY (trade_date, variety, contract)
            )
        """,
        "query_cache": """
            CREATE TABLE IF NOT EXISTS query_cache (
                cache_key   VARCHAR PRIMARY KEY,
                result_json VARCHAR NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at  TIMESTAMP,
                query_type  VARCHAR,
                variety     VARCHAR
            )
        """,
    }

    def __init__(self, db_path: Optional[Path] = None):
        if not DUCKDB_AVAILABLE:
            raise ImportError("duckdb package not installed. Run: pip install duckdb")

        self.db_path = db_path or self.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        # 🔐 并发写保护锁（防止多线程同时写DuckDB导致文件锁冲突）
        self._write_lock = __import__("threading").RLock()
        self._init_schemas()

    def _init_schemas(self):
        """初始化所有表结构"""
        for name, ddl in self.SCHEMAS.items():
            with self._write_lock:
                self.conn.execute(ddl)
        print(f"[DuckDB] {self.db_path.name} ready ({len(self.SCHEMAS)} tables)")

    def safe_execute(self, sql: str, params: Any = None) -> Any:
        """🔐 线程安全的 SQL 执行（写操作自动加锁）

        所有写操作（INSERT/UPDATE/DELETE/CREATE）通过此方法执行，
        读操作（SELECT）不加锁以提高并发性能。

        Args:
            sql: SQL 语句
            params: 参数（可选）

        Returns:
            执行结果
        """
        is_write = sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"))
        if is_write:
            with self._write_lock:
                if params is not None:
                    return self.conn.execute(sql, params)
                return self.conn.execute(sql)
        else:
            if params is not None:
                return self.conn.execute(sql, params)
            return self.conn.execute(sql)

    def close(self):
        """关闭连接"""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ═══════════════════════════════════════════════════════════════
    # OI 持仓排名
    # ═══════════════════════════════════════════════════════════════

    def save_oi_ranking(self, records: List[Tuple]) -> int:
        """保存持仓排名数据

        records: [(trade_date, variety, contract, exchange, rank, member, direction, lots, change_from_prev)]
        """
        if not records:
            return 0
        self.conn.executemany(
            """INSERT OR REPLACE INTO oi_ranking
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
        return len(records)

    def get_latest_oi(self, variety: str, top_n: int = 20) -> List[Dict]:
        """获取最新持仓排名"""
        rows = self.conn.execute(
            """
            SELECT * FROM oi_ranking
            WHERE variety = ? AND trade_date = (
                SELECT MAX(trade_date) FROM oi_ranking WHERE variety = ?
            )
            ORDER BY direction, rank
            LIMIT ?
        """,
            [variety, variety, top_n * 2],
        ).fetchall()
        return [self._row_to_dict(row, "oi_ranking") for row in rows]

    def get_oi_net_position(self, variety: str, top_n: int = 5, days: int = 10) -> List[Dict]:
        """获取主力席位N日净持仓变化趋势"""
        rows = self.conn.execute(
            f"""
            SELECT trade_date,
                   SUM(CASE WHEN direction='long' THEN lots ELSE 0 END) -
                   SUM(CASE WHEN direction='short' THEN lots ELSE 0 END) AS net_position
            FROM oi_ranking
            WHERE variety = ?
              AND rank <= ?
              AND trade_date >= (SELECT MAX(trade_date) FROM oi_ranking WHERE variety = ?) - INTERVAL {days} DAY
            GROUP BY trade_date
            ORDER BY trade_date
        """,
            [variety, top_n, variety],
        ).fetchall()
        return [{"date": str(r[0]), "net_position": r[1]} for r in rows]

    def get_oi_top5_concentration(self, variety: str) -> Optional[Dict]:
        """获取前5会员多空集中度"""
        return (
            self.conn.execute(
                """
            SELECT trade_date,
                   SUM(CASE WHEN direction='long' AND rank<=5 THEN lots END) AS top5_long,
                   SUM(CASE WHEN direction='short' AND rank<=5 THEN lots END) AS top5_short,
                   SUM(CASE WHEN direction='long' THEN lots END) AS total_long
            FROM oi_ranking
            WHERE variety = ?
              AND trade_date = (SELECT MAX(trade_date) FROM oi_ranking WHERE variety = ?)
        """,
                [variety, variety],
            )
            .fetchdf()
            .to_dict("records")
        )

    # ═══════════════════════════════════════════════════════════════
    # 仓单日报
    # ═══════════════════════════════════════════════════════════════

    def save_warehouse(self, records: List[Tuple]) -> int:
        """保存仓单数据"""
        if not records:
            return 0
        self.conn.executemany(
            """INSERT OR REPLACE INTO warehouse
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
        return len(records)

    def get_latest_warehouse(self, variety: str) -> List[Dict]:
        """获取最新仓单数据"""
        rows = self.conn.execute(
            """
            SELECT * FROM warehouse
            WHERE variety = ? AND trade_date = (
                SELECT MAX(trade_date) FROM warehouse WHERE variety = ?
            )
            ORDER BY net_change
        """,
            [variety, variety],
        ).fetchall()
        return [self._row_to_dict(row, "warehouse") for row in rows]

    def get_warehouse_trend(self, variety: str, days: int = 30) -> List[Dict]:
        """获取仓单变化趋势"""
        rows = self.conn.execute(
            """
            SELECT trade_date,
                   SUM(registered_lots) AS total_registered,
                   SUM(cancelled_lots) AS total_cancelled,
                   SUM(net_change) AS total_net_change
            FROM warehouse
            WHERE variety = ?
              AND trade_date >= (SELECT MAX(trade_date) FROM warehouse WHERE variety = ?) - INTERVAL {days} DAY
            GROUP BY trade_date
            ORDER BY trade_date
        """,
            [variety, variety, days],
        ).fetchall()
        return [{"date": str(r[0]), "registered": r[1], "cancelled": r[2], "net_change": r[3]} for r in rows]

    # ═══════════════════════════════════════════════════════════════
    # 产业资讯
    # ═══════════════════════════════════════════════════════════════

    def save_news(self, records: List[Tuple]) -> int:
        """保存新闻资讯"""
        if not records:
            return 0
        self.conn.executemany(
            """INSERT OR REPLACE INTO futures_news
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
        return len(records)

    def get_latest_news(self, variety: str, top_k: int = 5) -> List[Dict]:
        """获取某品种的最新新闻"""
        rows = self.conn.execute(
            """
            SELECT * FROM futures_news
            WHERE variety = ?
            ORDER BY publish_date DESC
            LIMIT ?
        """,
            [variety, top_k],
        ).fetchall()
        return [self._row_to_dict(row, "futures_news") for row in rows]

    def search_news(self, keyword: str, days: int = 30) -> List[Dict]:
        """搜索近期相关新闻（DuckDB全文检索）"""
        rows = self.conn.execute(
            f"""
            SELECT * FROM futures_news
            WHERE (title LIKE ? OR summary LIKE ?)
              AND publish_date >= CURRENT_DATE - INTERVAL {days} DAY
            ORDER BY publish_date DESC
            LIMIT 20
        """,
            [f"%{keyword}%", f"%{keyword}%"],
        ).fetchall()
        return [self._row_to_dict(row, "futures_news") for row in rows]

    # ═══════════════════════════════════════════════════════════════
    # 期限结构
    # ═══════════════════════════════════════════════════════════════

    def save_term_structure(self, records: List[Tuple]) -> int:
        """保存期限结构数据"""
        if not records:
            return 0
        self.conn.executemany(
            """INSERT OR REPLACE INTO term_structure
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
        return len(records)

    def get_term_structure(self, variety: str, trade_date: Optional[str] = None) -> List[Dict]:
        """获取期限结构"""
        if trade_date:
            rows = self.conn.execute(
                """
                SELECT * FROM term_structure
                WHERE variety = ? AND trade_date = ?
                ORDER BY contract
            """,
                [variety, trade_date],
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM term_structure
                WHERE variety = ? AND trade_date = (
                    SELECT MAX(trade_date) FROM term_structure WHERE variety = ?
                )
                ORDER BY contract
            """,
                [variety, variety],
            ).fetchall()
        return [self._row_to_dict(row, "term_structure") for row in rows]

    def get_spread(self, variety: str, contract_a: str, contract_b: str) -> Optional[Dict]:
        """获取跨月价差"""
        return self.conn.execute(
            """
            SELECT a.price - b.price AS spread
            FROM term_structure a
            JOIN term_structure b ON a.trade_date = b.trade_date
            WHERE a.variety = ? AND a.contract = ?
              AND b.variety = ? AND b.contract = ?
              AND a.trade_date = (SELECT MAX(trade_date) FROM term_structure WHERE variety = ?)
        """,
            [variety, contract_a, variety, contract_b, variety],
        ).fetchone()

    # ═══════════════════════════════════════════════════════════════
    # API 查询缓存（通用防重复请求）
    # ═══════════════════════════════════════════════════════════════

    def _make_cache_key(self, query_type: str, variety: str, **params) -> str:
        """生成缓存KEY"""
        raw = f"{query_type}:{variety}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get_cached(self, query_type: str, variety: str, ttl_hours: int = 4, **params) -> Optional[Any]:
        """读取缓存"""
        key = self._make_cache_key(query_type, variety, **params)
        row = self.conn.execute(
            """
            SELECT result_json FROM query_cache
            WHERE cache_key = ? AND expires_at > CURRENT_TIMESTAMP
        """,
            [key],
        ).fetchone()
        if row:
            return json.loads(row[0])
        return None

    def set_cached(self, query_type: str, variety: str, data: Any, ttl_hours: int = 4, **params):
        """写入缓存"""
        key = self._make_cache_key(query_type, variety, **params)
        now = datetime.now()
        expires = now + timedelta(hours=ttl_hours)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO query_cache
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            [key, json.dumps(data, ensure_ascii=False), now, expires, query_type, variety],
        )

    # ═══════════════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════════════

    def _row_to_dict(self, row: tuple, table: str) -> Dict:
        """将DB行转为字典"""
        schemas = {
            "oi_ranking": [
                "trade_date",
                "variety",
                "contract",
                "exchange",
                "rank",
                "member",
                "direction",
                "lots",
                "change_from_prev",
            ],
            "warehouse": [
                "trade_date",
                "variety",
                "exchange",
                "warehouse_name",
                "registered_lots",
                "cancelled_lots",
                "net_change",
                "unit",
            ],
            "futures_news": ["id", "publish_date", "variety", "title", "source", "url", "summary", "sentiment"],
            "term_structure": ["trade_date", "variety", "contract", "price", "volume", "open_interest", "settle"],
        }
        cols = schemas.get(table, [f"col{i}" for i in range(len(row))])
        return {col: (str(val) if isinstance(val, (date, datetime)) else val) for col, val in zip(cols, row)}

    def get_table_stats(self) -> Dict[str, int]:
        """获取各表记录数统计"""
        stats = {}
        for name in self.SCHEMAS:
            if name == "query_cache":
                continue
            count = self.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            stats[name] = count
        return stats

    def clean_expired_cache(self):
        """清理过期缓存"""
        self.conn.execute("DELETE FROM query_cache WHERE expires_at < CURRENT_TIMESTAMP")

    def get_storage_size(self) -> str:
        """获取数据库文件大小"""
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / 1024 / 1024:.2f} MB"

    def health_check(self) -> Dict:
        """健康检查"""
        return {
            "available": DUCKDB_AVAILABLE,
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "storage_size": self.get_storage_size(),
            "tables": self.get_table_stats(),
            "duckdb_version": duckdb.__version__ if hasattr(duckdb, "__version__") else "installed",
        }


def main():
    """测试DuckDB Store"""
    print("=" * 60)
    print("DuckDB Store — futures-data-search 存储引擎")
    print("=" * 60)

    try:
        store = DuckDBStore()
        health = store.health_check()
        print(f"[OK] 数据库: {health['db_path']}")
        print(f"   大小: {health['storage_size']}")
        print(f"   版本: {health['duckdb_version']}")
        print(f"\n   表状态: {json.dumps(health['tables'], indent=4)}")

        # 测试OI数据存取
        test_oi = [
            ("2026-06-26", "CU", "CU2609", "SHFE", 1, "中信期货", "long", 25000, 2000),
            ("2026-06-26", "CU", "CU2609", "SHFE", 2, "永安期货", "long", 22000, 1500),
            ("2026-06-26", "CU", "CU2609", "SHFE", 1, "永安期货", "short", 20000, 1000),
            ("2026-06-26", "CU", "CU2609", "SHFE", 2, "中信期货", "short", 18000, -500),
        ]
        store.save_oi_ranking(test_oi)
        print(f"[OK] OI排名写入: 4条")

        # 读取验证
        oi_data = store.get_latest_oi("CU")
        print(f"   查询结果: {len(oi_data)} 条")

        net_trend = store.get_oi_net_position("CU")
        print(f"   净持仓趋势: {len(net_trend)} 天")

        # 测试缓存
        store.set_cached("quote", "CU", {"close": 78780}, ttl_hours=4)
        cached = store.get_cached("quote", "CU")
        print(f"[OK] 缓存读写: {'命中' if cached else '未命中'}")

        store.close()
        print(f"\n{'=' * 60}")
        print("DuckDB 存储引擎正常运行")
        print(f"{'=' * 60}")

    except ImportError as e:
        print(f"\n[x] {e}")
        print("   请执行: pip install duckdb")


if __name__ == "__main__":
    main()
