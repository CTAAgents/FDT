#!/usr/bin/env python3
"""
output_versioning.py — 输出版本化管理 (D6 Output Phase 2)
==========================================================
功能:
  1. 输出带版本号管理 (project_version + output_revision)
  2. 输出历史记录 (JSONL)
  3. 版本比较与回滚能力
  4. 版本差异摘要

用法:
  from scripts.output_versioning import OutputVersioning
  v = OutputVersioning("judge")
  version_id = v.save_output({"symbol": "RB", ...})
  history = v.get_history(symbol="RB")
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = PROJECT_ROOT / "memory" / "output_history"


class OutputVersioning:
    """输出版本管理器"""

    def __init__(self, agent_name: str = "", storage_dir: Optional[Path] = None):
        self.agent_name = agent_name
        self.storage_dir = storage_dir or DEFAULT_STORAGE
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _history_file(self, agent_name: str) -> Path:
        return self.storage_dir / f"{agent_name}_history.jsonl"

    def _compute_hash(self, data: dict) -> str:
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:12]

    def save_output(
        self,
        output: dict,
        agent_name: str = "",
        project_version: str = "9.6.4",
        metadata: Optional[dict] = None,
    ) -> str:
        """
        保存输出并返回版本 ID

        Returns:
            str: version_id (格式: {agent}_{hash}_{timestamp})
        """
        name = agent_name or self.agent_name
        data_hash = self._compute_hash(output)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version_id = f"{name}_{data_hash}_{timestamp}"

        record = {
            "version_id": version_id,
            "agent_name": name,
            "project_version": project_version,
            "timestamp": datetime.now().isoformat(),
            "data_hash": data_hash,
            "output": output,
            "metadata": metadata or {},
        }

        # 追加写入
        history_file = self._history_file(name)
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return version_id

    def get_history(
        self,
        agent_name: str = "",
        symbol: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """
        获取版本历史

        Args:
            agent_name: Agent 名称
            symbol: 品种筛选
            limit: 返回条数

        Returns:
            list[dict]: 按时间倒序排列的历史记录
        """
        name = agent_name or self.agent_name
        history_file = self._history_file(name)
        if not history_file.exists():
            return []

        records = []
        with open(history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if symbol:
                        out = record.get("output", {})
                        if out.get("symbol") != symbol:
                            continue
                    records.append(record)
                except json.JSONDecodeError:
                    continue

        # 按时间倒序
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return records[:limit]

    def get_version(self, version_id: str) -> Optional[dict]:
        """按版本 ID 获取特定版本"""
        agent_name = version_id.split("_")[0]
        history_file = self._history_file(agent_name)
        if not history_file.exists():
            return None

        with open(history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("version_id") == version_id:
                        return record
                except json.JSONDecodeError:
                    continue
        return None

    def compare_versions(self, version_a: str, version_b: str) -> dict:
        """比较两个版本的内容差异"""
        rec_a = self.get_version(version_a)
        rec_b = self.get_version(version_b)

        if not rec_a or not rec_b:
            return {"error": "Version not found", "has_diff": False}

        out_a = rec_a.get("output", {})
        out_b = rec_b.get("output", {})

        # 顶层键差异
        keys_a = set(out_a.keys())
        keys_b = set(out_b.keys())

        added = keys_b - keys_a
        removed = keys_a - keys_b
        common = keys_a & keys_b

        changed = {}
        for key in common:
            if out_a[key] != out_b[key]:
                changed[key] = {"from": out_a[key], "to": out_b[key]}

        # 置信度变化 (如果 confidence 存在)
        conf_change = None
        if "confidence" in out_a and "confidence" in out_b:
            conf_change = out_b["confidence"] - out_a["confidence"]

        return {
            "version_a": version_a,
            "version_b": version_b,
            "has_diff": bool(added or removed or changed),
            "added_keys": sorted(added),
            "removed_keys": sorted(removed),
            "changed_keys": list(changed.keys()),
            "changes": changed,
            "confidence_delta": round(conf_change, 2) if conf_change is not None else None,
            "timestamp_a": rec_a.get("timestamp"),
            "timestamp_b": rec_b.get("timestamp"),
        }


def main():
    """CLI 入口"""
    import argparse
    parser = argparse.ArgumentParser(description="输出版本管理工具")
    sub = parser.add_subparsers(dest="cmd")

    # save
    save_p = sub.add_parser("save")
    save_p.add_argument("--agent", "-a", required=True, help="Agent 名称")
    save_p.add_argument("--file", "-f", required=True, help="输出 JSON 文件")

    # history
    hist_p = sub.add_parser("history")
    hist_p.add_argument("--agent", "-a", required=True, help="Agent 名称")
    hist_p.add_argument("--symbol", "-s", default="", help="品种筛选")
    hist_p.add_argument("--limit", "-l", type=int, default=10, help="返回条数")

    # compare
    cmp_p = sub.add_parser("compare")
    cmp_p.add_argument("version_a", help="版本 A")
    cmp_p.add_argument("version_b", help="版本 B")

    args = parser.parse_args()

    v = OutputVersioning()

    if args.cmd == "save":
        with open(args.file, "r", encoding="utf-8") as f:
            data = json.load(f)
        vid = v.save_output(data, agent_name=args.agent)
        print(f"Saved: {vid}")

    elif args.cmd == "history":
        records = v.get_history(agent_name=args.agent, symbol=args.symbol, limit=args.limit)
        for r in records:
            out = r.get("output", {})
            sym = out.get("symbol", "?")
            print(f"  {r['version_id'][:40]:<40} {r['timestamp'][:19]:<20} sym={sym}")

    elif args.cmd == "compare":
        diff = v.compare_versions(args.version_a, args.version_b)
        print(json.dumps(diff, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
