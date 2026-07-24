from sqlalchemy import JSON, TEXT, Boolean, Column, Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class ScanSignals(Base):
    __tablename__ = "scan_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False)
    date = Column(Date, nullable=False, index=True)
    signal_type = Column(String(32), nullable=False)
    signal_value = Column(Float)
    threshold = Column(Float)
    confidence = Column(Float)
    source = Column(String(32))
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("trace_id", "symbol", "signal_type", name="uq_scan_signals"),
        Index("idx_scan_signals_date", "date"),
        Index("idx_scan_signals_trace", "trace_id"),
    )


class ChainAnalysis(Base):
    __tablename__ = "chain_analysis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False)
    date = Column(Date, nullable=False, index=True)
    chain_name = Column(String(64))
    upstream_indicators = Column(JSON)
    downstream_indicators = Column(JSON)
    sentiment_score = Column(Float)
    bottleneck_analysis = Column(JSON)
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("trace_id", "symbol", name="uq_chain_analysis"),
        Index("idx_chain_analysis_date", "date"),
    )


class TechnicalScores(Base):
    __tablename__ = "technical_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False)
    date = Column(Date, nullable=False, index=True)
    trend_score = Column(Float)
    momentum_score = Column(Float)
    volatility_score = Column(Float)
    volume_score = Column(Float)
    support_resistance = Column(JSON)
    pattern_recognition = Column(JSON)
    composite_score = Column(Float)
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("trace_id", "symbol", name="uq_technical_scores"),
        Index("idx_technical_scores_date", "date"),
    )


class FundamentalScores(Base):
    __tablename__ = "fundamental_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False)
    date = Column(Date, nullable=False, index=True)
    supply_score = Column(Float)
    demand_score = Column(Float)
    inventory_score = Column(Float)
    macro_score = Column(Float)
    policy_analysis = Column(JSON)
    seasonal_analysis = Column(JSON)
    composite_score = Column(Float)
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("trace_id", "symbol", name="uq_fundamental_scores"),
        Index("idx_fundamental_scores_date", "date"),
    )


class JudgeDirection(Base):
    __tablename__ = "judge_direction"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True, unique=True)
    selected_symbols = Column(JSON)
    direction = Column(String(8))
    dispatch_sources = Column(JSON)
    reasoning = Column(TEXT)
    created_at = Column(DateTime, default=func.now())


class DebateArguments(Base):
    __tablename__ = "debate_arguments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False)
    side = Column(String(8), nullable=False)
    arguments = Column(JSON)
    confidence = Column(Float)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("trace_id", "symbol", "side", name="uq_debate_arguments"),
    )


class DebateVerdicts(Base):
    __tablename__ = "debate_verdicts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True, unique=True)
    symbol = Column(String(16), nullable=False)
    verdict = Column(String(8))
    conviction = Column(Float)
    reasoning = Column(TEXT)
    created_at = Column(DateTime, default=func.now())


class TradingPlans(Base):
    __tablename__ = "trading_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False)
    entry_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    position_size = Column(Float)
    timeframe = Column(String(32))
    plan_details = Column(JSON)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("trace_id", "symbol", name="uq_trading_plans"),
    )


class RiskChecks(Base):
    __tablename__ = "risk_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    symbol = Column(String(16), nullable=False)
    risk_score = Column(Float)
    risk_factors = Column(JSON)
    approved = Column(Boolean)
    approval_reason = Column(TEXT)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("trace_id", "symbol", name="uq_risk_checks"),
    )


class ExecutionFollowup(Base):
    __tablename__ = "execution_followup"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True, unique=True)
    verdict_date = Column(Date)
    symbol = Column(String(16))
    verdict = Column(String(8))
    validated = Column(Boolean, default=False)
    validation_date = Column(Date)
    pnl = Column(Float)
    followup_metadata = Column(JSON)
    created_at = Column(DateTime, default=func.now())


class AgentProfiles(Base):
    __tablename__ = "agent_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(64), nullable=False, unique=True)
    parameters = Column(JSON)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class Calibration(Base):
    __tablename__ = "calibration"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    weights = Column(JSON)
    statistics = Column(JSON)
    created_at = Column(DateTime, default=func.now())


class LogEntries(Base):
    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=func.now(), index=True)
    trace_id = Column(String(64), index=True)
    level = Column(String(8))
    logger = Column(String(64))
    message = Column(TEXT)
    metadata_json = Column(JSON)


class DebateIndex(Base):
    __tablename__ = "debate_index"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, unique=True)
    date = Column(Date, nullable=False, index=True)
    symbols = Column(JSON)
    report_path = Column(String(512))
    status = Column(String(32))
    created_at = Column(DateTime, default=func.now())


OLAP_VIEWS = {
    "v_debate_summary": """
    CREATE VIEW v_debate_summary AS
    SELECT
        dv.trace_id,
        dv.symbol,
        dv.verdict,
        dv.conviction,
        tp.entry_price,
        tp.stop_loss,
        tp.take_profit,
        rc.risk_score,
        rc.approved,
        ss.signal_value,
        ts.composite_score AS technical_score,
        fs.composite_score AS fundamental_score,
        dv.created_at AS verdict_time
    FROM debate_verdicts dv
    LEFT JOIN trading_plans tp ON dv.trace_id = tp.trace_id AND dv.symbol = tp.symbol
    LEFT JOIN risk_checks rc ON dv.trace_id = rc.trace_id AND dv.symbol = rc.symbol
    LEFT JOIN scan_signals ss ON dv.trace_id = ss.trace_id AND dv.symbol = ss.symbol
    LEFT JOIN technical_scores ts ON dv.trace_id = ts.trace_id AND dv.symbol = ts.symbol
    LEFT JOIN fundamental_scores fs ON dv.trace_id = fs.trace_id AND dv.symbol = fs.symbol
    ORDER BY dv.created_at DESC;
    """,
    "v_signal_performance": """
    CREATE VIEW v_signal_performance AS
    SELECT
        ss.signal_type,
        ss.symbol,
        ef.verdict,
        ef.pnl,
        COUNT(*) OVER (PARTITION BY ss.signal_type) AS sample_count,
        AVG(ef.pnl) OVER (PARTITION BY ss.signal_type) AS avg_pnl,
        SUM(CASE WHEN ef.pnl > 0 THEN 1 ELSE 0 END) OVER (PARTITION BY ss.signal_type) * 100.0 /
            COUNT(*) OVER (PARTITION BY ss.signal_type) AS win_rate
    FROM scan_signals ss
    JOIN execution_followup ef ON ss.trace_id = ef.trace_id AND ss.symbol = ef.symbol
    WHERE ef.validated = TRUE
    ORDER BY ss.signal_type, ss.symbol;
    """,
    "v_agent_effectiveness": """
    CREATE VIEW v_agent_effectiveness AS
    SELECT
        da.side,
        da.symbol,
        AVG(da.confidence) AS avg_confidence,
        AVG(dv.conviction) AS avg_verdict_conviction,
        COUNT(*) AS debate_count,
        SUM(CASE WHEN dv.verdict = 'bullish' AND da.side = 'bullish' THEN 1
                 WHEN dv.verdict = 'bearish' AND da.side = 'bearish' THEN 1
                 ELSE 0 END) AS correct_count,
        SUM(CASE WHEN dv.verdict = 'bullish' AND da.side = 'bullish' THEN 1
                 WHEN dv.verdict = 'bearish' AND da.side = 'bearish' THEN 1
                 ELSE 0 END) * 100.0 / COUNT(*) AS accuracy_rate
    FROM debate_arguments da
    JOIN debate_verdicts dv ON da.trace_id = dv.trace_id AND da.symbol = dv.symbol
    GROUP BY da.side, da.symbol
    ORDER BY da.side, accuracy_rate DESC;
    """
}
