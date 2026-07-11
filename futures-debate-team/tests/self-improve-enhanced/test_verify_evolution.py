"""
Unit tests for scripts.verify_evolution — Autoresearch-style A/B verification.
Covers: expert panel, scoring, verdict logic, ViBench loading.
"""

import json
from pathlib import Path

import pytest
from conftest import sample_vibench_cases


class TestEvolutionVerifierInit:
    """Panel configuration and defaults."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from scripts.verify_evolution import EvolutionVerifier, FDT_EXPERT_PANEL, MIN_SCORE
        self.panel = FDT_EXPERT_PANEL
        self.min_score = MIN_SCORE
        self.verifier = EvolutionVerifier  # class ref

    def test_panel_has_5_experts(self):
        """Must have exactly 5 FDT domain experts."""
        assert len(self.panel) == 5

    def test_expert_names_known(self):
        """All 5 expert names must match FDT roles."""
        names = {e["name"] for e in self.panel}
        expected = {"闫判官", "策执远", "风控明", "证真", "探源"}
        assert names == expected

    def test_each_expert_has_scoring_lens(self):
        """Each expert must define their evaluation criteria."""
        for e in self.panel:
            assert "scoring_lens" in e, f"{e['name']} missing scoring_lens"
            assert len(e["scoring_lens"]) > 10

    def test_min_score_default(self):
        """Default minimum score should be 70."""
        assert self.min_score == 70


class TestEvolutionVerifierScoring:
    """Score computation and A/B comparison."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from scripts.verify_evolution import EvolutionVerifier
        self.verifier = EvolutionVerifier()

    def test_verify_returns_expected_keys(self):
        """verify() must return all required fields."""
        result = self.verifier.verify("baseline", "evolved")
        required = {"baseline_score", "evolved_score", "delta", "verdict",
                     "per_expert", "test_cases"}
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_verify_with_test_cases(self):
        """Supports explicit test case list."""
        cases = sample_vibench_cases()
        result = self.verifier.verify("base", "evo", test_cases=cases)
        assert result["test_cases"] == len(cases)

    def test_scores_in_range(self):
        """Scores should be between 0 and 100."""
        result = self.verifier.verify("base", "evo")
        assert 0 <= result["baseline_score"] <= 100
        assert 0 <= result["evolved_score"] <= 100

    def test_delta_calculation(self):
        """Delta = evolved - baseline."""
        result = self.verifier.verify("base", "evo")
        assert abs(result["delta"] - (result["evolved_score"] - result["baseline_score"])) < 0.2

    def test_verdict_is_string(self):
        """Verdict must be 'approved' or 'rejected'."""
        result = self.verifier.verify("base", "evo")
        assert result["verdict"] in ("approved", "rejected")

    def test_per_expert_structure(self):
        """Each expert result must have name, baseline, evolved."""
        result = self.verifier.verify("base", "evo")
        for s in result["per_expert"]:
            assert "expert" in s
            assert "baseline" in s
            assert "evolved" in s

    def test_expert_count_matches_panel(self):
        """Number of expert results must equal panel size."""
        from scripts.verify_evolution import FDT_EXPERT_PANEL
        result = self.verifier.verify("base", "evo")
        assert len(result["per_expert"]) == len(FDT_EXPERT_PANEL)

    def test_multiple_calls_consistency(self):
        """Multiple calls should always return valid structure."""
        for _ in range(3):
            result = self.verifier.verify("base", "evo")
            assert result["verdict"] in ("approved", "rejected")


class TestEvolutionVerifierViBench:
    """ViBench JSON loading."""

    def test_load_vibench_missing_file(self, tmp_path):
        """Non-existent file → empty list."""
        from scripts.verify_evolution import EvolutionVerifier
        verifier = EvolutionVerifier(tmp_path)  # no vibench file
        cases = verifier._load_vibench()
        assert cases == []

    def test_load_vibench_valid_file(self, tmp_path):
        """Valid test_cases.json as list → load successfully."""
        from scripts.verify_evolution import EvolutionVerifier
        cases = sample_vibench_cases()
        vibench_path = tmp_path / "benchmarks" / "test_cases.json"
        vibench_path.parent.mkdir(parents=True)
        vibench_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")

        verifier = EvolutionVerifier(tmp_path)
        loaded = verifier._load_vibench()
        assert len(loaded) == len(cases)

    def test_load_vibench_as_object(self, tmp_path):
        """test_cases.json as {'cases': [...]} → load cases."""
        from scripts.verify_evolution import EvolutionVerifier
        cases = sample_vibench_cases()
        vibench_path = tmp_path / "benchmarks" / "test_cases.json"
        vibench_path.parent.mkdir(parents=True)
        vibench_path.write_text(
            json.dumps({"cases": cases, "meta": {"version": 1}}, ensure_ascii=False),
            encoding="utf-8")

        verifier = EvolutionVerifier(tmp_path)
        loaded = verifier._load_vibench()
        assert len(loaded) == len(cases)

    def test_load_vibench_malformed_json(self, tmp_path):
        """Corrupted JSON → empty list, no crash."""
        from scripts.verify_evolution import EvolutionVerifier
        vibench_path = tmp_path / "benchmarks" / "test_cases.json"
        vibench_path.parent.mkdir(parents=True)
        vibench_path.write_text("NOT JSON{broken", encoding="utf-8")

        verifier = EvolutionVerifier(tmp_path)
        loaded = verifier._load_vibench()
        assert loaded == []  # graceful degradation
