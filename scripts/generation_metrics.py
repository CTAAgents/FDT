#!/usr/bin/env python3
"""
generation_metrics.py — 解码质量监控与反馈 (D3 Generation Phase 4)
=============================================================
功能:
  1. 记录每次生成的指标 (格式正确率、Schema合规率、延迟、重试次数)
  2. 按 Agent 聚合统计
  3. 输出质量报告
  4. 趋势分析

用法:
  from scripts.generation_metrics import GenerationMetrics
  metrics = GenerationMetrics()
  metrics.record(agent_name="judge", success=True, latency_ms=1200)
  report = metrics.get_report()
"""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 默认存储路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = PROJECT_ROOT / "memory" / "generation_metrics"


class GenerationMetrics:
    """解码质量监控器"""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or DEFAULT_STORAGE
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存
        self._records: list[dict] = []
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 加载已有记录
        self._load()

    def _records_file(self) -> Path:
        return self.storage_dir / f"metrics_{datetime.now().strftime('%Y%m')}.jsonl"

    def _load(self):
        """加载本月已有记录"""
        records_file = self._records_file()
        if records_file.exists():
            try:
                with open(records_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                self._records.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                logger.warning(f"Failed to load metrics: {e}")

    def _save(self, record: dict):
        """追加写入记录"""
        records_file = self._records_file()
        try:
            with open(records_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

    def record(
        self,
        agent_name: str,
        success: bool,
        latency_ms: float,
        schema_valid: bool = False,
        retries: int = 0,
        error_count: int = 0,
        warning_count: int = 0,
        metadata: Optional[dict] = None,
    ):
        """
        记录一次生成指标

        Args:
            agent_name: Agent 名称
            success: 是否成功
            latency_ms: 延迟 (毫秒)
            schema_valid: Schema 校验是否通过
            retries: 重试次数
            error_count: 错误数
            warning_count: 警告数
            metadata: 额外元数据
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self._session_id,
            "agent_name": agent_name,
            "success": success,
            "latency_ms": round(latency_ms, 2),
            "schema_valid": schema_valid,
            "retries": retries,
            "error_count": error_count,
            "warning_count": warning_count,
            "metadata": metadata or {},
        }
        self._records.append(record)
        self._save(record)

    def get_agent_stats(self, agent_name: Optional[str] = None) -> dict:
        """
        获取 Agent 统计

        Returns:
            dict: {
                agent_name: {
                    "total": int,
                    "success": int,
                    "success_rate": float,
                    "avg_latency_ms": float,
                    "schema_pass_rate": float,
                    "avg_retries": float,
                    "total_errors": int,
                }
            }
        """
        stats: dict[str, dict] = {}

        for record in self._records:
            name = record["agent_name"]
            if agent_name and name != agent_name:
                continue

            if name not in stats:
                stats[name] = {
                    "total": 0,
                    "success": 0,
                    "total_latency": 0.0,
                    "schema_valid": 0,
                    "total_retries": 0,
                    "total_errors": 0,
                    "total_warnings": 0,
                }

            s = stats[name]
            s["total"] += 1
            if record["success"]:
                s["success"] += 1
            s["total_latency"] += record.get("latency_ms", 0)
            if record.get("schema_valid"):
                s["schema_valid"] += 1
            s["total_retries"] += record.get("retries", 0)
            s["total_errors"] += record.get("error_count", 0)
            s["total_warnings"] += record.get("warning_count", 0)

        # 计算比率
        result = {}
        for name, s in stats.items():
            result[name] = {
                "total": s["total"],
                "success": s["success"],
                "success_rate": round(s["success"] / s["total"] * 100, 2) if s["total"] > 0 else 0.0,
                "avg_latency_ms": round(s["total_latency"] / s["total"], 2) if s["total"] > 0 else 0.0,
                "schema_pass_rate": round(s["schema_valid"] / s["total"] * 100, 2) if s["total"] > 0 else 0.0,
                "avg_retries": round(s["total_retries"] / s["total"], 2) if s["total"] > 0 else 0.0,
                "total_errors": s["total_errors"],
                "total_warnings": s["total_warnings"],
            }

        return result

    def get_summary(self) -> dict:
        """获取全局汇总"""
        agent_stats = self.get_agent_stats()
        records = self._records

        total = len(records)
        success = sum(1 for r in records if r.get("success"))
        schema_valid_count = sum(1 for r in records if r.get("schema_valid"))

        return {
            "total_records": total,
            "total_success": success,
            "overall_success_rate": round(success / total * 100, 2) if total > 0 else 0.0,
            "overall_schema_pass_rate": round(schema_valid_count / total * 100, 2) if total > 0 else 0.0,
            "agent_count": len(agent_stats),
            "agents": agent_stats,
            "report_time": datetime.now().isoformat(),
        }

    def get_trend(self, hours: int = 24) -> dict:
        """
        趋势分析 (按小时聚合)

        Args:
            hours: 分析最近 N 小时

        Returns:
            dict: 按小时聚合的趋势数据
        """
        from collections import defaultdict

        cutoff = datetime.now().timestamp() - hours * 3600
        hourly: dict[str, dict] = {}

        for record in self._records:
            try:
                ts = datetime.fromisoformat(record["timestamp"])
                if ts.timestamp() < cutoff:
                    continue
                hour_key = ts.strftime("%Y-%m-%d %H:00")
            except (ValueError, TypeError):
                continue

            if hour_key not in hourly:
                hourly[hour_key] = {"total": 0, "success": 0, "total_latency": 0.0}

            hourly[hour_key]["total"] += 1
            if record["success"]:
                hourly[hour_key]["success"] += 1
            hourly[hour_key]["total_latency"] += record.get("latency_ms", 0)

        # 计算比率
        result = {}
        for hour, data in sorted(hourly.items()):
            result[hour] = {
                "total": data["total"],
                "success_rate": round(data["success"] / data["total"] * 100, 2) if data["total"] > 0 else 0.0,
                "avg_latency_ms": round(data["total_latency"] / data["total"], 2) if data["total"] > 0 else 0.0,
            }

        return result

    def get_report(self, pretty: bool = True) -> str:
        """
        生成质量报告

        Returns:
            str: 格式化的报告文本
        """
        summary = self.get_summary()
        trend = self.get_trend(hours=24)

        lines = []
        lines.append("=" * 60)
        lines.append(f"📊 Generation Quality Report")
        lines.append(f"   Report Time: {summary['report_time']}")
        lines.append(f"   Total Records: {summary['total_records']}")
        lines.append(f"   Overall Success Rate: {summary['overall_success_rate']}%")
        lines.append(f"   Active Agents: {summary['agent_count']}")
        lines.append("=" * 60)

        lines.append("\n📈 Per-Agent Stats:")
        lines.append(f"{'Agent':<20} {'Total':>6} {'Success':>8} {'S.Rate':>8} {'Latency':>10} {'Schema':>8} {'Retry':>6}")
        lines.append("-" * 70)
        for agent_name, s in sorted(summary["agents"].items()):
            lines.append(
                f"{agent_name:<20} {s['total']:>6} {s['success']:>8} "
                f"{s['success_rate']:>7.1f}% {s['avg_latency_ms']:>8.0f}ms "
                f"{s['schema_pass_rate']:>6.1f}% {s['avg_retries']:>5.1f}"
            )

        lines.append("\n📊 Hourly Trend (last 24h):")
        lines.append(f"{'Hour':<20} {'Calls':>6} {'S.Rate':>8} {'Avg Latency':>12}")
        lines.append("-" * 50)
        for hour, data in list(trend.items())[-12:]:  # 最近 12 小时
            lines.append(
                f"{hour:<20} {data['total']:>6} "
                f"{data['success_rate']:>7.1f}% {data['avg_latency_ms']:>10.0f}ms"
            )

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)


def main():
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="解码质量监控工具")
    parser.add_argument("action", nargs="?", default="report",
                        choices=["report", "stats", "trend", "record"])
    parser.add_argument("--agent", "-a", default="", help="Agent 名称")
    parser.add_argument("--success", action="store_true", help="是否成功 (record)")
    parser.add_argument("--latency", type=float, default=0, help="延迟毫秒 (record)")
    parser.add_argument("--retries", type=int, default=0, help="重试次数 (record)")
    parser.add_argument("--hours", type=int, default=24, help="趋势分析小时数")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    args = parser.parse_args()

    metrics = GenerationMetrics()

    if args.action == "record":
        metrics.record(
            agent_name=args.agent or "test",
            success=args.success,
            latency_ms=args.latency,
            retries=args.retries,
        )
        print(f"✅ Recorded for {args.agent or 'test'}")
        return

    if args.action == "stats":
        result = metrics.get_agent_stats(args.agent or None)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for name, s in result.items():
                print(f"{name}: {s['total']} calls, {s['success_rate']}% success, "
                      f"{s['avg_latency_ms']:.0f}ms avg, {s['schema_pass_rate']}% schema")
        return

    if args.action == "trend":
        result = metrics.get_trend(hours=args.hours)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for hour, data in result.items():
                print(f"{hour}: {data['total']} calls, {data['success_rate']}% success")
        return

    # 默认 report
    report = metrics.get_report()
    print(report)


if __name__ == "__main__":
    main()
