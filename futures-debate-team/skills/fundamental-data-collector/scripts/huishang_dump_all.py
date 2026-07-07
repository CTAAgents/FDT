"""
批量下载恒生数据中心全部数据到DuckDB
"""
import requests, json, time, sys, os
from datetime import datetime

requests.packages.urllib3.disable_warnings()

TOKEN = "eyJhbGciOiJIUzUxMiJ9.eyJjaGFubmVsIjoiMyIsImV4cCI6MTc4Mzk5MjUwMiwidXNlcklkIjoiTDZjTzdCVEFPdlBBTXU1MGhhMDgvZz09IiwidXVpZCI6IjEwNzM1IiwicGhvbmVObyI6IktZZ29OWXMxN2cxR2tZUWZGY3JSL3c9PSJ9.DNwnNU43g3S_Z36EBO9uFznn6nZW9irrwXmyjH_aTh5nHtAqqZk4pjCpe69KCmi39mO6J3CI-J8nPZOYittRtA"
BASE = "https://hyzx.hsqh.net:5443"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

# Progress tracking file
PROGRESS_FILE = "huishang_cache/dump_progress.json"
TOPICS_CACHE = "huishang_cache/topics_list.json"

import pathlib
CACHE_DIR = pathlib.Path("huishang_cache")
CACHE_DIR.mkdir(exist_ok=True)


def load_progress():
    if pathlib.Path(PROGRESS_FILE).exists():
        return json.loads(pathlib.Path(PROGRESS_FILE).read_text(encoding="utf-8"))
    return {"page": 0, "downloaded_ids": [], "total_topics": 0}


def save_progress(p):
    pathlib.Path(PROGRESS_FILE).write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")


# ── Step 1: Scan all topics ──
progress = load_progress()

if not pathlib.Path(TOPICS_CACHE).exists():
    print("=== Step 1: Scanning all topics ===")
    all_topics = []
    page = 1
    while True:
        try:
            r = requests.post(
                f"{BASE}/api/topicCharts/list",
                headers=HEADERS,
                json={"pageNum": page, "pageSize": 10},
                timeout=15, verify=False,
            )
            d = r.json()
            rows = d.get("rows", [])
            if not rows:
                break
            all_topics.extend(rows)
            total = d.get("total", 0)
            print(f"  Page {page}: got {len(rows)} topics (total so far: {len(all_topics)}/{total})")
            page += 1
            if len(all_topics) >= total:
                break
            time.sleep(0.3)  # Rate limit
        except Exception as e:
            print(f"  Error at page {page}: {e}")
            time.sleep(2)
            continue

    print(f"\nTotal topics collected: {len(all_topics)}")
    pathlib.Path(TOPICS_CACHE).write_text(
        json.dumps(all_topics, ensure_ascii=False), encoding="utf-8"
    )
    progress["total_topics"] = len(all_topics)
    save_progress(progress)
else:
    all_topics = json.loads(pathlib.Path(TOPICS_CACHE).read_text(encoding="utf-8"))
    print(f"=== Loaded {len(all_topics)} topics from cache ===")

# ── Step 2: Download details for each topic → DuckDB ──
print("\n=== Step 2: Downloading topic details ===")
duckdb_available = False
try:
    import duckdb
    duckdb_available = True
except ImportError:
    pass

# Prepare DuckDB
if duckdb_available:
    DB_PATH = r"C:\Users\yangd\Documents\WorkBuddy\futures_data.duckdb"
    con = duckdb.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS huishang_topics (
            id INTEGER PRIMARY KEY,
            name VARCHAR,
            query_ids VARCHAR,
            charts_type VARCHAR,
            source VARCHAR,
            lib_name VARCHAR,
            lib_id VARCHAR,
            options_json TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS huishang_data_points (
            topic_id INTEGER,
            series_name VARCHAR,
            date_label VARCHAR,
            value DOUBLE,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # Check existing IDs
    existing = set(r[0] for r in con.execute("SELECT id FROM huishang_topics").fetchall())
    print(f"Already in DB: {len(existing)} topics")
else:
    existing = set(progress.get("downloaded_ids", []))
    print(f"Already downloaded: {len(existing)} topics (no DuckDB)")

downloaded_ids = existing.copy()
failed_ids = []

for i, topic in enumerate(all_topics):
    tid = topic["id"]
    if tid in downloaded_ids:
        continue

    try:
        r = requests.get(
            f"{BASE}/api/topicCharts/{tid}",
            headers=HEADERS,
            timeout=15, verify=False,
        )
        detail = r.json().get("topicChart")
        if not detail:
            print(f"  [{i+1}/{len(all_topics)}] ID={tid} {topic.get('name','')[:20]} → no detail")
            failed_ids.append(tid)
            time.sleep(0.2)
            continue

        # Parse options for data points
        opts_str = detail.get("options", "{}")
        data_points = []
        try:
            opts = json.loads(opts_str) if isinstance(opts_str, str) else opts_str
            series = opts.get("series", [])
            xaxis = opts.get("xAxis", [{}])
            xdata = xaxis[0].get("data", []) if xaxis else []
            for s in series:
                sname = s.get("name", "")
                sdata = s.get("data", [])
                for idx, val in enumerate(sdata):
                    if val is not None:
                        xval = xdata[idx] if idx < len(xdata) else f"i{idx}"
                        data_points.append({
                            "topic_id": tid,
                            "series_name": sname,
                            "date_label": xval,
                            "value": float(val),
                        })
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        if duckdb_available:
            # Upsert topic
            con.execute("DELETE FROM huishang_topics WHERE id = ?", [tid])
            con.execute(
                "INSERT INTO huishang_topics (id, name, query_ids, charts_type, source, lib_name, lib_id, options_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [tid, detail.get("name", ""), detail.get("queryIds", ""),
                 detail.get("chartsType", ""), detail.get("source", ""),
                 detail.get("libName", ""), detail.get("libId", ""), opts_str]
            )
            # Upsert data points
            con.execute("DELETE FROM huishang_data_points WHERE topic_id = ?", [tid])
            if data_points:
                con.executemany(
                    "INSERT INTO huishang_data_points (topic_id, series_name, date_label, value) VALUES (?, ?, ?, ?)",
                    [(dp["topic_id"], dp["series_name"], dp["date_label"], dp["value"]) for dp in data_points]
                )
        else:
            # JSON fallback
            out = CACHE_DIR / f"detail_{tid}.json"
            out.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")

        downloaded_ids.add(tid)
        progress["downloaded_ids"] = list(downloaded_ids)

        if (i + 1) % 20 == 0:
            save_progress(progress)
            pts = f", {len(data_points)} data points" if data_points else ", no data"
            print(f"  [{i+1}/{len(all_topics)}] ID={tid} {topic.get('name','')[:25]} → OK{pts}")

        time.sleep(0.15)  # Rate limit

    except Exception as e:
        print(f"  [{i+1}/{len(all_topics)}] ID={tid} ERROR: {e}")
        failed_ids.append(tid)
        time.sleep(1)
        continue

# Final save
progress["downloaded_ids"] = list(downloaded_ids)
progress["failed_ids"] = failed_ids
progress["completed_at"] = datetime.now().isoformat()
save_progress(progress)

# Summary
print(f"\n=== Done ===")
print(f"Success: {len(downloaded_ids)} topics")
print(f"Failed: {len(failed_ids)} topics")
if duckdb_available:
    counts = con.execute("SELECT count(*) FROM huishang_topics").fetchone()[0]
    pts = con.execute("SELECT count(*) FROM huishang_data_points").fetchone()[0]
    print(f"DuckDB: {counts} topics, {pts} data points")
    con.close()
