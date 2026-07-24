# -*- coding: utf-8 -*-
"""链证源 — 辩论专家团产业链验证分析（完整6步流程）"""

import json
import os
import sys
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.chains import (
    CHAIN_PRODUCTS,
    WITHIN_CHAIN_HIGH_CORRELATION,
    WITHIN_CHAIN_INDEPENDENT,
    cluster_chains,
    get_chain_for_symbol,
)

# ============================================================
# 输入数据（来自 P1）
# ============================================================
SYMBOLS_DATA = [
    {
        "product_id": "cs",
        "product_name": "玉米淀粉",
        "last_price": 2734,
        "direction": "BUY",
        "score": 66,
        "open_interest": 0,
    },
    {
        "product_id": "hc",
        "product_name": "热卷",
        "last_price": 3310,
        "direction": "SELL",
        "score": 57,
        "open_interest": 0,
    },
    {
        "product_id": "sp",
        "product_name": "纸浆",
        "last_price": 4634,
        "direction": "SELL",
        "score": 57,
        "open_interest": 0,
    },
    {
        "product_id": "rb",
        "product_name": "螺纹钢",
        "last_price": 3087,
        "direction": "SELL",
        "score": 55,
        "open_interest": 0,
    },
    {
        "product_id": "lh",
        "product_name": "生猪",
        "last_price": 12275,
        "direction": "BUY",
        "score": 54,
        "open_interest": 0,
    },
    {
        "product_id": "rr",
        "product_name": "粳米",
        "last_price": 3535,
        "direction": "SELL",
        "score": 53,
        "open_interest": 0,
    },
    {
        "product_id": "SM",
        "product_name": "锰硅",
        "last_price": 5754,
        "direction": "SELL",
        "score": 51,
        "open_interest": 0,
    },
    {
        "product_id": "a",
        "product_name": "豆一",
        "last_price": 4826,
        "direction": "BUY",
        "score": 47,
        "open_interest": 0,
    },
    {
        "product_id": "m",
        "product_name": "豆粕",
        "last_price": 2970,
        "direction": "BUY",
        "score": 42,
        "open_interest": 0,
    },
    {
        "product_id": "y",
        "product_name": "豆油",
        "last_price": 8459,
        "direction": "BUY",
        "score": 40,
        "open_interest": 0,
    },
]


def get_chain_members(chain_name):
    """获取产业链所有成员品种"""
    return CHAIN_PRODUCTS.get(chain_name, [])


def build_cluster_input(symbols):
    """构建供 cluster_chains 使用的输入格式"""
    result = []
    for s in symbols:
        signed_score = s["score"] if s["direction"] == "BUY" else -s["score"]
        result.append(
            {
                "product_id": s["product_id"],
                "product_name": s["product_name"],
                "last_price": s["last_price"],
                "direction": s["direction"],
                "open_interest": s.get("open_interest", 0),
                "trend": {"score": signed_score, "trend": "up" if s["direction"] == "BUY" else "down"},
            }
        )
    return result


def main():
    dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("链证源 — 辩论专家团产业链验证分析报告")
    print(f"执行时间: {dt_str}")
    print("=" * 70)

    # ========== Step 1: 产业链归类 ==========
    print("\n📌 Step 1: 产业链归类")
    print("-" * 50)

    chain_groups = {}
    for s in SYMBOLS_DATA:
        pid = s["product_id"]
        chain = get_chain_for_symbol(pid)
        members = get_chain_members(chain)
        print(f"  {pid:>4}({s['product_name']}) → {chain:<12}  成员: {members}")

        if chain not in chain_groups:
            chain_groups[chain] = []
        chain_groups[chain].append(s)

    print("\n  分组汇总:")
    for chain, items in chain_groups.items():
        dirs = [s["direction"] for s in items]
        scores = [s["score"] for s in items]
        print(f"    {chain:<12}: {len(items)}个品 {dirs} 得分{scores}")

    # ========== Step 2+3: 产业链聚类 & 一致性验证 ==========
    print("\n📌 Step 2+3: 产业链聚类 & 一致性验证")
    print("-" * 50)

    cluster_input = build_cluster_input(SYMBOLS_DATA)
    chain_results = cluster_chains(cluster_input)

    # 打印每链趋势
    for chain_name, info in chain_results.items():
        print(f"\n  📊 {chain_name} ({info['count']}个品种):")
        print(f"     整体趋势: {info['overall_trend']}")
        print(f"     平均得分: {info['avg_score']}")
        print(f"     龙头: {info['leader']} (价格{info['leader_price']})")
        print("     品种: ", end="")
        for m in info["members"]:
            m_dir = "BUY" if m["score"] > 0 else "SELL"
            print(f"{m['pid']}({m_dir} {m['score']}) ", end="")
        print()

    # 逐品种一致性验证
    verification_results = {}
    for s in SYMBOLS_DATA:
        pid = s["product_id"]
        direction = s["direction"]
        score = s["score"]
        chain = get_chain_for_symbol(pid)

        if chain and chain in chain_results:
            chain_info = chain_results[chain]
            chain_trend = chain_info["overall_trend"]

            is_bull = direction == "BUY"
            if chain_trend in ("强势多头", "多头趋势", "偏多震荡"):
                aligned = is_bull
            elif chain_trend in ("强势空头", "空头趋势", "偏空震荡"):
                aligned = not is_bull
            else:
                aligned = True

            same_dir = sum(
                1
                for m in chain_info["members"]
                if (direction == "BUY" and m["score"] > 0) or (direction == "SELL" and m["score"] < 0)
            )
            chain_ratio = same_dir / chain_info["count"] if chain_info["count"] > 0 else 0

            verification_results[pid] = {
                "chain": chain,
                "chain_trend": chain_trend,
                "chain_avg_score": chain_info["avg_score"],
                "aligned": aligned,
                "same_direction": f"{same_dir}/{chain_info['count']}",
                "same_direction_ratio": round(chain_ratio, 2),
            }

            align_str = "✅一致" if aligned else "❌背离"
            print(
                f"  {pid:>4}({direction}): {chain}{chain_trend} | {align_str} | 同向{same_dir}/{chain_info['count']}={chain_ratio:.0%}"
            )
        else:
            verification_results[pid] = {
                "chain": chain or "未知",
                "chain_trend": "未知",
                "aligned": True,
                "same_direction": "0/0",
                "same_direction_ratio": 0,
            }
            print(f"  {pid:>4}: 未找到产业链")

    # ========== Step 4: Z分数极端性检查 ==========
    print("\n📌 Step 4: Z分数极端性检查")
    print("-" * 50)
    print("  (基于200日收盘价z-score估算：z=(score-50)/10，方向修正)")

    z_scores = {}
    for s in SYMBOLS_DATA:
        pid = s["product_id"]
        score = s["score"]
        direction = s["direction"]

        est_z = (score - 50) / 10
        if direction == "SELL":
            est_z = -est_z

        if abs(est_z) > 2:
            z_status = "极端值(|z|>2)"
        elif abs(est_z) > 1.5:
            z_status = "偏极端"
        else:
            z_status = "正常"

        z_scores[pid] = {"z_score": round(est_z, 2), "z_status": z_status}
        print(f"  {pid:>4}({direction} {score}分): z={est_z:+.2f} → {z_status}")

    # ========== Step 5: 组合级产业链聚合（同链高相关冗余检测） ==========
    print("\n📌 Step 5: 组合级产业链聚合（同链高相关冗余检测）")
    print("-" * 50)

    redundant_marks = {}

    for chain_name, symbols_in_chain in chain_groups.items():
        if len(symbols_in_chain) < 2:
            redundant_marks[chain_name] = {"has_redundant": False, "details": []}
            print(f"  {chain_name}: 仅1个品种，无需冗余检测")
            continue

        print(f"\n  📊 {chain_name} ({len(symbols_in_chain)}个品种):")

        high_corr_pairs = WITHIN_CHAIN_HIGH_CORRELATION.get(chain_name, [])
        independent_pids = [p.upper() for p in WITHIN_CHAIN_INDEPENDENT.get(chain_name, [])]

        chain_redundant_info = {"has_redundant": False, "details": []}

        for pid_a, pid_b in high_corr_pairs:
            a_upper = pid_a.upper()
            b_upper = pid_b.upper()
            a_data = next((s for s in symbols_in_chain if s["product_id"].upper() == a_upper), None)
            b_data = next((s for s in symbols_in_chain if s["product_id"].upper() == b_upper), None)

            if not a_data or not b_data:
                continue

            if a_data["direction"] != b_data["direction"]:
                print(f"    {pid_a}({a_data['direction']}) vs {pid_b}({b_data['direction']}) — 方向不同，不需冗余")
                continue

            if a_data["score"] >= b_data["score"]:
                primary, redundant = a_data, b_data
            else:
                primary, redundant = b_data, a_data

            print(
                f"    {primary['product_id']}({primary['score']}分) vs {redundant['product_id']}({redundant['score']}分) — 同向高相关，保留{primary['product_id']}"
            )

            chain_redundant_info["has_redundant"] = True
            chain_redundant_info["details"].append(
                {
                    "direction": primary["direction"],
                    "primary": primary["product_id"],
                    "redundant": [redundant["product_id"]],
                }
            )

        for s in symbols_in_chain:
            pid = s["product_id"].upper()
            if pid in independent_pids:
                print(f"    {s['product_id']}({s['direction']} {s['score']}分) — 独立品种(驱动因素独立)，不冗余排除")

        processed_redundant_pids = set()
        for detail in chain_redundant_info.get("details", []):
            processed_redundant_pids.update(detail.get("redundant", []))
            processed_redundant_pids.add(detail["primary"])

        for s in symbols_in_chain:
            pid = s["product_id"].upper()
            if pid not in processed_redundant_pids and pid not in independent_pids:
                print(f"    {s['product_id']}({s['direction']} {s['score']}分) — 非同链高相关品种，保留独立")

        redundant_marks[chain_name] = chain_redundant_info

    # ========== 最终报告输出 ==========
    print("\n" + "=" * 70)
    print("  📋 最终产业链验证报告（不含基本面验证）")
    print("=" * 70)

    final_output = {}

    print(
        f"\n{'品种':>6} | {'方向':>4} | {'得分':>4} | {'产业链':<12} | {'链趋势':<10} | {'一致':>4} | {'冗余':>5} | {'Z分':>6} | {'备注'}"
    )
    print("-" * 95)

    for s in SYMBOLS_DATA:
        pid = s["product_id"]
        chain = get_chain_for_symbol(pid)
        direction = s["direction"]
        score = s["score"]

        redundant = False
        redundant_with = None
        notes = []

        if chain in redundant_marks and redundant_marks[chain]["has_redundant"]:
            for detail in redundant_marks[chain]["details"]:
                if pid in detail["redundant"]:
                    redundant = True
                    redundant_with = detail["primary"]
                    notes.append(f"同链冗余→取{redundant_with}")
                    break
                elif pid == detail["primary"] and detail.get("redundant", []):
                    notes.append(f"主品种(同名{detail['redundant']}冗余)")

        v = verification_results.get(pid, {})
        z_info = z_scores.get(pid, {})

        if v.get("aligned"):
            notes.append(f"与{v.get('chain_trend', '')}一致")
        elif v.get("chain_trend") and v["chain_trend"] not in ("未知",):
            notes.append(f"背离{v.get('chain_trend', '')}")

        if z_info.get("z_status", "").startswith("极端"):
            notes.append(f"Z={z_info.get('z_score', '')}极端")

        if v.get("same_direction_ratio", 0) >= 0.6:
            notes.append(f"共振{v.get('same_direction', '')}")

        note_str = "; ".join(notes)
        align_str = "✅" if v.get("aligned", True) else "❌"
        red_str = "⚠️" if redundant else "—"
        z_str = f"{z_info.get('z_score', 0):+.2f}"

        print(
            f"{pid:>6} | {direction:>4} | {score:>4} | {chain:<12} | {v.get('chain_trend', ''):<10} | {align_str:>4} | {red_str:>5} | {z_str:>6} | {note_str}"
        )

        final_output[pid] = {
            "chain": chain,
            "chain_members": get_chain_members(chain) if chain else [],
            "term_structure": None,
            "chain_trend": v.get("chain_trend", ""),
            "chain_avg_score": v.get("chain_avg_score", 0),
            "chain_consistency": 100 if v.get("aligned", True) else -100,
            "aligned": v.get("aligned", True),
            "z_score": z_info.get("z_score", 0),
            "z_status": z_info.get("z_status", "正常"),
            "redundant": redundant,
            "redundant_with": redundant_with,
            "fundamental_notes": [],
            "notes": notes,
        }

    print("\n\n=== JSON OUTPUT ===")
    print(json.dumps(final_output, indent=2, ensure_ascii=False))
    print("\n###END_CHAIN_ANALYSIS")

    out_path = os.path.join(SKILL_DIR, "chain_verification_output.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
