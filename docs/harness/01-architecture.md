# 01 — Harness 架构总览

## 1. 分层架构

FDT 的 Harness 层从下到上分为 5 层，每层有明确的职责边界：

```
┌─────────────────────────────────────────────────────────────────────┐
│                     L5 — 可观测性层 (Observability)                   │
│   APM-CS五轴 · 统一日志 · ViBench回放 · 失败聚类 · 自改进脚手架        │
├─────────────────────────────────────────────────────────────────────┤
│                     L4 — LangGraph 编排层 (Orchestration)            │
│   StateGraph · 条件边 · Checkpointer · 流式输出 · 多模式路由          │
├─────────────────────────────────────────────────────────────────────┤
│                     L3 — 通信契约层 (Contract)                        │
│   DebateState TypedDict · JSON Schema(9个) · agent-protocol v3.0     │
├─────────────────────────────────────────────────────────────────────┤
│                     L2 — 鲁棒性防线 (Resilience)                      │
│   L1产出校验 · L2熔断降级 · L3信号门 · L4路径发现 · L5健康自检        │
├─────────────────────────────────────────────────────────────────────┤
│                     L1 — 基础设施层 (Infrastructure)                   │
│   PostgreSQL(OLTP+OLAP) · memory系统 · unified_logger · memory_writer │
│   · fdt_cache(SQLite增量缓存) · debate_archiver · fdt_pg(连接层)      │
│   · 独立CLI/FastAPI入口                                              │
```

### 各层职责

| 层 | 职责 | 核心组件 |
|:--|:-----|:---------|
| **L1 基础设施** | 持久化(PG混合存储)、日志、并发安全写入、独立入口、本地SQLite增量缓存(按品种+数据类型持久化K线/基本面/基差) | `fdt_pg/` (连接层+OLAP视图), `memory/` (27文件), `fdt_cache/` (SQLite增量缓存), `unified_logger.py`, `memory_writer.py`, `debate_archiver.py`, `fdt_cli.py`, `fdt_api.py` |
| **L2 鲁棒性** | 错误检测、降级、恢复 | L1-L5五层防线, `agent_waiter.py`, D06降级 |
| **L3 通信契约** | Agent 间数据格式约束 | `fdt_langgraph/state.py` (DebateState), `docs/schemas/` (9个JSON Schema), `contracts/debate_argument_schema.py`, `docs/agent-protocol.md` |
| **L4 LangGraph 编排** | 流程驱动、任务调度、状态管理、并行数据源 | `fdt_langgraph/graph.py`, `fdt_langgraph/nodes.py`, `fdt_langgraph/agents.py`（Checkpointer 逻辑在 graph.py 内联） |
| **L5 可观测性** | 质量度量、诊断、改进 | `apm_scorecard.py`, `cluster_failures.py`, `run_benchmark.py`, `self_improve.py`, LangGraph `get_state_history()` |

### L4 LangGraph 层详细说明

LangGraph 层替代了原有的文件传递 + S04 轮询机制，提供：

| 特性 | 说明 | 收益 |
|:-----|:-----|:-----|
| **StateGraph** | 声明式图定义 | 简化流程配置 |
| **条件边** | 动态路由支持多模式 | fast/deep_research/tournament 模式 |
| **Checkpointer** | SQLite 持久化 | 断点续跑、状态历史 |
| **流式输出** | 实时进度推送 | 改善用户体验 |
| **并发执行** | 并行节点执行 | 提升执行效率 |

### LangGraph 与原有组件映射

| 原有组件 | LangGraph 对应 | 状态 |
|:---------|:--------------|:-----|
| `coordinator.py` | `fdt_langgraph/graph.py` | 待迁移 |
| `pipeline/runner.py` | `fdt_langgraph/graph.py` | ✅ 已迁移（A/B 切换完成） |
| `debate_protocol_v2.py` | `fdt_langgraph/nodes.py` | 待迁移 |
| `agent_runner.py` | `fdt_langgraph/agents.py` | 待迁移 |
| S04 轮询 | Checkpointer + 状态传递 | 已替代 |
| 文件传递 | DebateState 内存传递 | 已替代 |
| WorkBuddy automation | `fdt_cli.py` / `fdt_api.py` 独立入口 | 已替代 |
| DuckDB (`futures.db`) | PostgreSQL (`fdt_pg/` 连接层) | 待迁移 |

## 2. 组件关系图

### 2.1 当前架构（文件传递模式）

```
                    ┌──────────────┐
                    │  fdt_cli     │ ← 入口 (once/daemon/interactive)
                    └──────┬───────┘
                           │
              ┌────────────▼────────────┐
              │   SchedulerEngine       │ ← 心跳调度 (60s间隔)
              │   (scheduler/engine.py) │
              └────────────┬────────────┘
                           │ 触发
              ┌────────────▼────────────┐
              │   Pipeline Runner       │ ← 全自动流水线 (6步)
              │   (pipeline/runner.py)  │
              └────────────┬────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                  ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ 自进化前置   │ │ 6阶段辩论    │ │ 归档+报告    │
  │ validate→    │ │ P1→P1.5→    │ │ archiver→   │
  │ calibrate→   │ │ P2→P3→     │ │ memory_writer│
  │ evolve→ML    │ │ P4→P5→P6   │ │ →HTML报告    │
  └──────────────┘ └──────────────┘ └──────────────┘
                           │
              ┌────────────▼────────────┐
              │   10 Agent 协作         │
              │  (spawn via Agent tool) │
              │  通信: 文件 + S04轮询   │
              │  契约: JSON Schema      │
              │  恢复: L1-L5 + D06      │
              └─────────────────────────┘
```

### 2.2 LangGraph 架构（迁移后 — 并行数据源 + 独立运行）

```
                    ┌─────────────────────────────────────┐
                    │  独立入口                            │
                    │  ┌────────────┐  ┌────────────────┐ │
                    │  │ fdt_cli.py │  │ fdt_api.py     │ │ ← CLI / FastAPI
                    │  │ (单次/守护)│  │ (HTTP服务)     │ │
                    │  └──────┬─────┘  └───────┬────────┘ │
                    └─────────┼────────────────┼──────────┘
                              │                │
                              ▼                ▼
                    ┌─────────────────────────────────────┐
                    │   SchedulerEngine (可选)            │
                    │   APScheduler / Celery Beat         │
                    │   (cron: 0 9 * * 1-5 触发)          │
                    └──────────────┬──────────────────────┘
                                   │ 触发
                    ┌──────────────▼──────────────────────┐
                    │         FdtDebateGraph              │ ← LangGraph 编译图
                    │         (fdt_langgraph/graph.py)    │
                    │                                     │
                    │  ┌───────────────────────────────┐  │
                    │  │ DebateState                   │  │ ← 统一状态管理
                    │  │ • trace_id                    │  │
                    │  │ • scan_results                │  │
                    │  │ • chain_analysis              │  │
                    │  │ • technical_data (观澜)       │  │
                    │  │ • fundamental_data (探源)     │  │
                    │  │ • bullish_arguments           │  │
                    │  │ • bearish_arguments           │  │
                    │  │ • verdict / trading_plan      │  │
                    │  └───────────────────────────────┘  │
                    │                                     │
                    │  ┌───────────────────────────────┐  │
                    │  │ Nodes:                        │  │
                    │  │ • [scan] 数技源               │  │
                    │  │       │                       │  │
                    │  │       ▼                       │  │
                    │  │ • [judge_direction] 闫判官     │  │
                    │  │   选品种+定方向+调度决策        │  │
                    │  │       │                       │  │
                    │  │       ▼                       │  │
                    │  │ • [prepare_data] 数据准备      │  │
                    │  │       │                       │  │
                    │  │  ┌────┴────┬────────┬──────┐  │  │
                    │  │  ▼         ▼        ▼      │  │  │
                    │  │ [链证源] [观澜]   [探源]    │  │  │ ← 并行数据源
                    │  │  产业链  技术面   基本面     │  │  │
                    │  │       └────┬────────┘      │  │  │
                    │  │            ▼               │  │  │
                    │  │  [merge_research] 合并节点  │  │  │
                    │  │       │                    │  │  │
                    │  │       ▼                    │  │  │
                    │  │ • [debate] 证真+慎思        │  │  │
                    │  │ • [verdict] 裁决+风控       │  │  │
                    │  │ • [report] 明鉴秋           │  │  │
                    │  │ • [risk_check] 风控明       │  │  │
                    │  │ • [signal_output] CTP信号    │  │  │
                    │  └───────────────────────────────┘  │
                    │                                     │
                    │  ┌───────────────────────────────┐  │
                    │  │ Checkpointer (PostgreSQL)     │  │
                    │  │ • 状态历史 (OLTP)             │  │
                    │  │ • 断点恢复                    │  │
                    │  └───────────────────────────────┘  │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │   FdtAgentExecutor                  │
                    │   (fdt_langgraph/agents.py)         │
                    │   • 读取 agent 配置                 │
                    │   • 调用 FdtLlm.chat()              │
                    │   • 返回结构化输出                   │
                    └─────────────────────────────────────┘
```

## 3. 数据流总览

### 3.1 主数据流（当前模式 — 文件传递）

```
用户请求
    │
    ▼
[自进化前置] ──→ validate_verdicts.py ──→ calibrate_weights.py ──→ evolve_agents.py
    │                    (K线验证)           (权重校准)              (参数进化)
    ▼
[P1] 可插拔多策略并行扫描（v8.8.6+ 架构）
    ├─ trend_following (10子信号)       ──→ scan_result_tf_{date}.json
    ├─ mean_reversion (3子信号)         ──→ scan_result_mr_{date}.json
    └─ 自定义策略插件                    ──→ scan_result_{plugin}_{date}.json
    │                    ↓ 信号检查闸门: select_triggers(all_ranked, threshold, disable_filter)
    │                    filter=ON → 读 total（P0-4过滤后，默认）
    │                    filter=OFF → 读 _raw_total（无过滤，配合 --mode no-filter）
    ▼
[P2] 闫判官 ──→ p2_judge_direction.json (选品种+定方向)
    │
    ▼
[P3] 链证源+观澜+探源 (并行) ──→ p3_chain_{sym}.json + p3_technical_{sym}.json + p3_fundamental_{sym}.json
    │                    ← 三源平行关系，无先后次序
    ▼
[P4] 六阶段攻防 (串行) ──→ state.bullish_arguments + bearish_arguments + bearish_rebuttal + bullish_rebuttal + bear_final + bull_final
    │
    ▼
[P5] 裁决链 (串行)
    ├─ 闫判官裁决(含完整交易参数) ──→ p5_verdict_{trace_id}.json
    └─ 风控明审核（直接基于闫判官 verdict）──→ p5_risk_check_{sym}.json
    │
    ▼
[P6] 明鉴秋报告生成 ──→ debate_results.json + debate_results.html
[P6a] CTP 信号输出（v8.7.0 新增）──→ signal_output.json（根据风控 risk_color 决定是否输出 CTP 交易信号）
```

> **与 LangGraph 模式的关键差异**:
> - **状态传递**: 文件传递 vs DebateState 内存传递
> - **调度方式**: 串行文件轮询 vs LangGraph 条件边动态路由
> - **并行粒度**: P3 三源并行 + P4 两源并行 vs 全图并行调度
> - **持久化**: JSON 文件 vs PostgreSQL (OLTP+OLAP)
> - **入口**: WorkBuddy 平台 vs 独立 CLI/FastAPI

### 3.2 主数据流（LangGraph 模式 — 并行数据源 + PostgreSQL）

```
用户请求 / cron 触发 / API 调用
    │
    ▼
[自进化前置] ──→ validate_verdicts.py ──→ calibrate_weights.py ──→ evolve_agents.py
    │                                              │
    │                                              ▼
    │                                    ┌──────────────────────┐
    │                                    │ PostgreSQL (OLAP)    │
    │                                    │ • agent_evolution    │
    │                                    │ • calibration_stats  │
    │                                    └──────────────────────┘
    ▼
[FdtDebateGraph] ──→ DebateState (内存状态传递)
    │
    ├─ [scan] 数技源 ──→ state["scan_results"]
    │       │
    │       ▼
    │  [judge_direction] 闫判官
    │  选品种 + 定方向 + 调度决策(需要哪些源？)
    │       │
    │       ▼ (按需并行调度)
    │  ┌──────────────────────────────────────┐
    │  │      按需并行数据源 (Parallel)        │
    │  │                                      │
    │  │   ┌──────────┬──────────┬────────┐  │
    │  │   ▼          ▼          ▼        │  │
    │  │ [链证源]   [观澜]     [探源]     │  │ ← 仅调度需要的源
    │  │ 产业链     技术面     基本面      │  │
    │  │ (按需)     (按需)     (按需)      │  │
    │  │   │         │          │         │  │
    │  │   └─────────┴──────────┘         │  │
    │  │              │                     │  │
    │  │              ▼                     │  │
    │  │  [merge_research] 合并分析结果     │  │
    │  └──────────────────────────────────────┘
    │       │
    │       ▼
    │  ┌──────────────────────────────────────┐
    │  │ PostgreSQL (OLTP)                    │
    │  │ • scan_signals (信号明细)            │
    │  │ • judge_direction (调度决策)         │
    │  │ • chain_analysis (产业链·按需)       │
    │  │ • technical_scores (技术面·按需)     │
    │  │ • fundamental_scores (基本面·按需)   │
    │  └──────────────────────────────────────┘
    │       │
    │       ▼
    │  [debate] 证真+慎思 ──→ state["bullish_arguments"]
    │                          state["bearish_arguments"]
    │       │
    │       ▼
    │  [verdict] 闫判官 ──→ state["verdict"] (含交易参数)
    │       │                 state["risk_check"] (风控明)
    │       │
    │       ▼
    │  ┌──────────────────────────────────────┐
    │  │ PostgreSQL (OLTP)                    │
    │  │ • debate_verdicts (裁决记录)         │
    │  │ • trading_plans (交易方案)           │
    │  │ • risk_checks (风控审核)             │
    │  └──────────────────────────────────────┘
    │       │
    │       ▼
    └─ [report] 明鉴秋 ──→ state["report_path"]
    │
    ▼
record_verdicts.py ──→ pg.execution_followup
    │
    ▼
Checkpointer ──→ PostgreSQL (langgraph_checkpoints 表)
    │               • 状态历史 (OLTP)
    │               • 断点恢复
    ▼
┌──────────────────────────────────────┐
│ PostgreSQL (OLAP 视图)               │
│ • v_debate_summary (辩论汇总)        │
│ • v_signal_performance (信号绩效)    │
│ • v_agent_effectiveness (Agent效能)  │
└──────────────────────────────────────┘
```

### 3.3 状态持久化路径

| 数据类型 | 当前存储位置 | 迁移后存储位置 | 格式 | 写入者 | 存储模式 |
|:---------|:-------------|:--------------|:-----|:-------|:---------|
| 信号扫描结果 | `Commodities/Reports/.../{date}/` | `pg.scan_signals` | PostgreSQL | `node_scan` | OLTP |
| 链证源分析 | `Commodities/Reports/.../{date}/` | `pg.chain_analysis` | PostgreSQL | `node_chain` | OLTP |
| 观澜技术面 | `Commodities/Reports/.../{date}/research_snapshots/` | `pg.technical_scores` | PostgreSQL | `node_technical` | OLTP |
| 探源基本面 | `Commodities/Reports/.../{date}/research_snapshots/` | `pg.fundamental_scores` | PostgreSQL | `node_fundamental` | OLTP |
| 扫描阶段报告 | `{workspace}/{date}/scan_report_{trace_id}.html` | `pg.scan_signals` | HTML+JSON | `node_scan` (嵌入) | 文件+OLTP |
| 研究阶段报告 | `{workspace}/{date}/research_report_{trace_id}.html` | - | HTML | `node_merge_research` | 文件 |
| 裁决阶段报告 | `{workspace}/{date}/verdict_report_{trace_id}.html` | `pg.debate_verdicts` | HTML+JSON | `node_verdict` (嵌入) | 文件+OLTP |
| 辩论阶段报告 | `{workspace}/{date}/debate_report_{date}.html` | - | HTML | `node_report` | 文件 |
| CTP信号扫描报告 | `{workspace}/{date}/signal_report_{trace_id}.html` | - | HTML+JSON | `node_signal_output` | 文件 |
| 辩论裁决 | `Commodities/Reports/.../{date}/debate_results.json` | `pg.debate_verdicts` | PostgreSQL | `node_verdict` | OLTP |
| HTML 报告 | `Commodities/Reports/.../{date}/debate_results.html` | 保持不变 | HTML | `phase3_generate_report.py` | - |
| 辩论日志 | `memory/debate_journal.json` | `pg.langgraph_checkpoints` | PostgreSQL | Checkpointer | OLTP |
| 裁决回溯 | `memory/execution_followup.json` | `pg.execution_followup` | PostgreSQL | `record_verdicts.py` | OLTP |
| Agent 进化参数 | `memory/agent_profiles.json` | `pg.agent_profiles` | PostgreSQL | `evolve_agents.py` | OLTP |
| 权重校准 | `memory/calibration.json` | `pg.calibration` | PostgreSQL | `calibrate_weights.py` | OLTP |
| 验证统计 | `memory/validation_stats.json` | `pg.validation_stats` | PostgreSQL | `validate_verdicts.py` | OLTP |
| 辩论索引 | `memory/debates/INDEX.md` | `pg.debate_index` | PostgreSQL | `debate_archiver.py` | OLTP |
| DuckDB 数据 | `futures.db` | `pg.*` 表 + `pg.v_*` 视图 | PostgreSQL | `fdt_pg/` | OLTP+OLAP |
| 统一日志 | `~/Documents/WorkBuddy/Logs/fdb_{date}.log` | `pg.log_entries` | PostgreSQL | `unified_logger.py` | OLTP |
| 调度器日志 | `scheduler/scheduler.log` | `pg.scheduler_logs` | PostgreSQL | `scheduler/engine.py` | OLTP |
| 状态历史 | - | `pg.langgraph_checkpoints` | PostgreSQL | Checkpointer | OLTP |
| 信号绩效分析 | - | `pg.v_signal_performance` | PostgreSQL 视图 | - | OLAP |
| 辩论汇总 | - | `pg.v_debate_summary` | PostgreSQL 视图 | - | OLAP |
| Agent 效能分析 | - | `pg.v_agent_effectiveness` | PostgreSQL 视图 | - | OLAP |

#### PostgreSQL 混合存储设计 (OLTP + OLAP)

```
┌─────────────────────────────────────────────────────────────┐
│                    PostgreSQL 16+                           │
│                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │      OLTP 层            │  │      OLAP 层            │  │
│  │  (行存储 · 事务处理)     │  │  (列存储 · 分析查询)     │  │
│  │                         │  │                         │  │
│  │  scan_signals           │  │  v_debate_summary       │  │
│  │  chain_analysis         │  │  v_signal_performance   │  │
│  │  technical_scores       │  │  v_agent_effectiveness  │  │
│  │  fundamental_scores     │  │  v_daily_pnl            │  │
│  │  debate_verdicts        │  │  v_win_rate_by_agent    │  │
│  │  trading_plans          │  │  v_drawdown_analysis    │  │
│  │  langgraph_checkpoints  │  │                         │  │
│  │  log_entries            │  │  (物化视图 + 索引)       │  │
│  │                         │  │  • BRIN 索引 (时间范围)  │  │
│  │  主键索引 + 外键约束     │  │  • GIN 索引 (JSONB)     │  │
│  │  • trace_id 唯一        │  │  • 分区表 (按日期)       │  │
│  │  • symbol + date 联合   │  │                         │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                             │
│  连接层: fdt_pg/ (asyncpg + sqlalchemy)                    │
│  迁移: scripts/migrate_duckdb_to_pg.py                     │
│  备份: pg_dump + WAL 归档                                  │
└─────────────────────────────────────────────────────────────┘
```

## 4. Agent 拓扑

### 4.1 当前拓扑（文件传递模式）

```
                    ┌─────────────┐
                    │  明鉴秋     │ ← 团队主管 (调度+汇总)
                    │  team-lead  │
                    └──────┬──────┘
                           │ spawn + 文件传递
          ┌────────────────┼────────────────┐
          ▼                │                ▼
   ┌──────────────┐       │       ┌──────────────┐
   │ 数技源       │       │       │ 闫判官       │
   │ datatech     │       │       │ judge        │
   │ (P1 多策略扫描)│      │       │ (P2 方向+调度)│
   │ tf+mr+插件    │       │       │ (P5 裁决链)   │
   └──────┬───────┘       │       └──────┬───────┘
          │               │               │ 定方向 + 调度决策
          ▼               │               ▼
   [信号检查闸门]         │       ┌──────────────────────────┐
          │               │       │     P3 并行数据源         │
          └───────┬───────┘       │                           │
                  │               │  ┌─────────┬──────────┐   │
                  │               │  ▼         ▼          ▼   │
                  │               │ │链证源   │ 观澜     │探源│
                  │               │ │产业链   │ 技术面   │基本面│
                  │               │ └─────────┴──────────┘   │
                  │               │       ← 平行关系，无先后  │
                  │               │            │              │
                  │               └────────────┼──────────────┘
                  │                            ▼
                  │                  ┌─────────────────────┐
                  │                  │ 证真 ⇄ 慎思         │ ← P4 (并行)
                  │                  │ affirmative/opposition│
                  │                  └──────────┬──────────┘
                  │                             │
                  │                  ┌──────────▼──────────┐
                  │                  │  P5 裁决链 (串行)     │
                  │                  │  闫判官(含交易参数)   │
                  │                  │        → 风控明      │
                  │                  │                  │
                  │                  └──────────┬──────────┘
                  └─────────────────────────────┘
```

> **当前模式关键特征**:
> - P1: 可插拔多策略并行扫描（trend_following + mean_reversion + 自定义插件）
> - P2: 闫判官兼具方向决策和数据源调度权
> - P3: 链证源/观澜/探源三源并行，平行关系无先后次序
> - P4: 证真+慎思并行辩论
> - P5: 裁决链串行执行（闫判官含交易参数→风控明）
> - 通信方式: 文件传递 + S04 轮询

### 4.2 LangGraph 拓扑（迁移后 — 并行数据源）

```
                    ┌────────────────────────────────────────────────────┐
                    │              FdtDebateGraph                         │
                    │              (fdt_langgraph/graph.py)               │
                    │                                                    │
                    │  ┌─────────────────────────────────────────────┐   │
                    │  │  Nodes (节点函数)                              │   │
                    │  │                                               │   │
                    │  │  [scan] 数技源 ──→ state["scan_results"]      │   │
                    │  │       │                                       │   │
                    │  │       ▼                                       │   │
                    │  │  [judge_direction] 闫判官                      │   │
                    │  │  选品种 + 定方向 + 调度决策                     │   │
                    │  │       │                                       │   │
                    │  │       ▼                                       │   │
                    │  │  [prepare_data] 数据准备                       │   │
                    │  │       │                                       │   │
                    │  │       ▼ (按需并行调度)                         │   │
                    │  │  ┌─────────┬──────────┬──────────┐           │   │
                    │  │  ▼         ▼          ▼          ▼           │   │
                    │  │ [链证源]  [观澜]     [探源]                  │   │
                    │  │ 产业链   技术面     基本面                    │   │
                    │  │ (按需)   (按需)     (按需)                    │   │
                    │  │       │         │              │              │   │
                    │  │       └─────────┴──────────────┘              │   │
                    │  │                 │                              │   │
                    │  │                 ▼                              │   │
                    │  │  [merge_research] ──→ 合并各源分析结果        │   │
                    │  │                 │                              │   │
                    │  │                 ▼                              │   │
                    │  │  [debate] 证真+慎思 ──→ 多空论据               │   │
                    │  │                 │                              │   │
                    │  │                 ▼                              │   │
                    │  │  [verdict] 闫判官 ──→ 裁决+方案+风控            │   │
                    │  │                 │                              │   │
                    │  │                 ▼                              │   │
                    │  │  [report] 明鉴秋 ──→ HTML辩论报告+signal_output │   │
                    │  │  [signal_output] 明鉴秋 ──→ CTP信号扫描报告      │   │
                    │  │                                               │   │
                    │  └─────────────────────────────────────────────┘   │
                    │                                                    │
                    │  ┌─────────────────────────────────────────────┐   │
                    │  │  Edges (边)                                    │   │
                    │  │                                               │   │
                    │  │  scan ──→ judge_direction (闫判官调度决策)    │   │
                    │  │              │                                │   │
                    │  │              ▼                                │   │
                    │  │  prepare_data (数据准备)                      │   │
                    │  │              │                                │   │
                    │  │              ▼ (按需并行调度三源)              │   │
                    │  │  ParallelMap(链证源,观澜,探源)                │   │
                    │  │              │                                │   │
                    │  │              ▼                                │   │
                    │  │  merge_research ──→ debate                    │   │
                    │  │              │                                │   │
                    │  │              ▼                                │   │
                    │  │  verdict ──→ report ──→ END                   │   │
                    │  │                                               │   │
                    │  │  条件边: fast模式  → 跳过debate直达verdict    │   │
                    │  │        deep模式  → debate循环(分歧>0.7)       │   │
                    │  │        tournament → 多轮辩论+投票             │   │
                    │  │        direct_debate → 跳过P1扫描,从fdt_cache/加载数据 │   │
                    │  └─────────────────────────────────────────────┘   │
                    │                                                    │
                    │  ┌─────────────────────────────────────────────┐   │
                    │  │  Checkpointer (PostgreSQL)                     │   │
                    │  │  • pg.langgraph_checkpoints (状态历史)         │   │
                    │  │  • pg.debate_verdicts (裁决记录)               │   │
                    │  └─────────────────────────────────────────────┘   │
                    └────────────────────────────────────────────────────┘
```

### 4.3 Agent 到图节点映射（按需并行数据源拓扑）

| Agent | 节点函数 | 角色 | 并行执行 | 阶段 | 调度权 |
|:------|:---------|:-----|:---------|:-----|:-------|
| 数技源 | `node_scan` | 信号扫描 | 否 | P1 | 无 |
| 闫判官 | `node_judge_direction` | 选品种+定方向+**调度决策** | 否 | P2 | **有** |
| 数据准备 | `node_prepare_data` | 数据准备（解析K线/计算指标） | 否 | P2→P3 | 无 |
| 链证源 | `node_chain` | 产业链分析（按需） | **是**（与观澜、探源并行） | P3 | 无 |
| 观澜 | `node_technical` | 技术面分析（按需） | **是**（与链证源、探源并行） | P3 | 无 |
| 探源 | `node_fundamental` | 基本面分析（按需） | **是**（与链证源、观澜并行） | P3 | 无 |
| 证真/多头分析员(v1) | `node_bullish_v1` | 多头立论（正方 v1） | 否（串行交叉质询） | P4 步1 | 无 |
| 慎思/空头分析员(v1) | `node_bearish_v1` | 空头质疑（反方 v1） | 否（串行交叉质询） | P4 步2 | 无 |
| 证真/多头分析员(v2) | `node_bullish_rebuttal` | 多头反驳（正方 v2 rebuttal） | 否（串行交叉质询） | P4 步3 | 无 |
| 闫判官 | `node_verdict` | 裁决(含交易参数) | 否 | P5 | 有 |
| 风控明 | `node_risk_check` | 风控审核(v8.7.0 直接基于 verdict) | 否 | P5 | 无 |
| 明鉴秋(报告) | `node_report` | 报告生成 | 否 | P6 | 有 |
| 明鉴秋(CTP) | `node_signal_output` | CTP信号输出(v8.7.0 新增) | 否 | P6a | 有 |

#### 运行模式说明

FDT 支持两种执行模式，通过环境变量控制：

| 模式 | 环境变量 | 流程 | 适用场景 |
|:-----|:---------|:-----|:---------|
| **全量分析模式** (默认) | 无需设置 | scan → judge_direction → prepare_data → 三源并行 → merge → debate → verdict → report | 常规每日全品种扫描分析 |
| **指定品种辩论模式** | `FDT_DIRECT_DEBATE=true` + `FDT_DEBATE_SYMBOLS=SF,SM,SC` | 跳过 P1 scan 节点；从 `fdt_cache/` 直接加载指定品种的缓存K线/基本面/基差数据；进入闫判官方向判定 → P3 三源并行 → P4 辩论 → P5 裁决 → P6 报告 | 快速对已知品种启动辩论，不依赖实时扫描信号 |

#### 按需并行数据源设计说明

**核心流程**：数技源输出信号 → 闫判官调度决策 → 按需并行触发三源 → 合并分析 → 辩论 → 裁决 → 策略 → 风控

```
变更前（串行）:
  scan → chain_analysis → judge_direction → research(观澜+探源并行)
    │         P1.5            P2                P3
    │
    └─→ 数技源产出后等待链证源完成，再等待闫判官方向，最后才触发研究

变更后（按需并行）:
  scan ──→ judge_direction (闫判官)
    │              │
    │              ▼ 调度决策：需要哪些源？
    │       [prepare_data] 数据准备
    │              │
    │       ┌──────┴──────┬─────────────┐
    │       ▼             ▼             ▼
    │   [链证源]      [观澜]       [探源]      ← 按需并行（仅调度需要的源）
    │   产业链       技术面        基本面
    │       │         │             │
    │       └─────────┴─────────────┘
    │                     │
    │                     ▼
    │              merge_research
    │                     │
    │                     ▼
    └──────────────→ debate → verdict → plan → risk → report

收益:
  • 总耗时: scan + judge + max(所需源) + debate + verdict...
  • 各源独立失败不影响其他源（L2 降级）
  • 闫判官根据信号特征智能调度（如趋势信号侧重观澜、周期品种侧重链证源）
  • 便于后续扩展新数据源（如宏观源、舆情源）
```

## 5. 与现有文档的关系

| 现有文档 | 关注点 | 与 Harness 文档的关系 |
|:---------|:-------|:---------------------|
| `README.md` | 功能特性 + 版本历史 + CLI | Harness 文档从工程视角补充"怎么跑起来的" |
| `docs/agent-protocol.md` | Agent 通信契约 | Harness 文档引用其 schema 定义，补充生命周期视角 |
| `docs/business_flow.md` | 业务流程 SOP | Harness 文档关注技术执行层，不重复业务逻辑 |
| `rules/futures-debate-team_rules.md` | 全局规则 | Harness 文档将规则映射到具体的工程实现 |
