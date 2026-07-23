"""
FDT Stage 3 自改进脚手架 (self_improve) — 增强版
===================================================
消费三类诊断输入，产出"改进建议清单"（CLQT 阶段三）。

已集成四技能流水线（v2026-07-11）：
  1. SkillAdaptor → 步级故障归因（替代模糊 proposal）
  2. Skillevolver → 高置信度故障自动生成 Agent MD 补丁
  3. EmbodiSkill → 四种反思分类（discovery/optimization/defect/lapse）
  4. Autoresearch → A/B 验证 + 自动驳回回滚

工作流：
  L2 诊断数据 → SkillAdaptor 步级归因 → 置信度≥0.8 → Skillevolver 补丁 → Autoresearch 验证 → deploy/rollback
                                                                 置信度<0.8 → proposal（人工介入）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# 确保脚本可以从任意 cwd 正确导入项目模块
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR.parent))

from scripts.analyze_trajectory import TrajectoryAnalyzer, FaultAttributor
from scripts.embodiskill_reflect import EmbodiSkillReflector
from scripts.skillevolver_evolution import SkillEvolver
from scripts.verify_evolution import EvolutionVerifier

PROJECT_ROOT = Path(__file__).parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"


def _load(rel: str):
    fp = MEMORY_DIR / rel
    if not fp.exists():
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def generate_improvement_suggestions(sc: str, clusters: list, replay: dict) -> str:
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


def enhanced_generate_with_evolution(sc: str, clusters: list, replay: dict) -> str:
    """增强版建议生成：集成四技能流水线。

    与 ``generate_improvement_suggestions`` 并存的增强入口。

    **执行流程**：
    1. SkillAdaptor 步级归因（从 debate_results.json 解析轨迹）
    2. EmbodiSkill 四种反思分类
    3. 高置信度(≥0.8) → 自动触发 Skillevolver 进化 + Autoresearch 验证
    4. 低置信度(<0.8) → 保持 proposal 状态
    """
    suggestions = generate_improvement_suggestions(sc, clusters, replay)

    # ── 1) SkillAdaptor: 轨迹解析 + 故障归因 ──
    analyzer = TrajectoryAnalyzer(PROJECT_ROOT)
    attributor = FaultAttributor()
    reflector = EmbodiSkillReflector(PROJECT_ROOT)
    evolver = SkillEvolver(PROJECT_ROOT)
    verifier = EvolutionVerifier(PROJECT_ROOT)

    debate_results_path = PROJECT_ROOT / "data" / "debate_results.json"
    if debate_results_path.exists():
        try:
            data = json.loads(debate_results_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    trajectory = analyzer.parse({"debate_results": data})
    if not trajectory:
        return suggestions  # fallback to original proposals

    # ── 2) 故障归因 ──
    faults = attributor.attribute(trajectory)

    # ── 3) EmbodiSkill 反思 ──
    for step in trajectory:
        reflector.reflect_on_trajectory([step], "")

    # ── 4) 分类处理 ──
    for fault in faults:
        confidence = fault.get("confidence", 0.0)
        if confidence >= 0.8:
            # 自动进化流水线
            updates = evolver.run_evolution_cycle(faults=[fault], dry_run=False)
            for u in updates:
                if u.get("status") == "ready":
                    # Autoresearch A/B 验证
                    ab_result = verifier.verify(
                        "baseline (current config)",
                        f"evolved ({fault.get('fault_agent', '?')})",
                    )
                    suggestion = {
                        "source": "skill_adaptor+skillevolver",
                        "priority": "P0",
                        "target_file": u.get("target_file", ""),
                        "patch": u.get("patch", ""),
                        "fault_type": fault.get("fault_type", ""),
                        "fault_agent": fault.get("fault_agent", ""),
                        "fault_step": fault.get("fault_step_id", ""),
                        "confidence": confidence,
                        "ab_verdict": ab_result.get("verdict", "rejected"),
                        "ab_delta": ab_result.get("delta", 0.0),
                        "status": "approved" if ab_result.get("verdict") == "approved" else "pending_manual",
                    }
                    suggestions.append(suggestion)
                else:
                    suggestions.append({
                        "source": "skillevolver",
                        "priority": "P1",
                        "fault_agent": fault.get("fault_agent", ""),
                        "fault_type": fault.get("fault_type", ""),
                        "status": "rejected_audit",
                        "confidence": confidence,
                        "audit_failures": u.get("audit_failures", []),
                    })
        else:
            # 低置信度 → proposal（人工介入）
            suggestions.append({
                "source": "skill_adaptor",
                "priority": "P1",
                "fault_type": fault.get("fault_type", ""),
                "agent": fault.get("fault_agent", ""),
                "step": fault.get("fault_step_id", ""),
                "evidence": fault.get("evidence", "")[:200],
                "confidence": confidence,
                "status": "proposal",
            })

    return suggestions


def main():
    sc = _load("apm_scorecard.json")
    clusters = _load("failure_clusters.json")
    replay = _load("benchmark_replay.json")

    suggestions = enhanced_generate_with_evolution(sc, clusters, replay)

    log_path = MEMORY_DIR / "self_improve_log.json"
    log = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as lf:
                log = json.load(lf)
            if isinstance(log, dict):
                log = log.get("entries", [])
        except Exception:
            log = []
    entry = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "enhanced",
        "n_suggestions": len(suggestions),
        "suggestions": suggestions,
    }
    log.append(entry)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"entries": log}, f, ensure_ascii=False, indent=2)

    # Print summary
    prio_counts = {}
    for s in suggestions:
        p = s.get("priority", "?")
        st = s.get("status", "proposal")
        key = f"{p}_{st}"
        prio_counts[key] = prio_counts.get(key, 0) + 1

    print("=" * 64)
    print("  Stage 3 自改进 — 增强版 (四技能流水线)")
    print("=" * 64)
    print(f"  建议总数: {len(suggestions)}")
    for key, count in sorted(prio_counts.items()):
        print(f"    {key}: {count}")
    print()

    auto_deployed = [s for s in suggestions if s.get("status") == "approved"]
    proposals = [s for s in suggestions if s.get("status") == "proposal"]
    if auto_deployed:
        print(f"  ✅ 自动部署: {len(auto_deployed)}")
        for s in auto_deployed:
            print(f"    {s.get('fault_agent', '?')} → {s.get('target_file', '?')}")
    if proposals:
        print(f"  📋 待人工审阅: {len(proposals)}")
    print(f"\n  已写入: {log_path}")


if __name__ == "__main__":
    main()
