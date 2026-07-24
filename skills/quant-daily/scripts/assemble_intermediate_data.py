#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据适配器：scan_all + chain_analysis(可选) → intermediate_data + debate_results
======================================================================
将双策略或单策略扫描产出适配为 phase3_generate_report.py 的输入格式。

兼容两种 scan 产出格式：
  1. 双策略 (--dual): summary["symbols"] 含子dict
  2. 单策略: summary["all_ranked"] 平铺dict列表

用法：
  python scripts/assemble_intermediate_data.py \\
    --summary <full_scan_*.json> \\
    [--chain-analysis <chain_analysis_clean.json>] \\
    [--chain-strategy <chain_strategy_report.json>] \\
    --output-dir <报告目录>
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime


def load_json(path: str) -> dict:
    """加载JSON文件，兼容纯JSON和混合格式"""
    content = open(path, "r", encoding="utf-8").read()
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        return json.loads(content[start : end + 1])
    return json.loads(content)


def _extract_symbols(summary: dict) -> tuple:
    """兼容双策略(symbols)和单策略(all_ranked)两种scan产出格式。

    返回 (items, format_type):
      format_type = "dual" → items含子dict
      format_type = "single" → items是平铺dict(all_ranked格式)
    """
    if "symbols" in summary and isinstance(summary["symbols"], list):
        items = summary["symbols"]
        if items and isinstance(items[0], dict) and "signal" in items[0]:
            return items, "dual"

    # 单策略模式: all_ranked 是平铺dict列表
    if "all_ranked" in summary and isinstance(summary["all_ranked"], list):
        items = summary["all_ranked"]
        if items and isinstance(items[0], dict) and "direction" in items[0]:
            return items, "single"

    # 兜底: 尝试 symbols 无子层（直接平铺）
    if "symbols" in summary and isinstance(summary["symbols"], list):
        items = summary["symbols"]
        if items and isinstance(items[0], dict) and "direction" in items[0]:
            return items, "single"

    return [], "unknown"


def _build_chain_map(chain_analysis: dict = None) -> dict:
    """构建品种→产业链映射。chain_analysis为None时使用内置SYMBOL_CHAIN_MAP"""
    chain_map = {}
    if chain_analysis and isinstance(chain_analysis, dict):
        chain_results_raw = chain_analysis.get("chain_results", {})
        for sym, info in chain_results_raw.items():
            if isinstance(info, dict):
                chain_map[sym.upper()] = info.get("chain", "未知")
    else:
        # 无 chain_analysis 时，从内置链映射构建
        try:
            _scripts_dir = os.path.dirname(os.path.abspath(__file__))
            if _scripts_dir not in sys.path:
                sys.path.insert(0, _scripts_dir)
            from config.settings import SYMBOL_CHAIN_MAP
            for sym, chain in SYMBOL_CHAIN_MAP.items():
                chain_map[sym.upper()] = chain
        except Exception:
            pass
    return chain_map


def build_intermediate(summary: dict, chain_analysis: dict = None, chain_strategy: dict = None) -> dict:
    """
    从 scan 产出 + chain_analysis(可选) 构建 intermediate_data.json。
    兼容双策略(--dual)和单策略两种格式。
    """
    meta = summary.get("_meta", {})
    items, format_type = _extract_symbols(summary)
    strategy_name = meta.get("strategy", "unknown")

    # ── 链映射构建 ──
    chain_map = _build_chain_map(chain_analysis)

    # 构建 chain_results（phase3_generate_report.py 需要 {name: {members: [...], ...}} 格式）
    chain_members = defaultdict(list)
    for sym, chain_name in chain_map.items():
        chain_members[chain_name].append(sym)

    chain_results = {}
    for chain_name in sorted(chain_members):
        members = chain_members[chain_name]
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

    # 构建 symbols_summary + all_actionable（格式感知）
    symbols_summary = []
    all_actionable = []

    if format_type == "dual":
        for s in items:
            sig = s.get("signal", {})
            sym = s["symbol"]
            price = sig.get("price", sig.get("last_price", 0))
            direction = "BUY" if sig.get("direction") == "bull" else ("SELL" if sig.get("direction") == "bear" else "HOLD")
            symbols_summary.append({
                "pid": sym,
                "product_name": s.get("name", sym),
                "direction": direction,
                "confidence": abs(sig.get("total", 0)) / 100.0,
                "price": price,
                "entry_price": price,
                "target_price": price * (1.05 if direction == "BUY" else 0.95),
                "stop_loss_price": price * (0.97 if direction == "BUY" else 1.03),
                "risk_reward_ratio": 1.5,
                "position_size": 5,
                "chain": chain_map.get(sym.upper(), ""),
                "score": sig.get("total", 0),
                "adx": sig.get("adx", 0),
                "signal_direction": direction,
                "decision": direction,
            })
            all_actionable.append(symbols_summary[-1])
    elif format_type == "single":
        for s in items:
            sym = s.get("symbol", "")
            price = s.get("price", s.get("last_price", 0))
            raw_dir = s.get("direction", "neutral")
            direction = "BUY" if raw_dir == "bull" else ("SELL" if raw_dir == "bear" else "HOLD")
            total = s.get("total", 0)
            grade = s.get("grade", "NOISE")
            symbols_summary.append({
                "pid": sym,
                "product_name": s.get("name", sym),
                "direction": direction,
                "confidence": abs(total) / 100.0,
                "price": price,
                "entry_price": price,
                "target_price": price * (1.05 if direction == "BUY" else 0.95),
                "stop_loss_price": price * (0.97 if direction == "BUY" else 1.03),
                "risk_reward_ratio": 1.5,
                "position_size": 5,
                "chain": chain_map.get(sym.upper(), ""),
                "score": total,
                "grade": grade,
                "z_score": s.get("z_score", 0),
                "adx": s.get("adx", 0),
                "rsi": s.get("rsi", s.get("RSI14", 50)),
                "stage": s.get("stage", ""),
                "macd_cross": s.get("macd_cross", ""),
                "dc20_break": s.get("dc20_break", ""),
                "signal_direction": direction,
                "decision": direction,
                "l1": s.get("l1", 0),
                "l2": s.get("l2", 0),
                "l3": s.get("l3", 0),
                "l4": s.get("l4", 0),
                "cons": s.get("cons", 0),
            })
            all_actionable.append(symbols_summary[-1])

    # 获取 tdx_bridge 可用性
    tdx_available = False
    try:
        _scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        from indicators.tdx_bridge import get_bridge
        tdx_available = get_bridge().available
    except Exception:
        pass

    return {
        "data_source": f"scan_all.py ({strategy_name}, quant-daily)",
        "format_type": format_type,
        "data_benchmark": datetime.now().strftime("%Y-%m-%d"),
        "symbols_count": len(symbols_summary),
        "tdx_bridge_available": tdx_available,
        "indicator_source": "通达信TQ-Local + numpy兜底",
        "all_actionable": all_actionable,
        "chain_results": chain_results,
        "symbols_summary": symbols_summary,
        "BUY_top5": [s["pid"] for s in sorted(symbols_summary, key=lambda x: x.get("score", 0), reverse=True)[:5]],
        "SELL_top5": [s["pid"] for s in sorted(symbols_summary, key=lambda x: -abs(x.get("score", 0)))[:5]],
        "_meta": {
            "strategy": strategy_name,
            "format_type": format_type,
            "tdx_bridge_available": tdx_available,
            "indicator_source": "通达信TQ-Local + numpy兜底",
        },
    }


def build_debate_results(summary: dict, chain_analysis: dict = None, candidates: dict = None) -> dict:
    """
    从 scan 产出 + chain_analysis(可选) + candidates 构建 debate_results.json。
    兼容双策略和单策略格式。
    """
    meta = summary.get("_meta", {})
    items, format_type = _extract_symbols(summary)
    chain_map = _build_chain_map(chain_analysis)

    results = {}
    for s in items:
        sym = s.get("symbol", "")
        if format_type == "dual":
            sig = s.get("signal", {})
            l_dir = sig.get("direction", "neutral")
            l_total = sig.get("total", 0)
            eng_dir = "BUY" if l_dir == "bull" else ("SELL" if l_dir == "bear" else "HOLD")
            raw_conf = abs(l_total)
        else:
            # 单策略模式
            raw_dir = s.get("direction", "neutral")
            eng_dir = "BUY" if raw_dir == "bull" else ("SELL" if raw_dir == "bear" else "HOLD")
            l_total = s.get("total", 0)
            raw_conf = abs(l_total)

        conf = min(90, max(20, raw_conf * 0.7))
        grade = s.get("grade", "NOISE")

        result = {
            "direction": eng_dir,
            "confidence": conf,
            "grade": grade,
            "judge_verdict": {
                "final_direction": eng_dir,
                "confidence": conf,
                "grade": grade,
            },
            "chain": chain_map.get(sym.upper(), ""),
            "l1l4_score": l_total,
            "z_score": s.get("z_score", 0),
            "divergence": False,
        }

        # 如果有候选品种数据，标记是否为直接推荐/观察级
        if candidates:
            for rec in candidates.get("trading_recommendations", []):
                if rec["symbol"].upper() == sym.upper():
                    result["source_path"] = "direct_recommend"
                    result["recommendation"] = "STRONG_RECOMMEND"
                    break
            for w in candidates.get("watch_list", []):
                if w["symbol"].upper() == sym.upper():
                    result["source_path"] = "watch"
                    result["recommendation"] = "WATCH"
                    break

        results[sym] = result

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="数据适配器: scan_all + chain_analysis(可选) → intermediate_data + debate_results"
    )
    parser.add_argument("--summary", required=True, help="scan产出JSON路径 (full_scan_*.json 或 scan_daily_*.json)")
    parser.add_argument("--chain-analysis", default=None, help="chain_analysis_clean.json 路径（可选，缺失时用内置链映射）")
    parser.add_argument("--candidates", default=None, help="debate_brief.py --select-debate 产出的candidates JSON路径（可选）")
    parser.add_argument("--chain-strategy", default=None, help="chain_strategy_report.json 路径（可选）")
    parser.add_argument("--output-dir", default=".", help="输出目录（默认为当前目录）")
    parser.add_argument("--prefix", default="", help="输出文件前缀")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    summary = load_json(args.summary)
    chain_analysis = load_json(args.chain_analysis) if args.chain_analysis else None
    chain_strategy = load_json(args.chain_strategy) if args.chain_strategy else None
    candidates = load_json(args.candidates) if args.candidates else None

    # 生成 intermediate_data.json
    intermediate = build_intermediate(summary, chain_analysis, chain_strategy)
    if candidates:
        intermediate["trading_recommendations"] = candidates.get("trading_recommendations", [])
        intermediate["watch_list"] = candidates.get("watch_list", [])
        intermediate["candidates_meta"] = candidates.get("_meta", {})
        print(f"  [双通道] 直接推荐: {len(intermediate['trading_recommendations'])}个 | 观察级: {len(intermediate['watch_list'])}个")
    im_path = os.path.join(args.output_dir, f"{args.prefix}intermediate_data.json")
    with open(im_path, "w", encoding="utf-8") as f:
        json.dump(intermediate, f, ensure_ascii=False, indent=2)
    print(f"[OK] intermediate_data: {im_path}")

    # 生成 debate_results.json
    debate_results = build_debate_results(summary, chain_analysis, candidates)
    dr_path = os.path.join(args.output_dir, f"{args.prefix}debate_results.json")
    with open(dr_path, "w", encoding="utf-8") as f:
        json.dump(debate_results, f, ensure_ascii=False, indent=2)
    print(f"[OK] debate_results: {dr_path}")

    # 统计
    all_s = intermediate.get("symbols_summary", [])
    buys = sum(1 for s in all_s if s.get("direction") == "BUY")
    sells = sum(1 for s in all_s if s.get("direction") == "SELL")
    holds = sum(1 for s in all_s if s.get("direction") == "HOLD")
    print(f"\n统计: {len(all_s)}品种 | 多头{buys} / 空头{sells} / 中性{holds}")
    print(f"    {len(intermediate.get('chain_results', {}))}条产业链")
    print("\n用法: python skills/futures-trading-analysis/scripts/phase3_generate_report.py")
    print("  (假定 intermediate_data.json 和 debate_results.json 均在输出目录)")
