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
│   · fdt_cache(SQLite增量缓存) · dominant_resolver(主力合约映射持久化)   │
│   · _datacore_bridge(Data-Core F10 桥接器) · debate_archiver · fdt_pg(连接层) │
│   · 独立CLI/FastAPI入口                                              │
```

### 各层职责

| 层 | 职责 | 核心组件 |
|:--|:-----|:---------|
| **L1 基础设施** | 持久化(PG混合存储)、日志、并发安全写入、独立入口、本地SQLite增量缓存(按品种+数据类型持久化K线/基本面/基差)、主力合约映射解析与换月事件追踪、Data-Core F10 桥接(统一F10数据入口，自动降级到原有采集器)、MCP 数据接入层(标准MCP协议客户端，支持金十等外部MCP服务) | `fdt_pg/` (连接层+OLAP视图), `memory/` (27文件), `fdt_cache/` (SQLite增量缓存), `dominant_resolver` (主力合约映射持久化), `_datacore_bridge` (Data-Core F10 桥接器), `mcp_client` (MCP协议通用客户端), `jin10_mcp` (金十数据MCP采集器), `unified_logger.py`, `memory_writer.py`, `debate_archiver.py`, `fdt_cli.py`, `fdt_api.py` |
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
| `coordinator.py` | `fdt_langgraph/graph.py` | ✅ **G93 — 已迁移**（已删除，由 `build_debate_graph_with_profile()` 替代） |
| `pipeline/runner.py` | `fdt_langgraph/graph.py` | ✅ 已迁移（A/B 切换完成） |
| `debate_protocol_v2.py` | `fdt_langgraph/nodes.py` | ✅ **G94 — 已迁移**（已删除，常量内联到 `nodes.py`） |
| `agent_runner.py` | `fdt_langgraph/agents.py` | ✅ **G95 — 已迁移**（已删除，由 `DebateAgentExecutor.run_single()` 替代） |
| S04 轮询 | Checkpointer + 状态传递 | 已替代 |
| 文件传递 | DebateState 内存传递 | 已替代 |
| WorkBuddy automation | `fdt_cli.py` / `fdt_api.py` 独立入口 | 已替代 |
| DuckDB (`futures.db`) | PostgreSQL (`fdt_pg/` 连接层) | ✅ **G96 — 已迁移**（JSON→PostgreSQL 写入逻辑已实现） |

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
                    │  │ • [scan:数技源]               │  │
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
                    │  │ [chain:链证源] [technical:观澜]   [fundamental:探源]    │  │  │ ← 并行数据源
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
[P2.5] FDC 数据预采集 + 金十快讯精选
    │  · 输入: selected_symbols
    │  · 处理: _build_jin10_context() 按品种中文关键词搜索金十快讯，去重后格式化
    │  · 输出: 格式化文本注入 node_fundamental 的 context 的 【金十精选快讯】 区块
    │  · 数据流: 金十MCP服务 → data_source_adapter.jin10_search_flash → _build_jin10_context → node_fundamental context
    │  · 消费方: 基本面研究员（探源）作为分析素材引用，非背景噪声
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
    ├─ [scan:数技源] ──→ state["scan_results"]
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
    │  │ [chain:链证源]   [technical:观澜]     [fundamental:探源]     │  │ ← 仅调度需要的源
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

### 3.4 Hook 链架构规范（v9.6.4+）

> **设计目标**: 通过 Hook 机制实现横切关注点的解耦，支持 pre-action/post-action/safety 三个层次的扩展

#### 3.4.1 Hook 接口定义

| Hook 类型 | 执行时机 | 接口签名 | 返回值 | 典型用途 |
|:----------|:---------|:---------|:-------|:---------|
| `pre_hook` | 节点执行前 | `async def pre_hook(state: DebateState) -> DebateState` | 修改后的状态 | 参数校验、权限检查、日志记录 |
| `post_hook` | 节点执行后 | `async def post_hook(state: DebateState, result: Any) -> DebateState` | 修改后的状态 | 结果校验、数据转换、指标收集 |
| `safety_hook` | 异常发生时 | `async def safety_hook(state: DebateState, error: Exception) -> DebateState` | 恢复后的状态 | 异常处理、降级策略、告警通知 |

#### 3.4.2 Hook 链执行顺序

```
用户请求
    │
    ▼
┌─────────────────────────────────────────────────────┐
│              Hook 链执行流程                          │
│                                                     │
│  ┌─────────────┐    ┌─────────────┐                 │
│  │ pre_hook_1  │───→│ pre_hook_2  │───→ ...        │
│  │ (权限检查)   │    │ (参数校验)   │                 │
│  └─────────────┘    └─────────────┘                 │
│         │                                           │
│         ▼                                           │
│  ┌─────────────────────────────┐                    │
│  │      Node 执行 (业务逻辑)     │                    │
│  └─────────────────────────────┘                    │
│         │                                           │
│         ▼                                           │
│  ┌─────────────┐    ┌─────────────┐                 │
│  │ post_hook_1 │───→│ post_hook_2 │───→ ...        │
│  │ (结果校验)   │    │ (指标收集)   │                 │
│  └─────────────┘    └─────────────┘                 │
│                                                     │
│  异常路径:                                          │
│  Node 执行 → Exception → safety_hook_1 → ...        │
│                                    │                 │
│                                    ▼                 │
│                             恢复/降级/告警            │
└─────────────────────────────────────────────────────┘
```

#### 3.4.3 Hook 注册机制

```python
# fdt_langgraph/hooks.py 核心接口
class HookManager:
    def register_pre_hook(self, node_name: str, hook: Callable) -> None: ...
    def register_post_hook(self, node_name: str, hook: Callable) -> None: ...
    def register_safety_hook(self, node_name: str, hook: Callable) -> None: ...
    def execute_pre_hooks(self, node_name: str, state: DebateState) -> DebateState: ...
    def execute_post_hooks(self, node_name: str, state: DebateState, result: Any) -> DebateState: ...
    def execute_safety_hooks(self, node_name: str, state: DebateState, error: Exception) -> DebateState: ...
```

#### 3.4.4 内置 Hook 清单

| Hook 名称 | 类型 | 目标节点 | 功能描述 |
|:----------|:-----|:---------|:---------|
| `validate_input` | pre | 所有节点 | 校验状态输入合法性 |
| `log_entry` | pre | 所有节点 | 记录节点执行开始日志 |
| `log_exit` | post | 所有节点 | 记录节点执行完成日志 |
| `record_duration` | post | 所有节点 | 记录节点执行耗时 |
| `validate_output` | post | verdict | 校验裁决输出格式 |
| `rate_limit` | safety | 所有节点 | 触发速率限制时降级 |
| `alert_on_error` | safety | 所有节点 | 异常时发送告警 |

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


### P1角色矫正（v9.6.8）

P1 数技源从"策略评分器"回归"数据统计器"角色：
- **新增产出物**：`all_ranked[].stats` 对象（纯定量统计特征：MA/ATR/RSI/ADX/量能比/通道位置/20日区间位置）
- **保留字段**：`total`/`direction`/`grade` 保留但降级为内部参考，不再作为P1的"判断产出"
- **P1.5 闸门变更**：`select_triggers()` 从基于 grade+total 的方向性过滤改为数据质量闸门（stats完整性+K线数量+流动性）
- **P2 闫判官变更**：消费 stats 而非 total/direction，新增 audit 字段记录与P1信号的偏离度
- **P3 观澜变更**：从 state 读取 stats 注入技术分析上下文
- **不变**：指定品种辩论模式、策略引擎 pipeline.py、验证器、P4辩论prompt、P5裁决prompt

### 4.2 LangGraph 拓扑（迁移后 — 并行数据源）

```
                    ┌────────────────────────────────────────────────────┐
                    │              FdtDebateGraph                         │
                    │              (fdt_langgraph/graph.py)               │
                    │                                                    │
                    │  ┌─────────────────────────────────────────────┐   │
                    │  │  Nodes (节点函数)                              │   │
                    │  │                                               │   │
                    │  │  [scan:数技源] ──→ state["scan_results"]      │   │
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
                    │  │ [chain:链证源]  [technical:观澜]     [fundamental:探源]                  │   │
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
    │   [chain:链证源]      [technical:观澜]       [fundamental:探源]      ← 按需并行（仅调度需要的源）
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

## 5. Loop Engineering 视角

### 5.1 双层循环结构

FDT 的 Harness 架构天然支持 Inner Loop（内循环）和 Outer Loop（外循环）双层结构：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Outer Loop（外循环）                           │
│  跨会话的经验积累与 Harness 进化                                 │
│                                                                 │
│  T+1验证 → 权重校准 → Agent进化 → ML训练 → 注入下一轮             │
│  (validate_verdicts.py → calibrate_weights.py → evolve_agents.py │
│   → ml/trainer.py → agent_profiles.json → 下轮辩论加载)          │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Inner Loop（内循环）                           │
│  单次辩论内的 Run-Until-Done + 六阶段攻防                         │
│                                                                 │
│  P1扫描 → P2调度 → P3并行研究 → P4六阶段攻防 → P5裁决链 → P6输出  │
│  （含 D06 降级、分歧度控制、攻防反驳等内循环优化）                │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 FDT 的 Harness 六维控制空间

对应 MemoHarness 六维 Harness 空间，FDT 的实现如下：

| 维度 | FDT 对应实现 | 成熟度 |
|------|-------------|:------:|
| **D1 Context（上下文组装）** | `AGENTS.md` + `memory/knowledge/` + 品种知识库 + Skill 渐进式披露 | ★★★★★ |
| **D2 Tool（工具交互）** | `fdt_langgraph/tools/registry.py` 工具注册中心(版本管理+调用统计) + `docs/schemas/tool_capability.json` 能力描述Schema + `scripts/tool_metrics.py` 效能追踪(异常检测) + `scripts/tool_circuit_breaker.py` 熔断降级(状态机+滑动窗口) | ★★★★★ |
| **D3 Generation（解码控制）** | `config/agents/decode_config.yaml` 逐Agent精细配置 + `scripts/enforce_structured_output.py` Pydantic+JSON Schema双校验 + `scripts/content_filter.py` 内容安全过滤 + `scripts/generation_metrics.py` 质量监控 | ★★★★★ |
| **D4 Orchestration（工作流拓扑）** | LangGraph 图编排 + 按需并行 + 条件路由 + 多模式（default/fast/deep/tournament） | ★★★★★ |
| **D5 Memory（跨调用状态持久化）** | PostgreSQL OLTP+OLAP + `scripts/vector_memory.py` 三层记忆 + `scripts/build_knowledge_graph.py` 知识图谱+ `scripts/memory_retriever.py` 召回策略(含强制负样本) + `scripts/memory_cleaner.py` 过期清理 | ★★★★★ |
| **D6 Output（输出处理）** | `scripts/output_metrics.py` 质量度量(4维评分) + `scripts/output_versioning.py` 版本化管理(哈希+时间戳) + `scripts/output_feedback.py` 反馈闭环(准确率追踪+改进建议) + `scripts/output_audit.py` 审计日志(溯源+合规差距) | ★★★★★ |

### 5.3 循环契约（Loop Contract）

FDT 的每个自动化循环都有明确的六维度契约（TRIGGER / SCOPE / ACTION / BUDGET / STOP / REPORT），详见 [loop-contracts/](loop-contracts/README.md)。

**已定义的循环契约**：

| 循环 ID | 名称 | 验证档位 | 权限 | 契约 |
|---------|------|----------|------|------|
| `daily-debate` | 每日自动辩论 | L3 (independent_agent) | Write | [daily-debate.contract.yaml](loop-contracts/daily-debate.contract.yaml) |

### 5.4 验证档位体系

| 档位 | FDT 实现 | 对应循环 |
|------|----------|----------|
| **L1 (self)** | Agent 自检 + JSON Schema 校验 + 4 铁律 | 报告型循环、数据采集 |
| **L2 (test_suite)** | pytest 测试套件 + 契约校验 + 门禁审计 | 自进化循环、ML 训练 |
| **L3 (independent_agent)** | 闫判官裁决 + 风控明独立审核（Maker-Checker 分离） | 每日辩论循环（生产级） |

> **核心规律**：Loop 的质量完全取决于它所连接的可验证信号的质量。FDT 之所以能达到 L3 验证档位，核心在于闫判官+风控明的 Maker-Checker 分离架构，以及 CTP 信号输出前的多道风控门控。

### 5.5 Hook 链架构规范

Hook 链是 FDT 护栏层的中间件架构，分类与接口：

| Hook 类型 | 阶段 | 作用 | FDT 实现 |
|-----------|------|------|----------|
| **pre-action** | Agent 执行前 | 越权检查、denylist、权限验证 | `validate_agent_output.py` + 信号门禁 |
| **post-action** | Agent 执行后 | 完整性校验、Schema 验证、4 铁律核验 | `validate_final_signals.py` |
| **safety** | 输出前 | 风险门控、CTP 信号拦截 | 风控明 + 风控颜色信号 |

**Hook 接口定义**：
```python
@dataclass
class HookContext:
    trace_id: str
    agent_name: str
    action: str
    input_data: dict
    output_data: dict | None
    errors: list[str]

class HarnessHook(ABC):
    @abstractmethod
    def pre_action(self, ctx: HookContext) -> HookContext: ...
    @abstractmethod
    def post_action(self, ctx: HookContext) -> HookContext: ...
```


## 6. 解码控制层架构（D3 Generation ★★★★★）

### 6.1 设计目标

解码控制层负责对每个 Agent 的 LLM 生成过程进行精细控制，确保：
1. **输出一致性** — 所有 Agent 输出严格遵循预定义的 JSON Schema
2. **质量可度量** — 每个 Agent 的生成质量可量化、可追踪
3. **安全合规** — 输出内容经过安全过滤，无敏感/违规内容
4. **差异化策略** — 不同角色（裁决/分析/研究）采用不同的解码策略

### 6.2 四层控制架构

```
                    ┌─────────────────────────────────────┐
                    │        Generation Metrics           │ ← L4 质量监控
                    │  · 格式正确率 · Schema合规率         │
                    │  · 生成延迟 · 重试次数               │
                    └──────────────┬──────────────────────┘
                                   │ 反馈
                    ┌──────────────▼──────────────────────┐
                    │        Content Filter               │ ← L3 内容安全
                    │  · 敏感词过滤 · 合规审查             │
                    │  · 输出脱敏 · 金融合规               │
                    └──────────────┬──────────────────────┘
                                   │ 校验
                    ┌──────────────▼──────────────────────┐
                    │    Enforce Structured Output        │ ← L2 结构化约束
                    │  · Pydantic模型校验                  │
                    │  · JSON Schema双校验                 │
                    │  · 自动重试（最多3次）               │
                    └──────────────┬──────────────────────┘
                                   │ 配置
                    ┌──────────────▼──────────────────────┐
                    │      Decode Config (逐Agent)        │ ← L1 解码配置
                    │  · model · temperature · top_p       │
                    │  · max_tokens · stop_sequences      │
                    │  · frequency_penalty · presence     │
                    └─────────────────────────────────────┘
```

### 6.3 逐Agent解码配置策略

| Agent | 角色 | 模型 | Temp | Top P | Max Tokens | 策略说明 |
|:------|:-----|:-----|:----:|:-----:|:----------:|:---------|
| 闫判官 | 裁决 | deepseek-v4-flash | 0.2 | 0.9 | 4000 | 低温度确保裁决一致性 |
| 闫判官副手 | 辅助裁决 | deepseek-v4-flash | 0.3 | 0.9 | 3000 | 低温度确保准确提取 |
| 一致性裁判 | 审计 | deepseek-v4-flash | 0.2 | 0.9 | 2000 | 最低温度确保审计一致性 |
| 多头分析员 | 立论 | deepseek-v4-flash | 0.4 | 0.95 | 3000 | 中等温度允许创造性发现 |
| 空头分析员 | 反驳 | deepseek-v4-flash | 0.4 | 0.95 | 3000 | 中等温度允许创造性发现 |
| 链证源 | 产业链 | deepseek-v4-flash | 0.3 | 0.9 | 2500 | 较低温度确保事实准确 |
| 观澜 | 技术面 | deepseek-v4-flash | 0.3 | 0.9 | 2500 | 较低温度确保指标准确 |
| 探源 | 基本面 | deepseek-v4-flash | 0.3 | 0.9 | 2500 | 较低温度确保数据准确 |
| 风控明 | 风控 | deepseek-v4-flash | 0.2 | 0.9 | 2000 | 低温度确保风控一致性 |
| 明鉴秋 | 主管 | deepseek-v4-flash | 0.35 | 0.95 | 4000 | 中等偏低温度确保汇总质量 |

### 6.4 结构化输出强制约束流程

```
Agent LLM 输出
    │
    ▼
┌──────────────────────┐
│ 1. JSON解析          │ ← 失败 → 重试（最多3次，温度×1.5）
└──────┬───────────────┘
       ▼
┌──────────────────────┐
│ 2. Pydantic模型校验   │ ← 失败 → 自动修复+重校验
└──────┬───────────────┘
       ▼
┌──────────────────────┐
│ 3. JSON Schema校验    │ ← 失败 → 记录异常+继续（非阻断）
└──────┬───────────────┘
       ▼
┌──────────────────────┐
│ 4. 内容安全过滤       │ ← 命中 → 脱敏/替换
└──────┬───────────────┘
       ▼
┌──────────────────────┐
│ 5. 质量指标记录       │ → generation_metrics
└──────────────────────┘
```

### 6.5 与现有文档的关系

| 现有文档 | 关注点 | 与 Harness 文档的关系 |
|:---------|:-------|:---------------------|
| `README.md` | 功能特性 + 版本历史 + CLI | Harness 文档从工程视角补充"怎么跑起来的" |
| `docs/agent-protocol.md` | Agent 通信契约 | Harness 文档引用其 schema 定义，补充生命周期视角 |
| `docs/business_flow.md` | 业务流程 SOP | Harness 文档关注技术执行层，不重复业务逻辑 |
| `rules/futures-debate-team_rules.md` | 全局规则 | Harness 文档将规则映射到具体的工程实现 |
| `docs/harness/loop-contracts/` | 循环契约规范 | 本文档的延伸，定义每个自动化循环的六维度契约 |


### 经验库架构（v9.8.0）

经验库采用双层结构：
- **Et 层（案例级记录）**：memory/experience/records/ — 每轮辩论自动写入 ExecutionRecord
- **Gt 层（全局模式）**：memory/experience/patterns/ — 从 Et 中蒸馏的 DistilledPattern
- **适配日志**：memory/experience/adaptation_log/ — 案例适配决策记录

数据流：daily-debate (post_loop) → Et → self-evolve (pipeline) → Gt → daily-debate (pre_loop) → W(x_j)


## 7. 未来扩展：新闻情绪分析因子

### 7.1 定位

新闻情绪分析师作为与**链证源（产业链）**、**观澜（技术面）**、**探源（基本面）** 平级的**第四分析因子**，在 P3 阶段并行运行，输出结构化新闻情绪状态向量。

### 7.2 架构示意

```
                        ┌──── 金十 MCP（原始快讯）────┐
                        │                            │
                        ▼                            ▼
               【精选注入探源】              【情绪分析通道】
               (Phase 1 已落地)              (Phase 2 规划中)
                        │                            │
                        ▼                            ▼
     P3: ┌──────┬──────┬──────┬──────┐
          │链证源 │ 观澜 │ 探源 │ 情绪 │  ← 四源并行
          └──┬───┴──┬───┴──┬───┴──┬───┘
             │      │      │      │
             ▼      ▼      ▼      ▼
          [chain] [technical] [fundamental] [sentiment]
             │      │      │      │
             └──────┴──┬───┴──────┘
                       ▼
                 P4-P6 辩手引用
                       ▼
                 P7 闫判官裁决
                 （四维加权评分）
```

### 7.3 输入源

- **金十 MCP 快讯**（`search_flash` / `list_flash`）— 事件驱动型实时快讯，主源
- **金十 MCP 资讯**（`search_news` / `get_news`）— 深度分析文章
- **WebSearch / WebFetch** — 情绪 Agent 自主采集补充（行业网站、新闻门户、政策原文等），用于交叉验证和深度事件分析
- **数据加工流程**：

```
金十 MCP（快讯+资讯）
        │
        ├──→ 按品种去重/分类/时效加权
        │
WebSearch（自主补充）
        │
        └──→ 来源标记 [sentiment:jin10] / [sentiment:web]
                │
                ▼
        情绪 Agent 加工标注
                │
                ▼
        SentimentStateVector（结构化输出）
```

### 7.4 预期输出契约（NewsSentimentVector）

```python
@dataclass
class NewsSentimentVector:
    symbol: str                    # 品种代码
    overall_sentiment: float       # -1.0 ~ 1.0（负→正）
    sentiment_breakdown: dict      # 按事件类型分类情绪（政策/供需/宏观/地缘）
    hot_volume: int                # 相关快讯数量（热度）
    trending_topics: list[str]     # 高频关键词
    key_events: list[dict]         # 关键事件列表
    source: str = "sentiment"      # 固定标签 [sentiment]
    confidence: float = 0.0        # 置信度
```

### 7.5 数据流说明

- **金十原始快讯**同时流入两条通道，互不干扰：
  - **精选通道**（Phase 1）：精选 → 探源 context → 分析师定性参考
  - **情绪通道**（Phase 2）：全量 → 情绪 Agent 加工 → 结构化情绪向量 → 独立因子
- 探源和情绪 Agent 可引用**同一批金十数据**的不同侧面
- 闫判官裁决时，`[sentiment]` 作为独立维度参与综合评分
