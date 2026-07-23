#!/usr/bin/env python3
"""
memory_cleaner.py — 记忆过期与清理策略 (D5 Memory Phase 4)
============================================================
功能:
  1. 过期记忆自动归档
  2. 存储容量控制
  3. 低价值记忆清理
  4. 清理报告生成

用法:
  from scripts.memory_cleaner import MemoryCleaner
  cleaner = MemoryCleaner()
  report = cleaner.clean(dry_run=True)
"""

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_DIR = PROJECT_ROOT / "memory"
DEFAULT_ARCHIVE_DIR = DEFAULT_MEMORY_DIR / "archive"


class MemoryCleaner:
    """记忆清理器"""

    def __init__(self, memory_dir: Optional[Path] = None, archive_dir: Optional[Path] = None):
        self.memory_dir = memory_dir or DEFAULT_MEMORY_DIR
        self.archive_dir = archive_dir or DEFAULT_ARCHIVE_DIR
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def clean(self, dry_run: bool = True, max_age_days: int = 90, max_storage_mb: int = 500) -> dict:
        """
        执行清理

        Args:
            dry_run: 如果为 True, 仅报告不删除
            max_age_days: 超过多少天视为过期
            max_storage_mb: 最大存储限制 (MB)

        Returns:
            dict: 清理报告
        """
        report = {
            "dry_run": dry_run,
            "timestamp": datetime.now().isoformat(),
            "archived_files": [],
            "deleted_files": [],
            "freed_space_kb": 0,
            "errors": [],
        }

        # 清理 JSONL 日志文件
        for pattern in ["*.jsonl", "*.log"]:
            for f in self.memory_dir.rglob(pattern):
                if not f.is_file():
                    continue
                age_days = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).days
                if age_days > max_age_days:
                    size_kb = f.stat().st_size / 1024
                    if dry_run:
                        report["archived_files"].append(str(f.relative_to(self.memory_dir)))
                        report["freed_space_kb"] += size_kb
                    else:
                        # 先归档再删除
                        archive_subdir = self.archive_dir / f.parent.relative_to(self.memory_dir)
                        archive_subdir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, archive_subdir / f.name)
                        f.unlink()
                        report["archived_files"].append(str(f.relative_to(self.memory_dir)))
                        report["freed_space_kb"] += size_kb
                        logger.info(f"Archived: {f.name} ({size_kb:.1f}KB)")

        # 清理 SQLite 数据库中的过期记录
        for db_file in self.memory_dir.rglob("*.db"):
            self._clean_sqlite(db_file, max_age_days, dry_run, report)

        # 压缩 debate_journal.json（保留最近 100 条）
        journal_path = self.memory_dir / "debate_journal.json"
        if journal_path.exists():
            try:
                with open(journal_path, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                if isinstance(entries, list) and len(entries) > 100:
                    keep = entries[-100:]
                    if not dry_run:
                        archived = entries[:-100]
                        archive_path = self.archive_dir / f"debate_journal_{datetime.now().strftime('%Y%m%d')}.json"
                        with open(archive_path, "w", encoding="utf-8") as f:
                            json.dump(archived, f, ensure_ascii=False)
                        with open(journal_path, "w", encoding="utf-8") as f:
                            json.dump(keep, f, ensure_ascii=False)
                        report["archived_files"].append(f"debate_journal.json ({len(archived)} 条归档)")
                        logger.info(f"Compressed debate_journal.json: {len(archived)} entries archived")
                    else:
                        report["archived_files"].append(f"debate_journal.json ({len(entries) - 100} 条可归档)")
            except Exception as e:
                report["errors"].append(f"debate_journal.json: {e}")

        # 清理 generation_metrics 过期记录（保留最近 7 天）
        metrics_dir = self.memory_dir / "generation_metrics"
        if metrics_dir.exists():
            for f in metrics_dir.iterdir():
                if f.suffix == ".jsonl" and f.is_file():
                    age_days = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).days
                    if age_days > 7:
                        size_kb = f.stat().st_size / 1024
                        if not dry_run:
                            f.unlink()
                            logger.info(f"Cleaned metrics: {f.name} ({size_kb:.1f}KB)")
                        report["freed_space_kb"] += size_kb

        # 总存储检查
        total_mb = sum(f.stat().st_size for f in self.memory_dir.rglob("*") if f.is_file()) / (1024 * 1024)
        report["current_storage_mb"] = round(total_mb, 1)
        report["over_limit"] = total_mb > max_storage_mb

        return report

    def _clean_sqlite(self, db_path: Path, max_age_days: int, dry_run: bool, report: dict):
        """清理 SQLite 过期记录"""
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            tables = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()

            for (table_name,) in tables:
                # 检查是否有 timestamp 列
                cols = [c[1] for c in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()]
                if "timestamp" not in cols:
                    continue

                cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
                count = cursor.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE timestamp < ?", (cutoff,)
                ).fetchone()[0]

                if count > 0:
                    if dry_run:
                        report["freed_space_kb"] += count * 0.1
                    else:
                        cursor.execute(f"DELETE FROM {table_name} WHERE timestamp < ?", (cutoff,))
                        conn.commit()
                        logger.info(f"Cleaned {count} records from {db_path.name}.{table_name}")

            conn.close()
        except Exception as e:
            report["errors"].append(f"SQLite {db_path.name}: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="记忆清理工具")
    parser.add_argument("--execute", "-x", action="store_true", help="实际执行 (默认 dry-run)")
    parser.add_argument("--days", "-d", type=int, default=90, help="过期天数")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    cleaner = MemoryCleaner()
    report = cleaner.clean(dry_run=not args.execute, max_age_days=args.days)

    if args.verbose:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Mode: {'DRY RUN' if report['dry_run'] else 'EXECUTED'}")
        print(f"Archived: {len(report['archived_files'])} files")
        print(f"Freed: {report['freed_space_kb']:.1f} KB")
        print(f"Current storage: {report['current_storage_mb']} MB")
        if report["errors"]:
            print(f"Errors: {len(report['errors'])}")


if __name__ == "__main__":
    main()
