# -*- coding: utf-8 -*-
"""辩论专家团产业链验证 — 链证源执行脚本"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.chains import get_chain_for_symbol, CHAIN_PRODUCTS
from scripts.chain_verifier import chain_verification

def get_chain_members(chain_name):
    return CHAIN_PRODUCTS.get(chain_name, [])

# ======== 辩论候选品种数据 ========
candidates = [
    {"product_id": "cs", "product_name": "玉米淀粉", "direction": "BUY", "score": 66, "last_price": 2734.0},
    {"product_id": "hc", "product_name": "热卷", "direction": "SELL", "score": 57, "last_price": 3310.0},
    {"product_id": "sp", "product_name": "纸浆", "direction": "SELL", "score": 57, "last_price": 4634.0},
    {"product_id": "rb", "product_name": "螺纹钢", "direction": "SELL", "score": 55, "last_price": 3087.0},
    {"product_id": "lh", "product_name": "生猪", "direction": "BUY", "score": 54, "last_price": 12275.0},
    {"product_id": "rr", "product_name": "粳米", "direction": "SELL", "score": 53, "last_price": 3535.0},
    {"product_id": "SM", "product_name": "锰硅", "direction": "SELL", "score": 51, "last_price": 5754.0},
    {"product_id": "a", "product_name": "豆一", "direction": "BUY", "score": 47, "last_price": 4826.0},
    {"product_id": "m", "product_name": "豆粕", "direction": "BUY", "score": 42, "last_price": 2970.0},
    {"product_id": "y", "product_name": "豆油", "direction": "BUY", "score": 40, "last_price": 8459.0},
]

# ======== Step 1: 产业链归类 ========
print("=" * 70)
print("Step 1: 产业链归类")
print("=" * 70)
for c in candidates:
    pid = c["product_id"]
    chain = get_chain_for_symbol(pid)
    members = get_chain_members(chain) if chain else []
    print(f"  {pid:<4} ({c['product_name']:<6}) -> chain={chain:<8}")

# ======== Step 3: 产业链一致性验证 ========
print()
print("=" * 70)
print("Step 3: 产业链一致性验证")
print("=" * 70)

chain_data = {
    "黑色系": {
        "members": [
            {"pid": "hc", "name": "热卷", "price": 3310.0, "score": 57, "trend": "SELL"},
            {"pid": "rb", "name": "螺纹钢", "price": 3087.0, "score": 55, "trend": "SELL"},
            {"pid": "SM", "name": "锰硅", "price": 5754.0, "score": 51, "trend": "SELL"},
        ],
        "overall_trend": "空头趋势",
        "avg_score": 46.4,
        "count": 3,
    },
    "谷物软商品": {
        "members": [
            {"pid": "cs", "name": "玉米淀粉", "price": 2734.0, "score": 66, "trend": "BUY"},
            {"pid": "lh", "name": "生猪", "price": 12275.0, "score": 54, "trend": "BUY"},
            {"pid": "rr", "name": "粳米", "price": 3535.0, "score": 53, "trend": "SELL"},
        ],
        "overall_trend": "震荡",
        "avg_score": 43.0,
        "count": 3,
    },
    "油脂油料": {
        "members": [
            {"pid": "a", "name": "豆一", "price": 4826.0, "score": 47, "trend": "BUY"},
            {"pid": "m", "name": "豆粕", "price": 2970.0, "score": 42, "trend": "BUY"},
            {"pid": "y", "name": "豆油", "price": 8459.0, "score": 40, "trend": "BUY"},
        ],
        "overall_trend": "多头趋势",
        "avg_score": 43.2,
        "count": 3,
    },
    "纸浆造纸": {
        "members": [
            {"pid": "sp", "name": "纸浆", "price": 4634.0, "score": 57, "trend": "SELL"},
        ],
        "overall_trend": "空头趋势",
        "avg_score": 57.0,
        "count": 1,
    },
}

verification_results = {}
for c in candidates:
    pid = c["product_id"]
    result = chain_verification(c, chain_data)
    verification_results[pid] = result
    adj_str = f"+{result['confidence_adjustment']:.0%}" if result["confidence_adjustment"] >= 0 else f"{result['confidence_adjustment']:.0%}"
    aligned_str = "✅一致" if result["aligned"] else "❌背离"
    print(f"  {pid:<4}: chain={result['chain_name']:<8} trend={result['chain_trend']:<8} {aligned_str} adj={adj_str}")
    print(f"         {result['detail']}")

# ======== Step 4: Z分数极端性检查 ========
print()
print("=" * 70)
print("Step 4: Z分数极端性检查")
print("=" * 70)

z_data = {
    "cs": {"z": 1.24, "term": "平水", "basis": -2},
    "hc": {"z": -3.88, "term": "升水(+0.13%)", "spread_z": -3.88},
    "sp": {"z": None, "term": "无数据"},
    "rb": {"z": 2.77, "term": "升水(+0.13%)", "spread_z": 2.77},
    "lh": {"z": -3.38, "term": "升水(+45.43%)", "spread_z": -3.38},
    "rr": {"z": None, "term": "无数据"},
    "SM": {"z": -0.98, "term": "升水(+3.68%)", "spread_z": -0.98},
    "a": {"z": -1.66, "term": "升水(+3.52%)", "spread_z": -1.66},
    "m": {"z": -2.92, "term": "升水(+0.73%)", "spread_z": -2.92},
    "y": {"z": -4.5, "term": "平水(-3.17%)", "spread_z": -4.5},
}

z_status = {}
for pid, dz in z_data.items():
    z = dz["z"]
    if z is None:
        status = "无数据"
        print(f"  {pid:<4}: Z=无数据 (数据不可用)")
    elif abs(z) > 3:
        status = "极度极端"
        print(f"  {pid:<4}: Z={z:<6} 🔴 极度极端(|z|>{3})，价格处于统计极端位置")
    elif abs(z) > 2:
        status = "极端"
        print(f"  {pid:<4}: Z={z:<6} ⚠️ 极端值(|z|>{2})，价格偏离200日均值超2σ")
    else:
        status = "正常"
        print(f"  {pid:<4}: Z={z:<6} 正常范围")
    print(f"     ⚠️ Z分数仅用于异常预警，不得作为左侧预判或均值回归交易依据")
    z_status[pid] = {"z_score": z, "status": status}

# ======== Step 5: 组合级产业链聚合（同链高相关冗余检测） ========
print()
print("=" * 70)
print("Step 5: 组合级产业链聚合（同链高相关冗余检测）")
print("=" * 70)

# 品种级高相关配对（驱动因素高度重叠才标记冗余）
HIGH_CORR_PAIRS = {
    ('rb', 'hc'),  # 螺纹钢≈热卷：地产+基建+粗钢产量+炉料成本驱动高度重叠
}

# 品种级独立声明（驱动因素独立，永不视为冗余）
INDEPENDENT_PIDS = {'SM', 'SF'}  # 锰硅/硅铁受独立供需+锰矿进口影响，与RB/HC相关性弱

chain_groups = {
    "黑色系": {"direction": "SELL", "candidates": [
        ("hc", 57, "SELL"), ("rb", 55, "SELL"), ("SM", 51, "SELL")
    ]},
    "谷物软商品": {"candidates": [
        ("cs", 66, "BUY"), ("lh", 54, "BUY"), ("rr", 53, "SELL")
    ]},
    "油脂油料": {"direction": "BUY", "candidates": [
        ("a", 47, "BUY"), ("m", 42, "BUY"), ("y", 40, "BUY")
    ]},
    "纸浆造纸": {"direction": "SELL", "candidates": [
        ("sp", 57, "SELL")
    ]},
}

redundancy_map = {}  # pid -> {redundant, redundant_with}

for chain_name, group in chain_groups.items():
    print(f"\n【{chain_name}】")
    
    # 初始化所有品种为非冗余
    for c in group["candidates"]:
        redundancy_map[c[0]] = {"redundant": False, "redundant_with": None}
        # 标记独立品种
        pid = c[0].upper()
        if pid in INDEPENDENT_PIDS or any(pid == p.upper() for pair in HIGH_CORR_PAIRS for p in pair):
            pass  # 独立品种初始标记非冗余，下面只处理高相关对
    
    # 遍历高相关配对，检查同方向冗余
    for pair in HIGH_CORR_PAIRS:
        a, b = pair
        a_data = next((c for c in group["candidates"] if c[0].upper() == a.upper()), None)
        b_data = next((c for c in group["candidates"] if c[0].upper() == b.upper()), None)
        
        if not a_data or not b_data:
            continue  # 配对品种之一不在本链候选列表中
        
        if a_data[2] != b_data[2]:
            print(f"  {a}({a_data[2]}) vs {b}({b_data[2]}) — 方向不同，无需冗余")
            continue
        
        # 同方向 → 按score保留高的
        if a_data[1] >= b_data[1]:
            primary, redundant = a_data, b_data
        else:
            primary, redundant = b_data, a_data
        
        print(f"  ⚠️ 高相关冗余: {a} vs {b} — 同方向({primary[2]})，保留 {primary[0]}(score={primary[1]})")
        redundancy_map[redundant[0]] = {"redundant": True, "redundant_with": primary[0]}
    
    # 信息: 独立品种
    for c in group["candidates"]:
        pid = c[0].upper()
        if pid in INDEPENDENT_PIDS:
            print(f"  ✓ {c[0]}(score={c[1]}) — 独立品种(驱动因素独立)，不参与冗余排除")
    
    # 信息: 非冗余保留品种
    non_flagged = [c[0] for c in group["candidates"] 
                   if not redundancy_map[c[0]]["redundant"]]
    if len(non_flagged) == len(group["candidates"]):
        if len(group["candidates"]) > 1:
            print(f"  ✓ 无高相关冗余排除（所有品种保留独立）")
    elif len(non_flagged) >= 2:
        print(f"  ✓ 保留品种: {non_flagged}（可多品种组合）")

# ======== 最终输出 ========
print()
print("=" * 70)
print("FINAL OUTPUT: 产业链验证完整报告")
print("=" * 70)

final_output = {}
for c in candidates:
    pid = c["product_id"]
    chain = get_chain_for_symbol(pid)
    members = get_chain_members(chain) if chain else []
    vr = verification_results.get(pid, {})
    z_info = z_status.get(pid, {"z_score": None, "status": "无数据"})
    red = redundancy_map.get(pid, {"redundant": False, "redundant_with": None})
    
    term_map = {
        "cs": "flat", "hc": "contango", "sp": "unknown",
        "rb": "contango", "lh": "contango", "rr": "unknown",
        "SM": "contango", "a": "contango", "m": "contango", "y": "flat"
    }
    basis_map = {
        "cs": "平稳", "hc": "走弱", "sp": "未知",
        "rb": "走弱", "lh": "走弱", "rr": "未知",
        "SM": "走弱", "a": "走弱", "m": "走弱", "y": "平稳"
    }
    
    notes = []
    
    # 检查期限结构与方向的一致性
    term = term_map[pid]
    direction = c["direction"]
    if term == "contango" and direction == "BUY":
        notes.append("⚠️ 升水结构下做多，展仓成本高，期限结构不利")
    elif term == "contango" and direction == "SELL":
        notes.append("✅ 升水结构支持做空，展仓收益")
    elif term == "backwardation" and direction == "SELL":
        notes.append("⚠️ 贴水结构下做空，展仓成本高")
    elif term == "backwardation" and direction == "BUY":
        notes.append("✅ 贴水结构支持做多，现货紧张")
    
    # 加入产业链一致性注释
    if vr.get("aligned"):
        notes.append(f"✅ 与{chain}趋势一致（置信度{vr.get('confidence_adjustment', 0):+.0%})")
    else:
        notes.append(f"❌ 与{chain}趋势背离（置信度{vr.get('confidence_adjustment', 0):+.0%})")
    
    # Z分数注释
    if z_info["status"] == "极度极端":
        notes.append("⚠️⚠️ Z分数极度极端，高概率均值回归，注意反向风险")
    elif z_info["status"] == "极端":
        notes.append("⚠️ Z分数极端，注意均值回归风险")
    
    # 冗余标记
    if red["redundant"]:
        notes.append(f"⚠️ 同链冗余，建议优先考虑 {red['redundant_with']}")
    
    entry = {
        "chain": chain,
        "chain_members": members,
        "term_structure": term_map[pid],
        "basis": basis_map[pid],
        "chain_trend": vr.get("chain_trend", "未知"),
        "chain_consistency": 1.0 if vr.get("aligned") else 0.0,
        "confidence_adjustment": vr.get("confidence_adjustment", 0),
        "z_score": z_info["z_score"],
        "z_status": z_info["status"],
        "redundant": red["redundant"],
        "redundant_with": red["redundant_with"],
        "notes": notes
    }
    final_output[pid] = entry

print(json.dumps(final_output, ensure_ascii=False, indent=2))
print()
print("###END_CHAIN_ANALYSIS")
