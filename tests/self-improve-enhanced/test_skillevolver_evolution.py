"""
Unit tests for scripts.skillevolver_evolution — SkillEvolver integration.
Covers: strategy exploration, contrastive update, audit, dry-run.
"""

from pathlib import Path

import pytest
from conftest import sample_debate_results, sample_trajectory


class TestSkillEvolverInit:
    """Initialisation and configuration."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from scripts.skillevolver_evolution import SkillEvolver, K_EXPLORATIONS, EXPLORATION_STRATEGIES, R_ITERATIONS
        self.SkillEvolver = SkillEvolver
        self.K = K_EXPLORATIONS
        self.strategies = EXPLORATION_STRATEGIES
        self.R = R_ITERATIONS

    def test_default_explorations(self):
        """K should be 4 (from SkillEvolver paper)."""
        assert self.K == 4

    def test_strategies_present(self):
        """All 4 strategy types must be defined."""
        expected = {"greedy", "exploratory", "imitative", "adversarial"}
        assert set(self.strategies.keys()) == expected

    def test_strategies_have_descriptions(self):
        """Each strategy must have desc and prompt_modifier."""
        for name, s in self.strategies.items():
            assert "desc" in s, f"{name} missing desc"
            assert "prompt_modifier" in s, f"{name} missing prompt_modifier"

    def test_agent_mapping_coverage(self):
        from scripts.skillevolver_evolution import ROLE_TO_FILE_ID
        assert len(ROLE_TO_FILE_ID) == 10  # 10 main roles
        role_ids = list(ROLE_TO_FILE_ID.values())
        for rid in role_ids:
            assert rid.startswith("futures-")


class TestSkillEvolverExploration:
    """Stage 1: strategy diversification exploration."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        from scripts.skillevolver_evolution import SkillEvolver
        # Use tmp_path as fake FDT root
        self.fake_root = tmp_path / "fdt"
        self.fake_root.mkdir()
        (self.fake_root / "agents").mkdir()
        (self.fake_root / "memory").mkdir()

        # Create a minimal agent file
        agent_file = self.fake_root / "agents" / "futures-judge.md"
        agent_file.write_text("# 闫判官\n\n## Role\n裁决者\n", encoding="utf-8")

        self.evolver = SkillEvolver(self.fake_root)

    def test_dry_run_no_files_written(self):
        """Dry run should not create variant files."""
        results = self.evolver._explore_strategies(dry_run=True)
        evo_dir = self.fake_root / "memory" / "evolutions"
        assert not evo_dir.exists() or len(list(evo_dir.iterdir())) == 0
        assert len(results) > 0

    def test_variant_files_created(self):
        """Wet run should create variant files in memory/evolutions/."""
        results = self.evolver._explore_strategies(dry_run=False)
        evo_dir = self.fake_root / "memory" / "evolutions"
        assert evo_dir.exists()
        files = list(evo_dir.iterdir())
        assert len(files) > 0

    def test_each_strategy_generates_variant(self):
        """All 4 strategies must produce variant files."""
        from scripts.skillevolver_evolution import EXPLORATION_STRATEGIES
        results = self.evolver._explore_strategies(dry_run=True)
        strategy_names = {r["strategy"] for r in results}
        assert strategy_names == set(EXPLORATION_STRATEGIES.keys())


class TestSkillEvolverContrastiveUpdate:
    """Stage 2: contrastive skill update."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        from scripts.skillevolver_evolution import SkillEvolver
        self.fake_root = tmp_path / "fdt"
        self.fake_root.mkdir()
        agents_dir = self.fake_root / "agents"
        agents_dir.mkdir()

        agent_file = agents_dir / "futures-opposition-debater.md"
        agent_file.write_text("# 慎思\n\n## Role\n慎思分析员\n", encoding="utf-8")

        self.evolver = SkillEvolver(self.fake_root)

    def test_contrastive_update_with_faults(self):
        """Faults should generate patch records."""
        from scripts.skillevolver_evolution import SkillEvolver
        faults = [{
            "fault_step_id": "P4",
            "fault_agent": "慎思",
            "fault_type": "skill_defect",
            "responsible_skill": "debate-argument-builder",
            "evidence": "confidence type mismatch",
            "confidence": 0.92,
            "fix_suggestion": {
                "action": "修正",
                "target": "debate-argument-builder",
                "content_hint": "修正慎思 Agent MD 中与 P4 相关的约束"
            }
        }]
        updates = self.evolver._contrastive_update(faults)
        assert len(updates) == 1
        assert updates[0]["patch"] is not None
        assert updates[0]["target_file"].endswith("futures-opposition-debater.md")

    def test_contrastive_update_with_unknown_role(self):
        """Unknown fault agent → no update (graceful skip)."""
        faults = [{
            "fault_step_id": "P1",
            "fault_agent": "未知角色",
            "fault_type": "skill_defect",
            "evidence": "n/a",
            "confidence": 0.7,
            "fix_suggestion": {"action": "修正", "target": "s", "content_hint": "hint"}
        }]
        updates = self.evolver._contrastive_update(faults)
        assert len(updates) == 0

    def test_contrastive_update_empty_faults(self):
        """Empty faults list → empty updates."""
        updates = self.evolver._contrastive_update([])
        assert updates == []


class TestSkillEvolverAudit:
    """Stage 3: independent audit."""

    def test_audit_passes_good_patch(self):
        from scripts.skillevolver_evolution import SkillEvolver
        updates = [{
            "target_file": "/agents/futures-judge.md",
            "patch": "+# SkillEvolver 补丁\n+# 修复建议: 修正 ADX>60 约束",
            "fault_evidence": "高 ADX 场景连续错误",
            "confidence": 0.92,
        }]
        validated = SkillEvolver._audit_skills(updates)
        assert len(validated) == 1
        assert validated[0]["status"] == "ready"

    def test_audit_rejects_low_confidence(self):
        from scripts.skillevolver_evolution import SkillEvolver
        updates = [{
            "target_file": "/agents/futures-judge.md",
            "patch": "+# small",
            "fault_evidence": "marginal",
            "confidence": 0.3,
        }]
        validated = SkillEvolver._audit_skills(updates)
        assert validated[0]["status"] == "rejected"

    def test_audit_rejects_date_hardcoded(self):
        from scripts.skillevolver_evolution import SkillEvolver
        updates = [{
            "target_file": "/agents/futures-judge.md",
            "patch": "+# 2026-07-11 specific case",
            "fault_evidence": "n/a",
            "confidence": 0.9,
        }]
        validated = SkillEvolver._audit_skills(updates)
        assert "2026-" in validated[0].get("patch", "")
        assert validated[0]["status"] == "rejected"


class TestSkillEvolverFullCycle:
    """Full evolution cycle (dry run)."""

    def test_full_cycle_dry_run(self, tmp_path):
        from scripts.skillevolver_evolution import SkillEvolver
        fake_root = tmp_path / "fdt"
        fake_root.mkdir()
        (fake_root / "agents").mkdir()
        (fake_root / "memory").mkdir()
        agent_file = fake_root / "agents" / "futures-judge.md"
        agent_file.write_text("# 闫判官\n\n## Role\n裁决者\n", encoding="utf-8")

        evolver = SkillEvolver(fake_root)
        faults = [{
            "fault_step_id": "P5_judge",
            "fault_agent": "闫判官",
            "fault_type": "skill_defect",
            "responsible_skill": "debate-judge",
            "evidence": "verdict reasoning incomplete",
            "confidence": 0.85,
            "fix_suggestion": {"action": "修正", "target": "debate-judge",
                               "content_hint": "修正裁决约束"}
        }]
        result = evolver.run_evolution_cycle(faults=faults, dry_run=True)
        assert isinstance(result, list)
