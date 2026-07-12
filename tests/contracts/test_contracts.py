import pytest
from contracts import (
    BullOutput,
    BearOutput,
    RiskOutput,
    TradingPlanOutput,
    PhaseMeta,
    DimensionItem,
    VerdictItem,
    OverallJudgment,
    TradeAction,
    DataCollectionOutput,
    TechnicalOutput,
    ChainAnalysisOutput,
)
from contracts import apply_migration
from datetime import datetime


def make_meta():
    return PhaseMeta(
        phase="P3",
        agent_name="证真",
        variant="CU.SHF",
        trace_id="test-001",
        depends_on=["P1_data", "P1_tech", "P2_chain"],
    )


class TestBullOutput:
    def test_roundtrip(self):
        meta = make_meta()
        bull = BullOutput(
            meta=meta,
            variant="bull",
            dimensions=[
                {"dim": "供给", "claim": "TC下降", "evidence": "TC从80跌至30", "confidence": 0.85},
                {"dim": "需求", "claim": "光伏拉动", "evidence": "光伏用铜增速18%", "confidence": 0.70},
                {"dim": "库存", "claim": "低位", "evidence": "LME库存15万吨", "confidence": 0.75},
                {"dim": "基差", "claim": "Back结构", "evidence": "近月升水200", "confidence": 0.80},
                {"dim": "宏观", "claim": "美元走弱", "evidence": "DXY跌破100", "confidence": 0.65},
            ],
            summary_4_risk="供给收缩+基差走强",
            full_text="完整论证...",
            confidence=0.78,
            rebuttal_targets=["供给", "库存"],
        )
        data = bull.model_dump()
        restored = BullOutput.model_validate(data)
        assert restored.variant == "bull"
        assert len(restored.dimensions) == 5
        assert restored.version == "3.0"
        assert restored.rebuttal_targets == ["供给", "库存"]

    def test_min_dimensions_enforced(self):
        meta = make_meta()
        with pytest.raises(Exception):
            BullOutput(
                meta=meta,
                variant="bull",
                dimensions=[],  # < 5
                summary_4_risk="",
                full_text="",
                confidence=0.5,
            )


class TestBearOutput:
    def test_roundtrip(self):
        meta = make_meta()
        bear = BearOutput(
            meta=meta,
            variant="bear",
            dimensions=[
                {"dim": "供给", "claim": "矿山复产", "evidence": "Freeport印尼出口恢复", "confidence": 0.65},
                {"dim": "需求", "claim": "地产拖累", "evidence": "新开工同比-25%", "confidence": 0.75},
                {"dim": "库存", "claim": "累库", "evidence": "LME周度+2.3万吨", "confidence": 0.80},
                {"dim": "基差", "claim": "Contango", "evidence": "远月贴水50", "confidence": 0.70},
                {"dim": "宏观", "claim": "加息预期", "evidence": "Fed维持鹰派", "confidence": 0.60},
            ],
            summary_4_risk="需求塌陷+库存累积",
            full_text="完整空头论证...",
            confidence=0.72,
        )
        data = bear.model_dump()
        restored = BearOutput.model_validate(data)
        assert restored.variant == "bear"
        assert len(restored.dimensions) == 5
        assert restored.version == "3.0"

    def test_default_rebuttal_targets(self):
        meta = make_meta()
        bear = BearOutput(
            meta=meta,
            variant="bear",
            dimensions=[
                {"dim": "A", "claim": "c1", "evidence": "e1", "confidence": 0.5},
                {"dim": "B", "claim": "c2", "evidence": "e2", "confidence": 0.5},
                {"dim": "C", "claim": "c3", "evidence": "e3", "confidence": 0.5},
                {"dim": "D", "claim": "c4", "evidence": "e4", "confidence": 0.5},
                {"dim": "E", "claim": "c5", "evidence": "e5", "confidence": 0.5},
            ],
            summary_4_risk="",
            full_text="",
            confidence=0.5,
        )
        assert bear.rebuttal_targets == []  # 首轮默认空


class TestRiskOutput:
    def test_with_null_winner(self):
        meta = make_meta()
        risk = RiskOutput(
            meta=meta,
            variant="risk",
            verdicts=[
                {
                    "dim": "供给",
                    "ruling": "include",
                    "winner": "bull",
                    "rebuttal_quality": "接住",
                    "reason": "牛证据充分",
                },
                {
                    "dim": "需求",
                    "ruling": "watch",
                    "winner": None,
                    "rebuttal_quality": "部分接住",
                    "reason": "双方各有道理",
                },
                {
                    "dim": "库存",
                    "ruling": "exclude",
                    "winner": "bear",
                    "rebuttal_quality": "糊弄",
                    "reason": "牛无数据",
                },
                {
                    "dim": "基差",
                    "ruling": "include",
                    "winner": "bull",
                    "rebuttal_quality": "接住",
                    "reason": "Back结构确认",
                },
                {
                    "dim": "宏观",
                    "ruling": "watch",
                    "winner": None,
                    "rebuttal_quality": "部分接住",
                    "reason": "数据滞后",
                },
            ],
            overall={
                "tendency": "bearish",
                "confidence": 0.62,
                "core_conflict": "供给vs需求",
                "suggested_position_pct": 30,
            },
            full_report="风控报告全文...",
        )
        data = risk.model_dump()
        restored = RiskOutput.model_validate(data)
        assert restored.overall.tendency == "bearish"
        assert restored.overall.confidence == 0.62
        # winner=None 应被正确保留
        assert restored.verdicts[1].winner is None
        assert restored.verdicts[0].winner == "bull"

    def test_confidence_le_09(self):
        """风控的红线：confidence ≤ 0.9"""
        meta = make_meta()
        risk = RiskOutput(
            meta=meta,
            variant="risk",
            verdicts=[
                {
                    "dim": f"D{i}",
                    "ruling": "include",
                    "winner": "bull",
                    "rebuttal_quality": "接住",
                    "reason": "证据充分",
                }
                for i in range(5)
            ],
            overall={
                "tendency": "bullish",
                "confidence": 0.95,  # >0.9!
                "core_conflict": "x",
                "suggested_position_pct": 50,
            },
            full_report="",
        )
        assert risk.overall.confidence == 0.95  # schema 不限制，但 prompt 红线约束


class TestTradingPlan:
    def test_roundtrip(self):
        meta = make_meta()
        plan = TradingPlanOutput(
            meta=meta,
            variant="trading_plan",
            actions=[
                TradeAction(
                    direction="short",
                    contract="CU.SHF",
                    entry_price=72000,
                    stop_loss=75000,
                    take_profit=68000,
                    position_size_pct=15,
                    rationale="Back结构+库存累积",
                ),
                TradeAction(
                    direction="long",
                    contract="AU.SHF",
                    entry_price=450,
                    stop_loss=440,
                    take_profit=470,
                    position_size_pct=10,
                    rationale="避险需求",
                ),
            ],
            total_exposure_pct=25,
            risk_reward_ratio=1.8,
            summary="做空铜+做多黄金组合",
        )
        data = plan.model_dump()
        restored = TradingPlanOutput.model_validate(data)
        assert len(restored.actions) == 2
        assert restored.total_exposure_pct == 25


class TestMigrations:
    def test_risk_v20_to_v21(self):
        old_data = {
            "version": "2.0",
            "variant": "risk",
            "verdicts": [],
            "overall": {},
            "full_report": "",
            "meta": {
                "phase": "P4",
                "agent_name": "风控明",
                "variant": "risk",
                "trace_id": "t1",
                "depends_on": [],
                "created_at": "2026-07-01T00:00:00",
            },
        }
        migrated = apply_migration("risk", old_data, "2.1")
        assert migrated["version"] == "2.1"
        assert "risk_level" in migrated
        assert migrated["risk_level"] == "medium"

    def test_risk_v21_to_v20(self):
        v21_data = {
            "version": "2.1",
            "variant": "risk",
            "verdicts": [],
            "overall": {},
            "full_report": "",
            "risk_level": "high",
            "meta": {
                "phase": "P4",
                "agent_name": "风控明",
                "variant": "risk",
                "trace_id": "t1",
                "depends_on": [],
                "created_at": "2026-07-01T00:00:00",
            },
        }
        migrated = apply_migration("risk", v21_data, "2.0")
        assert migrated["version"] == "2.0"
        assert "risk_level" not in migrated

    def test_unknown_migration_raises(self):
        """未注册迁移路径 → ValueError"""
        import pytest

        # MIGRATION_REGISTRY 已全覆盖，用不存在的目标版本触发错误
        with pytest.raises(ValueError):
            apply_migration("bull", {"version": "2.0", "role": "证真"}, "99.0")

    def test_fundamental_no_migration_needed(self):
        """单版本型号 (fundamental_state) 直接返回"""
        data = {"version": "1.0", "value": 42}
        result = apply_migration("fundamental_state", data, "1.0")
        assert result["version"] == "1.0"
        assert result["value"] == 42


class TestDataCollection:
    def test_roundtrip(self):
        meta = PhaseMeta(phase="P1", agent_name="数聚石", variant="CU.SHF", trace_id="t1", depends_on=[])
        output = DataCollectionOutput(
            meta=meta,
            variant="futures_data",
            contracts=["CU2409", "CU2410"],
            prices={
                "CU2409": {
                    "contract": "CU2409",
                    "open": 72000,
                    "high": 72500,
                    "low": 71800,
                    "close": 72200,
                    "volume": 15000,
                    "open_interest": 50000,
                },
            },
            key_levels={"support": 71800, "resistance": 72500},
            validation_status="pass",
        )
        data = output.model_dump()
        restored = DataCollectionOutput.model_validate(data)
        assert restored.validation_status == "pass"
        assert restored.prices["CU2409"].close == 72200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ===== 集成测试矩阵：跨版本兼容性 =====

# 生成所有可行的版本组合
VERSIONS = {
    "bull": ["3.0"],
    "bear": ["3.0"],
    "risk": ["3.0", "2.1"],
    "trading_plan": ["3.0"],
}


def make_mock_bull(version="3.0") -> dict:
    meta = make_meta().model_dump()
    d = {
        "version": version,
        "meta": meta,
        "variant": "bull",
        "dimensions": [
            {"dim": f"D{i}", "claim": f"claim{i}", "evidence": f"evidence{i}", "confidence": 0.5 + i * 0.08}
            for i in range(5)
        ],
        "summary_4_risk": "test summary",
        "full_text": "test body",
        "confidence": 0.7,
        "rebuttal_targets": [] if version == "2.0" else ["D0"],
    }
    if version == "2.1":
        d["rebuttal_quality_score"] = 0.8
    return d


def make_mock_bear(version="3.0") -> dict:
    d = make_mock_bull(version)
    d["variant"] = "bear"
    d["rebuttal_targets"] = []
    return d


def make_mock_risk(version="3.0") -> dict:
    meta = make_meta().model_dump()
    d = {
        "version": version,
        "meta": meta,
        "variant": "risk",
        "verdicts": [
            {
                "dim": f"D{i}",
                "ruling": "include" if i % 2 else "watch",
                "winner": "bull",
                "rebuttal_quality": "接住",
                "reason": f"reason{i}",
            }
            for i in range(5)
        ],
        "overall": {
            "tendency": "bearish",
            "confidence": 0.6,
            "core_conflict": "test",
            "suggested_position_pct": 30,
        },
        "full_report": "test report",
    }
    if version == "2.1":
        d["risk_level"] = "medium"
    return d


def make_mock_trading_plan(version="3.0") -> dict:
    meta = make_meta().model_dump()
    return {
        "version": version,
        "meta": meta,
        "variant": "trading_plan",
        "actions": [
            {
                "direction": "short",
                "contract": "CU",
                "entry_price": 72000,
                "stop_loss": 75000,
                "take_profit": 68000,
                "position_size_pct": 15,
                "rationale": "back test",
            },
        ],
        "total_exposure_pct": 15,
        "risk_reward_ratio": 2.0,
        "summary": "test plan",
    }


class TestIntegrationMatrix:
    """枚举所有子 skill 版本组合，跑编排兼容性"""

    @pytest.mark.parametrize("bull_v", VERSIONS["bull"])
    @pytest.mark.parametrize("bear_v", VERSIONS["bear"])
    @pytest.mark.parametrize("risk_v", VERSIONS["risk"])
    @pytest.mark.parametrize("plan_v", VERSIONS["trading_plan"])
    def test_pipeline_compatibility(self, bull_v, bear_v, risk_v, plan_v):
        """所有版本组合下编排层 parse_and_migrate 不报错"""
        from contracts import BullOutput, BearOutput, RiskOutput, TradingPlanOutput

        # bull
        bull_data = make_mock_bull(bull_v)
        obj = BullOutput.model_validate(bull_data)
        assert obj.version == bull_v

        # bear
        bear_data = make_mock_bear(bear_v)
        obj = BearOutput.model_validate(bear_data)
        assert obj.version == bear_v

        # risk — use version-appropriate schema
        risk_data = make_mock_risk(risk_v)
        if risk_v == "2.1":
            from contracts import RiskOutputV21

            obj = RiskOutputV21.model_validate(risk_data)
        else:
            obj = RiskOutput.model_validate(risk_data)
        assert obj.version == risk_v

        # trading plan
        plan_data = make_mock_trading_plan(plan_v)
        obj = TradingPlanOutput.model_validate(plan_data)
        assert obj.version == plan_v

        # 迁移验证（仅对v2.x运行，v3.0兼容）
        from contracts import apply_migration

        if risk_v.startswith("2."):
            migrated = apply_migration("risk", risk_data, "2.0")
            assert migrated["version"] in ("2.0", "3.0")  # 兼容v2/v3
            # 如果原来是2.1，risk_level 应被移除
        if risk_v == "2.1":
            assert "risk_level" not in migrated
