#!/usr/bin/env python3
"""
失败模式聚类引擎 — 对标 Replit Telescope，从生产轨迹中聚类问题模式。

读取 execution_followup.json + debate_journal.json，对已验证裁决提取多维特征，
按链×方向、ADX×方向、RSI×方向、共振×冲突、置信度等维度聚类，生成诊断假设，
关联 judgment_revisions.md 中的已知规则，输出到 failure_clusters.json。

用法:
  python cluster_failures.py [--min-cases 3] [--min-winrate 40]

  --min-cases    最低聚类案例数（默认3）
  --min-winrate  告警胜率阈值%（默认40，低于此值标记为高风险）

输出:
  - memory/failure_clusters.json  聚类分析报告
  - memory/cluster_run_log.json   运行历史记录

设计原则（Replit Telescope 方法论）:
  1. 不只看总数，找出总指标中被掩盖的反复发生模式
  2. 每个 cluster 包含 hypothesis → rule 关联 → severity
  3. 支持增量运行，累积历史数据做趋势分析
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Any


# ─── 项目根 ────────────────────────────────────────────

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ─── 数据加载 ───────────────────────────────────────────

def _load_json(rel_path: str) -> dict | list:
    fp = _project_root() / rel_path
    if not fp.exists():
        return {} if "." in os.path.basename(rel_path) else []
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(rel_path: str, data: Any):
    fp = _project_root() / rel_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 特征提取 ───────────────────────────────────────────

def extract_verdict_features(verdict: dict, validation_result: dict | None = None) -> dict | None:
    """
    从单条裁决提取多维特征向量。
    返回 None 表示该条无有效数据，跳过。
    """
    adx = verdict.get("adx", 0)
    rsi = verdict.get("rsi", 0)
    score = verdict.get("score", 0)
    confidence = verdict.get("confidence", "中")
    direction = verdict.get("direction", "neutral")
    chain = verdict.get("chain", "未分类")
    ft_dir = verdict.get("ft_dir", "neutral")
    resonance = verdict.get("resonance", 0)
    conflict = verdict.get("conflict", False)
    symbol = verdict.get("symbol", "")
    name = verdict.get("name", symbol)

    # ADX 区间
    if adx >= 70:
        adx_regime = "ADX≥70_极强趋势"
    elif adx >= 60:
        adx_regime = "ADX60-70_强趋势末端"
    elif adx >= 50:
        adx_regime = "ADX50-60_趋势偏强"
    elif adx >= 25:
        adx_regime = "ADX25-50_正常趋势"
    elif adx >= 15:
        adx_regime = "ADX15-25_突破初期"
    else:
        adx_regime = "ADX<15_无趋势"

    # RSI 区间
    if direction == "bear":
        if rsi < 25:
            rsi_regime = "RSI<25_深度超卖"
        elif rsi < 30:
            rsi_regime = "RSI25-30_超卖区"
        elif rsi < 35:
            rsi_regime = "RSI30-35_偏卖"
        elif rsi < 50:
            rsi_regime = "RSI35-50_弱势区"
        else:
            rsi_regime = "RSI≥50_正常区"
    else:
        if rsi > 75:
            rsi_regime = "RSI>75_深度超买"
        elif rsi > 70:
            rsi_regime = "RSI70-75_超买区"
        elif rsi > 65:
            rsi_regime = "RSI65-70_偏买"
        elif rsi > 50:
            rsi_regime = "RSI50-65_强势区"
        else:
            rsi_regime = "RSI≤50_正常区"

    # FT 方向匹配
    if ft_dir == direction:
        ft_match = "ft_一致"
    elif ft_dir == "neutral":
        ft_match = "ft_中性无确认"
    else:
        ft_match = "ft_反向冲突"

    # 共振状态
    resonance_label = "共振=1" if resonance == 1 else "共振=0"

    feature = {
        "symbol": symbol,
        "name": name,
        "direction": direction,
        "confidence": confidence,
        "score": score,
        "adx": adx,
        "adx_regime": adx_regime,
        "rsi": rsi,
        "rsi_regime": rsi_regime,
        "chain": chain,
        "ft_dir": ft_dir,
        "ft_match": ft_match,
        "resonance": resonance,
        "conflict": conflict,
        "resonance_label": resonance_label,
    }

    # 验证结果（如果有）
    if validation_result:
        feature["correct"] = validation_result.get("correct")
        feature["pnl_pct"] = validation_result.get("realized_pnl_pct", 0)
        feature["hit_stop"] = validation_result.get("hit_stop", False)
        feature["hit_target1"] = validation_result.get("hit_target1", False)
        feature["hit_target2"] = validation_result.get("hit_target2", False)
        feature["gap_stop"] = validation_result.get("gap_stop", False)
    else:
        feature["correct"] = None
        feature["pnl_pct"] = 0
        feature["hit_stop"] = False
        feature["hit_target1"] = False
        feature["hit_target2"] = False
        feature["gap_stop"] = False

    return feature


def extract_all_features(followup_data: dict) -> list[dict]:
    """从 execution_followup.json 提取所有有效特征。"""
    features = []
    for record in followup_data.get("records", []):
        verdicts = record.get("verdicts", [])
        vr = record.get("validation_results", {})
        results = vr.get("results", []) if vr else []

        for i, v in enumerate(verdicts):
            vr_item = results[i] if i < len(results) else None
            f = extract_verdict_features(v, vr_item)
            if f:
                f["round_id"] = record.get("round_id", "")
                f["generated_at"] = record.get("generated_at", "")
                features.append(f)

    return features


# ─── 聚类引擎 ───────────────────────────────────────────

def cluster_by_dimension(
    features: list[dict],
    dim_key: str,
    min_cases: int = 3,
) -> list[dict]:
    """
    按单个维度聚类，返回所有 cluster 列表。
    每个 cluster: {cluster_id, dimension, pattern, cases, win_rate, avg_pnl, avg_score, ...}
    """
    groups = defaultdict(list)
    for f in features:
        # 只对已验证（correct 非 None）结果聚类
        if f.get("correct") is None:
            continue
        key = f.get(dim_key, "unknown")
        groups[key].append(f)

    clusters = []
    for key, cases in groups.items():
        if len(cases) < min_cases:
            continue

        correct = sum(1 for c in cases if c.get("correct") is True)
        total = len(cases)
        win_rate = correct / total if total > 0 else 0
        avg_pnl = sum(c.get("pnl_pct", 0) for c in cases) / total
        avg_score = sum(c.get("score", 0) for c in cases) / total
        avg_adx = sum(c.get("adx", 0) for c in cases) / total
        avg_rsi = sum(c.get("rsi", 0) for c in cases) / total
        stop_hit = sum(1 for c in cases if c.get("hit_stop"))
        gap_stop = sum(1 for c in cases if c.get("gap_stop"))

        cluster = {
            "dimension": dim_key,
            "pattern": key,
            "cases": [c["symbol"] for c in cases],
            "total_cases": total,
            "correct_cases": correct,
            "wrong_cases": total - correct,
            "win_rate": round(win_rate * 100, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "avg_score": round(avg_score, 1),
            "avg_adx": round(avg_adx, 1),
            "avg_rsi": round(avg_rsi, 1),
            "stop_hit_count": stop_hit,
            "stop_hit_rate": round(stop_hit / total * 100, 1),
            "gap_stop_count": gap_stop,
        }
        clusters.append(cluster)

    # 按胜率升序排列（最差的在前）
    clusters.sort(key=lambda x: x["win_rate"])
    return clusters


def cluster_cross_dimension(
    features: list[dict],
    dim1: str,
    dim2: str,
    min_cases: int = 2,
) -> list[dict]:
    """二维交叉聚类。"""
    groups = defaultdict(list)
    for f in features:
        if f.get("correct") is None:
            continue
        key = f"{f.get(dim1, '?')} × {f.get(dim2, '?')}"
        groups[key].append(f)

    clusters = []
    for key, cases in groups.items():
        if len(cases) < min_cases:
            continue

        correct = sum(1 for c in cases if c.get("correct") is True)
        total = len(cases)
        win_rate = correct / total if total > 0 else 0
        avg_pnl = sum(c.get("pnl_pct", 0) for c in cases) / total
        avg_score = sum(c.get("score", 0) for c in cases) / total
        avg_adx = sum(c.get("adx", 0) for c in cases) / total
        stop_hit = sum(1 for c in cases if c.get("hit_stop"))

        clusters.append({
            "dimension": f"{dim1}_cross_{dim2}",
            "pattern": key,
            "dim1": dim1,
            "dim2": dim2,
            "cases": [c["symbol"] for c in cases],
            "total_cases": total,
            "correct_cases": correct,
            "wrong_cases": total - correct,
            "win_rate": round(win_rate * 100, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "avg_score": round(avg_score, 1),
            "avg_adx": round(avg_adx, 1),
            "stop_hit_count": stop_hit,
            "stop_hit_rate": round(stop_hit / total * 100, 1),
        })
    clusters.sort(key=lambda x: x["win_rate"])
    return clusters


def symbol_direction_clusters(
    features: list[dict],
    min_cases: int = 2,
) -> list[dict]:
    """按品种×方向聚类（同品种同方向连续失败检测）。"""
    groups = defaultdict(list)
    for f in features:
        if f.get("correct") is None:
            continue
        key = f"{f['symbol']}_{f['direction']}"
        groups[key].append(f)

    clusters = []
    for key, cases in groups.items():
        if len(cases) < min_cases:
            continue

        correct = sum(1 for c in cases if c.get("correct") is True)
        total = len(cases)
        win_rate = correct / total if total > 0 else 0
        avg_pnl = sum(c.get("pnl_pct", 0) for c in cases) / total

        symbol = cases[0]["symbol"]
        name = cases[0]["name"]
        direction = cases[0]["direction"]
        chain = cases[0]["chain"]

        clusters.append({
            "dimension": "symbol_direction",
            "pattern": f"{name}({symbol})_{direction}",
            "symbol": symbol,
            "name": name,
            "chain": chain,
            "direction": direction,
            "cases": [f"{c['symbol']}_{c.get('round_id','?')}" for c in cases],
            "total_cases": total,
            "correct_cases": correct,
            "wrong_cases": total - correct,
            "win_rate": round(win_rate * 100, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
        })
    clusters.sort(key=lambda x: x["win_rate"])
    return clusters


# ─── 诊断假设生成 ───────────────────────────────────────

# 规则→问题模式的映射表
RULE_PATTERN_MAP = [
    {
        "rule": "R01",
        "trigger": "空头 + RSI<30",
        "check": lambda c: c["dimension"] == "rsi_regime" and "RSI<25" in c["pattern"] or "RSI25-30" in c["pattern"],
        "description": "空头方向RSI<30被强制降置信度至SELL中，但实际胜率可能反映了超卖追空的结构性问题",
    },
    {
        "rule": "R13",
        "trigger": "ADX>50 仓位减半",
        "check": lambda c: ("ADX≥70" in c["pattern"] or "ADX60-70" in c["pattern"] or "ADX50-60" in c["pattern"]) and c["win_rate"] < 50,
        "description": "ADX>50趋势已运行较远，仓位上限已减半。若此区间胜率仍低，说明减仓幅度可能不够或信号本身质量差",
    },
    {
        "rule": "R14",
        "trigger": "ADX>60 追高/追空风险",
        "check": lambda c: ("ADX≥70" in c["pattern"] or "ADX60-70" in c["pattern"]) and c["win_rate"] < 35,
        "description": "ADX>60应标记追高/追空风险、建议放弃。若此区间胜率极低，可能需要升级为硬约束禁止开仓",
    },
    {
        "rule": "R07",
        "trigger": "反向证据未充分检索",
        "check": lambda c: "ft_反向冲突" in c["pattern"] and c["win_rate"] < 40,
        "description": "因子择时方向与裁决方向反向冲突时胜率低，可能因R07反向证据检索未充分执行",
    },
    {
        "rule": "R03",
        "trigger": "同链集中风险",
        "check": lambda c: c["dimension"] == "chain" and c["win_rate"] < 40 and c["total_cases"] >= 3,
        "description": "该产业链整体胜率偏低，可能存在链内冗余（R03同链最多保留1个）执行不到位或产业链分析偏差",
    },
    {
        "rule": "R22",
        "trigger": "止损频繁触发",
        "check": lambda c: c.get("stop_hit_rate", 0) > 50 and c["total_cases"] >= 3,
        "description": "止损触发率>50%，可能止损距设置过窄，未充分基于技术位（R22技术位优先规则可能未严格执行）",
    },
    {
        "rule": "R17",
        "trigger": "高ADX下的V型反转漏判",
        "check": lambda c: ("ADX60-70" in c["pattern"] or "ADX≥70" in c["pattern"]) and c["dimension"] == "adx_regime" and c["win_rate"] < 30,
        "description": "极强趋势区间胜率极低，可能漏判V型反转——ADX高但价格已反向（R16-R18 V型反转规则可能未正确触发）",
    },
]


def generate_hypothesis(cluster: dict) -> dict:
    """为一个 cluster 生成诊断假设，关联已知规则。"""
    hypotheses = []

    for rule_entry in RULE_PATTERN_MAP:
        if rule_entry["check"](cluster):
            hypotheses.append({
                "rule": rule_entry["rule"],
                "trigger": rule_entry["trigger"],
                "description": rule_entry["description"],
            })

    # 通用假设：低胜率 + 高分数 → 评分模型偏差
    if cluster["win_rate"] < 40 and cluster.get("avg_score", 0) > 50:
        hypotheses.append({
            "rule": "评分模型",
            "trigger": f"avg_score={cluster['avg_score']} 但 WR={cluster['win_rate']}%",
            "description": "评分均值偏高但实际胜率低，可能存在评分模型的系统性偏差——六维评分某维度标准与实际市场表现不匹配",
        })

    # 通用假设：高止损率 → 入场时机问题
    if cluster.get("stop_hit_rate", 0) > 50:
        hypotheses.append({
            "rule": "入场时机",
            "trigger": f"止损率={cluster['stop_hit_rate']}%",
            "description": "高频止损触发，可能入场时机偏早（突破初期假信号）或止损距设置不合理",
        })

    return {
        "main_hypothesis": hypotheses[0]["description"] if hypotheses else "需进一步分析",
        "affected_rules": [h["rule"] for h in hypotheses],
        "detail_hypotheses": hypotheses,
    }


# ─── 严重程度评估 ──────────────────────────────────────

def assess_severity(cluster: dict, total_validated: int) -> str:
    """
    评估 cluster 严重程度。
    high: 胜率<30% 且案例数>=3
    medium: 胜率<40% 或 高止损率
    low: 其他
    """
    wr = cluster["win_rate"]
    n = cluster["total_cases"]
    sr = cluster.get("stop_hit_rate", 0)

    if wr < 30 and n >= 3:
        return "high"
    if sr > 60 and n >= 3:
        return "high"
    if wr < 40 and n >= 2:
        return "medium"
    if sr > 50 and n >= 2:
        return "medium"
    return "low"


# ─── 主聚类流程 ────────────────────────────────────────

def run_clustering(
    features: list[dict],
    min_cases: int = 3,
    min_winrate_alert: float = 40.0,
    cross_min_cases: int = 2,
) -> dict:
    """主聚类流程：单维 → 二维交叉 → 品种方向 → 严重度评估 → 关联规则"""

    total_with_result = sum(1 for f in features if f.get("correct") is not None)

    # ── 单维度聚类 ──
    single_dim_clusters = []
    for dim in ["chain", "adx_regime", "rsi_regime", "confidence", "ft_match", "resonance_label", "direction"]:
        clusters = cluster_by_dimension(features, dim, min_cases=min_cases)
        # 只保留低于告警阈值的
        for c in clusters:
            if c["win_rate"] < min_winrate_alert or c.get("stop_hit_rate", 0) > 50:
                hypothesis = generate_hypothesis(c)
                severity = assess_severity(c, total_with_result)
                c["cluster_id"] = f"C-{dim}-{len(single_dim_clusters)+1:03d}"
                c["severity"] = severity
                c["hypothesis"] = hypothesis
                single_dim_clusters.append(c)

    # ── 二维交叉聚类 ──
    cross_clusters = []
    cross_pairs = [
        ("chain", "direction"),
        ("chain", "adx_regime"),
        ("adx_regime", "direction"),
        ("rsi_regime", "direction"),
        ("ft_match", "confidence"),
        ("chain", "confidence"),
    ]
    for dim1, dim2 in cross_pairs:
        clusters = cluster_cross_dimension(features, dim1, dim2, min_cases=cross_min_cases)
        for c in clusters:
            if c["win_rate"] < min_winrate_alert or c.get("stop_hit_rate", 0) > 50:
                hypothesis = generate_hypothesis(c)
                severity = assess_severity(c, total_with_result)
                c["cluster_id"] = f"C-cross-{len(cross_clusters)+1:03d}"
                c["severity"] = severity
                c["hypothesis"] = hypothesis
                cross_clusters.append(c)

    # ── 品种×方向聚类 ──
    sym_dir_clusters = symbol_direction_clusters(features, min_cases=cross_min_cases)
    for c in sym_dir_clusters:
        if c["win_rate"] < min_winrate_alert or c.get("stop_hit_rate", 0) > 50:
            hypothesis = generate_hypothesis(c)
            severity = assess_severity(c, total_with_result)
            c["cluster_id"] = f"C-sym-{len(sym_dir_clusters):03d}"
            c["severity"] = severity
            c["hypothesis"] = hypothesis
        else:
            sym_dir_clusters.remove(c)  # 过滤掉正常表现的

    # 按严重程度和胜率排序
    all_clusters = single_dim_clusters + cross_clusters + sym_dir_clusters
    all_clusters.sort(key=lambda x: (
        {"high": 0, "medium": 1, "low": 2}[x["severity"]],
        x["win_rate"],
    ))

    # ── 执行摘要 ──
    high_count = sum(1 for c in all_clusters if c["severity"] == "high")
    med_count = sum(1 for c in all_clusters if c["severity"] == "medium")

    return {
        "_schema_version": "1.0",
        "_description": "失败模式聚类分析。对标 Replit Telescope，从生产轨迹中聚类问题模式。每周一自动更新。",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_range": {
            "total_features": len(features),
            "total_validated": total_with_result,
            "unvalidated": len(features) - total_with_result,
        },
        "summary": {
            "total_clusters": len(all_clusters),
            "high_severity": high_count,
            "medium_severity": med_count,
            "low_severity": len(all_clusters) - high_count - med_count,
        },
        "clusters": all_clusters,
    }


# ─── 历史趋势分析 ──────────────────────────────────────

def load_previous_run() -> dict | None:
    """加载上一次聚类运行结果用于趋势对比。"""
    fp = _project_root() / "memory" / "failure_clusters.json"
    if not fp.exists():
        return None
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_trends(current: dict, previous: dict | None) -> list[dict]:
    """对比前后两次运行的 cluster 变化趋势。"""
    if not previous or not previous.get("clusters"):
        return []

    prev_by_id = {c.get("cluster_id", ""): c for c in previous["clusters"]}
    trends = []

    for cur in current.get("clusters", []):
        cid = cur.get("cluster_id", "")
        prev = prev_by_id.get(cid)
        if prev:
            wr_delta = cur["win_rate"] - prev["win_rate"]
            trend_label = "improving" if wr_delta > 3 else ("worsening" if wr_delta < -3 else "stable")
            trends.append({
                "cluster_id": cid,
                "pattern": cur["pattern"],
                "prev_win_rate": prev["win_rate"],
                "curr_win_rate": cur["win_rate"],
                "delta": round(wr_delta, 1),
                "trend": trend_label,
            })

    # 新增的 cluster
    prev_ids = set(prev_by_id.keys())
    cur_ids = {c.get("cluster_id", "") for c in current.get("clusters", [])}
    new_ids = cur_ids - prev_ids
    for cid in new_ids:
        cur = next((c for c in current["clusters"] if c.get("cluster_id") == cid), None)
        if cur:
            trends.append({
                "cluster_id": cid,
                "pattern": cur["pattern"],
                "prev_win_rate": None,
                "curr_win_rate": cur["win_rate"],
                "delta": None,
                "trend": "new",
            })

    return trends


# ─── 主程序 ────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="失败模式聚类引擎（Telescope层）")
    parser.add_argument("--min-cases", type=int, default=3,
                        help="最低聚类案例数（默认3）")
    parser.add_argument("--min-winrate", type=float, default=40.0,
                        help="告警胜率阈值%%（默认40）")
    parser.add_argument("--cross-min", type=int, default=2,
                        help="交叉聚类最低案例数（默认2）")
    parser.add_argument("--output", default=None,
                        help="输出文件路径（默认 memory/failure_clusters.json）")
    args = parser.parse_args()

    # 加载数据
    print("📂 加载 execution_followup.json ...")
    followup = _load_json("memory/execution_followup.json")
    if isinstance(followup, dict):
        followup = followup
    else:
        followup = {"records": []}

    print("📂 加载 debate_journal.json ...")
    debate_journal = _load_json("memory/debate_journal.json")

    # 提取特征
    print("🔍 提取裁决特征向量 ...")
    features = extract_all_features(followup)

    total = len(features)
    validated = sum(1 for f in features if f.get("correct") is not None)
    unvalidated = total - validated

    print(f"   总特征数: {total}")
    print(f"   已验证:   {validated}")
    print(f"   未验证:   {unvalidated}")

    if validated == 0:
        print("\n⚠️ 无已验证数据。需要先运行 validate_verdicts.py 获取验证结果。")
        print("   将输出基于[置信度 x ADX x RSI]结构性风险的预聚类（无 PnL 验证）。")

        # 即使无 PnL 验证，也做结构性风险预聚类
        # 基于现有规则 R01-R14 检查结构性风险
        structural_risks = []

        # 检查超卖追空
        oversold_sells = [f for f in features if f["direction"] == "bear" and f["rsi"] < 30]
        if len(oversold_sells) >= args.min_cases:
            structural_risks.append({
                "cluster_id": "C-structural-001",
                "dimension": "structural_risk",
                "pattern": "空头_RSI<30_超卖追空",
                "severity": "high",
                "total_cases": len(oversold_sells),
                "cases": [f["symbol"] for f in oversold_sells],
                "hypothesis": {
                    "main_hypothesis": "空头方向RSI<30区间开仓追空，R01已强制降级但仍存在结构性风险",
                    "affected_rules": ["R01", "R02"],
                },
                "note": "预聚类：无PnL验证，基于规则R01-R02的结构性风险预警",
            })

        # 检查ADX>60高风险
        high_adx = [f for f in features if f["adx"] >= 60 and f["direction"] != "neutral"]
        if len(high_adx) >= args.min_cases:
            structural_risks.append({
                "cluster_id": "C-structural-002",
                "dimension": "structural_risk",
                "pattern": "ADX≥60_追高追空风险",
                "severity": "high",
                "total_cases": len(high_adx),
                "cases": list(set(f["symbol"] for f in high_adx)),
                "hypothesis": {
                    "main_hypothesis": f"{len(high_adx)}个品种ADX≥60进入高风险区，R14标记追高/追空风险",
                    "affected_rules": ["R13", "R14", "R16", "R17", "R18"],
                },
                "note": "预聚类：无PnL验证，基于规则R13-R18的结构性风险预警",
            })

        # 检查共振=0（无因子择时确认）
        no_resonance = [f for f in features if f["resonance"] == 0]
        if len(no_resonance) >= args.min_cases:
            structural_risks.append({
                "cluster_id": "C-structural-003",
                "dimension": "structural_risk",
                "pattern": "共振=0_无因子择时确认",
                "severity": "medium",
                "total_cases": len(no_resonance),
                "cases": list(set(f["symbol"] for f in no_resonance)),
                "hypothesis": {
                    "main_hypothesis": f"{len(no_resonance)}个品种裁决无因子择时确认（共振=0），信号可靠性可能偏低",
                    "affected_rules": ["R25"],
                },
                "note": "预聚类：无PnL验证，信号来源仅通道突破无因子择时共振",
            })

        # 检查同链集中
        chain_groups = defaultdict(list)
        for f in features:
            chain_groups[f["chain"]].append(f["symbol"])
        overconcentrated = {ch: syms for ch, syms in chain_groups.items() if len(set(syms)) >= 3}
        if overconcentrated:
            structural_risks.append({
                "cluster_id": "C-structural-004",
                "dimension": "structural_risk",
                "pattern": "同链集中风险",
                "severity": "medium",
                "total_cases": sum(len(v) for v in overconcentrated.values()),
                "cases": [],
                "chains": {k: list(set(v)) for k, v in overconcentrated.items()},
                "hypothesis": {
                    "main_hypothesis": f"{len(overconcentrated)}条产业链品种集中度≥3，R03要求同链最多保留1个",
                    "affected_rules": ["R03", "R04"],
                },
                "note": "预聚类：无PnL验证，基于R03-R04的结构性风险预警",
            })

        result = {
            "_schema_version": "1.0",
            "_description": "失败模式聚类分析（预聚类模式：无PnL验证，仅结构性风险检查）",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_range": {
                "total_features": total,
                "total_validated": 0,
                "unvalidated": unvalidated,
                "mode": "structural_only",
            },
            "summary": {
                "total_clusters": len(structural_risks),
                "high_severity": sum(1 for c in structural_risks if c["severity"] == "high"),
                "medium_severity": sum(1 for c in structural_risks if c["severity"] == "medium"),
                "low_severity": sum(1 for c in structural_risks if c["severity"] == "low"),
                "needs_validation": True,
                "action_required": "运行 validate_verdicts.py 获取PnL验证结果以启用真实聚类",
            },
            "clusters": structural_risks,
            "trends": [],
        }

        output_path = args.output or "memory/failure_clusters.json"
        _save_json(output_path, result)
        print(f"\n✅ 结构性风险预聚类完成: {output_path}")
        print(f"   {len(structural_risks)} 个结构性问题已识别")
        for c in structural_risks:
            print(f"   [{c['severity']}] {c['pattern']}: {c['total_cases']}条 → {c['hypothesis']['main_hypothesis']}")
        return

    # 运行聚类
    print(f"\n🧬 运行聚类分析 (min_cases={args.min_cases}, winrate_alert={args.min_winrate}%) ...")
    result = run_clustering(
        features,
        min_cases=args.min_cases,
        min_winrate_alert=args.min_winrate,
        cross_min_cases=args.cross_min,
    )

    # 加载历史趋势
    previous = load_previous_run()
    trends = compute_trends(result, previous)
    result["trends"] = trends

    # 保存
    output_path = args.output or "memory/failure_clusters.json"
    _save_json(output_path, result)

    # 运行日志
    run_log = _load_json("memory/cluster_run_log.json")
    if isinstance(run_log, dict):
        if "runs" not in run_log:
            run_log["runs"] = []
        run_log["runs"].append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "features_total": total,
            "features_validated": validated,
            "clusters_found": len(result["clusters"]),
            "high_severity": result["summary"]["high_severity"],
            "min_cases": args.min_cases,
            "min_winrate": args.min_winrate,
        })
        # 只保留最近50次运行记录
        run_log["runs"] = run_log["runs"][-50:]
        _save_json("memory/cluster_run_log.json", run_log)

    # ── 输出报告 ──
    print("\n" + "=" * 70)
    print("🔬 失败模式聚类报告")
    print("=" * 70)
    print(f"  数据范围: {total}条特征 | {validated}条已验证 | {unvalidated}条待验证")
    print(f"  聚类总数: {len(result['clusters'])}")
    print(f"  🔴 高风险: {result['summary']['high_severity']}")
    print(f"  🟡 中风险: {result['summary']['medium_severity']}")
    print(f"  🟢 低风险: {result['summary']['low_severity']}")

    if trends:
        worsening = [t for t in trends if t["trend"] == "worsening"]
        improving = [t for t in trends if t["trend"] == "improving"]
        new = [t for t in trends if t["trend"] == "new"]
        print(f"\n  📈 趋势: {len(improving)}改善 | {len(worsening)}恶化 | {len(new)}新增")

    if result["clusters"]:
        print("\n" + "─" * 70)
        print("  高风险 Clusters:")
        print("─" * 70)
        for c in result["clusters"]:
            if c["severity"] != "high":
                continue
            print(f"\n  [{c['cluster_id']}] 🔴 {c['pattern']}")
            print(f"    胜率: {c['win_rate']}% ({c['correct_cases']}/{c['total_cases']})")
            print(f"    均盈: {c['avg_pnl_pct']:+.2f}%")
            print(f"    止损率: {c.get('stop_hit_rate', 0)}%")
            if c.get("avg_score"):
                print(f"    均评分: {c['avg_score']}")
            hyp = c.get("hypothesis", {})
            print(f"    诊断: {hyp.get('main_hypothesis', 'N/A')}")
            rules = hyp.get("affected_rules", [])
            if rules:
                print(f"    关联规则: {', '.join(rules)}")
            if "cases" in c:
                print(f"    涉及: {', '.join(c['cases'][:10])}")

        # 中风险摘要
        medium = [c for c in result["clusters"] if c["severity"] == "medium"]
        if medium:
            print(f"\n  🟡 中风险 Clusters ({len(medium)}个):")
            for c in medium[:5]:
                print(f"    [{c['cluster_id']}] {c['pattern']} — WR={c['win_rate']}% "
                      f"止损率={c.get('stop_hit_rate',0)}%")

    print(f"\n✅ 聚类报告已保存: {output_path}")


if __name__ == "__main__":
    main()
