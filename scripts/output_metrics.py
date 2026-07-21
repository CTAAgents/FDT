#!/usr/bin/env python3
"""
output_metrics.py — 输出质量度量体系 (D6 Output Phase 1)
=========================================================
功能:
  1. 输出格式完整性检查
  2. 输出一致性评估
  3. 输出质量评分 (0-100)
  4. 输出质量报告生成

用法:
  from scripts.output_metrics import OutputMetrics
  metrics = OutputMetrics()
  score = metrics.score_output(output_data, agent_name="judge")
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class OutputMetrics:
    """输出质量度量器"""

    QUALITY_DIMENSIONS = ["completeness", "consistency", "conformity", "conciseness"]

    def __init__(self):
        self._records: list[dict] = []

    def score_output(self, output: dict, agent_name: str = "") -> dict:
        """
        对输出进行质量评分 (0-100)

        Args:
            output: 输出数据
            agent_name: Agent 名称 (用于角色差异化评估)

        Returns:
            dict: {"total_score": float, "dimensions": dict, "details": list[str]}
        """
        dimensions = {}
        details = []

        # 1. 完整性 (completeness) - 是否有缺失字段
        completeness = self._score_completeness(output, agent_name)
        dimensions["completeness"] = completeness

        # 2. 一致性 (consistency) - 字段值是否自洽
        consistency = self._score_consistency(output)
        dimensions["consistency"] = consistency

        # 3. 合规性 (conformity) - 是否符合预期格式
        conformity = self._score_conformity(output)
        dimensions["conformity"] = conformity

        # 4. 简洁性 (conciseness) - 信息密度
        conciseness = self._score_conciseness(output)
        dimensions["conciseness"] = conciseness

        # 加权总分
        weights = {"completeness": 0.35, "consistency": 0.30,
                   "conformity": 0.20, "conciseness": 0.15}
        total_score = sum(dimensions[d] * weights[d] for d in self.QUALITY_DIMENSIONS)

        result = {
            "total_score": round(total_score, 1),
            "dimensions": dimensions,
            "details": details,
            "agent_name": agent_name,
            "timestamp": datetime.now().isoformat(),
        }

        self._records.append(result)
        return result

    def _score_completeness(self, output: dict, agent_name: str = "") -> float:
        """完整性评分 (0-100)"""
        if not output:
            return 0.0

        # 关键字段检查
        key_fields = {
            "judge": ["symbol", "direction", "confidence"],
            "bullish_analyst": ["role", "dimensions", "summary_4_risk"],
            "bearish_analyst": ["role", "dimensions", "summary_4_risk"],
            "risk_manager": ["risk_color", "max_leverage"],
        }

        required = key_fields.get(agent_name, [])
        if not required:
            return 80.0  # 无指定字段时给基础分

        present = sum(1 for f in required if f in output and output[f] is not None)
        return round((present / len(required)) * 100, 1)

    def _score_consistency(self, output: dict) -> float:
        """一致性评分 (0-100)"""
        score = 100.0
        issues = []

        # Rule 1: direction 和 confidence 应一致
        if "direction" in output and "confidence" in output:
            conf = output["confidence"]
            if isinstance(conf, (int, float)) and conf < 0.5:
                score -= 10  # 低置信度但给出了方向

        # Rule 2: risk_color 和 max_leverage 应匹配
        if "risk_color" in output and "max_leverage" in output:
            color = output["risk_color"]
            leverage = output.get("max_leverage", 0)
            if color == "red" and leverage > 1:
                score -= 20
            elif color == "yellow" and leverage > 3:
                score -= 10

        return max(0.0, score)

    def _score_conformity(self, output: dict) -> float:
        """合规性评分 (0-100)"""
        score = 100.0

        # 检查值域合规
        if "confidence" in output:
            conf = output["confidence"]
            if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
                score -= 20

        if "max_leverage" in output:
            lev = output["max_leverage"]
            if not isinstance(lev, (int, float)) or lev < 0 or lev > 10:
                score -= 20

        # 检查必填字符串非空
        for field in ["symbol", "direction", "risk_color"]:
            if field in output and output[field] is None:
                score -= 15

        return max(0.0, score)

    def _score_conciseness(self, output: dict) -> float:
        """简洁性评分 (0-100)"""
        text = json.dumps(output, ensure_ascii=False)
        length = len(text)

        if length < 50:
            return 60.0  # 过短可能信息不足
        elif length < 200:
            return 95.0  # 简洁
        elif length < 1000:
            return 85.0  # 适中
        elif length < 3000:
            return 70.0
        else:
            return 50.0  # 过于冗长

    def get_summary(self) -> dict:
        """获取评分汇总"""
        if not self._records:
            return {"total_records": 0, "avg_score": 0.0}

        scores = [r["total_score"] for r in self._records]
        return {
            "total_records": len(self._records),
            "avg_score": round(sum(scores) / len(scores), 1),
            "min_score": min(scores),
            "max_score": max(scores),
        }


def main():
    """CLI 入口"""
    import argparse
    parser = argparse.ArgumentParser(description="输出质量度量工具")
    parser.add_argument("--agent", "-a", default="", help="Agent 名称")
    parser.add_argument("--file", "-f", help="从 JSON 文件读取输出")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        import sys
        data = json.loads(sys.stdin.read())

    metrics = OutputMetrics()
    result = metrics.score_output(data, agent_name=args.agent)
    if args.verbose:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Total Score: {result['total_score']}/100")
        for dim, score in result["dimensions"].items():
            print(f"  {dim}: {score}/100")

if __name__ == "__main__":
    main()
