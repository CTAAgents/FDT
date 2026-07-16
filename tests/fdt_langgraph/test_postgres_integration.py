import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fdt_pg.schema import (
    Base, ScanSignals, ChainAnalysis, TechnicalScores, FundamentalScores,
    JudgeDirection, DebateArguments, DebateVerdicts, TradingPlans,
    RiskChecks, ExecutionFollowup, AgentProfiles, Calibration,
    LogEntries, DebateIndex, OLAP_VIEWS
)


class TestPostgresSchema:
    """PostgreSQL Schema 定义测试"""

    def test_oltp_tables_count(self):
        """验证 OLTP 表数量为 14 个"""
        tables = [
            ScanSignals, ChainAnalysis, TechnicalScores, FundamentalScores,
            JudgeDirection, DebateArguments, DebateVerdicts, TradingPlans,
            RiskChecks, ExecutionFollowup, AgentProfiles, Calibration,
            LogEntries, DebateIndex
        ]
        assert len(tables) == 14

    def test_olap_views_count(self):
        """验证 OLAP 视图数量为 3 个"""
        assert len(OLAP_VIEWS) == 3

    def test_olap_view_names(self):
        """验证 OLAP 视图名称"""
        expected_views = {"v_debate_summary", "v_signal_performance", "v_agent_effectiveness"}
        assert set(OLAP_VIEWS.keys()) == expected_views

    def test_trace_id_in_all_tables(self):
        """验证所有业务表都有 trace_id 字段"""
        tables_with_trace = [
            ScanSignals, ChainAnalysis, TechnicalScores, FundamentalScores,
            JudgeDirection, DebateArguments, DebateVerdicts, TradingPlans,
            RiskChecks, ExecutionFollowup, DebateIndex
        ]
        for table in tables_with_trace:
            assert hasattr(table, 'trace_id'), f"{table.__tablename__} 缺少 trace_id 字段"

    def test_scan_signals_schema(self):
        """验证 scan_signals 表结构"""
        assert ScanSignals.__tablename__ == "scan_signals"
        assert hasattr(ScanSignals, 'symbol')
        assert hasattr(ScanSignals, 'date')
        assert hasattr(ScanSignals, 'signal_type')
        assert hasattr(ScanSignals, 'signal_value')
        assert hasattr(ScanSignals, 'confidence')

    def test_debate_verdicts_schema(self):
        """验证 debate_verdicts 表结构"""
        assert DebateVerdicts.__tablename__ == "debate_verdicts"
        assert hasattr(DebateVerdicts, 'symbol')
        assert hasattr(DebateVerdicts, 'verdict')
        assert hasattr(DebateVerdicts, 'conviction')
        assert hasattr(DebateVerdicts, 'reasoning')

    def test_trading_plans_schema(self):
        """验证 trading_plans 表结构"""
        assert TradingPlans.__tablename__ == "trading_plans"
        assert hasattr(TradingPlans, 'symbol')
        assert hasattr(TradingPlans, 'entry_price')
        assert hasattr(TradingPlans, 'stop_loss')
        assert hasattr(TradingPlans, 'take_profit')
        assert hasattr(TradingPlans, 'position_size')

    def test_risk_checks_schema(self):
        """验证 risk_checks 表结构"""
        assert RiskChecks.__tablename__ == "risk_checks"
        assert hasattr(RiskChecks, 'symbol')
        assert hasattr(RiskChecks, 'risk_score')
        assert hasattr(RiskChecks, 'risk_factors')
        assert hasattr(RiskChecks, 'approved')

    def test_execution_followup_schema(self):
        """验证 execution_followup 表结构"""
        assert ExecutionFollowup.__tablename__ == "execution_followup"
        assert hasattr(ExecutionFollowup, 'symbol')
        assert hasattr(ExecutionFollowup, 'verdict')
        assert hasattr(ExecutionFollowup, 'validated')
        assert hasattr(ExecutionFollowup, 'pnl')

    def test_debate_index_schema(self):
        """验证 debate_index 表结构"""
        assert DebateIndex.__tablename__ == "debate_index"
        assert hasattr(DebateIndex, 'date')
        assert hasattr(DebateIndex, 'symbols')
        assert hasattr(DebateIndex, 'report_path')
        assert hasattr(DebateIndex, 'status')


class TestPostgresConnection:
    """PostgreSQL 连接层测试"""

    def test_pg_config_defaults(self):
        """验证 PGConfig 默认配置"""
        from fdt_pg.connection import PGConfig
        config = PGConfig()
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "fdt"
        assert config.username == "fdt_user"
        assert isinstance(config.dsn, str)
        assert "postgresql+psycopg2://" in config.dsn

    def test_pg_connection_singleton(self):
        """验证 PGConnection 单例模式"""
        from fdt_pg.connection import PGConnection
        engine1 = PGConnection.get_engine()
        engine2 = PGConnection.get_engine()
        assert engine1 is engine2

    def test_session_scope_exists(self):
        """验证 session_scope 上下文管理器存在"""
        from fdt_pg.connection import PGConnection
        assert hasattr(PGConnection, 'session_scope')
        assert callable(PGConnection.session_scope)

    def test_health_check_exists(self):
        """验证 health_check 方法存在"""
        from fdt_pg.connection import PGConnection
        assert hasattr(PGConnection, 'health_check')
        assert callable(PGConnection.health_check)


class TestPostgresDeploy:
    """PostgreSQL 部署工具测试"""

    def test_deploy_module_exists(self):
        """验证 deploy 模块存在"""
        try:
            from fdt_pg import deploy
            assert hasattr(deploy, 'deploy_schema')
            assert hasattr(deploy, 'migrate_json_to_pg')
            assert hasattr(deploy, 'show_status')
        except ImportError:
            pytest.fail("fdt_pg.deploy 模块导入失败")

    def test_deploy_schema_function(self):
        """验证 deploy_schema 函数可调用"""
        from fdt_pg.deploy import deploy_schema
        assert callable(deploy_schema)

    def test_migrate_function(self):
        """验证 migrate_json_to_pg 函数可调用"""
        from fdt_pg.deploy import migrate_json_to_pg
        assert callable(migrate_json_to_pg)

    def test_status_function(self):
        """验证 show_status 函数可调用"""
        from fdt_pg.deploy import show_status
        assert callable(show_status)
