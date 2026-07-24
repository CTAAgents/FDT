"""
MlSignalStrategy 测试 — ONNX 推理桥接 + 降级 fallback
"""


class TestMlSignal:
    """ML 信号策略测试"""

    def test_strategy_interface(self):
        from strategies.ml_signal_strategy import MlSignalStrategy
        s = MlSignalStrategy()
        assert s.name == "ml_signal"
        assert s.weight == 0.8

    def test_no_model_returns_empty(self):
        """无 ONNX 模型时优雅降级"""
        from strategies.ml_signal_strategy import MlSignalStrategy
        s = MlSignalStrategy()
        signals = s.compute([{"symbol": "RB", "carry": 0.1, "momentum": 0.2,
                              "inventory_pct": -0.3, "skew": 0.1, "corr": 0.2}], {})
        assert len(signals) == 0  # 无模型 → 无信号

    def test_model_registry_populated(self):
        """MODEL_REGISTRY 存在且可读"""
        from strategies.ml_signal_strategy import MODEL_REGISTRY
        assert isinstance(MODEL_REGISTRY, dict)

    def test_score_fallback(self):
        """score 在传入信号时正常工作"""
        from strategies.base_v2 import RawSignal
        from strategies.ml_signal_strategy import MlSignalStrategy
        s = MlSignalStrategy()
        raw = RawSignal(symbol="RB", direction="bull", signal_type="ml.prob",
                        raw_score=0.7, strategy_name="ml_signal",
                        meta={"probability": 0.85})
        results = s.score([raw], [])
        assert len(results) == 1
        assert results[0].grade == "WATCH"
        assert results[0].total > 0

    def test_via_pipeline(self):
        """接入 StrategyPipeline（降级模式）"""
        from strategies.ml_signal_strategy import MlSignalStrategy
        from strategies.pipeline import StrategyPipeline
        pipe = StrategyPipeline([MlSignalStrategy()])
        result = pipe.run([{"symbol": "RB"}], {}, {})
        assert len(result["all_ranked"]) == 0  # 无模型无信号
        assert "ml_signal" in result["_meta"]["strategies_run"]
