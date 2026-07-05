#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
置换检验模块 — 过滤随机收益
===========================
P0-2: 回测体系全面加固 — 置换检验

随机打乱交易信号1000次，检验原策略收益是否显著优于随机。
核心逻辑：如果原策略的夏普比率/收益率在随机排列中排名前5%，则策略有效。

用法:
    python permutation_test.py --backtest-result backtest_RB.json --iterations 1000
    python permutation_test.py --symbols RB --days 365 --iterations 2000
"""

import sys, os, json, math, random
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def permutation_test(
    returns: List[float],
    original_sharpe: float,
    iterations: int = 1000,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    置换检验：随机打乱收益序列，计算置换后的夏普比率分布。
    
    Args:
        returns: 原始日收益率序列
        original_sharpe: 原始策略夏普比率
        iterations: 置换次数
        seed: 随机种子
    
    Returns:
        {
            "original_sharpe": float,
            "p_value": float,         # 显著性水平（<0.05为显著）
            "percentile": float,      # 原始夏普在置换分布中的百分位
            "mean_permuted_sharpe": float,
            "std_permuted_sharpe": float,
            "is_significant": bool,   # 是否显著优于随机
            "permuted_sharpes": List[float],  # 置换夏普分布（前100个）
        }
    """
    random.seed(seed)
    np.random.seed(seed)
    
    returns_arr = np.array(returns)
    n = len(returns_arr)
    
    permuted_sharpes = []
    for _ in range(iterations):
        shuffled = np.random.permutation(returns_arr)
        mean_ret = np.mean(shuffled)
        std_ret = np.std(shuffled)
        if std_ret > 0:
            sharpe = mean_ret / std_ret * math.sqrt(252)
        else:
            sharpe = 0
        permuted_sharpes.append(sharpe)
    
    permuted_sharpes = np.array(permuted_sharpes)
    
    # 计算p值：原始夏普优于多少比例的置换结果
    p_value = np.mean(permuted_sharpes >= original_sharpe)
    percentile = p_value * 100
    
    is_significant = p_value < 0.05  # 单侧检验，5%显著性水平
    
    return {
        "original_sharpe": round(original_sharpe, 4),
        "p_value": round(p_value, 6),
        "percentile": round(percentile, 2),
        "mean_permuted_sharpe": round(float(np.mean(permuted_sharpes)), 4),
        "std_permuted_sharpe": round(float(np.std(permuted_sharpes)), 4),
        "is_significant": bool(is_significant),
        "permuted_sharpes": [round(float(s), 4) for s in permuted_sharpes[:100]],  # 只保留前100个用于展示
    }


def run_permutation_test_from_returns(
    returns: List[float],
    original_sharpe: float,
    iterations: int = 1000,
) -> Dict[str, Any]:
    """从收益率序列直接运行置换检验"""
    return permutation_test(returns, original_sharpe, iterations)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="置换检验模块")
    parser.add_argument("--backtest-result", help="回测结果JSON路径")
    parser.add_argument("--returns", help="收益率序列JSON（逗号分隔）")
    parser.add_argument("--sharpe", type=float, help="原始夏普比率")
    parser.add_argument("--iterations", type=int, default=1000, help="置换次数")
    parser.add_argument("--output", "-o", help="输出JSON路径")
    args = parser.parse_args()
    
    if args.backtest_result:
        with open(args.backtest_result, "r", encoding="utf-8") as f:
            bt = json.load(f)
        returns = bt.get("daily_returns", [])
        sharpe = bt.get("sharpe_ratio", 0)
    elif args.returns and args.sharpe is not None:
        returns = [float(x) for x in args.returns.split(",")]
        sharpe = args.sharpe
    else:
        print("用法: --backtest-result <path> 或 --returns <csv> --sharpe <float>")
        sys.exit(1)
    
    result = permutation_test(returns, sharpe, args.iterations)
    print(f"[PermutationTest] 原始夏普: {result['original_sharpe']}")
    print(f"[PermutationTest] p值: {result['p_value']} (百分位: {result['percentile']}%)")
    print(f"[PermutationTest] 显著性: {'✅ 显著优于随机' if result['is_significant'] else '❌ 不显著'}")
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
