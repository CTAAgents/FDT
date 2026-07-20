#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 输出质量校验器 — 检测和度量 LLM 数值型幻觉。

职责：
  1. 价格合理性校验：检测 LLM 生成的价格与扫描数据的偏差
  2. 数值一致性校验：检测置信度、评分等数值是否在合理范围内
  3. 批量校验历史裁决，产出结构化统计报告

用法：
  python validate_llm_output.py --scan <scan_file> --verdict <verdict_file>
  python validate_llm_output.py --history <history_dir>
  python validate_llm_output.py --stats <stats_file>

输出：
  - llm_hallucination_stats.json (幻觉统计)
  - stdout JSON 报告

阈值：
  - PRICE_DEVIATION_THRESHOLD: 价格偏差阈值（默认 20%）
  - CONFIDENCE_RANGE: 置信度有效范围 [0, 1]
"""

from __future__ import annotations

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PRICE_DEVIATION_THRESHOLD = 0.20
CONFIDENCE_MIN = 0.0
CONFIDENCE_MAX = 1.0


def validate_price_deviation(
    llm_price: float,
    scan_price: float,
    threshold: float = PRICE_DEVIATION_THRESHOLD,
) -> Tuple[bool, float]:
    """
    校验 LLM 生成价格与扫描价格的偏差。

    Args:
        llm_price: LLM 生成的价格
        scan_price: 扫描数据中的价格
        threshold: 偏差阈值（默认 20%）

    Returns:
        (is_valid, deviation_rate)
    """
    if scan_price == 0:
        return True, 0.0

    deviation_rate = abs(llm_price - scan_price) / abs(scan_price)
    return deviation_rate <= threshold, deviation_rate


def validate_confidence(confidence: Any) -> Tuple[bool, float]:
    """
    校验置信度数值是否在合理范围内。

    Args:
        confidence: LLM 输出的置信度值

    Returns:
        (is_valid, normalized_value)
    """
    try:
        value = float(confidence)
        is_valid = CONFIDENCE_MIN <= value <= CONFIDENCE_MAX
        return is_valid, value
    except (ValueError, TypeError):
        return False, 0.5


def validate_score_range(score: Any, min_val: float = -100.0, max_val: float = 100.0) -> Tuple[bool, float]:
    """
    校验评分值是否在合理范围内。

    Args:
        score: LLM 输出的评分值
        min_val: 最小值
        max_val: 最大值

    Returns:
        (is_valid, normalized_value)
    """
    try:
        value = float(score)
        is_valid = min_val <= value <= max_val
        return is_valid, value
    except (ValueError, TypeError):
        return False, 0.0


def validate_single_verdict(
    verdict: Dict[str, Any],
    scan_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    校验单个裁决的 LLM 输出质量。

    Args:
        verdict: LLM 裁决数据
        scan_data: 对应扫描数据（可选）

    Returns:
        校验结果字典
    """
    result = {
        "symbol": verdict.get("symbol", "unknown"),
        "is_hallucinated": False,
        "issues": [],
        "price_validation": None,
        "confidence_validation": None,
        "score_validation": None,
        "max_deviation_rate": 0.0,
    }

    entry_price = verdict.get("entry_price")
    stop_loss = verdict.get("stop_loss")
    take_profit = verdict.get("take_profit")
    confidence = verdict.get("confidence")
    bull_score = verdict.get("bull_score")
    bear_score = verdict.get("bear_score")

    if scan_data:
        scan_price = scan_data.get("price") or scan_data.get("close") or scan_data.get("entry_price")
        if scan_price and entry_price:
            is_valid, deviation = validate_price_deviation(entry_price, scan_price)
            result["price_validation"] = {
                "llm_price": entry_price,
                "scan_price": scan_price,
                "deviation_rate": round(deviation * 100, 2),
                "is_valid": is_valid,
            }
            if not is_valid:
                result["is_hallucinated"] = True
                result["issues"].append(f"价格偏差 {round(deviation*100, 1)}% > {PRICE_DEVIATION_THRESHOLD*100}%")
                result["max_deviation_rate"] = max(result["max_deviation_rate"], deviation)

        if scan_price and stop_loss:
            is_valid, deviation = validate_price_deviation(stop_loss, scan_price)
            if not is_valid:
                result["is_hallucinated"] = True
                result["issues"].append(f"止损价偏差 {round(deviation*100, 1)}% > {PRICE_DEVIATION_THRESHOLD*100}%")
                result["max_deviation_rate"] = max(result["max_deviation_rate"], deviation)

        if scan_price and take_profit:
            is_valid, deviation = validate_price_deviation(take_profit, scan_price)
            if not is_valid:
                result["is_hallucinated"] = True
                result["issues"].append(f"目标价偏差 {round(deviation*100, 1)}% > {PRICE_DEVIATION_THRESHOLD*100}%")
                result["max_deviation_rate"] = max(result["max_deviation_rate"], deviation)

    if confidence is not None:
        is_valid, value = validate_confidence(confidence)
        result["confidence_validation"] = {
            "value": confidence,
            "normalized": round(value, 2),
            "is_valid": is_valid,
        }
        if not is_valid:
            result["issues"].append(f"置信度 {confidence} 超出范围 [{CONFIDENCE_MIN}, {CONFIDENCE_MAX}]")

    if bull_score is not None:
        is_valid, value = validate_score_range(bull_score)
        result["score_validation"] = result.get("score_validation") or {}
        result["score_validation"]["bull_score"] = {
            "value": bull_score,
            "normalized": round(value, 2),
            "is_valid": is_valid,
        }

    if bear_score is not None:
        is_valid, value = validate_score_range(bear_score)
        result["score_validation"] = result.get("score_validation") or {}
        result["score_validation"]["bear_score"] = {
            "value": bear_score,
            "normalized": round(value, 2),
            "is_valid": is_valid,
        }

    return result


def batch_validate(
    verdicts: List[Dict[str, Any]],
    scan_results: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    批量校验多个裁决的 LLM 输出质量。

    Args:
        verdicts: 裁决列表
        scan_results: 扫描结果（按品种索引）

    Returns:
        汇总统计报告
    """
    stats = {
        "generated_at": datetime.now().isoformat(),
        "total_verdicts": len(verdicts),
        "hallucinated_count": 0,
        "hallucination_rate": 0.0,
        "max_deviation_rate": 0.0,
        "price_deviation_mean": 0.0,
        "confidence_issues": 0,
        "details": [],
    }

    total_deviation = 0.0
    deviation_count = 0

    for verdict in verdicts:
        symbol = verdict.get("symbol")
        scan_data = scan_results.get(symbol) if scan_results else None
        validation = validate_single_verdict(verdict, scan_data)

        stats["details"].append(validation)

        if validation["is_hallucinated"]:
            stats["hallucinated_count"] += 1

        if validation["max_deviation_rate"] > stats["max_deviation_rate"]:
            stats["max_deviation_rate"] = validation["max_deviation_rate"]

        if validation["price_validation"] and not validation["price_validation"]["is_valid"]:
            total_deviation += validation["price_validation"]["deviation_rate"]
            deviation_count += 1

        if validation["confidence_validation"] and not validation["confidence_validation"]["is_valid"]:
            stats["confidence_issues"] += 1

    if stats["total_verdicts"] > 0:
        stats["hallucination_rate"] = round(
            stats["hallucinated_count"] / stats["total_verdicts"] * 100, 2
        )

    if deviation_count > 0:
        stats["price_deviation_mean"] = round(total_deviation / deviation_count * 100, 2)
    else:
        stats["price_deviation_mean"] = 0.0

    stats["max_deviation_rate"] = round(stats["max_deviation_rate"] * 100, 2)

    return stats


def load_scan_results(scan_file: str) -> Dict[str, Any]:
    """加载扫描结果文件。"""
    with open(scan_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "all_ranked" in data:
        return {item.get("symbol"): item for item in data["all_ranked"]}
    if isinstance(data, list):
        return {item.get("symbol"): item for item in data}
    return data


def load_verdicts(verdict_file: str) -> List[Dict[str, Any]]:
    """加载裁决文件。"""
    with open(verdict_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "signals" in data:
            return data["signals"]
        if "verdict" in data:
            return [data["verdict"]]
        if data.get("symbol"):
            return [data]
    return []


def save_stats(stats: Dict[str, Any], output_file: str = "llm_hallucination_stats.json") -> None:
    """保存统计结果到文件。"""
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def main() -> None:
    import argparse

    global PRICE_DEVIATION_THRESHOLD

    parser = argparse.ArgumentParser(description="LLM 输出质量校验器")
    parser.add_argument("--scan", type=str, help="扫描结果文件路径")
    parser.add_argument("--verdict", type=str, help="裁决文件路径")
    parser.add_argument("--history", type=str, help="历史裁决目录")
    parser.add_argument("--stats", type=str, help="输出统计文件路径")
    parser.add_argument("--threshold", type=float, default=PRICE_DEVIATION_THRESHOLD,
                        help=f"价格偏差阈值（默认 {PRICE_DEVIATION_THRESHOLD*100}%%）")

    args = parser.parse_args()

    PRICE_DEVIATION_THRESHOLD = args.threshold

    scan_results = None
    verdicts = []

    if args.scan:
        scan_results = load_scan_results(args.scan)

    if args.verdict:
        verdicts = load_verdicts(args.verdict)
    elif args.history:
        history_dir = Path(args.history)
        for verdict_file in history_dir.glob("*verdict*.json"):
            verdicts.extend(load_verdicts(str(verdict_file)))

    if not verdicts:
        print(json.dumps({"error": "未找到裁决数据"}, ensure_ascii=False))
        sys.exit(1)

    stats = batch_validate(verdicts, scan_results)

    output_file = args.stats or "llm_hallucination_stats.json"
    save_stats(stats, output_file)

    summary = {
        "total_verdicts": stats["total_verdicts"],
        "hallucinated_count": stats["hallucinated_count"],
        "hallucination_rate": f"{stats['hallucination_rate']}%",
        "max_deviation": f"{stats['max_deviation_rate']}%",
        "avg_deviation": f"{stats['price_deviation_mean']}%",
        "confidence_issues": stats["confidence_issues"],
        "output_file": output_file,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
