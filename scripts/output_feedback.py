#!/usr/bin/env python3
"""
output_feedback.py — 输出反馈闭环 (D6 Output Phase 3)
========================================================
功能:
  1. 收集下游消费端反馈 (正确/错误/忽略)
  2. 按 Agent/品种/时间聚合反馈
  3. 反馈驱动质量改进建议
  4. 反馈趋势分析

用法:
  from scripts.output_feedback import OutputFeedback
  fb = OutputFeedback()
  fb.record_feedback(version_id="...", is_correct=True, notes="...")
  report = fb.get_report()
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = PROJECT_ROOT / "memory" / "output_feedback"


class OutputFeedback:
    """输出反馈收集器"""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or DEFAULT_STORAGE
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._records: list[dict] = []
        self._load()

    def _feedback_file(self) -> Path:
        return self.storage_dir / f"feedback_{datetime.now().strftime('%Y%m')}.jsonl"

    def _load(self):
        f = self._feedback_file()
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
        with open(self._feedback_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_feedback(
        self,
        version_id: str,
        is_correct: bool,
        agent_name: str = "",
        symbol: str = "",
        feedback_type: str = "manual",
        notes: str = "",
    ):
        """记录一条反馈"""
        record = {
            "version_id": version_id,
            "is_correct": is_correct,
            "agent_name": agent_name,
            "symbol": symbol,
            "feedback_type": feedback_type,
            "notes": notes,
            "timestamp": datetime.now().isoformat(),
        }
        self._records.append(record)
        self._save(record)

    def get_agent_accuracy(self, agent_name: str = "", days: int = 30) -> dict:
        """获取 Agent 准确率"""
        cutoff = datetime.now() - timedelta(days=days)
        stats: dict[str, dict] = {}

        for r in self._records:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            name = r.get("agent_name", "unknown")
            if agent_name and name != agent_name:
                continue

            if name not in stats:
                stats[name] = {"total": 0, "correct": 0, "incorrect": 0}

            stats[name]["total"] += 1
            if r.get("is_correct", False):
                stats[name]["correct"] += 1
            else:
                stats[name]["incorrect"] += 1

        result = {}
        for name, s in stats.items():
            result[name] = {
                "total": s["total"],
                "correct": s["correct"],
                "incorrect": s["incorrect"],
                "accuracy": round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0.0,
            }
        return result

    def get_improvement_suggestions(self) -> list[dict]:
        """基于反馈数据生成改进建议"""
        accuracy = self.get_agent_accuracy()
        suggestions = []

        for agent_name, stats in accuracy.items():
            if stats["total"] < 5:
                continue
            if stats["accuracy"] < 70:
                suggestions.append({
                    "agent": agent_name,
                    "priority": "high",
                    "issue": f"Accuracy {stats['accuracy']}% (below 70%)",
                    "suggestion": f"Review {agent_name} prompt and temperature settings",
                    "samples": stats["total"],
                })
            elif stats["accuracy"] < 85:
                suggestions.append({
                    "agent": agent_name,
                    "priority": "medium",
                    "issue": f"Accuracy {stats['accuracy']}% (below 85%)",
                    "suggestion": f"Consider adjusting {agent_name} decode parameters",
                    "samples": stats["total"],
                })

        return sorted(suggestions, key=lambda x: x["priority"] == "high", reverse=True)

    def get_summary(self) -> dict:
        """获取反馈汇总"""
        total = len(self._records)
        correct = sum(1 for r in self._records if r.get("is_correct"))
        return {
            "total_feedback": total,
            "correct": correct,
            "incorrect": total - correct,
            "accuracy": round(correct / total * 100, 1) if total > 0 else 0.0,
            "agent_accuracy": self.get_agent_accuracy(),
            "suggestions": self.get_improvement_suggestions(),
        }


def main():
    """CLI 入口"""
    import argparse
    parser = argparse.ArgumentParser(description="输出反馈工具")
    parser.add_argument("action", choices=["record", "accuracy", "suggestions"])
    parser.add_argument("--version", help="版本 ID (record)")
    parser.add_argument("--agent", "-a", help="Agent 名称")
    parser.add_argument("--correct", action="store_true", help="是否正确 (record)")
    parser.add_argument("--symbol", "-s", help="品种 (record)")
    parser.add_argument("--notes", "-n", help="备注 (record)")
    args = parser.parse_args()

    fb = OutputFeedback()

    if args.action == "record":
        fb.record_feedback(
            version_id=args.version or "test",
            is_correct=args.correct,
            agent_name=args.agent or "",
            symbol=args.symbol or "",
            notes=args.notes or "",
        )
        print("Feedback recorded")
    elif args.action == "accuracy":
        acc = fb.get_agent_accuracy(args.agent or "")
        print(json.dumps(acc, ensure_ascii=False, indent=2))
    elif args.action == "suggestions":
        suggestions = fb.get_improvement_suggestions()
        for s in suggestions:
            print(f"[{s['priority']}] {s['agent']}: {s['issue']}")
            print(f"  → {s['suggestion']}")


if __name__ == "__main__":
    main()
