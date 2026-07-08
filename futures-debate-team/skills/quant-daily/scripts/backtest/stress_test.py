#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
压力测试模块 — 极端行情场景复刻
================================
P0-2: 回测体系全面加固 — 压力测试

复刻历史极端行情，验证策略在极端场景下的鲁棒性：
- 2020年原油负价事件（原油暴跌）
- 2022年大宗商品暴涨（俄乌冲突）
- 2015年股指期货限仓（A股暴跌）
- 2024年黑色系负反馈（螺纹钢产业链崩盘）

用法:
    python stress_test.py --scenario crude_2020 --symbols SC,RB
    python stress_test.py --scenario commodity_2022 --symbols RB,HC,I
    python stress_test.py --all-scenarios --symbols RB
"""

import sys, os, json, math
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np


# ── 预定义极端场景 ──
STRESS_SCENARIOS = {
    "crude_2020": {
        "name": "2020年原油负价事件",
        "period": ("2020-03-01", "2020-05-01"),
        "description": "WTI原油跌至负值，全球需求崩溃，恐慌性抛售",
        "impact_factor": {"SC": -3.0, "FU": -2.5, "BU": -2.0, "RB": -1.5, "HC": -1.5},
        "volatility_multiplier": 3.0,
        "liquidity_shock": True,
    },
    "commodity_2022": {
        "name": "2022年大宗商品暴涨",
        "period": ("2022-02-01", "2022-06-01"),
        "description": "俄乌冲突引发能源/粮食/金属全线暴涨",
        "impact_factor": {"SC": 2.5, "RB": 1.5, "HC": 1.5, "I": 2.0, "M": 2.0, "P": 2.0},
        "volatility_multiplier": 2.5,
        "liquidity_shock": False,
    },
    "a_share_2015": {
        "name": "2015年A股股灾+股指期货限仓",
        "period": ("2015-06-01", "2015-09-01"),
        "description": "A股暴跌，股指期货大幅贴水，交易所限仓",
        "impact_factor": {"IF": -3.0, "IC": -3.0, "IH": -3.0, "RB": -1.0, "HC": -1.0},
        "volatility_multiplier": 3.5,
        "liquidity_shock": True,
    },
    "black_2024": {
        "name": "2024年黑色系负反馈",
        "period": ("2024-03-01", "2024-07-01"),
        "description": "房地产下行→钢材需求萎缩→产业链负反馈",
        "impact_factor": {"RB": -2.0, "HC": -2.0, "I": -2.5, "J": -2.0, "JM": -2.0},
        "volatility_multiplier": 2.0,
        "liquidity_shock": False,
    },
    "custom": {
        "name": "自定义场景",
        "period": (None, None),
        "description": "用户自定义极端场景",
        "impact_factor": {},
        "volatility_multiplier": 2.0,
        "liquidity_shock": False,
    },
}


def load_historical_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """加载历史数据（使用MultiSourceAdapter）"""
    try:
        from data.multi_source_adapter import MultiSourceAdapter

        adapter = MultiSourceAdapter()
        df = adapter.get_kline(symbol, period="1d", start_date=start, end_date=end)
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception as e:
        print(f"[StressTest] 加载 {symbol} 数据失败: {e}")
        return pd.DataFrame()


def simulate_stress_scenario(
    symbol: str,
    scenario: Dict[str, Any],
    base_data: pd.DataFrame,
) -> Dict[str, Any]:
    """
    对单个品种在极端场景下进行模拟。

     Returns:
        {
            "symbol": str,
            "scenario": str,
            "max_drawdown": float,
            "volatility_increase": float,
            "liquidity_impact": float,
            "survival_rate": float,  # 策略在该场景下存活率
            "recommendation": str,   # 建议动作
        }
    """
    if base_data.empty:
        return {"symbol": symbol, "error": "无数据"}

    impact = scenario.get("impact_factor", {}).get(symbol, 0)
    vol_mult = scenario.get("volatility_multiplier", 2.0)
    liq_shock = scenario.get("liquidity_shock", False)

    # 计算基础波动率
    returns = base_data["close"].pct_change().dropna()
    base_vol = returns.std() * math.sqrt(252)

    # 模拟极端波动
    stressed_vol = base_vol * vol_mult

    # 模拟方向性冲击
    if impact != 0:
        stressed_returns = returns * (1 + abs(impact) * 0.5)
        if impact < 0:
            stressed_returns = -stressed_returns
    else:
        stressed_returns = returns * vol_mult

    # 模拟最大回撤
    cum_returns = (1 + stressed_returns).cumprod()
    running_max = cum_returns.expanding().max()
    drawdown = (cum_returns - running_max) / running_max
    max_dd = drawdown.min()

    # 存活率 = 最大回撤未超过20%的概率（简化）
    survival = max(0, 1 - abs(max_dd) / 0.20) if abs(max_dd) < 0.50 else 0.0

    # 建议动作
    if abs(max_dd) > 0.30:
        recommendation = "极端场景：暂停开仓，减仓至30%"
    elif abs(max_dd) > 0.20:
        recommendation = "高风险：减半仓位，收紧止损"
    elif abs(max_dd) > 0.10:
        recommendation = "中等风险：标准风控"
    else:
        recommendation = "低风险：正常操作"

    return {
        "symbol": symbol,
        "scenario": scenario["name"],
        "period": scenario["period"],
        "max_drawdown": round(float(max_dd), 4),
        "volatility_increase": round(float(vol_mult), 2),
        "liquidity_impact": "高" if liq_shock else "中",
        "survival_rate": round(float(survival), 4),
        "recommendation": recommendation,
    }


def run_stress_test(symbols: List[str], scenario_key: str = "all") -> Dict[str, Any]:
    """
    运行压力测试。

    Args:
        symbols: 品种列表
        scenario_key: 场景名或"all"运行所有场景

    Returns:
        {"summary": {...}, "results": [...]}
    """
    scenarios = [scenario_key] if scenario_key != "all" else list(STRESS_SCENARIOS.keys())[:-1]  # 排除custom

    all_results = []
    for sc_key in scenarios:
        scenario = STRESS_SCENARIOS.get(sc_key)
        if not scenario:
            continue

        start, end = scenario["period"]
        print(f"\n[StressTest] 场景: {scenario['name']} ({start} ~ {end})")

        for sym in symbols:
            df = load_historical_data(sym, start, end)
            result = simulate_stress_scenario(sym, scenario, df)
            all_results.append(result)
            print(f"  {sym}: MDD={result.get('max_drawdown', 'N/A')}, 建议={result.get('recommendation', 'N/A')}")

    # 汇总
    survival_rates = [r.get("survival_rate", 0) for r in all_results if "survival_rate" in r]
    avg_survival = sum(survival_rates) / max(len(survival_rates), 1)

    summary = {
        "scenario_count": len(scenarios),
        "symbol_count": len(symbols),
        "total_tests": len(all_results),
        "avg_survival_rate": round(avg_survival, 4),
        "pass_rate": round(sum(1 for s in survival_rates if s > 0.5) / max(len(survival_rates), 1), 4),
    }

    return {"summary": summary, "results": all_results}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="压力测试模块")
    parser.add_argument("--symbols", "-s", default="RB", help="品种代码（逗号分隔）")
    parser.add_argument("--scenario", default="all", help="场景名或all")
    parser.add_argument("--output", "-o", help="输出JSON路径")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    result = run_stress_test(symbols, args.scenario)

    print(f"\n[StressTest] 汇总: {json.dumps(result['summary'], ensure_ascii=False, indent=2)}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[StressTest] 结果已保存: {args.output}")
