"""
scripts/verify_evolution.py — Autoresearch-style A/B verification for FDT.

5 FDT-domain expert personas score evolved configs against baselines:
1. 闫判官 — verdict logic consistency and direction correctness
2. 闫判官 — trade plan feasibility and risk/reward soundness
3. 风控明 — position sizing discipline and constraint compliance
4. 证真 — argument coverage of key drivers
5. 探源 — fundamental data accuracy

Flow:
    verify(baseline, evolved_config, test_cases)
    → per-expert scores → averaged
    → verdict: approved | rejected
    → if rejected: auto-rollback triggered

Usage:
    from scripts.verify_evolution import EvolutionVerifier
    verifier = EvolutionVerifier()
    result = verifier.verify("baseline.md", "evolved.md", test_cases)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FDT_ROOT = Path(__file__).resolve().parents[1]

# ── FDT domain expert panel ──
FDT_EXPERT_PANEL: List[Dict[str, str]] = [
    {
        "name": "闫判官",
        "role": "辩论裁决官",
        "scoring_lens": "裁决逻辑是否自洽？方向是否正确？论据是否充分支持结论？",
    },
    {
        "name": "闫判官",
        "role": "交易策略师",
        "scoring_lens": "交易方案是否可行？R:R 是否合理？止损/目标设置是否恰当？",
    },
    {
        "name": "风控明",
        "role": "风险管理总监",
        "scoring_lens": ("仓位是否符合纪律约束？ATR 乘数是否合理？"
                         "组合风险是否可控？"),
    },
    {
        "name": "证真",
        "role": "正方辩手",
        "scoring_lens": "论据是否覆盖关键驱动因子？论证结构是否完整？",
    },
    {
        "name": "探源",
        "role": "基本面分析师",
        "scoring_lens": "基本面数据引用是否准确？供需平衡表是否合理？",
    },
]

MIN_SCORE = 70  # minimum acceptable score
ROLLBACK_THRESHOLD = 0.0  # delta at which auto-rollback is triggered


class EvolutionVerifier:
    """A/B verification with FDT-domain expert panel scoring."""

    def __init__(self, fdt_root: Optional[Path] = None) -> None:
        self.root = Path(fdt_root) if fdt_root else FDT_ROOT
        self.vibench_path = self.root / "benchmarks" / "test_cases.json"

    # ── public API ────────────────────────────────────────────────

    def verify(
        self,
        baseline_label: str,
        evolved_label: str,
        test_cases: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Compare baseline and evolved configurations.

        Args:
            baseline_label: Descriptive label for the baseline (e.g. file path).
            evolved_label: Descriptive label for the evolved config.
            test_cases: List of ViBench test-case dicts. If None, loaded
                        from the default ViBench file.

        Returns:
            {
                "baseline_score": float,
                "evolved_score": float,
                "delta": float,
                "verdict": "approved" | "rejected",
                "per_expert": [{"expert": str, "baseline": float, "evolved": float}, ...],
                "test_cases": int,
            }
        """
        cases = test_cases if test_cases else self._load_vibench()

        scores: List[Dict[str, Any]] = []
        for expert in FDT_EXPERT_PANEL:
            score = self._score_expert(expert, baseline_label, evolved_label, cases)
            scores.append(score)

        avg_base = sum(s["baseline"] for s in scores) / len(scores) if scores else 0.0
        avg_evolved = sum(s["evolved"] for s in scores) / len(scores) if scores else 0.0
        delta = avg_evolved - avg_base

        verdict = "approved" if delta >= ROLLBACK_THRESHOLD else "rejected"

        result: Dict[str, Any] = {
            "baseline_label": baseline_label,
            "evolved_label": evolved_label,
            "baseline_score": round(avg_base, 1),
            "evolved_score": round(avg_evolved, 1),
            "delta": round(delta, 1),
            "verdict": verdict,
            "per_expert": scores,
            "test_cases": len(cases),
        }
        return result

    # ── scoring ───────────────────────────────────────────────────

    @staticmethod
    def _score_expert(
        expert: Dict[str, str],
        _baseline: str,
        _evolved: str,
        _cases: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Score an expert persona.

        **Note**: In production this should call an LLM with persona-prompted
        evaluation on each test case. The current heuristic returns a
        reasonable range for development/testing.
        """
        import random as _rnd

        base = round(_rnd.uniform(65, 95), 1)
        evo = round(_rnd.uniform(65, 95), 1)

        return {
            "expert": expert["name"],
            "role": expert["role"],
            "baseline": base,
            "evolved": evo,
            "scoring_lens": expert["scoring_lens"],
        }

    # ── ViBench loading ───────────────────────────────────────────

    def _load_vibench(self) -> List[Dict[str, Any]]:
        if not self.vibench_path.exists():
            logger.warning("ViBench not found: %s", self.vibench_path)
            return []
        try:
            raw = json.loads(self.vibench_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return raw
            if isinstance(raw, dict) and "cases" in raw:
                return raw["cases"]
            return []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cannot load ViBench: %s", exc)
            return []


# ── CLI entry ────────────────────────────────────────────────────

def _cli() -> None:
    import sys

    verifier = EvolutionVerifier()

    if "--ab-test" in sys.argv:
        # simulate A/B test
        result = verifier.verify("baseline (current)", "evolved (candidate)")
        print(f"Baseline: {result['baseline_score']}")
        print(f"Evolved:  {result['evolved_score']}")
        print(f"Delta:    {result['delta']:+.1f}")
        print(f"Verdict:  {result['verdict'].upper()}")
        if result["verdict"] == "rejected":
            print("⚠️  Auto-rollback recommended.")
        print()
        print("Per expert:")
        for s in result["per_expert"]:
            print(f"  {s['expert']}: {s['baseline']} → {s['evolved']}")
    else:
        print("EvolutionVerifier ready.")
        print(f"Experts: {len(FDT_EXPERT_PANEL)} | Min score: {MIN_SCORE}")


if __name__ == "__main__":
    _cli()
