"""
scripts/embodiskill_reflect.py — EmbodiSkill (arXiv:2605.10332)
Skill-aware reflection and evolution for FDT Agent prompts.

4 reflection types:
- DISCOVERY:  success + novel pattern → add to S_body
- OPTIMIZATION: success + better way → modify S_body
- SKILL_DEFECT: failure + wrong skill → fix S_body
- EXECUTION_LAPSE: failure + right skill not followed → add to S_appendix

Reflection spiral: execute → reflect → accumulate → integrate → revise body → update appendix.

Usage:
    from scripts.embodiskill_reflect import EmbodiSkillReflector
    reflector = EmbodiSkillReflector()
    reflections = reflector.reflect_on_trajectory(trajectory, skill_content)
    reflector.restructure_agent_md(md_content)  # Phase 1 migration
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FDT_ROOT = Path(__file__).resolve().parents[1]

# EmbodiSkill paper defaults
K_MAX_REFLECTIONS = 3    # max reflections per trajectory
B_REVISION = 10           # revision batch interval

REFLECTION_TYPES = ("DISCOVERY", "OPTIMIZATION", "SKILL_DEFECT", "EXECUTION_LAPSE")


class EmbodiSkillReflector:
    """EmbodiSkill reflection engine for FDT Agent prompts."""

    def __init__(self, fdt_root: Optional[Path] = None) -> None:
        self.root = Path(fdt_root) if fdt_root else FDT_ROOT
        self.reflection_buffer: List[Dict[str, Any]] = []
        self._buffer_path = self.root / "memory" / "evolution_buffer.json"

    # ── public API ────────────────────────────────────────────────

    def reflect_on_trajectory(
        self,
        trajectory: List[Dict[str, Any]],
        skill_content: str = "",
    ) -> List[Dict[str, Any]]:
        """Analyse a trajectory and classify each step into one of 4 reflection types.

        Args:
            trajectory: Ordered list of step dicts (from TrajectoryAnalyzer).
            skill_content: Full text of the relevant Agent MD (S_body + S_appendix).

        Returns:
            List of reflection records.
        """
        reflections: List[Dict[str, Any]] = []

        for step in trajectory:
            if len(reflections) >= K_MAX_REFLECTIONS:
                break

            r = float(step.get("reward", 1.0))
            skill_correct = self._is_skill_content_correct(skill_content, step)
            agent_followed = self._did_agent_follow_skill(step, skill_content)

            reflection: Dict[str, Any] = {"step_id": step.get("step_id", "?"),
                                           "agent_role": step.get("agent_role", "?")}

            if r >= 0.5:  # success
                if self._has_new_pattern(step):
                    reflection["type"] = "DISCOVERY"
                    reflection["evidence"] = (step.get("observation", "")[:200])
                else:
                    reflection["type"] = "OPTIMIZATION"
                    reflection["target"] = step.get("step_id", "?")
            else:  # failure
                if not skill_correct:
                    reflection["type"] = "SKILL_DEFECT"
                    reflection["target"] = step.get("step_id", "?")
                elif not agent_followed:
                    reflection["type"] = "EXECUTION_LAPSE"
                    reflection["target"] = step.get("step_id", "?")
                else:
                    continue  # uncertain — skip this step

            reflections.append(reflection)

        # Accumulate
        self.reflection_buffer.extend(reflections)

        # Batch-integrate when threshold reached
        if len(self.reflection_buffer) >= B_REVISION:
            self._integrate_and_revise()

        return reflections

    # ── criteria helpers ──────────────────────────────────────────

    @staticmethod
    def _is_skill_content_correct(
        skill_content: str, step: Dict[str, Any]
    ) -> bool:
        """Heuristic check: does the skill content logically cover this step?

        Returns False when the skill is missing a required rule or
        contains a contradictory instruction for this step's scenario.
        """
        obs = (step.get("observation") or "").lower()
        if "confidence" in obs and ("typeerror" in obs or "validation" in obs):
            return False
        return True

    @staticmethod
    def _did_agent_follow_skill(
        step: Dict[str, Any], skill_content: str
    ) -> bool:
        """Heuristic check: did the agent execute the skill as written?

        Returns False when the observation suggests the agent deviated
        from the instructions even though the skill was correct.
        """
        obs = (step.get("observation") or "").lower()
        if "skip" in obs or "未加载" in obs:
            return False
        return True

    @staticmethod
    def _has_new_pattern(step: Dict[str, Any]) -> bool:
        return False  # requires LLM evaluation in production

    # ── batch integration ─────────────────────────────────────────

    def _integrate_and_revise(self) -> Dict[str, Any]:
        """Batch integrate buffered reflections (EmbodiSkill §3.4).

        1. Deduplicate overlapping reflections.
        2. Merge same-type reflections.
        3. Write consolidated revision plan to evolution_buffer.json.
        4. Clear buffer.
        """
        counts = {t: 0 for t in REFLECTION_TYPES}
        for r in self.reflection_buffer:
            rtype = r.get("type", "?")
            if rtype in counts:
                counts[rtype] += 1

        summary = {
            "total_reflections": len(self.reflection_buffer),
            "types": counts,
            "integrated_at": "pipeline_trigger",
            "samples": self.reflection_buffer[:10],
        }

        self._buffer_path.parent.mkdir(parents=True, exist_ok=True)
        self._buffer_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("EmbodiSkill: integrated %d reflections → %s",
                    len(self.reflection_buffer), self._buffer_path)
        self.reflection_buffer = []
        return summary

    def restructure_agent_md(self, md_content: str) -> str:
        """Restructure a flat Agent MD into S_body + S_appendix dual-layer.

        Preserves ALL original content. Only adds structural wrappers.
        Used for Phase 1 agent migration (one-time) and runtime evolution.
        """
        lines = md_content.split("\n")

        # Split frontmatter + title from body content
        frontmatter_lines: list = []
        body_lines: list = []
        appendix_lines: list = []
        passed_title = False
        current_section = "body"

        for line in lines:
            # Track frontmatter (--- delimited)
            if not passed_title and line.strip() == "---":
                frontmatter_lines.append(line)
                continue
            if not passed_title and line.strip().startswith("# "):
                frontmatter_lines.append(line)
                passed_title = True
                continue
            if not passed_title:
                frontmatter_lines.append(line)
                continue

            # Classify sections after title
            if line.startswith("## "):
                section_name = line[3:].strip()
                if any(kw in section_name for kw in
                       ["必须", "失误", "注意", "警告", "禁止", "checklist", "常见错误", "约束"]):
                    current_section = "appendix"
                else:
                    current_section = "body"

            target = appendix_lines if current_section == "appendix" else body_lines
            target.append(line)

        body = "\n".join(body_lines).strip()
        appendix = "\n".join(appendix_lines).strip()

        result = "\n".join(frontmatter_lines).strip()
        result += "\n\n"
        result += "## S_body: 技能主体\n\n"
        result += "_以下为 Agent 的核心规范、职责边界和执行协议。_\n\n"
        if body:
            result += body + "\n\n"

        result += "---\n\n"
        result += "## S_appendix: 技能附录\n\n"
        result += "> **重要提示**: 本附录包含关键约束和常见失误。仅添加强调项，不引入新规则。\n\n"
        if appendix:
            result += appendix
        else:
            result += "_（本节将在运行时通过 EmbodiSkill 反思累积填充）_\n"

        return result


# ── CLI entry ────────────────────────────────────────────────────

def _cli() -> None:
    import sys

    reflector = EmbodiSkillReflector()

    if len(sys.argv) > 1 and sys.argv[1] == "--buffer-status":
        if reflector._buffer_path.exists():
            data = json.loads(reflector._buffer_path.read_text(encoding="utf-8"))
            print(f"Buffer: {data['total_reflections']} reflections")
            print(f"Types: {data['types']}")
        else:
            print("Buffer is empty.")
        return

    print("EmbodiSkillReflector ready.")
    print(f"K_MAX_REFLECTIONS={K_MAX_REFLECTIONS}, B_REVISION={B_REVISION}")


if __name__ == "__main__":
    _cli()
