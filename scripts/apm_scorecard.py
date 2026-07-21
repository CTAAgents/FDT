"""
APM-CS 五轴能力诊断评分卡引擎 v1.0
=====================================
基于 CLQT (arXiv:2606.29771) 方法论，为 FDT 辩论专家团构建五轴诊断框架。

五轴定义：
  D1 Coherence  — 裁决与论据一致性（held-out judge；机制已就位，有 debate_record 即算分）
  D2 Acuity     — 信号-噪音辨识力（需多轮 PnL 交叉验证，已激活）
  D3 Composure  — 波动率-过度反应（去重辩论轮次 ≥5 自动点亮，门控中）
  D4 Discipline — 规则自检遵守度（✅ 可立即计算）
  D5 Reliability— 闭环完成率（✅ 可立即计算）

数据源：
  - execution_followup.json: 裁决数据（D4 源）
  - debate_journal.json: session 日志（D5 源）
  - judgment_revisions.md: 规则定义（D4 规则库）
  - failure_clusters.json: 阶段一聚类（交叉引用）

用法：
  python scripts/apm_scorecard.py
"""
from __future__ import annotations

import json
import os
import re
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


# ── 路径配置 ──

PROJECT_ROOT = Path(__file__).parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"
FOLLOWUP_PATH = MEMORY_DIR / "execution_followup.json"
JOURNAL_PATH = MEMORY_DIR / "debate_journal.json"
REVISIONS_PATH = MEMORY_DIR / "judgment_revisions.md"
CLUSTERS_PATH = MEMORY_DIR / "failure_clusters.json"
OUTPUT_PATH = MEMORY_DIR / "apm_scorecard.json"


# ── 工具函数 ──

def load_json(path: Path) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def conf_value(conf: str) -> int:
    """置信度 → 数值权重：高=3, 中=2, 低=1"""
    return {"高": 3, "中": 2, "低": 1}.get(conf, 2)


def conf_max_pos(conf: str, base_pct: float = 5.0) -> float:
    """置信度对应的基准仓位上限"""
    return {"高": 5.0, "中": 3.5, "低": 2.0}.get(conf, 3.5)


# ── D4: Discipline — 规则自检遵守度 ──

class RuleChecker:
    """基于 judgment_revisions.md 的结构化规则检查器"""

    def __init__(self) -> None:
        self.violations: List[Dict] = []

    def check_verdict(self, v: Dict) -> List[Dict]:
        """对单条裁决执行全部适用规则检查，返回违规列表"""
        violations = []

        direction = v.get("direction", "")
        rsi = v.get("rsi", 50)
        adx = v.get("adx", 30)
        confidence = v.get("confidence", "中")
        position_pct = v.get("position_pct", 3.5)
        conflict = v.get("conflict", False)
        ft_dir = v.get("ft_dir", "neutral")
        resonance = v.get("resonance", 0)
        symbol = v.get("symbol", "?")

        # ── R01: SELL + RSI<30 → 禁止标记为高 ──
        if direction == "bear" and rsi < 30 and confidence == "高":
            violations.append({
                "rule": "R01",
                "severity": "P0",
                "type": "硬约束",
                "desc": f"空头RSI={rsi}<30 禁止标记为SELL高",
                "actual": f"confidence=高, RSI={rsi}",
                "expected": "confidence ≤ 中",
            })

        # ── R02: SELL + RSI<35 + 高 → 标注超卖风险 ──
        if direction == "bear" and rsi < 35 and confidence == "高":
            violations.append({
                "rule": "R02",
                "severity": "P1",
                "type": "软约束",
                "desc": f"空头RSI={rsi}<35 + SELL高需标注超卖风险",
                "actual": f"未标注超卖（confidence=高, RSI={rsi}）",
                "expected": "标注⚠️超卖风险",
            })

        # ── R13: ADX>50 → 仓位上限减半 ──
        if adx > 50:
            base_cap = conf_max_pos(confidence)
            halved_cap = base_cap / 2
            if position_pct > halved_cap + 1e-6:  # +epsilon 防止浮点边界误判
                violations.append({
                    "rule": "R13",
                    "severity": "P0",
                    "type": "硬约束",
                    "desc": f"ADX={adx}>50 仓位应≤{halved_cap}%（减半）",
                    "actual": f"position={position_pct}% (cap={halved_cap}%)",
                    "expected": f"position ≤ {halved_cap}%",
                })

        # ── R14: ADX≥60 → 仓位≤3% 或放弃 ──
        if adx >= 60 and position_pct > 3.0 + 1e-6:
            violations.append({
                "rule": "R14",
                "severity": "P0",
                "type": "硬约束",
                "desc": f"ADX={adx}≥60 追高/追空风险，仓位应≤3%或放弃",
                "actual": f"position={position_pct}%",
                "expected": "position ≤ 3% 或方向放弃",
            })

        # ── R01-R02 的多头对称检查：方向=bull 时检查超买 ──
        if direction == "bull" and rsi > 70 and confidence == "高":
            violations.append({
                "rule": "R01-sym",
                "severity": "P1",
                "type": "软约束",
                "desc": f"多头RSI={rsi}>70 超买风险，建议降为SELL中",
                "actual": f"confidence=高",
                "expected": "confidence ≤ 中 或标注超买风险",
            })

        # ── 冲突检查：conflict=true + direction与ft_dir反向 ──
        if conflict and ft_dir != "neutral":
            dir_opposite = (
                (direction == "bear" and ft_dir == "bull") or
                (direction == "bull" and ft_dir == "bear")
            )
            if dir_opposite:
                violations.append({
                    "rule": "R-conflict",
                    "severity": "P1",
                    "type": "软约束",
                    "desc": f"conflict标记 + direction={direction}与ft_dir={ft_dir}相反",
                    "actual": "冲突品种方向与因子择时反向",
                    "expected": "需标注冲突原因及override理由",
                })

        # ── 共振检查：resonance=0 → 无因子确认，应适度降仓 ──
        if resonance == 0:
            expected_max = conf_max_pos(confidence) * 0.7
            if position_pct > expected_max + 1e-6:  # +epsilon 防止浮点边界误判（如 2.45 > 3.5*0.7）
                violations.append({
                    "rule": "R-resonance",
                    "severity": "P1",
                    "type": "软约束",
                    "desc": f"共振=0无因子择时确认，仓位应≤{expected_max}%",
                    "actual": f"position={position_pct}%",
                    "expected": f"position ≤ {expected_max}%",
                })

        return violations

    def check_all(self, verdicts: List[Dict]) -> Tuple[float, List[Dict]]:
        """对全部裁决执行规则检查，返回 (D4评分, 违规明细)"""
        all_violations = []
        rule_hit_count = {"P0": 0, "P1": 0}

        for v in verdicts:
            v_violations = self.check_verdict(v)
            for viol in v_violations:
                viol["symbol"] = v.get("symbol", "?")
                viol["name"] = v.get("name", "")
                viol["direction"] = v.get("direction", "")
                viol["adx"] = v.get("adx", 0)
                viol["rsi"] = v.get("rsi", 0)
                viol["chain"] = v.get("chain", "")
            all_violations.extend(v_violations)
            for viol in v_violations:
                rule_hit_count[viol["severity"]] += 1

        total_checks = len(verdicts) * 4  # 每条裁决~4个检查点（R01/R02/R13/R14 变量叠）
        p0_weight = 1.0
        p1_weight = 0.5
        total_penalty = rule_hit_count["P0"] * p0_weight + rule_hit_count["P1"] * p1_weight
        max_penalty = total_checks * p0_weight
        d4_score = max(0.0, min(1.0, 1.0 - (total_penalty / max(max_penalty, 1))))

        return d4_score, all_violations


# ── D5: Reliability — 闭环完成率 ──

def compute_reliability(journal_entries: List[Dict], exclude_signatures: Optional[List[str]] = None) -> Tuple[float, Dict]:
    """从 debate_journal 计算可靠性指标。

    exclude_signatures: 匹配到 steps 文本的失败签名，判定为"基础设施/陈旧失败"，
      不计入当前(headline)可靠性；raw 明细仍透明保留以供审计。
      默认排除 "目标目录不存在"（reports/ 目录修复前的环境 bug，非辩论逻辑缺陷）。
    """
    exclude_signatures = exclude_signatures or ["目标目录不存在"]
    total = len(journal_entries)
    if total == 0:
        return 1.0, {"total_sessions": 0, "message": "无 session 数据"}

    def _classify(entries: List[Dict]) -> Tuple[float, Dict]:
        total = len(entries)  # 必须用本函数入参长度，而非闭包外层 total
        errors: List[Dict] = []
        completions = 0
        partial = 0
        failures = 0
        error_types: Dict[str, int] = {}
        for entry in entries:
            action = entry.get("action", entry.get("type", "unknown"))
            steps = entry.get("steps", [])
            has_error = False
            error_msg = ""
            if steps:
                for s in steps:
                    if isinstance(s, str) and ("⚠" in s or "❌" in s or "失败" in s):
                        has_error = True
                        error_msg = s.split(":")[-1].strip() if ":" in s else s
                        error_types[error_msg] = error_types.get(error_msg, 0) + 1
            if entry.get("report_count", 0) == 0 and action == "daily_debate_full":
                has_error = True
                error_msg = "report_count=0"
                error_types[error_msg] = error_types.get(error_msg, 0) + 1
            if has_error:
                failures += 1
                errors.append({
                    "timestamp": entry.get("timestamp", entry.get("triggered_at", "")),
                    "action": action,
                    "error": error_msg or "未知错误",
                })
            elif action in ("verdict", "chain_analysis", "dual_scan", "daily_debate_full"):
                if entry.get("report_count", 1) > 0:
                    completions += 1
                else:
                    partial += 1
            else:
                completions += 1
        r_complete = completions / total if total > 0 else 0
        r_failure = failures / total if total > 0 else 0
        d5 = r_complete * (1.0 - r_failure) + r_failure * 0.3  # 失败仍给 0.3 残值
        return d5, {
            "total_sessions": total,
            "completed": completions,
            "partial": partial,
            "failed": failures,
            "completion_rate": round(r_complete, 3),
            "failure_rate": round(r_failure, 3),
            "error_types": error_types,
            "errors": errors,
        }

    raw_score, raw_detail = _classify(journal_entries)

    # ── C 项：排除陈旧/基础设施失败 → fresh headline ──
    stale = 0
    fresh_entries = []
    for entry in journal_entries:
        steps = entry.get("steps", [])
        step_text = " ".join(map(str, steps))
        if any(sig in step_text for sig in exclude_signatures):
            stale += 1
            continue
        fresh_entries.append(entry)

    fresh_score, fresh_detail = _classify(fresh_entries)

    return fresh_score, {
        "raw_score": round(raw_score, 3),
        "fresh_score": round(fresh_score, 3),
        "stale_excluded": stale,
        "exclude_signatures": exclude_signatures,
        "raw": raw_detail,
        "fresh": fresh_detail,
        # headline 字段（供 D5 轴块与摘要使用）默认取 fresh
        "total_sessions": fresh_detail["total_sessions"],
        "completed": fresh_detail["completed"],
        "partial": fresh_detail["partial"],
        "failed": fresh_detail["failed"],
        "completion_rate": fresh_detail["completion_rate"],
        "failure_rate": fresh_detail["failure_rate"],
        "error_types": fresh_detail["error_types"],
        "errors": fresh_detail["errors"],
    }


# ── D2: Acuity — 信号-噪音辨识力（Spearman 秩相关，无第三方依赖）──

def _rankdata(xs: List[float]) -> List[float]:
    """平均秩（处理并列值）"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based 平均秩
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _spearman(a: List[float], b: List[float]) -> float:
    """Spearman 秩相关系数（纯标准库实现）"""
    n = len(a)
    if n < 3:
        return 0.0
    ra = _rankdata(a)
    rb = _rankdata(b)
    ma = sum(ra) / n
    mb = sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((x - mb) ** 2 for x in rb))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def compute_acuity(verdicts_pnl: List[Dict]) -> Tuple[float, Dict]:
    """D2 Acuity — 信号-噪音辨识力

    D2 = ρs(quality, I_info) − ρs(quality, N_noise)

      quality  = realized_pnl_pct（已验证真实盈亏，已按方向对齐）
      I_info   = resonance（因子择时共振确认 0/1）— 信息性信号代理
      N_noise  = adx（高ADX=趋势衰竭/假突破噪音代理）

    正值 = 辨识力正常（好交易伴随信息信号、远离噪音）
    负值 = 系统在追逐噪音（高ADX/共振品种反而更差）
    """
    if len(verdicts_pnl) < 10:
        return 0.0, {"n": len(verdicts_pnl), "reason": "样本不足(<10)"}

    quality = [float(v.get("realized_pnl_pct", 0.0)) for v in verdicts_pnl]
    i_info = [float(v.get("resonance", 0)) for v in verdicts_pnl]
    n_noise = [float(v.get("adx", 0)) for v in verdicts_pnl]

    rho_info = _spearman(quality, i_info)
    rho_noise = _spearman(quality, n_noise)
    d2 = rho_info - rho_noise

    # 辅助诊断：共振组 vs 非共振组 平均 PnL
    res_on = [q for q, r in zip(quality, i_info) if r == 1]
    res_off = [q for q, r in zip(quality, i_info) if r == 0]
    avg_res_on = sum(res_on) / len(res_on) if res_on else 0.0
    avg_res_off = sum(res_off) / len(res_off) if res_off else 0.0

    # ADX 高/低组平均 PnL
    adx_high = [q for q, a in zip(quality, n_noise) if a >= 60]
    adx_low = [q for q, a in zip(quality, n_noise) if a < 60]
    avg_adx_high = sum(adx_high) / len(adx_high) if adx_high else 0.0
    avg_adx_low = sum(adx_low) / len(adx_low) if adx_low else 0.0

    # ── 信号质量退化检测（B 项）──
    # resonance=1 占比过低或样本不足 → ρ_info 不可靠，D2 值不应解读为"系统辨识力"
    res_on = [q for q, r in zip(quality, i_info) if r == 1]
    frac_on = len(res_on) / len(i_info) if i_info else 0
    # 阈值修正：设计意图为"共振=0 占多数(≥75%)即退化"。真实数据恰 frac_on=0.25(5/20)，
    # 边界应判退化，故用 <= 0.25（而非 < 0.25）以忠实体现"75% 退化为 0"的告警意图。
    degenerate = (frac_on <= 0.25) or (len(res_on) < 5)
    signal_quality = "degenerate" if degenerate else "informative"
    degenerate_note = (
        "共振信号退化（resonance=1 占比<25% 或样本<5）：ρ_info 不可靠，"
        "D2 值仅作信号质量告警，不应解读为'系统辨识力=0.022'。需改进辩论共振信号设计。"
    ) if degenerate else None

    return d2, {
        "n": len(verdicts_pnl),
        "rho_info": round(rho_info, 3),
        "rho_noise": round(rho_noise, 3),
        "signal_quality": signal_quality,
        "resonance_frac_on": round(frac_on, 3),
        "resonance_group_avg_pnl": round(avg_res_on, 3),
        "non_resonance_group_avg_pnl": round(avg_res_off, 3),
        "adx_ge60_group_avg_pnl": round(avg_adx_high, 3),
        "adx_lt60_group_avg_pnl": round(avg_adx_low, 3),
        "degenerate_note": degenerate_note,
        "diagnostic": (
            "共振组平均PnL低于非共振组，且高ADX品种与负收益正相关，"
            "系统在高ADX/共振环境下存在噪音追逐倾向"
            if (avg_res_on < avg_res_off or rho_noise > 0)
            else "信号选择基本有效：信息信号与收益正相关、噪音与收益负相关"
        ),
    }


# ── D1: Coherence — 裁决-论据一致性（held-out judge）──

def _norm_variety(sym: str) -> str:
    return (sym or "").split(".")[0].upper().strip()


def compute_coherence(debate_records: List[Dict]) -> Tuple[Optional[float], Dict]:
    """D1 Coherence — 裁决是否真正源于辩论论据。

    读取 debate_record 的 held_out_judge.coherence_score 均值（CLQT §6.4.1 held-out judge）。
    附加自动校验：胜方论据是否被记录（论据-方向可审计性）。
    """
    scored = [
        r for r in debate_records
        if isinstance(r.get("held_out_judge"), dict)
        and r["held_out_judge"].get("coherence_score") is not None
    ]
    n = len(scored)
    if n == 0:
        return None, {
            "n": 0,
            "reason": "无带 held_out_judge 的 debate_record（机制已就位，等待首轮辩论产出）",
        }

    scores = [float(r["held_out_judge"]["coherence_score"]) for r in scored]
    mean = sum(scores) / n

    direction_auditable = 0
    for r in scored:
        v = r.get("verdict", {})
        winner_side = r.get("pro_args") if str(v.get("direction", "")).lower() in ("bear", "short", "sell") else r.get("con_args")
        if winner_side:
            direction_auditable += 1

    return mean, {
        "n": n,
        "mean_coherence": round(mean, 3),
        "min": round(min(scores), 3),
        "max": round(max(scores), 3),
        "direction_auditable": direction_auditable,
        "note": "held-out judge 一致性（CLQT §6.4.1）；≥0.8=裁决由论据充分支撑，<0.5=忽视反方重大质疑",
    }


# ── D3: Composure — 波动率-过度反应 ──

def compute_composure(debate_records: List[Dict], followup: Dict) -> Tuple[Optional[float], Dict]:
    """D3 Composure — 波动率越高、止损触发/亏损越大 → 组合度越差。

    取各 debate_record 的 volatility.adx（自变量）与 ground_truth 的 hit_stop/净PnL（因变量），
    对 hit_stop ~ adx 做线性回归，斜率越陡（高波动更易止损=过度反应）→ 组合度越差。
    门控：去重辩论轮次 ≥5 才计算；否则 blocked(n/5)。
    """
    rounds = set(r.get("round_id") for r in debate_records if r.get("round_id"))
    n_rounds = len(rounds)
    if n_rounds < 5:
        return None, {
            "status": "blocked",
            "n_rounds": n_rounds,
            "threshold": 5,
            "reason": f"需 ≥5 轮辩论的波动率-止损配对，当前 {n_rounds}/5 轮",
            "action_required": "积累 ≥5 轮 debate_record 后由 d3_auto_light 触发器自动点亮",
        }

    # join ground_truth（hit_stop / 净PnL）from followup，key=(round_id, variety)
    gt: Dict = {}
    for rec in followup.get("records", []):
        rid = rec.get("round_id")
        for i, v in enumerate(rec.get("verdicts", [])):
            vr = rec.get("validation_results", {}).get("results", [])
            res = vr[i] if i < len(vr) else {}
            gt[(_norm_variety(rid), _norm_variety(v.get("symbol")))] = res

    xs, ys_stop = [], []
    matched = 0
    for r in debate_records:
        adx = r.get("volatility", {}).get("adx")
        if adx is None:
            continue
        rid = r.get("round_id")
        sym = r.get("symbol") or r.get("variety")
        res = gt.get((_norm_variety(rid), _norm_variety(sym)))
        if res is None:
            res = gt.get((None, _norm_variety(sym)))
        if res is None:
            continue
        xs.append(float(adx))
        ys_stop.append(1.0 if res.get("hit_stop") else 0.0)
        matched += 1

    if len(xs) < 5:
        return None, {
            "status": "blocked",
            "n_matched": matched,
            "reason": "匹配到 ground_truth 的 debate_record 不足 5 条",
            "action_required": "辩论轮次需同时具备 debate_record 与 execution_followup 验证",
        }

    # 简单线性回归斜率
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys_stop) / n
    num = sum((xs[i] - mx) * (ys_stop[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0
    d3 = max(0.0, min(1.0, 1.0 - abs(slope)))
    return d3, {
        "status": "active",
        "n_rounds": n_rounds,
        "n_matched": matched,
        "slope_stop_vs_adx": round(slope, 4),
        "mean_adx": round(mx, 2),
        "mean_stop_rate": round(my, 3),
        "interpretation": "斜率>0 表示高波动品种更易触发止损（过度反应）；D3=1-|slope| 衡量组合度",
    }


# ── 主入口 ──

def main() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 加载数据
    followup = load_json(FOLLOWUP_PATH)
    journal = load_json(JOURNAL_PATH)

    # 提取裁决
    records = followup.get("records", [])
    all_verdicts = []
    for rec in records:
        all_verdicts.extend(rec.get("verdicts", []))

    # 提取 journal entries
    journal_entries = journal.get("entries", [])

    # 提取 debate_record 条目（D1/D3 源）
    debate_records = [e for e in journal_entries if e.get("action") == "debate_record"]

    # ── D4: Discipline ──
    checker = RuleChecker()
    d4_score, d4_violations = checker.check_all(all_verdicts)

    # 按规则聚合
    by_rule: Dict[str, Dict] = {}
    for v in d4_violations:
        r = v["rule"]
        if r not in by_rule:
            by_rule[r] = {"rule": r, "type": v["type"], "severity": v["severity"],
                          "desc": v["desc"], "count": 0, "symbols": []}
        by_rule[r]["count"] += 1
        by_rule[r]["symbols"].append(v["symbol"])

    # 按品种聚合
    by_symbol: Dict[str, Dict] = {}
    for v in d4_violations:
        sym = v["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {"symbol": sym, "name": v.get("name", ""), "chain": v.get("chain", ""),
                              "violation_count": 0, "rules": []}
        by_symbol[sym]["violation_count"] += 1
        by_symbol[sym]["rules"].append(v["rule"])

    # ── D5: Reliability ──
    d5_score, d5_detail = compute_reliability(journal_entries)

    # ── 交叉引用 failure_clusters ──
    cluster_ref = None
    if CLUSTERS_PATH.exists():
        clusters_data = load_json(CLUSTERS_PATH)
        cluster_ref = {
            "generated_at": clusters_data.get("generated_at", ""),
            "total_clusters": clusters_data["summary"]["total_clusters"],
            "high_severity": clusters_data["summary"]["high_severity"],
            "patterns": [
                {"id": c["cluster_id"], "pattern": c["pattern"],
                 "severity": c["severity"], "cases": c["total_cases"]}
                for c in clusters_data.get("clusters", [])
            ],
        }

    # ── PnL 验证状态 ──
    validation_status = followup.get("records", [{}])[0].get("validation_results", {})
    pnl_ready = validation_status.get("validatable", False)
    pnl_total = validation_status.get("total", 0)
    pnl_unknown = validation_status.get("unknown", 0)

    # ── 构建 裁决+验证PnL 合并列表（用于 D2 Acuity）──
    verdicts_pnl: List[Dict] = []
    for rec in records:
        vr = rec.get("validation_results", {})
        res_list = vr.get("results", [])
        vs = rec.get("verdicts", [])
        for i, v in enumerate(vs):
            pnl_info = res_list[i] if i < len(res_list) else {}
            merged = dict(v)
            merged["realized_pnl_pct"] = float(pnl_info.get("realized_pnl_pct", 0.0))
            merged["correct"] = bool(pnl_info.get("correct", False))
            verdicts_pnl.append(merged)

    # ── D2: Acuity（仅 PnL 就绪时计算真实分数）──
    d2_score = None
    d2_detail = {}
    d2_status = "blocked"
    if pnl_ready and pnl_unknown == 0 and pnl_total >= 10:
        d2_score, d2_detail = compute_acuity(verdicts_pnl)
        d2_status = "degenerate" if d2_detail.get("signal_quality") == "degenerate" else "active"

    # ── D1: Coherence（有 held-out judge 评分即算分）──
    d1_score, d1_detail = compute_coherence(debate_records)
    d1_status = "active" if d1_score is not None else "ready"

    # ── D3: Composure（去重轮次 ≥5 自动点亮）──
    d3_score, d3_detail = compute_composure(debate_records, followup)
    d3_status = d3_detail.get("status", "blocked")

    # ── 构建输出 ──
    # APM Overall = 当前已激活轴的等权均值（CLQT 等权哲学；D1 ready/D3 门控时暂不计入）
    active_scores = [d4_score, d5_score]
    # 设计书 B 项：D2 在 degenerate 时仍计入 overall（避免人为抬高；[DEGENERATE] 标签已透明标注）
    if d2_status in ("active", "degenerate") and d2_score is not None:
        active_scores.append(d2_score)
    if d1_status == "active" and d1_score is not None:
        active_scores.append(d1_score)
    if d3_status == "active" and d3_score is not None:
        active_scores.append(d3_score)
    apm_overall = sum(active_scores) / len(active_scores)

    scorecard = {
        "_schema_version": "1.0",
        "_methodology": "CLQT APM-CS (arXiv:2606.29771) adapted for FDT",
        "generated_at": now,
        "data_range": {
            "verdicts_total": len(all_verdicts),
            "sessions_total": len(journal_entries),
            "pnl_validated": 0 if pnl_unknown > 0 else pnl_total,
            "pnl_unvalidated": pnl_unknown,
        },
        "apm_overall": round(apm_overall, 3),
        "axes": {
            "D1_Coherence": (
                {
                    "score": round(d1_score, 3),
                    "status": "active",
                    "description": "裁决-论据一致性（held-out judge, CLQT §6.4.1）。D1=裁决是否真正源于辩论论据。",
                    "mean_coherence": d1_detail.get("mean_coherence"),
                    "n": d1_detail.get("n"),
                    "min": d1_detail.get("min"),
                    "max": d1_detail.get("max"),
                    "direction_auditable": d1_detail.get("direction_auditable"),
                    "note": d1_detail.get("note"),
                }
                if d1_status == "active"
                else {
                    "score": None,
                    "status": "ready",
                    "reason": "机制已就位（schema 升级 + held-out judge + held_out_judge 字段）。尚无带 held_out_judge 的 debate_record。",
                    "action_required": "每轮辩论由 futures-judge-heldout 产出 held_out_judge，首条即点亮 D1",
                }
            ),
            "D2_Acuity": (
                {
                    "score": round(d2_score, 3),
                    "status": d2_status,
                    "description": "信号-噪音辨识力。D2 = ρs(PnL, 共振信号) − ρs(PnL, ADX噪音)。正值=好交易伴随信息信号、远离噪音；负值=追逐噪音。",
                    "rho_info": d2_detail.get("rho_info"),
                    "rho_noise": d2_detail.get("rho_noise"),
                    "signal_quality": d2_detail.get("signal_quality"),
                    "resonance_frac_on": d2_detail.get("resonance_frac_on"),
                    "degenerate_note": d2_detail.get("degenerate_note"),
                    "resonance_group_avg_pnl": d2_detail.get("resonance_group_avg_pnl"),
                    "non_resonance_group_avg_pnl": d2_detail.get("non_resonance_group_avg_pnl"),
                    "adx_ge60_group_avg_pnl": d2_detail.get("adx_ge60_group_avg_pnl"),
                    "adx_lt60_group_avg_pnl": d2_detail.get("adx_lt60_group_avg_pnl"),
                    "diagnostic": d2_detail.get("diagnostic"),
                    "n": d2_detail.get("n"),
                }
                if d2_status in ("active", "degenerate")
                else {
                    "score": None,
                    "status": "blocked",
                    "reason": "需跨多轮 PnL 交叉验证数据计算 Spearman 秩相关。当前 %d 条裁决 PnL=unknown。至少需要 10+ 条 validated 裁决。" % pnl_unknown,
                    "action_required": "validate_verdicts.py 成功获取 ≥10 条已验证 PnL 后自动解锁",
                }
            ),
            "D3_Composure": (
                {
                    "score": round(d3_score, 3),
                    "status": "active",
                    "description": "波动率-过度反应。D3=1-|slope(stop~ADX)|。斜率>0=高波动更易止损(过度反应)。",
                    "slope_stop_vs_adx": d3_detail.get("slope_stop_vs_adx"),
                    "n_rounds": d3_detail.get("n_rounds"),
                    "n_matched": d3_detail.get("n_matched"),
                    "mean_adx": d3_detail.get("mean_adx"),
                    "mean_stop_rate": d3_detail.get("mean_stop_rate"),
                    "interpretation": d3_detail.get("interpretation"),
                }
                if d3_status == "active"
                else {
                    "score": None,
                    "status": d3_status,
                    "reason": d3_detail.get("reason", "需 ≥5 轮辩论的波动率-止损配对"),
                    "n_rounds": d3_detail.get("n_rounds", len({r.get("round_id") for r in debate_records if r.get("round_id")})),
                    "action_required": d3_detail.get("action_required", "积累 ≥5 轮辩论后自动点亮"),
                }
            ),
            "D4_Discipline": {
                "score": round(d4_score, 3),
                "status": "active",
                "description": "裁决对 R01-R14 规则的自我遵守度。P0 硬约束权重 1.0，P1 软约束权重 0.5。",
                "total_violations": len(d4_violations),
                "p0_violations": sum(1 for v in d4_violations if v["severity"] == "P0"),
                "p1_violations": sum(1 for v in d4_violations if v["severity"] == "P1"),
                "by_rule": sorted(by_rule.values(), key=lambda x: x["count"], reverse=True),
                "by_symbol": sorted(by_symbol.values(), key=lambda x: x["violation_count"], reverse=True),
                "top_violations": d4_violations[:10],
            },
            "D5_Reliability": {
                "score": round(d5_score, 3),
                "status": "active",
                "description": "辩论 session 闭环完成率与错误率。",
                "detail": d5_detail,
            },
        },
        "cross_reference": {
            "failure_clusters": cluster_ref,
        },
    }

    # 写入
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, ensure_ascii=False, indent=2)

    # ── 终端摘要 ──
    print("=" * 64)
    print("  APM-CS 五轴能力诊断评分卡")
    print("  方法论: CLQT (arXiv:2606.29771) → FDT 适配")
    print("=" * 64)
    print(f"\n  数据源: {len(all_verdicts)} 条裁决, {len(journal_entries)} 个 session")
    d2_tag = " (D2 已就绪)" if (pnl_unknown == 0 and pnl_total >= 10) else ""
    print(f"  PnL 验证: {pnl_total - pnl_unknown}/{pnl_total} 已验证, {pnl_unknown} unknown{d2_tag}")
    print()
    active_axes = [
        a for a, key in [
            ("D1", "D1_Coherence"), ("D2", "D2_Acuity"),
            ("D3", "D3_Composure"), ("D4", "D4_Discipline"), ("D5", "D5_Reliability"),
        ] if scorecard["axes"][key]["status"] == "active"
    ]
    print(f"  APM Overall:  {apm_overall:.3f}  (激活轴等权均值: {', '.join(active_axes) or '—'})")
    print(f"  ─────────────────────────────────")
    d1ax = scorecard["axes"]["D1_Coherence"]
    d1str = f"{d1ax['score']:.3f}  (n={d1ax.get('n')}, mean_coh={d1ax.get('mean_coherence')})" if d1ax["status"] == "active" else "— 机制就位，待 debate_record"
    print(f"  D1 Coherence   : {d1ax['status'].upper()}  {d1str}")
    d2ax = scorecard["axes"]["D2_Acuity"]
    d2str = f"{d2ax['score']:.3f}  (ρ_info={d2ax.get('rho_info')}, ρ_noise={d2ax.get('rho_noise')})" if d2ax["status"] in ("active", "degenerate") else "— 缺 PnL 交叉验证"
    d2_tag = " [DEGENERATE]" if d2ax.get("status") == "degenerate" else ""
    print(f"  D2 Acuity      : {d2ax['status'].upper()}{d2_tag}  {d2str}")
    d3ax = scorecard["axes"]["D3_Composure"]
    d3str = f"{d3ax['score']:.3f}  (slope={d3ax.get('slope_stop_vs_adx')}, 轮={d3ax.get('n_rounds')})" if d3ax["status"] == "active" else f"— {d3ax.get('n_rounds',0)}/5 轮"
    print(f"  D3 Composure   : {d3ax['status'].upper()}  {d3str}")
    print(f"  D4 Discipline  : {d4_score:.3f}  ({len(d4_violations)} 条违规)")
    print(f"  D5 Reliability : {d5_score:.3f}  (完成率 {d5_detail['completion_rate']:.1%}; raw={d5_detail.get('raw_score')}, 剔除陈旧 {d5_detail.get('stale_excluded')} 例)")
    if d2_status == "active":
        print(f"\n  D2 诊断: {d2_detail.get('diagnostic', '')}")
        print(f"    共振组平均PnL={d2_detail.get('resonance_group_avg_pnl')}% | 非共振组={d2_detail.get('non_resonance_group_avg_pnl')}%")
        print(f"    ADX≥60组平均PnL={d2_detail.get('adx_ge60_group_avg_pnl')}% | ADX<60组={d2_detail.get('adx_lt60_group_avg_pnl')}%")
    print()
    print(f"  D4 违规分布:")
    for rule_info in sorted(by_rule.values(), key=lambda x: x["count"], reverse=True):
        symbols_str = ",".join(rule_info["symbols"][:5])
        trail = "..." if len(rule_info["symbols"]) > 5 else ""
        print(f"    [{rule_info['severity']}] {rule_info['rule']}: {rule_info['count']}次 → {symbols_str}{trail}")
    print()
    if d5_detail.get("error_types"):
        print(f"  D5 错误类型:")
        for et, cnt in d5_detail["error_types"].items():
            print(f"    {et}: {cnt}次")
    print(f"\n  输出: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
