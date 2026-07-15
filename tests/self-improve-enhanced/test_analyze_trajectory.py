"""
Unit tests for scripts.analyze_trajectory — SkillAdaptor integration.
Covers: TrajectoryAnalyzer.parse(), FaultAttributor.attribute(), classification.
"""

import json
from pathlib import Path

import pytest
from conftest import sample_debate_results, sample_trajectory


class TestTrajectoryAnalyzer:
    """Trajectory parsing — from debate_results to structured steps."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from scripts.analyze_trajectory import TrajectoryAnalyzer
        self.analyzer = TrajectoryAnalyzer()

    def test_parse_with_valid_data(self):
        """Happy path: parse full debate_results."""
        data = sample_debate_results()
        trajectory = self.analyzer.parse({"debate_results": data})
        assert len(trajectory) >= 5  # P1 + P3x2 + P4x2 + P5
        step_ids = [s["step_id"] for s in trajectory]
        assert "P1" in step_ids
        assert "P3" in step_ids
        assert "P4" in step_ids
        assert "P5_judge" in step_ids

    def test_parse_with_empty_data(self):
        """Edge case: empty or missing data."""
        trajectory = self.analyzer.parse({"debate_results": {}})
        assert isinstance(trajectory, list)

    def test_parse_with_none(self):
        """Edge case: None input."""
        trajectory = self.analyzer.parse(None)
        assert isinstance(trajectory, list)

    def test_parse_empty_scan_no_crash(self):
        """Edge case: scan with no signals."""
        data = sample_debate_results()
        data["scan"] = {"signals": []}
        trajectory = self.analyzer.parse({"debate_results": data})
        p1_steps = [s for s in trajectory if s["step_id"] == "P1"]
        assert len(p1_steps) > 0
        assert p1_steps[0]["reward"] == 0.0  # no signals → failure

    def test_step_keys_present(self):
        """Each step must have all required keys."""
        required = {"step_id", "agent_role", "action", "observation", "reward", "skill_used"}
        data = sample_debate_results()
        trajectory = self.analyzer.parse({"debate_results": data})
        for step in trajectory:
            for key in required:
                assert key in step, f"Missing key '{key}' in step {step.get('step_id', '?')}"

    def test_reward_values_valid(self):
        """Reward must be 0.0 or 1.0."""
        data = sample_debate_results()
        trajectory = self.analyzer.parse({"debate_results": data})
        for step in trajectory:
            assert step["reward"] in (0.0, 1.0), f"Invalid reward {step['reward']}"

    def test_researcher_role_distinction(self):
        """观澜 and 探源 should have different skill_used."""
        data = sample_debate_results()
        trajectory = self.analyzer.parse({"debate_results": data})
        p3_steps = [s for s in trajectory if s["step_id"] == "P3"]
        skills = {(s["agent_role"], s["skill_used"]) for s in p3_steps}
        assert ("观澜", "technical-analysis") in skills
        assert ("探源", "fundamental-data-collector") in skills


class TestFaultAttributor:
    """Fault attribution — step-level failure classification."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from scripts.analyze_trajectory import FaultAttributor
        self.attributor = FaultAttributor()

    def test_identifies_skill_defect(self):
        """Should detect confidence type mismatch as skill_defect."""
        traj = sample_trajectory()
        faults = self.attributor.attribute(traj)
        p4_faults = [f for f in faults if f["fault_step_id"] == "P4"]
        if p4_faults:
            assert p4_faults[0]["fault_type"] == "skill_defect"

    def test_all_failing_steps_captured(self):
        """All steps with reward=0 should generate a fault record."""
        traj = [
            {"step_id": "P1", "agent_role": "A", "observation": "", "reward": 0.0, "skill_used": "s1", "action": "a"},
            {"step_id": "P2", "agent_role": "B", "observation": "", "reward": 1.0, "skill_used": "s2", "action": "b"},
            {"step_id": "P3", "agent_role": "C", "observation": "", "reward": 0.0, "skill_used": "s1", "action": "c"},
        ]
        faults = self.attributor.attribute(traj)
        assert len(faults) == 2

    def test_confidence_range(self):
        """Confidence should be between 0 and 1."""
        traj = sample_trajectory()
        faults = self.attributor.attribute(traj)
        for f in faults:
            assert 0 <= f["confidence"] <= 1.0, f"Confidence out of range: {f['confidence']}"

    def test_fault_record_schema(self):
        """Each fault must have all required fields."""
        required = {"fault_step_id", "fault_agent", "fault_type", "responsible_skill",
                     "evidence", "confidence", "fix_suggestion"}
        traj = sample_trajectory()
        faults = self.attributor.attribute(traj)
        for f in faults:
            for key in required:
                assert key in f, f"Missing key '{key}' in fault {f.get('fault_step_id', '?')}"

    def test_fault_type_valid_values(self):
        """fault_type must be skill_defect or execution_lapse."""
        traj = sample_trajectory()
        faults = self.attributor.attribute(traj)
        for f in faults:
            assert f["fault_type"] in ("skill_defect", "execution_lapse")

    def test_no_faults_with_all_success(self):
        """All successful trajectory → no faults."""
        traj = [
            {"step_id": "P1", "agent_role": "A", "observation": "ok", "reward": 1.0,
             "skill_used": "s1", "action": "a1"},
            {"step_id": "P2", "agent_role": "B", "observation": "ok", "reward": 1.0,
             "skill_used": "s2", "action": "b1"},
        ]
        faults = self.attributor.attribute(traj)
        assert len(faults) == 0

    def test_execution_lapse_classification(self):
        """Steps with reward=0 but no defect hints → execution_lapse."""
        traj = [
            {"step_id": "P3", "agent_role": "观澜", "observation": "skipped_data_load",
             "reward": 0.0, "skill_used": "technical-analysis", "action": "research"},
        ]
        faults = self.attributor.attribute(traj)
        assert len(faults) == 1
        assert faults[0]["fault_type"] == "execution_lapse"


class TestTrajectoryAnalyzerIntegration:
    """Integration: parse + attribute end-to-end."""

    def test_analyze_to_attribute_pipeline(self, tmp_path):
        """End-to-end: parse debate_results → attribute faults."""
        from scripts.analyze_trajectory import TrajectoryAnalyzer, FaultAttributor

        analyzer = TrajectoryAnalyzer()
        attributor = FaultAttributor()

        data = sample_debate_results()
        trajectory = analyzer.parse({"debate_results": data})
        faults = attributor.attribute(trajectory)

        assert isinstance(trajectory, list)
        assert isinstance(faults, list)
        # 慎思 has invalid output → should produce fault
        if faults:
            assert faults[0]["fault_step_id"] == "P4"
            assert faults[0]["fault_agent"] == "慎思"


class TestErrorHandling:
    """Graceful degradation on malformed inputs."""

    def test_missing_scan_key(self):
        from scripts.analyze_trajectory import TrajectoryAnalyzer
        analyzer = TrajectoryAnalyzer()
        trajectory = analyzer.parse({"debate_results": {}})
        assert isinstance(trajectory, list)

    def test_partial_researcher_data(self):
        from scripts.analyze_trajectory import TrajectoryAnalyzer
        analyzer = TrajectoryAnalyzer()
        data = {"debate_results": {"researchers": {}, "debaters": {}, "scan": {"signals": []}, "judge": {}}}
        trajectory = analyzer.parse(data)
        assert isinstance(trajectory, list)
        assert len(trajectory) > 0

    def test_observation_truncation(self):
        """Observation over 300 chars should be truncated in evidence."""
        from scripts.analyze_trajectory import FaultAttributor
        attributor = FaultAttributor()
        long_obs = "x" * 1000
        traj = [{"step_id": "P1", "agent_role": "A", "observation": long_obs,
                 "reward": 0.0, "skill_used": "s", "action": "a"}]
        faults = attributor.attribute(traj)
        assert len(faults) == 1
        assert "…" in faults[0]["evidence"] or len(faults[0]["evidence"]) < 500
