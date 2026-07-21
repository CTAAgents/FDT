#!/usr/bin/env python3
"""
output_audit.py — 输出审计日志 (D6 Output Phase 4)
=====================================================
功能:
  1. 完整输出溯源 (who/what/when/why)
  2. 审计追踪与合规检查
  3. 输出变更记录
  4. 审计报告生成

用法:
  from scripts.output_audit import OutputAudit
  audit = OutputAudit()
  audit.log_output(agent_name="judge", output={...}, trace_id="...")
  trail = audit.get_trail(trace_id="...")
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = PROJECT_ROOT / "memory" / "output_audit"


class OutputAudit:
    """输出审计追踪器"""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or DEFAULT_STORAGE
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._records: list[dict] = []
        self._load()

    def _audit_file(self) -> Path:
        return self.storage_dir / f"audit_{datetime.now().strftime('%Y%m')}.jsonl"

    def _load(self):
        f = self._audit_file()
        if f.exists():
            with open(f, "r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if line:
                        try:
                            self._records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

    def _save(self, record: dict):
        with open(self._audit_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_output(
        self,
        agent_name: str,
        output: dict,
        trace_id: str = "",
        action: str = "generate",
        triggered_by: str = "",
        compliance_checked: bool = False,
        schema_validated: bool = False,
        version_id: str = "",
    ):
        """
        记录一条审计日志

        Args:
            agent_name: Agent 名称
            output: 输出数据
            trace_id: 追踪 ID
            action: 操作类型 (generate/revise/review/approve)
            triggered_by: 触发源 (cron/manual/api)
            compliance_checked: 是否已通过合规检查
            schema_validated: 是否已通过 Schema 校验
            version_id: 版本 ID (引用 OutputVersioning)
        """
        record = {
            "agent_name": agent_name,
            "trace_id": trace_id or "unknown",
            "action": action,
            "triggered_by": triggered_by or "unknown",
            "compliance_checked": compliance_checked,
            "schema_validated": schema_validated,
            "version_id": version_id,
            "output_summary": self._summarize_output(output),
            "timestamp": datetime.now().isoformat(),
        }
        self._records.append(record)
        self._save(record)

    def _summarize_output(self, output: dict) -> dict:
        """提取输出摘要用于审计 (不含完整数据)"""
        summary = {}
        for key in ["symbol", "direction", "confidence", "risk_color", "max_leverage", "variant"]:
            if key in output:
                summary[key] = output[key]
        return summary

    def get_trail(self, trace_id: str = "", agent_name: str = "", days: int = 7) -> list[dict]:
        """
        获取审计追踪

        Args:
            trace_id: 追踪 ID 筛选
            agent_name: Agent 筛选
            days: 最近天数

        Returns:
            按时间倒序的审计记录
        """
        cutoff = datetime.now() - timedelta(days=days)
        results = []

        for r in self._records:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            if trace_id and r.get("trace_id") != trace_id:
                continue
            if agent_name and r.get("agent_name") != agent_name:
                continue

            results.append(r)

        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results

    def get_summary(self, days: int = 30) -> dict:
        """获取审计汇总"""
        records = self.get_trail(days=days)
        if not records:
            return {"total": 0, "agents": {}, "actions": {}}

        agent_stats: dict[str, int] = {}
        action_stats: dict[str, int] = {}
        for r in records:
            agent_stats[r.get("agent_name", "?")] = agent_stats.get(r.get("agent_name", "?"), 0) + 1
            action_stats[r.get("action", "?")] = action_stats.get(r.get("action", "?"), 0) + 1

        compliance_count = sum(1 for r in records if r.get("compliance_checked"))
        schema_count = sum(1 for r in records if r.get("schema_validated"))

        return {
            "total": len(records),
            "agents": agent_stats,
            "actions": action_stats,
            "compliance_checked": compliance_count,
            "schema_validated": schema_count,
            "compliance_rate": round(compliance_count / len(records) * 100, 1) if records else 0.0,
        }

    def check_compliance_gap(self, days: int = 7) -> list[dict]:
        """检查合规差距 (未做合规检查的记录)"""
        records = self.get_trail(days=days)
        gaps = [r for r in records if not r.get("compliance_checked")]
        return gaps[:20]  # 返回最多 20 条


def main():
    """CLI 入口"""
    import argparse
    parser = argparse.ArgumentParser(description="输出审计工具")
    parser.add_argument("action", choices=["log", "trail", "summary", "gaps"])
    parser.add_argument("--agent", "-a", help="Agent 名称")
    parser.add_argument("--trace", "-t", help="追踪 ID")
    parser.add_argument("--action-type", help="操作类型 (log)")
    parser.add_argument("--days", "-d", type=int, default=7, help="天数")
    args = parser.parse_args()

    audit = OutputAudit()

    if args.action == "log":
        audit.log_output(
            agent_name=args.agent or "test",
            output={},
            trace_id=args.trace or "",
            action=args.action_type or "generate",
        )
        print("Audit log recorded")

    elif args.action == "trail":
        records = audit.get_trail(trace_id=args.trace or "", agent_name=args.agent or "", days=args.days)
        for r in records:
            print(f"  [{r['timestamp'][:19]}] {r['agent_name']:<20} {r['action']:<10} trace={r['trace_id']}")

    elif args.action == "summary":
        summary = audit.get_summary(days=args.days)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    elif args.action == "gaps":
        gaps = audit.check_compliance_gap(days=args.days)
        print(f"Compliance gaps: {len(gaps)}")
        for g in gaps:
            print(f"  [{g['timestamp'][:19]}] {g['agent_name']} trace={g['trace_id']}")


if __name__ == "__main__":
    main()
