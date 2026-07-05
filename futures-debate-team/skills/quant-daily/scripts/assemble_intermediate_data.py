#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据适配器：scan_all + chain_analysis → intermediate_data + debate_results
======================================================================
将双策略扫描产出适配为 phase3_generate_report.py 的输入格式。

用法：
  python scripts/assemble_intermediate_data.py \\
    --summary <full_scan_summary_*.json> \\
    --chain-analysis <chain_analysis_clean.json> \\
    --chain-strategy <chain_strategy_report.json> \\
    --output-dir <报告目录>

这消灭了以下几类胶水代码：
  ❌ 手动写 Python -c 查询信号/链分类/分歧统计
  ❌ 临时生成 generate_debate_report.py
  ❌ 手动拼接 full_data_js.json
"""

import json
import os
import sys
from datetime import datetime


def load_summary(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_chain_analysis(path: str) -> dict:
    content = open(path, 'r', encoding='utf-8').read()
    start = content.find('{')
    end = content.rfind('}')
    if start >= 0 and end > start:
        return json.loads(content[start:end + 1])
    raise ValueError(f"未在{path}中找到JSON数据")


def build_intermediate(summary: dict, chain_analysis: dict,
                       chain_strategy: dict = None) -> dict:
    """
    从 full_scan_summary + chain_analysis 构建 intermediate_data.json。
    """
    meta = summary.get("_meta", {})
    symbols = summary.get("symbols", [])

    # 提取链映射
    chain_results_raw = chain_analysis.get("chain_results", {})
    chain_map = {}
    for sym, info in chain_results_raw.items():
        if isinstance(info, dict):
            chain_map[sym.upper()] = info.get("chain", "未知")

    # 构建 chain_results（phase3_generate_report.py 需要 {name: {members: [...], ...}} 格式）
    from collections import defaultdict
    chain_members = defaultdict(list)
    for sym, chain_name in chain_map.items():
        chain_members[chain_name].append(sym)

    chain_results = {}
    for chain_name in sorted(chain_members):
        members = chain_members[chain_name]
        # 从 chain_strategy 获取趋势数据（如果有）
        trend_data = {}
        if chain_strategy and isinstance(chain_strategy, dict):
            cs = chain_strategy.get("chain_summary", {})
            if chain_name in cs:
                trend_data = cs[chain_name]
        chain_results[chain_name] = {
            "members": members,
            "count": len(members),
            "avg_score": trend_data.get("avg_score", 0),
            "overall_trend": trend_data.get("trend", "中性"),
            "direction_counts": {
                "BUY": trend_data.get("buy_count", 0),
                "SELL": trend_data.get("sell_count", 0),
            },
        }

    # 构建 symbols_summary
    symbols_summary = []
    all_actionable = []
    for s in symbols:
        l1l4 = s.get("l1l4", {})
        factor = s.get("factor_timing", {})
        sym = s["symbol"]
        price = l1l4.get("price", l1l4.get("last_price", 0))
        direction = "BUY" if l1l4.get("direction") == "bull" else (
            "SELL" if l1l4.get("direction") == "bear" else "HOLD")
        symbols_summary.append({
            "pid": sym,
            "product_name": s.get("name", sym),
            "direction": direction,
            "confidence": abs(l1l4.get("total", 0)) / 100.0,
            "price": price,
            "entry_price": price,
            "target_price": price * (1.05 if direction == "BUY" else 0.95),
            "stop_loss_price": price * (0.97 if direction == "BUY" else 1.03),
            "risk_reward_ratio": 1.5,
            "position_size": 5,
            "chain": chain_map.get(sym.upper(), ""),
            "score": l1l4.get("total", 0),
            "adx": l1l4.get("adx", 0),
            "signal_direction": direction,
            "decision": direction,
        })
        all_actionable.append(symbols_summary[-1])

    # 获取 tdx_bridge 可用性
    tdx_available = False
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                          "quant-daily", "scripts"))
        from indicators.tdx_bridge import get_bridge
        tdx_available = get_bridge().available
    except Exception:
        pass

    return {
        "data_source": "scan_all.py --dual (quant-daily)",
        "data_benchmark": datetime.now().strftime("%Y-%m-%d"),
        "symbols_count": len(symbols_summary),
        "tdx_bridge_available": tdx_available,
        "indicator_source": "通达信TQ-Local + numpy兜底",
        "all_actionable": all_actionable,
        "chain_results": chain_results,
        "symbols_summary": symbols_summary,
        "BUY_top5": [s["pid"] for s in sorted(
            symbols_summary, key=lambda x: x.get("score", 0), reverse=True)[:5]],
        "SELL_top5": [s["pid"] for s in sorted(
            symbols_summary, key=lambda x: -abs(x.get("score", 0)))[:5]],
        "_meta": {
            "tdx_bridge_available": tdx_available,
            "indicator_source": "通达信TQ-Local + numpy兜底",
        },
    }


def build_debate_results(summary: dict, chain_analysis: dict) -> dict:
    """
    从 full_scan_summary + chain_analysis 构建 debate_results.json。
    """
    meta = summary.get("_meta", {})
    symbols = summary.get("symbols", [])

    chain_results_raw = chain_analysis.get("chain_results", {})
    judge_verdict = chain_analysis.get("judge_verdict", {})

    results = {}
    for s in symbols:
        sym = s["symbol"]
        l1l4 = s.get("l1l4", {})
        factor = s.get("factor_timing", {})
        l_dir = l1l4.get("direction", "neutral")
        f_dir = factor.get("direction", "neutral")
        l_total = l1l4.get("total", 0)
        f_total = factor.get("total", 0)

        # 方向映射
        direction_map = {
            ("bull", "bull"): "BUY", ("bear", "bear"): "SELL",
        }
        eng_dir = direction_map.get((l_dir, f_dir), "HOLD")

        # 置信度估算
        raw_conf = (abs(l_total) + abs(f_total)) / 2
        conf = min(90, max(20, raw_conf * 0.7))

        results[sym] = {
            "direction": eng_dir,
            "confidence": conf,
            "judge_verdict": {
                "final_direction": eng_dir,
                "confidence": conf,
                "reasoning": f"L1-L4={l_dir}({l_total:+d}), 因子择时={f_dir}({f_total:+d})",
            },
            "chain": chain_results_raw.get(sym.upper(), {}).get("chain", ""),
            "l1l4_score": l_total,
            "factor_score": f_total,
            "divergence": l_dir != f_dir and l_dir != "neutral" and f_dir != "neutral",
        }

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="数据适配器: scan_all + chain_analysis → intermediate_data + debate_results")
    parser.add_argument("--summary", required=True,
                        help="full_scan_summary_YYYYMMDD.json 路径")
    parser.add_argument("--chain-analysis", required=True,
                        help="chain_analysis_clean.json 路径")
    parser.add_argument("--chain-strategy", default=None,
                        help="chain_strategy_report.json 路径（可选）")
    parser.add_argument("--output-dir", default=".",
                        help="输出目录（默认为当前目录）")
    parser.add_argument("--prefix", default="", help="输出文件前缀")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    summary = load_summary(args.summary)
    chain_analysis = load_chain_analysis(args.chain_analysis)
    chain_strategy = load_chain_analysis(args.chain_strategy) if args.chain_strategy else None

    # 生成 intermediate_data.json
    intermediate = build_intermediate(summary, chain_analysis, chain_strategy)
    im_path = os.path.join(args.output_dir, f"{args.prefix}intermediate_data.json")
    with open(im_path, 'w', encoding='utf-8') as f:
        json.dump(intermediate, f, ensure_ascii=False, indent=2)
    print(f"[OK] intermediate_data: {im_path}")

    # 生成 debate_results.json
    debate_results = build_debate_results(summary, chain_analysis)
    dr_path = os.path.join(args.output_dir, f"{args.prefix}debate_results.json")
    with open(dr_path, 'w', encoding='utf-8') as f:
        json.dump(debate_results, f, ensure_ascii=False, indent=2)
    print(f"[OK] debate_results: {dr_path}")

    # 统计
    all_s = intermediate.get("symbols_summary", [])
    buys = sum(1 for s in all_s if s.get("direction") == "BUY")
    sells = sum(1 for s in all_s if s.get("direction") == "SELL")
    print(f"\n统计: {len(all_s)}品种 | 多头{buys} / 空头{sells}")
    print(f"    {len(intermediate.get('chain_results', {}))}条产业链")
    print(f"\n用法: python skills/futures-trading-analysis/scripts/phase3_generate_report.py")
    print(f"  (假定 intermediate_data.json 和 debate_results.json 均在输出目录)")
