# PostgreSQL 数据库升级方案

> **文档版本**: v1.0 | **日期**: 2026-07-05 | **状态**: 方案咨询（暂不实施）

---

## 1. 现状分析：当前数据层生态

当前系统存在 **8 种持久化方式**，散落在 6 个 skill + scripts/ 中：

| # | 存储方式 | 位置 | 存储内容 | 并发安全 | 查询能力 |
|:-:|:--------|:-----|:---------|:--------|:--------|
| 1 | **DuckDB** | `skills/quant-daily/data/futures.db` | K线数据、持仓量、期限结构 | 🟡 单写 | 🟢 SQL |
| 2 | **SQLite** | `scripts/memory_writer.py` 创建的 `debate_journal.db` | 10Agent各轮日志 | 🟡 单写 | 🟢 SQL |
| 3 | **JSON 文件** | `memory/debate_journal.json` | 辩论记录（明鉴秋汇总） | ❌ 读写竞态 | ❌ 全量加载 |
| 4 | **JSON 文件** | `memory/execution_followup.json` | 执行回溯 | ❌ 读写竞态 | ❌ 全量加载 |
| 5 | **JSON 文件** | `scripts/attribution_analyzer.py` | 论据绩效库、判官权重 | ❌ 读写竞态 | ❌ 全量加载 |
| 6 | **JSON 文件** | `scripts/compliance_agent.py` | 审计日志（哈希链） | 🟡 追加写 | ❌ 全量加载 |
| 7 | **JSON 文件** | `skills/.../trading_memory/{symbol}.json` | 品种记忆 | ❌ 读写竞态 | ❌ 全量加载 |
| 8 | **Markdown 文件** | `memory/policies/*.md` | 否决规则、权重历史 | ❌ 无并发 | ❌ 无查询 |
| 9 | **settings.json** | `settings.json` | 全局配置 | ✅ 只读为主 | ❌ 键值对 |
| 10 | **HTML 文件** | `docs/reports/` + `backtest/results/` | 报告（只读归档） | ✅ 只读 | ❌ 无 |

---

## 2. 核心问题

### 2.1 数据一致性

```
# 场景：10Agent 并发写入 memory_writer.py
Agent A: write("RB辩论结果")     → JSON 文件
Agent B: write("PK辩论结果")     → JSON 文件（同时刻，覆盖）
Agent C: merge_all()            → 读到残缺数据
```

当前使用 "独立文件 + 明鉴秋汇总" 方案（P0-4 修复），但未解决根本问题：
- JSON 文件非事务性
- 无 ACID 保证
- 10Agent 同时写入时，SQLite WAL 模式可缓解但非终极方案

### 2.2 查询能力

所有 JSON/MD 持久化无法按条件查询：

```python
# ❌ 当前
with open("memory/debate_journal.json") as f:
    all = json.load(f)
    rb_entries = [e for e in all if e["symbol"] == "RB"]

# ✅ 理想
cursor.execute("SELECT * FROM debate_journal WHERE symbol = 'RB' AND created_at > NOW() - INTERVAL '30 days'")
```

### 2.3 数据冗余与一致性

取数流程当前：DuckDB（行情）→ JSON（记忆），JSON 中存了行情快照的副本，两份数据无同步机制。

---

## 3. 目标架构

### 3.1 统一存储层

```
┌─────────────────────────────────────┐
│            PostgreSQL                │
├─────────────────────────────────────┤
│  fdb_market     → 行情数据            │
│  fdb_debates    → 辩论日志            │
│  fdb_memory     → 记忆（短/中/长期）   │
│  fdb_trading    → 交易记录+执行回溯     │
│  fdb_compliance → 合规审计（哈希链）    │
│  fdb_backtest   → 回测结果             │
│  fdb_config     → 配置管理             │
└─────────────────────────────────────┘
```

### 3.2 保留的本地存储

以下内容运行在本地生成，**不需要放入 PG**，保留文件系统：

- `*.html` 报告：只读归档，每次辩论生成一次，无需并发
- `settings.json`：本地配置（不提交 git），通过 `ConfigManager` 读取
- `data/sentiment/sentiment_cache.json`：情感因子缓存（自动重建）
- `reports/daily/*.html`：每日复盘报告（自动生成，可归档）

---

## 4. 数据库 Schema 设计

### 4.1 `fdb_market` — 行情数据（替换 DuckDB + 交易记忆）

```sql
CREATE TABLE market_ohlc (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL,        -- "RB" / "CU"
    contract        VARCHAR(20),                  -- "rb2510"
    ts              TIMESTAMPTZ NOT NULL,         -- K线时间
    open            DECIMAL(12,2),
    high            DECIMAL(12,2),
    low             DECIMAL(12,2),
    close           DECIMAL(12,2),
    volume          BIGINT,
    open_interest   BIGINT,
    resolution      VARCHAR(5) DEFAULT '1d',     -- 1d / 1h / 15min
    source          VARCHAR(20) DEFAULT 'tdx',
    UNIQUE(symbol, contract, ts, resolution)
);

-- 分区：按月分区，保留6个月热数据
CREATE TABLE market_term_structure (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL,
    trade_date      DATE NOT NULL,
    contracts       JSONB NOT NULL,              -- {"cu2409": 72000, "cu2410": 71800, ...}
    front_month     VARCHAR(20),
    back_month      VARCHAR(20),
    spread          DECIMAL(10,2),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, trade_date)
);

CREATE TABLE market_indicators (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    indicator_group VARCHAR(20) NOT NULL,         -- "l1l4" / "factor_timing" / "sentiment"
    data            JSONB NOT NULL,               -- 完整指标快照
    fingerprint     VARCHAR(64),                  -- 策略指纹
    UNIQUE(symbol, ts, indicator_group, fingerprint)
);

CREATE INDEX idx_market_ohlc_symbol_ts ON market_ohlc(symbol, ts DESC);
CREATE INDEX idx_market_indicators_group ON market_indicators(indicator_group, ts DESC);
```

### 4.2 `fdb_debates` — 辩论日志（替换 debate_journal.json + memory_writer）

```sql
CREATE TYPE debate_role AS ENUM ('数技源', '链证源', '探源', '观澜', '证真', '慎思', '策执远', '风控明', '闫判官', '明鉴秋');

CREATE TABLE debate_sessions (
    id              BIGSERIAL PRIMARY KEY,
    round_id        VARCHAR(32) NOT NULL UNIQUE, -- "RB_20260705"
    symbol          VARCHAR(10) NOT NULL,
    direction       VARCHAR(4),                   -- "bull" / "bear"
    status          VARCHAR(10) DEFAULT 'active',  -- active / completed / aborted
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE debate_entries (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT REFERENCES debate_sessions(id),
    agent_id        VARCHAR(32) NOT NULL,
    role            debate_role NOT NULL,
    phase           VARCHAR(5) NOT NULL,          -- "P1"~"P5"
    data_type       VARCHAR(20) NOT NULL,          -- "signal" / "analysis" / "argument" / "verdict"
    content         JSONB NOT NULL,               -- 结构化的 Agent 输出
    fingerprint     VARCHAR(64),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_debate_entries_session ON debate_entries(session_id);
CREATE INDEX idx_debate_entries_role ON debate_entries(role);
```

### 4.3 `fdb_memory` — 记忆系统（替换 vector_memory.py + attribution_analyzer + trading_memory）

```sql
CREATE TABLE memory_records (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL,
    layer           VARCHAR(10) NOT NULL,          -- "short" / "mid" / "long"
    record_type     VARCHAR(20) NOT NULL,          -- "trade" / "failure" / "black_swan" / "argument"
    direction       VARCHAR(4),
    pnl             DECIMAL(12,2),
    regime          VARCHAR(20),                   -- "strong_trend" / "wide_range" / "extreme"
    attribution     JSONB,                         -- Shapley归因标签
    embedding       VECTOR(64),                    -- pgvector向量，用于相似检索
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ                   -- short=24h, mid=30d, long=NULL
);

-- pgvector 索引
CREATE INDEX idx_memory_embedding ON memory_records 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_memory_symbol_layer ON memory_records(symbol, layer);
```

### 4.4 `fdb_trading` — 交易执行（替换 execution_followup.json + trade_journal）

```sql
CREATE TABLE trading_plans (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT REFERENCES debate_sessions(id),
    symbol          VARCHAR(10) NOT NULL,
    direction       VARCHAR(4) NOT NULL,
    contract        VARCHAR(20),
    entry_price     DECIMAL(12,2),
    stop_loss       DECIMAL(12,2),
    take_profit     DECIMAL(12,2),
    lots            INTEGER,
    margin          DECIMAL(12,2),
    status          VARCHAR(10) DEFAULT 'pending', -- pending / filled / closed / cancelled
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE trading_executions (
    id              BIGSERIAL PRIMARY KEY,
    plan_id         BIGINT REFERENCES trading_plans(id),
    order_id        VARCHAR(32),
    batch           INTEGER,                       -- TWAP分批
    filled_price    DECIMAL(12,2),
    filled_lots     INTEGER,
    slippage        DECIMAL(8,4),
    commission      DECIMAL(10,2),
    executed_at     TIMESTAMPTZ DEFAULT NOW()
);
```

### 4.5 `fdb_compliance` — 合规审计（替换 compliance_agent.py 的 JSON 日志）

```sql
CREATE TABLE compliance_audit (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT REFERENCES debate_sessions(id),
    check_type      VARCHAR(20) NOT NULL,           -- "position_limit" / "delivery_month" / "large_trader" / "frequency"
    symbol          VARCHAR(10),
    passed          BOOLEAN NOT NULL,
    current_value   INTEGER,                        -- 当前持仓
    threshold       INTEGER,                        -- 限额
    severity        VARCHAR(10),                    -- "INFO" / "WARNING" / "HIGH"
    detail          TEXT,
    prev_hash       VARCHAR(64),                    -- 哈希链
    hash            VARCHAR(64) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- PG 内置哈希函数保证链完整性
CREATE INDEX idx_compliance_session ON compliance_audit(session_id);
```

### 4.6 `fdb_backtest` — 回测结果（替换 JSON + HTML 报告）

```sql
CREATE TABLE backtest_results (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL,
    strategy        VARCHAR(32) NOT NULL,
    run_id          VARCHAR(32),                    -- 同一运行的标识
    params          JSONB,                          -- {seed: 42, fee_rate: 0.001, ...}
    fingerprint     VARCHAR(64),
    cr              DECIMAL(10,4),
    sr              DECIMAL(10,4),
    win_rate        DECIMAL(6,4),
    max_dd          DECIMAL(8,4),
    profit_factor   DECIMAL(10,4),
    trades          INTEGER,
    detailed_metrics JSONB,                         -- 月度/品种层级指标
    completed_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_backtest_symbol ON backtest_results(symbol, completed_at DESC);
```

### 4.7 `fdb_config` — 配置管理（替换 settings.json）

```sql
CREATE TABLE app_config (
    key             VARCHAR(64) PRIMARY KEY,
    value           JSONB NOT NULL,
    description     TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_by      VARCHAR(32)
);
```

---

## 5. 实施步骤

### 阶段一：基础设施搭建（1小时）

```bash
# 1. 启动 PostgreSQL 实例（Docker）
docker run -d \
  --name fdb-postgres \
  -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=futures_debate \
  -p 5432:5432 \
  ankane/pgvector:latest    # 自带 pgvector 扩展

# 2. 安装 Python 驱动
pip install psycopg2-binary pgvector sqlalchemy alembic

# 3. 初始化数据库
alembic init migrations
alembic revision --autogenerate -m "init"
alembic upgrade head
```

### 阶段二：连接层抽象（2小时）

创建统一数据库连接池：

```
scripts/db/
├── __init__.py         # DatabasePool 单例
├── models.py           # SQLAlchemy ORM 模型（映射上述 schema）
├── repositories/       # 数据访问层
│   ├── market_repo.py
│   ├── debate_repo.py
│   ├── memory_repo.py
│   ├── trading_repo.py
│   └── config_repo.py
└── migrations/         # Alembic 迁移
```

```python
# 示例：scripts/db/__init__.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

class DatabasePool:
    _instance = None
    
    def __init__(self, dsn: str = None):
        self.engine = create_engine(
            dsn or "postgresql://fdb_user:password@localhost:5432/futures_debate",
            pool_size=10, max_overflow=20,
            pool_pre_ping=True,
        )
        self.Session = scoped_session(sessionmaker(bind=self.engine))
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            raise RuntimeError("DatabasePool not initialized")
        return cls._instance
```

### 阶段三：数据迁移（3小时）

```
迁移顺序（按依赖关系）:
1. config_repo   → 读 settings.json 写入 app_config 表
2. market_repo   → DuckDB → fdb_market.* 表
3. debate_repo   → memory/debate_journal.json → fdb_debates.*
4. memory_repo   → memory/*.json + trading_memory/*.json → fdb_memory.*
5. trading_repo  → execution_followup.json → fdb_trading.*
6. compliance    → compliance JSON → fdb_compliance.*
7. backtest      → backtest/results/*.json → fdb_backtest.*
```

使用脚本化迁移，支持幂等重跑：

```python
# scripts/db/migrate_from_json.py
python scripts/db/migrate_from_json.py --source memory/debate_journal.json --target debates
```

### 阶段四：逐步替换读取路径（4小时）

按"读先切、写后切"原则，逐个模块替换：

| 模块 | 当前读取方式 | PG 替换方式 | 替换顺序 |
|:-----|:------------|:------------|:--------|
| `memory_writer.py` | 写 JSON + SQLite | 写 PG `debate_entries` | 1️⃣ |
| `fingerprint.py` | 生成指纹字符串 | 同时写入 `market_indicators` | 2️⃣ |
| `attribution_analyzer.py` | JSON 文件 | 读 PG `memory_records` | 3️⃣ |
| `vector_memory.py` | 三层文件系统 | pgvector 向量检索 | 4️⃣ |
| `portfolio_risk.py` | 内存计算 | 读 PG `trading_plans` | 5️⃣ |
| `compliance_agent.py` | JSON 哈希链 | PG 哈希链 | 6️⃣ |
| `ConfigManager` | settings.json | 读 PG `app_config`（保留 JSON 为本地 fallback） | 7️⃣ |
| `scan_all.py` | DuckDB | 读 PG `market_ohlc` | 8️⃣ |
| `backtest_report.py` | DuckDB + JSON | 读 PG `market_ohlc` | 9️⃣ |

### 阶段五：旧存储退役（1小时）

```bash
# 确认 PG 数据完整性后
rm memory/debate_journal.json
rm memory/execution_followup.json
# DuckDB 保留为只读备份
mv skills/quant-daily/data/futures.db skills/quant-daily/data/futures.db.bak
```

---

## 6. 风险与缓解

### 6.1 性能风险

| 场景 | 风险 | 缓解 |
|:-----|:-----|:------|
| DuckDB → PG 行存储，OLAP 查询变慢 | 回测时指标计算需要大量历史数据 | 保留 DuckDB 作为 OLAP 层，PG 只存结果；需要时用 PG Foreign Data Wrapper (fdw) 透明查询 DuckDB |
| 10Agent 并发写入 debate_entries | PG 连接池耗尽 | 连接池 `max_overflow=20`，写入线程数限制 `max_workers=4`，写入超时 `statement_timeout=5s` |
| pgvector 查询慢（>1M 向量） | IVFFlat 索引在数据量小时精度下降 | 初期用余弦相似度替代向量检索，数据量达到 100K 行后再开启 pgvector |

### 6.2 迁移风险

```yaml
风险1: DuckDB → PG 数据类型不兼容
  - DuckDB 的 DECIMAL 精度与 PG 不完全一致
  → 用 NUMERIC(20,4) 作为泛化类型，迁移脚本中显式 CAST
  
风险2: JSON 文件写入时系统崩溃导致数据丢失
  → 先迁移读取路径（旧文件仍可读），再切换写入路径
  → 回退方案：切回 JSON 文件，PG 作为只读副本

风险3: pgvector 扩展在 PG 15 上不可用
  → 使用 PostgreSQL 16+，或跳过向量检索功能暂缓实施
```

### 6.3 回退方案

每个步骤都有回退机制：

```
第N步失败 → 切回第N-1步
     ↓
写入 PG 失败 → 保留 JSON 文件作为 fallback（双写模式）
     ↓
PG 宕机 → DatabasePool 自动降级到 SQLite（local fallback）
     ↓
全部不可用 → 只读模式，继续使用 JSON 文件
```

---

## 7. 变更清单

### 修改文件（共 18 个）

| 文件 | 修改方式 | 变更内容 |
|:-----|:--------|:---------|
| `scripts/memory_writer.py` | ✏️ 重构 | 写 PG `debate_entries`，保留 SQLite 为 fallback |
| `scripts/vector_memory.py` | ✏️ 重构 | 替换文件系统为 pgvector 检索 |
| `scripts/attribution_analyzer.py` | ✏️ 修改 | JSON → PG `memory_records` |
| `scripts/portfolio_risk.py` | ✏️ 修改 | 读 PG `trading_plans` 计算集中度 |
| `scripts/compliance_agent.py` | ✏️ 修改 | JSON → PG `compliance_audit` |
| `scripts/config_manager.py` | ✏️ 修改 | 新增 PG 数据源（保留 JSON fallback） |
| `scripts/fingerprint.py` | ✏️ 修改 | 写 PG `market_indicators` |
| `scripts/auto_factor_mining.py` | ✏️ 修改 | JSON → PG |
| `skills/quant-daily/scripts/scan_all.py` | ✏️ 修改 | DuckDB → PG `market_ohlc` |
| `skills/quant-daily/scripts/data/multi_source_adapter.py` | ✏️ 修改 | 新增 PG 数据源适配器 |
| `skills/quant-daily/scripts/strategies/factor_timing.py` | ✏️ 修改 | DuckDB → PG |
| `skills/quant-daily/scripts/backtest/backtest_report.py` | ✏️ 修改 | DuckDB → PG（保留 DuckDB OLAP） |
| `skills/commodity-chain-analysis/scripts/term_basis.py` | ✏️ 修改 | DuckDB → PG |
| `skills/commodity-chain-analysis/scripts/debate.py` | ✏️ 修改 | DuckDB → PG |
| `skills/debate-risk-manager/scripts/risk_engine.py` | ✏️ 修改 | 读 PG 交易数据 |
| `skills/quant-daily/data/futures.db` | 🗑️ 退役 | 迁移后改为 .bak |
| `memory/debate_journal.json` | 🗑️ 退役 | 迁移后删除 |
| `memory/execution_followup.json` | 🗑️ 退役 | 迁移后删除 |

### 新建文件（共 8 个）

```
scripts/db/__init__.py              # DatabasePool 单例
scripts/db/models.py                # SQLAlchemy ORM
scripts/db/repositories/market_repo.py
scripts/db/repositories/debate_repo.py
scripts/db/repositories/memory_repo.py
scripts/db/repositories/trading_repo.py
scripts/db/repositories/config_repo.py
scripts/db/migrate_from_json.py    # 数据迁移脚本
```

---

## 8. 成本估算

| 阶段 | 预估工时 | 依赖 | 产出 |
|:-----|:--------|:-----|:-----|
| 一：基础设施 | 1h | Docker / pgvector | PG 实例 + 迁移框架 |
| 二：连接层 | 2h | psycopg2 + SQLAlchemy | DatabasePool + ORM |
| 三：数据迁移 | 3h | 旧数据完整性 | 全量迁移脚本（可重跑） |
| 四：读取替换 | 4h | 阶段二 | 8个模块读取切换 |
| 五：退役清理 | 1h | 阶段四确认 | 旧文件退役 |
| **合计** | **11h** | — | PG 全量迁移完成 |

---

## 9. 建议优先级

**建议分两批实施**：

### 第一批（6h — 核心链路）

```
顺序: config → memory_writer → fingerprint → attribution → compliance
收益: 解决记忆读写竞态 + 数据丢失 + 审计哈希链
风险: 低（非交易核心路径，K线数据仍在 DuckDB）
```

### 第二批（5h — 交易链路）

```
顺序: market_repo → term_basis → scan_all → backtest → old decommission
收益: K线数据统一 + 回测结果可查询
风险: 中（DuckDB → PG 数据类型兼容需验证）
```

---

## 10. 附录：关键决策记录

| 编号 | 决策 | 理由 |
|:----|:-----|:------|
| ADR-001 | 保留 DuckDB 为 OLAP 层，PG 负责 OLTP | DuckDB 列存对回测指标计算（大量历史数据扫描）更优 |
| ADR-002 | 使用 pgvector 而非独立向量库 | 减少运维复杂度，1 个数据库实例替代 2 个 |
| ADR-003 | 双写模式过渡（新文件同时写 PG + JSON） | 零停机迁移，随时回退 |
| ADR-004 | 配置表使用 JSONB 而非多列 | 配置项结构频繁变化，JSONB 无 schema 迁移成本 |
| ADR-005 | 不使用 pg_partman 自动分区，手动管理分区 | 数据量 < 500GB，手动分区足够，减少依赖 |
