#!/usr/bin/env python3
"""
tool_metrics.py — 工具调用日志与效能追踪 (D2 Tool Phase 3)
============================================================
功能:
  1. 记录每次工具调用的耗时、成功率、成本
  2. 按工具/分类聚合统计
  3. 效能报告生成
  4. 异常检测 (高延迟/高失败率)

用法:
  from scripts.tool_metrics import ToolMetrics
  tm = ToolMetrics()
  tm.record_call("data_scan", success=True, latency_ms=1200)
  report = tm.get_report()
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = PROJECT_ROOT / "memory" / "tool_metrics"


class ToolMetrics:
    """工具效能追踪器"""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or DEFAULT_STORAGE
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._records: list[dict] = []
        self._load()

    def _data_file(self) -> Path:
        return self.storage_dir / f"tool_metrics_{datetime.now().strftime('%Y%m')}.jsonl"

    def _load(self):
        f = self._data_file()
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
        with open(self._data_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_call(self, tool_name: str, success: bool, latency_ms: float,
                    tokens: int = 0, error: str = ""):
        """记录工具调用"""
        record = {
            "tool_name": tool_name,
            "success": success,
            "latency_ms": round(latency_ms, 2),
            "tokens": tokens,
            "error": error[:200] if error else "",
            "timestamp": datetime.now().isoformat(),
        }
        self._records.append(record)
        self._save(record)

    def get_tool_stats(self, tool_name: str = "", days: int = 7) -> dict:
        """获取工具统计"""
        cutoff = datetime.now() - timedelta(days=days)
        stats: dict[str, dict] = {}

        for r in self._records:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            name = r.get("tool_name", "?")
            if tool_name and name != tool_name:
                continue

            if name not in stats:
                stats[name] = {"calls": 0, "success": 0, "failures": 0,
                               "total_latency": 0.0, "max_latency": 0.0, "total_tokens": 0}

            s = stats[name]
            s["calls"] += 1
            if r.get("success"):
                s["success"] += 1
            else:
                s["failures"] += 1
            lat = r.get("latency_ms", 0)
            s["total_latency"] += lat
            s["max_latency"] = max(s["max_latency"], lat)
            s["total_tokens"] += r.get("tokens", 0)

        result = {}
        for name, s in stats.items():
            result[name] = {
                "calls": s["calls"],
                "success_rate": round(s["success"] / s["calls"] * 100, 1) if s["calls"] > 0 else 0.0,
                "avg_latency_ms": round(s["total_latency"] / s["calls"], 1) if s["calls"] > 0 else 0.0,
                "max_latency_ms": round(s["max_latency"], 1),
                "avg_tokens": round(s["total_tokens"] / s["calls"]) if s["calls"] > 0 else 0,
            }
        return result

    def detect_anomalies(self, days: int = 1) -> list[dict]:
        """检测异常 (高延迟/高失败率)"""
        stats = self.get_tool_stats(days=days)
        anomalies = []
        for name, s in stats.items():
            if s["avg_latency_ms"] > 5000:
                anomalies.append({"tool": name, "type": "high_latency",
                                  "value": s["avg_latency_ms"], "threshold": 5000})
            if s["success_rate"] < 80 and s["calls"] >= 5:
                anomalies.append({"tool": name, "type": "low_success_rate",
                                  "value": s["success_rate"], "threshold": 80})
        return anomalies

    def get_report(self) -> str:
        """生成效能报告"""
        stats = self.get_tool_stats(days=7)
        anomalies = self.detect_anomalies(days=1)
        total = sum(s["calls"] for s in stats.values())

        lines = [
            "=" * 60,
            "📊 Tool Performance Report (last 7 days)",
            f"   Total calls: {total}",
            f"   Active tools: {len(stats)}",
            "=" * 60,
            "",
            f"{'Tool':<25} {'Calls':>6} {'S.Rate':>8} {'Avg Lat':>10} {'Max Lat':>10} {'Tokens':>8}",
            "-" * 70,
        ]
        for name, s in sorted(stats.items()):
            lines.append(
                f"{name:<25} {s['calls']:>6} {s['success_rate']:>7.1f}% "
                f"{s['avg_latency_ms']:>8.0f}ms {s['max_latency_ms']:>8.0f}ms {s['avg_tokens']:>6}"
            )

        if anomalies:
            lines.append("", "⚠️ Anomalies detected:", "")
            for a in anomalies:
                lines.append(f"  [{a['type']}] {a['tool']}: {a['value']} (threshold: {a['threshold']})")

        return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="工具效能追踪工具")
    parser.add_argument("action", choices=["record", "stats", "report", "anomalies"])
    parser.add_argument("--tool", "-t", help="工具名")
    parser.add_argument("--success", action="store_true", help="是否成功")
    parser.add_argument("--latency", type=float, default=0, help="延迟毫秒")
    parser.add_argument("--tokens", type=int, default=0, help="token数")
    args = parser.parse_args()

    tm = ToolMetrics()
    if args.action == "record":
        tm.record_call(args.tool or "test", args.success, args.latency, args.tokens)
        print("Recorded")
    elif args.action == "stats":
        print(json.dumps(tm.get_tool_stats(args.tool or ""), ensure_ascii=False, indent=2))
    elif args.action == "anomalies":
        for a in tm.detect_anomalies():
            print(f"[{a['type']}] {a['tool']}: {a['value']}")
    else:
        print(tm.get_report())


if __name__ == "__main__":
    main()
