"""
FDT Stage 3 自改进脚手架 (self_improve)
========================================
消费三类诊断输入，产出"改进建议清单"（CLQT 阶段三：harness 自改进 的最小骨架）。
不直接修改 Agent / skill 定义 —— 仅生成 proposal，待人工审阅或 ≥5 轮数据后接入自动执行。

输入：
  - memory/apm_scorecard.json    五轴诊断（D4 违规、D2 退化信号）
  - memory/failure_clusters.json 阶段一 Telescope 失败模式聚类
  - benchmarks/benchmark_replay.json  ViBench 回放结果

输出：
  - memory/self_improve_log.json  append 模式，保存每次生成的建议

用法：
  python scripts/self_improve.py
"""

import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"


def _load(rel: str):
    fp = MEMORY_DIR / rel
    if not fp.exists():
        return None
    try:
        return json.load(open(fp, "r", encoding="utf-8"))
    except Exception:
        return None


def generate_improvement_suggestions(sc, clusters, replay):
    suggestions = []

    # 1) 来自 D4 违规（纪律缺口）
    #    仓位类规则(R13/R14/R-resonance) → 强制 apply capped_position；
    #    标注类规则(R01/R02/R-conflict) → 复核信号/置信度赋值逻辑
    POSITION_RULES = {"R13", "R14", "R-resonance"}
    if sc:
        d4 = sc.get("axes", {}).get("D4_Discipline", {})
        for r in d4.get("by_rule", []):
            rule = r.get("rule", "")
            if r.get("severity") == "P0":
                if rule in POSITION_RULES:
                    txt = f"规则 {rule} 违规 {r['count']} 次 → 在裁决组装期强制 apply enforce_discipline.capped_position()"
                else:
                    txt = f"规则 {rule} 违规 {r['count']} 次 → 复核辩论信号/置信度/冲突标注逻辑（非仓位类，capped_position 不适用）"
                suggestions.append({"source": "D4_Discipline", "priority": "P0", "text": txt})
            elif r.get("severity") == "P1" and r["count"] >= 5:
                if rule in POSITION_RULES:
                    txt = f"规则 {rule} 违规 {r['count']} 次 → 复核该规则阈值或辩论信号赋值"
                else:
                    txt = f"规则 {rule} 违规 {r['count']} 次 → 复核置信度/冲突标注逻辑"
                suggestions.append({"source": "D4_Discipline", "priority": "P1", "text": txt})

        # 2) 来自 D2 degenerate（信号质量）
        d2 = sc.get("axes", {}).get("D2_Acuity", {})
        if d2.get("status") == "degenerate" or d2.get("signal_quality") == "degenerate":
            suggestions.append({
                "source": "D2_Acuity",
                "priority": "P1",
                "text": "共振信号退化（resonance=1 占比<25% 或样本<5）：ρ_info 不可靠，"
                        "需复盘辩论信号设计中 resonance 赋值逻辑，避免噪音追逐",
            })

        # 3) 来自 D3（若已点亮）
        d3 = sc.get("axes", {}).get("D3_Composure", {})
        if d3.get("status") == "active" and isinstance(d3.get("slope_stop_vs_adx"), (int, float)):
            slope = d3["slope_stop_vs_adx"]
            if slope > 0.3:
                suggestions.append({
                    "source": "D3_Composure",
                    "priority": "P1",
                    "text": f"高波动品种止损斜率={slope:.3f}（过度反应）："
                            f"对 ADX≥{d3.get('mean_adx', '?')} 品种收紧止损或降仓",
                })

    # 4) 来自失败聚类
    if clusters:
        for c in clusters.get("clusters", []):
            sev = c.get("severity", "")
            pri = "P0" if sev == "high" else ("P1" if sev == "medium" else "P2")
            suggestions.append({
                "source": "failure_clusters",
                "priority": pri,
                "text": f"聚类 {c['cluster_id']}({c['pattern']}) → {c['total_cases']} 例，"
                        f"纳入扫描风险加权 / 规则库补强",
            })

    # 5) 来自 ViBench 回放（coherence_weighted_accuracy 若已填充）
    if replay:
        cwa = replay.get("coherence_weighted_accuracy")
        if isinstance(cwa, (int, float)):
            suggestions.append({
                "source": "ViBench_replay",
                "priority": "P2",
                "text": f"回放 coherence_weighted_accuracy={cwa:.3f}："
                        f"作为阶段三 A/B 测试对照基线，比较 held-out judge 与实操裁决一致性",
            })

    return suggestions


def main():
    sc = _load("apm_scorecard.json")
    clusters = _load("failure_clusters.json")
    replay = _load("benchmark_replay.json")

    suggestions = generate_improvement_suggestions(sc, clusters, replay)

    log_path = MEMORY_DIR / "self_improve_log.json"
    log = []
    if log_path.exists():
        try:
            log = json.load(open(log_path, "r", encoding="utf-8"))
            if isinstance(log, dict):
                log = log.get("entries", [])
        except Exception:
            log = []
    entry = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "proposal",
        "n_suggestions": len(suggestions),
        "suggestions": suggestions,
    }
    log.append(entry)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"entries": log}, f, ensure_ascii=False, indent=2)

    print("=" * 64)
    print("  Stage 3 自改进脚手架 — 改进建议清单 (proposal)")
    print("=" * 64)
    print(f"  建议总数: {len(suggestions)}")
    print()
    for i, s in enumerate(suggestions, 1):
        print(f"  [{s['priority']}] ({s['source']}) {s['text']}")
    print()
    print(f"  已写入: {log_path}")


if __name__ == "__main__":
    main()
