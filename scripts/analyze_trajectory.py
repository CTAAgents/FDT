"""
scripts/analyze_trajectory.py — SkillAdaptor (arXiv:2606.01311)
Step-level trajectory analysis + fault attribution for FDT debate pipeline.

Parses debate_results.json and debate_journal.json into structured trajectories,
then attributes failures to specific steps, agents, and skills.

Usage:
    from scripts.analyze_trajectory import TrajectoryAnalyzer, FaultAttributor
    analyzer = TrajectoryAnalyzer()
    attributor = FaultAttributor()
    trajectory = analyzer.parse(debate_data)
    faults = attributor.attribute(trajectory)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

FDT_ROOT = Path(__file__).resolve().parents[1]

# ── trajectory schema keys ──
STEP_KEYS = {
    "step_id": str,      # "P1", "P3", "P4", "P5_judge", ...
    "agent_role": str,   # "数技源", "闫判官", "证真", ...
    "action": str,       # the action the agent performed
    "observation": str,  # output / result summary
    "reward": float,     # 1.0 = success, 0.0 = failure
    "skill_used": str,   # which skill was invoked
}


class TrajectoryAnalyzer:
    """Debate trajectory parser.

    Reads FDT debate artifacts and produces a list of structured steps
    suitable for fault attribution.
    """

    def __init__(self, fdt_root: Optional[Path] = None) -> None:
        self.root = Path(fdt_root) if fdt_root else FDT_ROOT

    # ── public API ────────────────────────────────────────────────

    def parse(self, source: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Return a trajectory from in-memory data or by reading disk artifacts.

        Args:
            source: If given, a dict with keys ``debate_results`` and/or
                    ``debate_journal``.  If *None*, the latest live files
                    under *self.root* are read.

        Returns:
            Ordered list of step dicts following *STEP_KEYS*.
        """
        data = source if source is not None else self._read_live_data()

        if not isinstance(data, dict):
            data = {}

        debate_results: Dict[str, Any] = data.get("debate_results", {}) or {}
        debate_journal: List[Dict[str, Any]] = data.get("debate_journal", []) or []
        if not isinstance(debate_journal, list):
            debate_journal = []

        steps: List[Dict[str, Any]] = []
        seen: set = set()

        for step in self._build_from_debate_results(debate_results):
            key = f"{step['step_id']}_{step['agent_role']}"
            if key not in seen:
                steps.append(step)
                seen.add(key)
        for step in self._build_from_journal(debate_journal):
            key = f"{step['step_id']}_{step['agent_role']}"
            if key not in seen:
                steps.append(step)
                seen.add(key)

        return steps

    # ── internal builders ─────────────────────────────────────────

    @staticmethod
    def _build_from_debate_results(results: Dict[str, Any]) -> List[Dict[str, Any]]:
        steps: List[Dict[str, Any]] = []

        # P1 – scan
        scan = results.get("scan") or {}
        signals = scan.get("signals", [])
        steps.append({
            "step_id": "P1",
            "agent_role": "数技源",
            "action": "channel_breakout_scan",
            "observation": json.dumps(signals[:5], ensure_ascii=False) if signals else "no_signals",
            "reward": 1.0 if signals else 0.0,
            "skill_used": "quant-daily",
        })

        # P3 – researchers
        researchers = results.get("researchers") or {}
        for role, skill in [("观澜", "technical-analysis"), ("探源", "fundamental-data-collector")]:
            rdata = researchers.get(role) or {}
            valid = bool(rdata.get("valid", False))
            steps.append({
                "step_id": "P3",
                "agent_role": role,
                "action": "research",
                "observation": rdata.get("summary", "") or "",
                "reward": 1.0 if valid else 0.0,
                "skill_used": skill,
            })

        # P4 – debaters
        debaters = results.get("debaters") or {}
        for role in ["证真", "慎思"]:
            ddata = debaters.get(role) or {}
            valid = bool(ddata.get("valid", False))
            args_raw = ddata.get("arguments", [])
            obs = json.dumps(args_raw[:3], ensure_ascii=False) if args_raw else ""
            steps.append({
                "step_id": "P4",
                "agent_role": role,
                "action": "argue",
                "observation": obs,
                "reward": 1.0 if valid else 0.0,
                "skill_used": "debate-argument-builder",
            })

        # P5 – judge verdict
        judge = results.get("judge") or {}
        steps.append({
            "step_id": "P5_judge",
            "agent_role": "闫判官",
            "action": "verdict",
            "observation": judge.get("reasoning", "") or "",
            "reward": 1.0,
            "skill_used": "debate-judge",
        })

        return steps

    @staticmethod
    def _build_from_journal(journal: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract steps from debate_journal.json array."""
        entry_fields = {
            "agent": ("agent_role", str),
            "action": ("action", str),
        }
        steps: List[Dict[str, Any]] = []
        for entry in journal:
            if not isinstance(entry, dict):
                continue
            agent_role = entry.get("agent", "unknown")
            action = entry.get("action", "unknown")
            steps.append({
                "step_id": entry.get("step", "P?"),
                "agent_role": agent_role,
                "action": action,
                "observation": json.dumps(entry.get("data", {}), ensure_ascii=False)[:500],
                "reward": 1.0 if entry.get("success", True) else 0.0,
                "skill_used": entry.get("skill", "unknown"),
            })
        return steps

    def _read_live_data(self) -> Dict[str, Any]:
        debate_results_path = self.root / "data" / "debate_results.json"
        journal_path = self.root / "memory" / "debate_journal.json"

        data: Dict[str, Any] = {}
        if debate_results_path.exists():
            try:
                data["debate_results"] = json.loads(
                    debate_results_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Cannot read %s: %s", debate_results_path, exc)
        if journal_path.exists():
            try:
                data["debate_journal"] = json.loads(
                    journal_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Cannot read %s: %s", journal_path, exc)
        return data


# ═══════════════════════════════════════════════════════════════════
# FaultAttributor
# ═══════════════════════════════════════════════════════════════════


class FaultAttributor:
    """Step-level fault attribution.

    Inspects a trajectory, identifies failing steps, and classifies each
    as a **skill defect** (the content is wrong) or an **execution lapse**
    (the content is right but the agent did not follow it).

    Produces actionable evidence suitable for downstream evolution modules
    (SkillEvolver, EmbodiSkill).
    """

    # Keywords that hint at schema/type errors (= skill defects)
    _DEFECT_HINTS = ("confidence", "schema", "type", "validation", "invalid",
                     "missing_field", "typeerror")

    def attribute(self, trajectory: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run attribution on a full trajectory.

        Returns:
            One fault record per failing step, each containing::

                {
                    "fault_step_id": str,
                    "fault_agent": str,
                    "fault_type": "skill_defect" | "execution_lapse",
                    "responsible_skill": str,
                    "evidence": str,
                    "confidence": float,
                    "fix_suggestion": dict,
                }
        """
        faults: List[Dict[str, Any]] = []
        for step in trajectory:
            if step.get("reward", 1.0) >= 0.5:
                continue  # not a failure

            fault_type = self._classify_fault(step)
            evidence = self._extract_evidence(step)
            confidence = self._calc_confidence(step, evidence)
            suggestion = self._generate_suggestion(step, fault_type)

            faults.append({
                "fault_step_id": step.get("step_id", "?"),
                "fault_agent": step.get("agent_role", "?"),
                "fault_type": fault_type,
                "responsible_skill": step.get("skill_used", "?"),
                "evidence": evidence,
                "confidence": confidence,
                "fix_suggestion": suggestion,
            })
        return faults

    # ── classification ────────────────────────────────────────────

    @staticmethod
    def _classify_fault(step: Dict[str, Any]) -> str:
        """Decide between **skill_defect** and **execution_lapse**.

        Heuristics (adapted from EmbodiSkill §3.3 + FDT known failures):
        - JSON schema / type errors → skill_defect (the skill spec is wrong).
        - ADX role not injected in spawn prompt → skill_defect.
        - Agent produced output but format doesn't match contract → skill_defect.
        - Agent reports "pattern followed but got unexpected result" → execution_lapse.
        """
        obs = (step.get("observation") or "").lower()
        for hint in FaultAttributor._DEFECT_HINTS:
            if hint in obs:
                return "skill_defect"
        evidence = step.get("observation", "")
        if "confidence" in evidence and ("type" in evidence or "str" in evidence or "float" in evidence):
            return "skill_defect"
        return "execution_lapse"

    # ── evidence extraction ───────────────────────────────────────

    @staticmethod
    def _extract_evidence(step: Dict[str, Any]) -> str:
        obs = step.get("observation", "")
        if len(obs) > 300:
            obs = obs[:300] + "…"
        return f"{step.get('step_id', '?')} {step.get('agent_role', '?')}: {step.get('action', '?')} — {obs}"

    # ── confidence ────────────────────────────────────────────────

    @staticmethod
    def _calc_confidence(step: Dict[str, Any], evidence: str) -> float:
        """Confidence based on defect-hint presence (+bias).

        Returns 0.85+ when clear defect signals are present, 0.65 otherwise.
        Threshold 0.8 is used by self_improve.py to gate auto-execution.
        """
        obs = (step.get("observation") or "").lower()
        hit_count = sum(1 for h in FaultAttributor._DEFECT_HINTS if h in obs)
        if hit_count >= 2:
            return 0.92
        if hit_count == 1:
            return 0.85
        return 0.65

    # ── fix suggestion ────────────────────────────────────────────

    @staticmethod
    def _generate_suggestion(
        step: Dict[str, Any],
        fault_type: str,
    ) -> Dict[str, str]:
        if fault_type == "skill_defect":
            return {
                "action": "修正",
                "target": step.get("skill_used", "unknown"),
                "content_hint": (
                    f"修正 {step.get('agent_role', '?')} Agent MD 中"
                    f"与 {step.get('step_id', '?')} 相关的约束"
                ),
            }
        return {
            "action": "强调",
            "target": f"agent_{step.get('agent_role', '?')}",
            "content_hint": (
                f"在 {step.get('agent_role', '?')} Agent MD S_appendix 中"
                f"添加强调项：{step.get('action', '')}"
            ),
        }


# ── CLI entry point ──────────────────────────────────────────────

def _cli() -> None:
    import sys
    import pprint

    source_arg = sys.argv[1] if len(sys.argv) > 1 else None

    if source_arg:
        path = Path(source_arg)
        if not path.exists():
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = None

    analyzer = TrajectoryAnalyzer()
    attributor = FaultAttributor()

    trajectory = analyzer.parse(data)
    faults = attributor.attribute(trajectory)

    print(f"Steps: {len(trajectory)} | Faults: {len(faults)}")
    for f in faults:
        print(f"  [{f['fault_step_id']}] {f['fault_agent']} | "
              f"{f['fault_type']} | conf={f['confidence']:.2f} | "
              f"skill={f['responsible_skill']}")
    print("\nDetail:")
    pprint.pprint(faults)


if __name__ == "__main__":
    _cli()
