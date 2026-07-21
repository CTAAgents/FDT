#!/usr/bin/env python3
"""
update_matrix.py — 品种×策略族适应性矩阵更新脚本

基于 OmniOpt 论文的分类法方法论，每次闫判官裁决 + 实际行情验证后，
用 EMA 在线更新各品种在各策略族（F1-F5）上的历史胜率权重。

调用方式:
    python scripts/update_matrix.py             # 批量更新（从 latest debate 读取）
    python scripts/update_matrix.py --symbol rb --family F1 --correct 1  # 单条更新

依赖: numpy (可选，用于 EMA 计算)
"""

import json
import os
import sys
import argparse
from datetime import datetime

MATRIX_PATH = os.path.join(os.path.dirname(__file__), "..", "memory",
                           "instrument_strategy_matrix.json")
LEARNING_RATE = 0.3
MIN_SAMPLES = 3


def load_matrix() -> dict:
    """加载品种适应性矩阵"""
    if not os.path.exists(MATRIX_PATH):
        return {
            "meta": {
                "version": "1.0",
                "created_at": datetime.now().strftime("%Y-%m-%d"),
                "description": "品种×策略族适应性矩阵",
                "learning_rate": LEARNING_RATE,
                "min_samples": MIN_SAMPLES,
            },
            "data": {},
        }
    with open(MATRIX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_matrix(matrix: dict) -> None:
    """保存品种适应性矩阵"""
    with open(MATRIX_PATH, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=2, ensure_ascii=False)
    print(f"[update_matrix] ✅ 矩阵已保存: {MATRIX_PATH}")


def ensure_symbol(matrix: dict, symbol: str, display_name: str = "", chain: str = "") -> None:
    """确保品种在矩阵中存在，不存在则按默认值创建"""
    if symbol not in matrix["data"]:
        # 按产业链推断默认值
        chain_defaults = {
            "黑色系":    {"F1": 0.70, "F2": 0.65, "F3": 0.45, "F4": 0.30, "F5": 0.55},
            "有色金属":  {"F1": 0.45, "F2": 0.55, "F3": 0.60, "F4": 0.75, "F5": 0.70},
            "能源化工":  {"F1": 0.40, "F2": 0.42, "F3": 0.55, "F4": 0.85, "F5": 0.60},
            "农产品":    {"F1": 0.50, "F2": 0.75, "F3": 0.35, "F4": 0.30, "F5": 0.40},
            "贵金属":    {"F1": 0.42, "F2": 0.38, "F3": 0.48, "F4": 0.82, "F5": 0.35},
            "聚酯链":    {"F1": 0.55, "F2": 0.68, "F3": 0.40, "F4": 0.45, "F5": 0.62},
        }
        defaults = chain_defaults.get(chain, chain_defaults["能源化工"])  # 默认能源化工
        matrix["data"][symbol] = {
            "display_name": display_name or symbol,
            "chain": chain or "未知",
            "families": {
                f: {"v": 0, "w": defaults[f], "updated": datetime.now().strftime("%Y-%m-%d")}
                for f in ["F1", "F2", "F3", "F4", "F5"]
            },
        }
        print(f"[update_matrix] 🆕 新品种 {symbol} 已创建 (chain={chain})")
    return matrix


def update_family(matrix: dict, symbol: str, family_code: str, was_correct: bool) -> None:
    """
    EMA 在线更新某一策略族在特定品种上的权重。

    Formula: w_new = w_old + lr * (was_correct - w_old)
    钳制: [0.05, 0.95]

    Args:
        matrix: 矩阵数据
        symbol: 品种代码
        family_code: 策略族 "F1"-"F5"
        was_correct: 该论据方向是否被后市验证正确
    """
    entry = matrix["data"].get(symbol)
    if not entry:
        print(f"[update_matrix] ⚠️ 品种 {symbol} 不存在，跳过")
        return

    fam = entry["families"].get(family_code)
    if not fam:
        print(f"[update_matrix] ⚠️ 品种 {symbol} 的策略族 {family_code} 不存在，跳过")
        return

    fam["v"] += 1
    lr = matrix["meta"]["learning_rate"]
    target = 1.0 if was_correct else 0.0
    old_w = fam["w"]
    fam["w"] = round(old_w + lr * (target - old_w), 3)
    fam["w"] = max(0.05, min(0.95, fam["w"]))
    fam["updated"] = datetime.now().strftime("%Y-%m-%d")

    print(f"[update_matrix] 📊 {symbol}.{family_code}: w={old_w:.3f} → {fam['w']:.3f} "
          f"(correct={int(was_correct)}, v={fam['v']})")


def batch_update(symbol: str, family_results: list, display_name: str = "", chain: str = "") -> None:
    """
    批量更新一个品种的多个策略族权重。

    Args:
        symbol: 品种代码
        family_results: dict of {family_code: was_correct}
        display_name: 品种显示名（可选，新建时使用）
        chain: 产业链（可选，新建时使用）
    """
    matrix = load_matrix()
    matrix = ensure_symbol(matrix, symbol, display_name, chain)
    for family_code, was_correct in family_results.items():
        update_family(matrix, symbol, family_code, was_correct)
    save_matrix(matrix)


def parse_verdicts(debate_results_path: str) -> list:
    """
    从 debate_results.json 中解析裁决结果并更新矩阵。
    注意：此函数为存根设计，实际使用时需对接行情验证流程。

    Args:
        debate_results_path: debate_results.json 路径
    """
    if not os.path.exists(debate_results_path):
        print(f"[update_matrix] ⚠️ 未找到 {debate_results_path}，跳过批量更新")
        return

    with open(debate_results_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    # TODO: 对接行情验证流程，获取各策略族论据的实际正确性
    # 当前为占位逻辑，每个品种的所有族标记为 True（视作验证通过）
    verdicts = results.get("verdicts", {})
    for symbol, v in verdicts.items():
        chain = v.get("chain", "")
        display_name = v.get("name", symbol)
        family_results = {"F1": True, "F2": True, "F3": True, "F4": True, "F5": True}
        batch_update(symbol, family_results, display_name, chain)


def main() -> None:
    parser = argparse.ArgumentParser(description="品种×策略族适应性矩阵更新")
    parser.add_argument("--symbol", "-s", type=str, help="品种代码")
    parser.add_argument("--family", "-f", type=str, choices=["F1", "F2", "F3", "F4", "F5"],
                        help="策略族代码")
    parser.add_argument("--correct", "-c", type=int, choices=[0, 1],
                        help="论据方向是否被后市验证正确 (1=正确, 0=错误)")
    parser.add_argument("--batch", "-b", type=str,
                        help="从 debate_results.json 批量更新")
    parser.add_argument("--name", "-n", type=str, default="", help="品种显示名")
    parser.add_argument("--chain", type=str, default="", help="产业链")

    args = parser.parse_args()

    if args.batch:
        parse_verdicts(args.batch)
    elif args.symbol and args.family and args.correct is not None:
        batch_update(args.symbol, {args.family: bool(args.correct)},
                     args.name, args.chain)
    else:
        print("用法:")
        print("  python scripts/update_matrix.py --symbol rb --family F1 --correct 1")
        print("  python scripts/update_matrix.py --batch debate_results.json")
        sys.exit(1)


if __name__ == "__main__":
    main()
