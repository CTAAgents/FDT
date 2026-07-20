import os
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from fdt_pg.connection import PGConnection
from fdt_pg.schema import Base, OLAP_VIEWS
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


def deploy_schema():
    """部署 PostgreSQL Schema"""
    engine = PGConnection.get_engine()

    print("📦 部署 FDT PostgreSQL Schema...")
    print(f"   主机: {engine.url.host}:{engine.url.port}")
    print(f"   数据库: {engine.url.database}")

    Base.metadata.create_all(engine)
    print("✅ 14 个 OLTP 表创建完成")

    with engine.connect() as conn:
        for view_name, view_sql in OLAP_VIEWS.items():
            conn.execute(text(view_sql))
        conn.commit()
    print("✅ 3 个 OLAP 视图创建完成")

    print("\n🎉 Schema 部署完成!")
    return True


def migrate_json_to_pg():
    """从 JSON 文件迁移历史数据到 PostgreSQL"""
    memory_dir = Path(__file__).parent.parent / "memory"
    migrated = 0

    if not memory_dir.exists():
        print(f"⚠️  memory/ 目录不存在: {memory_dir}")
        return 0

    journal_path = memory_dir / "debate_journal.json"
    if journal_path.exists():
        print("\n📖 迁移 debate_journal.json...")
        try:
            with open(journal_path, 'r', encoding='utf-8') as f:
                journal = json.load(f)

            entries = journal.get("entries", [])
            print(f"   找到 {len(entries)} 条记录")
            migrated += len(entries)
        except Exception as e:
            print(f"   ⚠️  迁移失败: {e}")
    else:
        print("\nℹ️  debate_journal.json 不存在，跳过")

    followup_path = memory_dir / "execution_followup.json"
    if followup_path.exists():
        print("📖 迁移 execution_followup.json...")
        try:
            with open(followup_path, 'r', encoding='utf-8') as f:
                followup = json.load(f)

            records = followup.get("records", [])
            print(f"   找到 {len(records)} 条记录")
            migrated += len(records)
        except Exception as e:
            print(f"   ⚠️  迁移失败: {e}")
    else:
        print("ℹ️  execution_followup.json 不存在，跳过")

    agent_profiles_path = memory_dir / "agent_profiles.json"
    if agent_profiles_path.exists():
        print("📖 迁移 agent_profiles.json...")
        try:
            with open(agent_profiles_path, 'r', encoding='utf-8') as f:
                profiles = json.load(f)
            print(f"   找到 {len(profiles)} 个 Agent 配置")
        except Exception as e:
            print(f"   ⚠️  迁移失败: {e}")
    else:
        print("ℹ️  agent_profiles.json 不存在，跳过")

    print(f"\n📊 数据迁移完成，共处理 {migrated} 条记录")

    # TODO: 实现实际的 INSERT 写入逻辑
    # 当前仅打印找到的记录数，未写入 PostgreSQL
    # 需要从 fdt_pg/connection.py 导入 session_scope
    # 然后执行 INSERT INTO ... 语句
    logger.warning("migrate_json_to_pg() 当前仅打印不写入 — 待实现 INSERT 逻辑 (G74-⑤)")

    # G96: 实现 INSERT 写入逻辑
    from fdt_pg.connection import session_scope
    from fdt_pg.schema import (
        ScanSignals, DebateVerdicts, ExecutionFollowup,
        AgentProfiles, CalibrationStats, ValidationStats,
        LogEntries, SchedulerLogs,
    )
    from sqlalchemy import text

    # 迁移 debate_journal.json -> DebateVerdicts
    if journal_path.exists():
        try:
            with open(journal_path, 'r', encoding='utf-8') as f:
                journal = json.load(f)
            entries = journal.get("entries", [])
            with session_scope() as session:
                count = 0
                for entry in entries:
                    verdict = DebateVerdicts(
                        trace_id=entry.get("trace_id", ""),
                        symbol=entry.get("symbol", ""),
                        direction=entry.get("direction", ""),
                        confidence=entry.get("confidence", 0.0),
                        created_at=datetime.fromisoformat(entry.get("timestamp", datetime.now().isoformat())),
                    )
                    session.add(verdict)
                    count += 1
                    if count % 100 == 0:
                        session.flush()
                print(f"   ✅ 已写入 {count} 条辩论裁决到 PostgreSQL")
        except Exception as e:
            print(f"   ⚠️ debate_journal 迁移失败: {e}")

    # 迁移 execution_followup.json -> ExecutionFollowup
    if followup_path.exists():
        try:
            with open(followup_path, 'r', encoding='utf-8') as f:
                followup = json.load(f)
            records = followup.get("records", [])
            with session_scope() as session:
                count = 0
                for rec in records:
                    followup_rec = ExecutionFollowup(
                        trace_id=rec.get("trace_id", ""),
                        symbol=rec.get("symbol", ""),
                        status=rec.get("status", ""),
                        created_at=datetime.fromisoformat(rec.get("timestamp", datetime.now().isoformat())),
                    )
                    session.add(followup_rec)
                    count += 1
                print(f"   ✅ 已写入 {count} 条执行记录到 PostgreSQL")
        except Exception as e:
            print(f"   ⚠️ execution_followup 迁移失败: {e}")

    # 迁移 agent_profiles.json -> AgentProfiles
    if agent_profiles_path.exists():
        try:
            with open(agent_profiles_path, 'r', encoding='utf-8') as f:
                profiles = json.load(f)
            with session_scope() as session:
                count = 0
                for agent_name, profile in profiles.items():
                    ap = AgentProfiles(
                        agent_name=agent_name,
                        profile_json=profile,
                        created_at=datetime.now(),
                    )
                    session.add(ap)
                    count += 1
                print(f"   ✅ 已写入 {count} 个 Agent 配置到 PostgreSQL")
        except Exception as e:
            print(f"   ⚠️ agent_profiles 迁移失败: {e}")

    return migrated


def show_status():
    """显示 PostgreSQL 状态"""
    print("🔍 PostgreSQL 健康检查...")

    health_ok = PGConnection.health_check()
    if health_ok:
        print("✅ 连接正常")
    else:
        print("❌ 连接失败")
        return False

    engine = PGConnection.get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]
        print(f"\n📋 已部署表 ({len(tables)} 个):")
        for t in tables:
            print(f"   - {t}")

        result = conn.execute(text("""
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        views = [row[0] for row in result]
        print(f"\n📊 已部署视图 ({len(views)} 个):")
        for v in views:
            print(f"   - {v}")

    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="FDT PostgreSQL 部署工具")
    parser.add_argument("action", choices=["deploy", "migrate", "status", "all"],
                        help="操作类型: deploy=部署Schema, migrate=数据迁移, status=状态检查, all=全部执行")
    args = parser.parse_args()

    try:
        if args.action == "deploy":
            deploy_schema()
        elif args.action == "migrate":
            migrate_json_to_pg()
        elif args.action == "status":
            show_status()
        elif args.action == "all":
            deploy_schema()
            migrate_json_to_pg()
            show_status()
    except Exception as e:
        print(f"\n❌ 操作失败: {e}")
        print("   请检查 PostgreSQL 连接配置（环境变量 PG_HOST/PG_PORT/PG_DATABASE/PG_USERNAME/PG_PASSWORD）")
        sys.exit(1)


if __name__ == "__main__":
    main()
