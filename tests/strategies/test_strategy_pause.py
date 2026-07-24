"""
策略持久化暂停开关测试（G28）。

覆盖：
  - config.settings.DISABLED_STRATEGIES 含 3 个缺资源策略
  - BaseStrategyV2.enabled 默认 True
  - get_pipeline() 默认跳过禁用策略（仅 4 个活跃）
  - get_pipeline([显式名称]) 覆盖禁用（CLI --strategies 语义）
"""


def _all_seven():
    from strategies.arbitrage_strategy import ArbitrageStrategy
    from strategies.event_driven_strategy import EventDrivenStrategy
    from strategies.macro_regime_strategy import MacroRegimeStrategy
    from strategies.mean_reversion_strategy import MeanReversionStrategy
    from strategies.ml_signal_strategy import MlSignalStrategy
    from strategies.multi_factor_strategy import MultiFactorStrategy
    from strategies.registry_v2 import clear_v2, register_v2
    from strategies.trend_following_strategy import TrendFollowingStrategy

    clear_v2()
    for C in (TrendFollowingStrategy, MeanReversionStrategy, ArbitrageStrategy,
              MacroRegimeStrategy, EventDrivenStrategy, MlSignalStrategy, MultiFactorStrategy):
        register_v2(C())


class TestPauseConfig:
    def test_disabled_set_has_three(self):
        from config.settings import DISABLED_STRATEGIES
        assert {"multi_factor", "ml_signal", "event_driven"} <= set(DISABLED_STRATEGIES)

    def test_base_enabled_default_true(self):
        # 抽象类不可实例化，用子类验证默认 enabled
        from strategies.trend_following_strategy import TrendFollowingStrategy
        assert TrendFollowingStrategy().enabled is True


class TestPipelinePause:
    def test_default_excludes_disabled(self):
        from strategies.registry_v2 import get_pipeline
        _all_seven()
        p = get_pipeline()
        names = {s.name for s in p.strategies}
        # 禁用的 3 个必须缺席
        assert "multi_factor" not in names
        assert "ml_signal" not in names
        assert "event_driven" not in names
        # 活跃的 4 个必须存在
        assert {"trend_following", "mean_reversion", "arbitrage", "macro_regime"} <= names
        # 恰好 4 个（无禁用、无多余）
        assert len(names) == 4

    def test_cli_override_enables_disabled(self):
        from strategies.registry_v2 import get_pipeline
        _all_seven()
        # CLI --strategies 显式指定 → 覆盖禁用
        p = get_pipeline(["multi_factor", "trend_following"])
        names = {s.name for s in p.strategies}
        assert names == {"multi_factor", "trend_following"}

    def test_cli_override_single_disabled(self):
        from strategies.registry_v2 import get_pipeline
        _all_seven()
        p = get_pipeline(["ml_signal"])
        assert {s.name for s in p.strategies} == {"ml_signal"}
