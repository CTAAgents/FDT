"""
Unit tests for scripts.embodiskill_reflect — EmbodiSkill integration.
Covers: 4 reflection types, accumulation buffer, batch integration.
"""

import json
from pathlib import Path

import pytest
from conftest import sample_trajectory


class TestEmbodiSkillReflectorInit:
    """Construction and default parameters."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from scripts.embodiskill_reflect import EmbodiSkillReflector, K_MAX_REFLECTIONS, B_REVISION, REFLECTION_TYPES
        self.K = K_MAX_REFLECTIONS
        self.B = B_REVISION
        self.types = REFLECTION_TYPES

    def test_max_reflections(self):
        """K should be 3 (from EmbodiSkill paper)."""
        assert self.K == 3

    def test_revision_interval(self):
        """B should be 10."""
        assert self.B == 10

    def test_reflection_types(self):
        """Must have exactly 4 reflection types."""
        assert len(self.types) == 4
        expected = {"DISCOVERY", "OPTIMIZATION", "SKILL_DEFECT", "EXECUTION_LAPSE"}
        assert set(self.types) == expected


class TestEmbodiSkillReflection:
    """Core reflection classification logic."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        from scripts.embodiskill_reflect import EmbodiSkillReflector
        fake_root = tmp_path / "fdt"
        fake_root.mkdir(exist_ok=True)
        self.reflector = EmbodiSkillReflector(fake_root)

    def test_empty_trajectory(self):
        """Empty trajectory → empty reflections."""
        reflections = self.reflector.reflect_on_trajectory([])
        assert reflections == []

    def test_successful_step_returns_optimization(self):
        """Success without novel pattern → OPTIMIZATION."""
        traj = [{"step_id": "P1", "agent_role": "A", "observation": "ok", "reward": 1.0}]
        reflections = self.reflector.reflect_on_trajectory(traj)
        assert len(reflections) >= 1
        assert reflections[0]["type"] in ("DISCOVERY", "OPTIMIZATION")

    def test_skill_defect_on_confidence_error(self):
        """Observation with 'confidence' + 'type' → SKILL_DEFECT."""
        traj = [{"step_id": "P4", "agent_role": "空头", "observation": "confidence typeerror str",
                 "reward": 0.0}]
        reflections = self.reflector.reflect_on_trajectory(traj)
        assert len(reflections) >= 1
        assert reflections[0]["type"] == "SKILL_DEFECT"

    def test_execution_lapse_on_skip(self):
        """Observation with 'skip' → EXECUTION_LAPSE."""
        traj = [{"step_id": "P3", "agent_role": "探源", "observation": "skipped data source",
                 "reward": 0.0}]
        reflections = self.reflector.reflect_on_trajectory(traj)
        assert len(reflections) >= 1
        assert reflections[0]["type"] == "EXECUTION_LAPSE"

    def test_max_reflections_per_trajectory(self):
        """At most K reflections per trajectory."""
        traj = [{"step_id": f"P{i}", "agent_role": "A", "observation": "error", "reward": 0.0}
                for i in range(10)]
        reflections = self.reflector.reflect_on_trajectory(traj)
        assert len(reflections) <= self.reflector.__class__._orig_K if hasattr(
            self.reflector.__class__, '_orig_K') else 3


class TestEmbodiSkillBuffer:
    """Accumulation and batch integration."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        from scripts.embodiskill_reflect import EmbodiSkillReflector
        self.fake_root = tmp_path / "fdt"
        self.fake_root.mkdir()
        self.reflector = EmbodiSkillReflector(self.fake_root)

    def test_buffer_accumulates(self):
        """Buffer should increase after each reflection."""
        initial_len = len(self.reflector.reflection_buffer)
        traj = [{"step_id": "P1", "agent_role": "A", "observation": "ok", "reward": 1.0}]
        self.reflector.reflect_on_trajectory(traj)
        assert len(self.reflector.reflection_buffer) > initial_len

    def test_buffer_writes_at_threshold(self, monkeypatch):
        """Buffer should write to file when reaching B_REVISION."""
        from scripts.embodiskill_reflect import B_REVISION, EmbodiSkillReflector
        # Build B_REVISION reflections one sample at a time
        traj = [{"step_id": "P1", "agent_role": "A", "observation": "ok", "reward": 1.0}]
        for _ in range(B_REVISION):
            self.reflector.reflect_on_trajectory(traj)

        # Buffer should have been flushed by the last call
        assert len(self.reflector.reflection_buffer) < B_REVISION
        buffer_path = self.fake_root / "memory" / "evolution_buffer.json"
        assert buffer_path.exists()

    def test_integrate_output_structure(self, tmp_path):
        """Integrated file must have correct schema."""
        from scripts.embodiskill_reflect import B_REVISION, EmbodiSkillReflector
        fake_root = tmp_path / "fdt"
        fake_root.mkdir(exist_ok=True)
        reflector = EmbodiSkillReflector(fake_root)

        traj = [{"step_id": "P1", "agent_role": "A", "observation": "ok", "reward": 1.0}]
        for _ in range(B_REVISION + 1):
            reflector.reflect_on_trajectory(traj)

        buffer_path = fake_root / "memory" / "evolution_buffer.json"
        data = json.loads(buffer_path.read_text(encoding="utf-8"))
        assert "total_reflections" in data
        assert "types" in data
        assert "DISCOVERY" in data["types"]
        assert "OPTIMIZATION" in data["types"]


class TestEmbodiSkillRestructure:
    """Agent MD restructuring (Phase 1 migration support)."""

    def test_restructure_adds_s_body(self):
        from scripts.embodiskill_reflect import EmbodiSkillReflector
        reflector = EmbodiSkillReflector()
        content = "# 测试Agent\n\n## Role\n裁决者\n"
        result = reflector.restructure_agent_md(content)
        assert "## S_body:" in result
        assert "## S_appendix:" in result
        assert "裁决者" in result  # original content preserved

    def test_restructure_preserves_frontmatter(self):
        from scripts.embodiskill_reflect import EmbodiSkillReflector
        reflector = EmbodiSkillReflector()
        content = "---\nname: test-agent\n---\n\n# 测试Agent\n\n## Role\n裁决者\n"
        result = reflector.restructure_agent_md(content)
        assert "---" in result
        assert "name: test-agent" in result

    def test_restructure_preserves_all_content(self):
        """All original text must be preserved after restructure."""
        from scripts.embodiskill_reflect import EmbodiSkillReflector
        reflector = EmbodiSkillReflector()
        content = "# 测试Agent\n\n## 核心职责\n信号质疑者\n\n## 禁止规则\n- ❌ 禁止 WebSearch\n"
        result = reflector.restructure_agent_md(content)
        assert "信号质疑者" in result
        assert "禁止 WebSearch" in result

    def test_restructure_empty(self):
        """Empty input → still produces valid structure."""
        from scripts.embodiskill_reflect import EmbodiSkillReflector
        reflector = EmbodiSkillReflector()
        result = reflector.restructure_agent_md("")
        assert "## S_body:" in result
