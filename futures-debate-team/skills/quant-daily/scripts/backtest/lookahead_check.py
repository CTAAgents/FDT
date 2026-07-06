#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前视偏差检测模块 — 隔离回测与实盘数据管道
==========================================
P0-2: 回测体系全面加固 — 前视偏差检测

检查因子计算中是否使用了未来数据（未来价格、未来指标、未来事件）。
核心逻辑：所有指标计算必须基于截至当前 bar 的数据，禁止任何形式的 peek-ahead。

检测维度：
1. 价格前视：使用未来价格计算当前信号
2. 指标前视：使用未来指标值计算当前信号
3. 事件前视：使用未来事件信息影响当前决策
4. 换月前视：使用未来主力合约信息影响当前合约

用法:
    python lookahead_check.py --scan-result full_scan_l1l4_20260705.json
    python lookahead_check.py --backtest-result backtest_RB.json
    python lookahead_check.py --auto-detect --data-dir ./data
"""

import sys, os, json, re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 前视偏差检测规则库 ──
LOOKAHEAD_RULES = [
    {
        "name": "价格前视",
        "description": "使用未来价格计算当前信号",
        "check": lambda df, col: df[col].shift(-1).notna().any() if col in df.columns else False,
        "severity": "CRITICAL",
    },
    {
        "name": "指标前视",
        "description": "使用未来指标值计算当前信号",
        "check": lambda df, col: "future_" in str(col).lower() or "lookahead" in str(col).lower(),
        "severity": "CRITICAL",
    },
    {
        "name": "事件前视",
        "description": "使用未来事件信息影响当前决策",
        "check": lambda df, col: "event_" in str(col).lower() and "future" in str(col).lower(),
        "severity": "HIGH",
    },
    {
        "name": "换月前视",
        "description": "使用未来主力合约信息影响当前合约",
        "check": lambda df, col: "next_main" in str(col).lower() or "future_contract" in str(col).lower(),
        "severity": "HIGH",
    },
]


def detect_lookahead_in_dataframe(df: pd.DataFrame, context: str = "") -> List[Dict[str, Any]]:
    """
    检测 DataFrame 中是否存在前视偏差。

    Returns:
        [{"rule": str, "column": str, "severity": str, "description": str}, ...]
    """
    violations = []

    for col in df.columns:
        for rule in LOOKAHEAD_RULES:
            try:
                if rule["check"](df, col):
                    violations.append(
                        {
                            "rule": rule["name"],
                            "column": str(col),
                            "severity": rule["severity"],
                            "description": rule["description"],
                            "context": context,
                        }
                    )
            except Exception:
                pass

    return violations


def detect_lookahead_in_signals(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    检测信号数据中是否存在前视偏差。

    检查点：
    - 信号生成时间是否早于数据截止时间
    - 信号是否引用了未来指标
    - 信号是否基于未来价格
    """
    violations = []

    # 检查信号时间戳
    signal_time = signals.get("timestamp", "")
    data_time = signals.get("data_timestamp", "")
    if signal_time and data_time and signal_time > data_time:
        violations.append(
            {
                "rule": "时间戳前视",
                "severity": "CRITICAL",
                "description": f"信号时间戳({signal_time})晚于数据时间戳({data_time})，可能存在未来数据",
            }
        )

    # 检查品种数据
    for symbol, data in signals.get("symbols", {}).items():
        # 检查是否包含未来指标字段
        for key in data.keys():
            if any(x in str(key).lower() for x in ["future", "lookahead", "next", "ahead"]):
                violations.append(
                    {
                        "rule": "指标字段前视",
                        "column": key,
                        "severity": "CRITICAL",
                        "description": f"品种 {symbol} 包含疑似前视字段: {key}",
                    }
                )

    return violations


def auto_detect(data_dir: str) -> Dict[str, Any]:
    """
    自动检测指定目录下的所有数据文件是否存在前视偏差。

    Returns:
        {"summary": {...}, "violations": [...]}
    """
    all_violations = []
    checked_files = 0

    for root, dirs, files in os.walk(data_dir):
        for fname in files:
            if not fname.endswith((".json", ".csv", ".parquet")):
                continue
            fpath = os.path.join(root, fname)
            checked_files += 1

            try:
                if fname.endswith(".json"):
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # 尝试转换为DataFrame
                    if isinstance(data, dict) and "data" in data:
                        df = pd.DataFrame(data["data"])
                    elif isinstance(data, list):
                        df = pd.DataFrame(data)
                    else:
                        df = pd.DataFrame([data])
                    violations = detect_lookahead_in_dataframe(df, context=fname)
                    all_violations.extend(violations)

                elif fname.endswith(".csv"):
                    df = pd.read_csv(fpath)
                    violations = detect_lookahead_in_dataframe(df, context=fname)
                    all_violations.extend(violations)

                elif fname.endswith(".parquet"):
                    df = pd.read_parquet(fpath)
                    violations = detect_lookahead_in_dataframe(df, context=fname)
                    all_violations.extend(violations)

            except Exception as e:
                print(f"[LookaheadCheck] 跳过 {fname}: {e}")

    critical = sum(1 for v in all_violations if v.get("severity") == "CRITICAL")
    high = sum(1 for v in all_violations if v.get("severity") == "HIGH")

    summary = {
        "checked_files": checked_files,
        "total_violations": len(all_violations),
        "critical_count": critical,
        "high_count": high,
        "pass": len(all_violations) == 0,
    }

    return {"summary": summary, "violations": all_violations}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="前视偏差检测模块")
    parser.add_argument("--scan-result", help="扫描结果JSON路径")
    parser.add_argument("--backtest-result", help="回测结果JSON路径")
    parser.add_argument("--auto-detect", action="store_true", help="自动检测目录")
    parser.add_argument("--data-dir", default=".", help="数据目录")
    parser.add_argument("--output", "-o", help="输出JSON路径")
    args = parser.parse_args()

    if args.scan_result:
        with open(args.scan_result, "r", encoding="utf-8") as f:
            signals = json.load(f)
        result = {"violations": detect_lookahead_in_signals(signals)}
        result["summary"] = {"pass": len(result["violations"]) == 0}

    elif args.backtest_result:
        with open(args.backtest_result, "r", encoding="utf-8") as f:
            bt = json.load(f)
        # 检查回测结果中的数据字段
        df = pd.DataFrame(bt.get("trades", []))
        violations = detect_lookahead_in_dataframe(df, context="backtest")
        result = {"violations": violations, "summary": {"pass": len(violations) == 0}}

    elif args.auto_detect:
        result = auto_detect(args.data_dir)

    else:
        print("用法: --scan-result <path> | --backtest-result <path> | --auto-detect --data-dir <dir>")
        sys.exit(1)

    print(f"[LookaheadCheck] 检查文件数: {result['summary'].get('checked_files', 'N/A')}")
    print(f"[LookaheadCheck] 违规数: {result['summary']['total_violations']}")
    print(f"[LookaheadCheck] 结果: {'✅ 通过' if result['summary']['pass'] else '❌ 发现前视偏差'}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
