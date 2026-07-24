"""检查 DuckDB 中 huishang 相关表的数据"""
import os
import sys

import duckdb

db = os.path.expanduser("~/.skills/futures_data.duckdb")
if not os.path.exists(db):
    print(f"DB not found at {db}")
    sys.exit(1)

con = duckdb.connect(db, read_only=True)

print("=== huishang_topics 表结构 ===")
for r in con.execute("PRAGMA table_info('huishang_topics')").fetchall():
    print(f"  {r}")

print()
print("=== huishang_data_points 表结构 ===")
for r in con.execute("PRAGMA table_info('huishang_data_points')").fetchall():
    print(f"  {r}")

print()
print(f"topics 总数: {con.execute('SELECT count(*) FROM huishang_topics').fetchone()[0]}")
print(f"data_points 总数: {con.execute('SELECT count(*) FROM huishang_data_points').fetchone()[0]}")

print()
print("=== topics 的 updated_at 分布 ===")
print(con.execute("SELECT updated_at::VARCHAR, cnt FROM (SELECT updated_at, count(*) cnt FROM huishang_topics GROUP BY updated_at ORDER BY updated_at DESC) LIMIT 10").fetchdf().to_string())

print()
print("=== 前5个 topic ===")
print(con.execute("SELECT id, name, updated_at FROM huishang_topics ORDER BY id LIMIT 5").fetchdf().to_string())

print()
print("=== 最后5个 topic ===")
print(con.execute("SELECT id, name, updated_at FROM huishang_topics ORDER BY id DESC LIMIT 5").fetchdf().to_string())

print()
print("=== data_points 的 date_label 样本 ===")
rows = con.execute("SELECT topic_id, series_name, left(date_label,20) dt, value FROM huishang_data_points LIMIT 15").fetchall()
for r in rows:
    print(f"  topic={r[0]} series={r[1]} date={r[2]} val={r[3]}")

print()
print("=== date_label 时间精度分析 ===")
print(con.execute("""
    SELECT 
        CASE 
            WHEN len(date_label) >= 10 THEN '日级(>=10chars)'
            WHEN len(date_label) >= 7 THEN '月级(7-9chars)'
            WHEN len(date_label) >= 4 THEN '年级(4-6chars)'
            ELSE '其他'
        END AS date_granularity,
        count(*) AS cnt,
        count(DISTINCT topic_id) AS topics
    FROM huishang_data_points 
    WHERE date_label IS NOT NULL
    GROUP BY 1
""").fetchdf().to_string())

print()
print("=== 不同 topic 的 date_label 格式示例 ===")
print(con.execute("""
    SELECT topic_id, 
           min(length(date_label)) min_len, 
           max(length(date_label)) max_len,
           min(date_label) first_date,
           max(date_label) last_date
    FROM huishang_data_points 
    GROUP BY topic_id 
    LIMIT 10
""").fetchdf().to_string())

con.close()
