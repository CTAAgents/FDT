BEGIN;

CREATE TABLE IF NOT EXISTS scan_signals (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    date DATE NOT NULL,
    signal_type VARCHAR(32) NOT NULL,
    signal_value FLOAT,
    threshold FLOAT,
    confidence FLOAT,
    source VARCHAR(32),
    metadata_json JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trace_id, symbol, signal_type)
);

CREATE INDEX IF NOT EXISTS idx_scan_signals_date ON scan_signals(date);
CREATE INDEX IF NOT EXISTS idx_scan_signals_trace ON scan_signals(trace_id);

CREATE TABLE IF NOT EXISTS chain_analysis (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    date DATE NOT NULL,
    chain_name VARCHAR(64),
    upstream_indicators JSON,
    downstream_indicators JSON,
    sentiment_score FLOAT,
    bottleneck_analysis JSON,
    metadata_json JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trace_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_chain_analysis_date ON chain_analysis(date);

CREATE TABLE IF NOT EXISTS technical_scores (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    date DATE NOT NULL,
    trend_score FLOAT,
    momentum_score FLOAT,
    volatility_score FLOAT,
    volume_score FLOAT,
    support_resistance JSON,
    pattern_recognition JSON,
    composite_score FLOAT,
    metadata_json JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trace_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_technical_scores_date ON technical_scores(date);

CREATE TABLE IF NOT EXISTS fundamental_scores (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    date DATE NOT NULL,
    supply_score FLOAT,
    demand_score FLOAT,
    inventory_score FLOAT,
    macro_score FLOAT,
    policy_analysis JSON,
    seasonal_analysis JSON,
    composite_score FLOAT,
    metadata_json JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trace_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_fundamental_scores_date ON fundamental_scores(date);

CREATE TABLE IF NOT EXISTS judge_direction (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL UNIQUE,
    selected_symbols JSON,
    direction VARCHAR(8),
    dispatch_sources JSON,
    reasoning TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_judge_direction_trace ON judge_direction(trace_id);

CREATE TABLE IF NOT EXISTS debate_arguments (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    side VARCHAR(8) NOT NULL,
    arguments JSON,
    confidence FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trace_id, symbol, side)
);

CREATE INDEX IF NOT EXISTS idx_debate_arguments_trace ON debate_arguments(trace_id);

CREATE TABLE IF NOT EXISTS debate_verdicts (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL UNIQUE,
    symbol VARCHAR(16) NOT NULL,
    verdict VARCHAR(8),
    conviction FLOAT,
    reasoning TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_debate_verdicts_trace ON debate_verdicts(trace_id);

CREATE TABLE IF NOT EXISTS trading_plans (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    entry_price FLOAT,
    stop_loss FLOAT,
    take_profit FLOAT,
    position_size FLOAT,
    timeframe VARCHAR(32),
    plan_details JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trace_id, symbol)
);

CREATE TABLE IF NOT EXISTS risk_checks (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    risk_score FLOAT,
    risk_factors JSON,
    approved BOOLEAN,
    approval_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trace_id, symbol)
);

CREATE TABLE IF NOT EXISTS execution_followup (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL UNIQUE,
    verdict_date DATE,
    symbol VARCHAR(16),
    verdict VARCHAR(8),
    validated BOOLEAN DEFAULT FALSE,
    validation_date DATE,
    pnl FLOAT,
    followup_metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_profiles (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(64) NOT NULL UNIQUE,
    parameters JSON,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calibration (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    weights JSON,
    statistics JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS log_entries (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trace_id VARCHAR(64),
    level VARCHAR(8),
    logger VARCHAR(64),
    message TEXT,
    metadata_json JSON
);

CREATE INDEX IF NOT EXISTS idx_log_entries_timestamp ON log_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_log_entries_trace ON log_entries(trace_id);

CREATE TABLE IF NOT EXISTS debate_index (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL UNIQUE,
    date DATE NOT NULL,
    symbols JSON,
    report_path VARCHAR(512),
    status VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_debate_index_date ON debate_index(date);

COMMIT;

BEGIN;

CREATE OR REPLACE VIEW v_debate_summary AS
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

CREATE OR REPLACE VIEW v_signal_performance AS
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

CREATE OR REPLACE VIEW v_agent_effectiveness AS
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

COMMIT;