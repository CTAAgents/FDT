# FDT Code Wiki — 期货辩论专家团技术百科全书

> **项目版本**: v9.19.0 | **文档版本**: v9.19.0 | **最后更新**: 2026-07-23 | **定位**: 理解项目的技术基础文档

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 整体架构](#2-整体架构)
- [3. 核心模块详解](#3-核心模块详解)
- [4. 关键类与函数](#4-关键类与函数)
- [5. 数据流与依赖关系](#5-数据流与依赖关系)
- [6. 运行方式与配置](#6-运行方式与配置)
- [7. 测试体系](#7-测试体系)
- [8. 开发规范](#8-开发规范)
- [9. 附录](#9-附录)

---

## 1. 项目概述

### 1.1 项目定位

**FDT (Futures Debate Team)** 是一套基于 **LangGraph** 构建的 **13-Agent 多角色交叉质询的 CTA 决策系统**（11 核心 + 2 辅助评估 Agent）。通过多 Agent 辩论制衡机制，实现期货市场的智能分析与交易信号生成。

### 1.2 核心特性

| 特性 | 说明 |
|:-----|:------|
| 13-Agent 辩论制衡 | 数技源/闫判官/链证源/观澜/探源/读心/多头分析员/空头分析员/风控明/明鉴秋/品藻 + 副裁官/独立裁官 |
| 六阶段攻防辩论 | 多头立论→空头立论→空头驳论→多头反驳→空头结辩→多头结辩，辩手只做方向论证不自行搜索 |
| 逐品种循环处理 | v9.13.0 新增，每个品种独立循环执行 P3→P4→P5→质检→存储，全部完成汇聚 |
| 辩论输出质量治理 | v9.14.0 新增，不合格输出退回重修（最多 2 次），含 Schema 校验 |
| 四源并行 LLM 推理 | 技术面/基本面/产业链/新闻情绪并行分析，任一源超时(300s)跳过其余继续 |
| NO_FUSION 零融合 | 通道突破(trend_following)含 10 子信号独立产出不融合 |
| 自进化闭环 | LangGraph Evolution Graph 驱动：APM 退化→self_improve 提案，样本≥5→校准权重，样本≥5→Agent 进化，样本≥50→ML 增量训练 |
| 高置信入口门禁 | grade∈{STRONG,WATCH} 或 \|total\|≥40 进入辩论候选池 |
| P0-4 假突破拦截 | 六种验证器 + 全局 data_quality/crowding |
| Master Orchestrator | LangGraph 统一编排 14 个自动化任务，纯 Python datetime 调度，零第三方依赖 |
| 逐 Agent LLM 配置 | 支持按角色独立配置 API Key/BaseURL/Model + D3 Generation 解码控制 |
| 5 层鲁棒防线 (L1-L5) | 产出校验→熔断降级→信号门禁→路径发现→健康自检 |

### 1.3 当前版本

**v9.19.0** — Master Orchestrator Graph 稳定运行：全量自动化迁移至 LangGraph，统一编排辩论/进化/数据采集/APM/发布/自优化，纯 Python datetime 调度，零第三方依赖。`fdt_cli.py daemon` 模式替换 APScheduler 为 LangGraph 守护进程。

---

## 2. 整体架构

### 2.1 系统分层

```
┌──────────────────────────────────────────────────────────────┐
│                     应用层 (Application)                      │
│  fdt_cli.py | fdt_api.py | fdt_daily_runner.py              │
│  CLI / FastAPI / 每日自动运行                                 │
├──────────────────────────────────────────────────────────────┤
│                     编排层 (Orchestration)                    │
│  fdt_langgraph/ (3 个 LangGraph 子图)                        │
│    ├── graph.py           — 辩论图结构 + 逐品种循环           │
│    ├── master_graph.py    — Master Orchestrator 图 (14 任务)  │
│    ├── evolution_graph.py — 自进化图 (APM-CS 五轴驱动)        │
│    ├── nodes.py           — 辩论节点函数                      │
│    ├── master_nodes.py    — Master 节点函数                   │
│    ├── evolution_nodes.py — 进化节点函数                      │
│    ├── state.py           — DebateState 定义                  │
│    ├── master_state.py    — Master 状态定义 + 调度注册表       │
│    ├── evolution_state.py — EvolutionState 定义 + 阈值常量    │
│    ├── agents.py          — Agent 执行器 + D3 Decode Control  │
│    ├── health.py          — 健康检查器                        │
│    ├── llm_provider.py    — 独立 LLM 客户端                   │
│    ├── quality_inspector.py — 辩论输出质检器                  │
│    ├── single_symbol_report.py — 单品种报告生成器             │
│    ├── web_crawl_tool.py  — Web + 金十 MCP LangChain 工具     │
│    └── tools/registry.py  — 工具注册中心                      │
├──────────────────────────────────────────────────────────────┤
│                     适配层 (Adapter)                          │
│  data_source_adapter.py — FDC ↔ Data-Core 统一接口           │
│  支持 fdc/datacore 两种数据源动态切换                         │
├──────────────────────────────────────────────────────────────┤
│                     数据层 (Data)                             │
│  futures_data_core/ — 期货数据核心引擎                        │
│    ├── core/         — 多源降级链、缓存、熔断器、主力合约解析   │
│    │   ├── multi_source_adapter.py — 5 级采集器自动降级       │
│    │   ├── dominant_resolver.py   — 主力合约解析与换月追踪    │
│    │   ├── circuit_breaker.py     — A1 级熔断器状态机        │
│    │   ├── cache_store.py         — 多级缓存 (PG/Redis/Mem)  │
│    │   ├── field_normalizer.py    — 字段标准化               │
│    │   ├── data_quality.py        — 数据质量评估             │
│    │   └── types.py               — 归一化数据载体           │
│    ├── collectors/   — 5 级采集器 (DataCore/TDX/QMT/TqSDK/Web)│
│    ├── f10/          — F10 数据 (基差/期限结构/仓单/持仓/金十)│
│    ├── indicators/   — 技术指标计算 (numpy 纯函数)           │
│    └── mcp_client.py — 标准 MCP 协议 HTTP 客户端              │
├──────────────────────────────────────────────────────────────┤
│                     契约层 (Contracts)                        │
│  contracts/ — 统一数据信封、辩论 Schema、质检 Schema          │
│    ├── a2a_payload.py          — A2A 数据信封                │
│    ├── debate_argument_schema.py — 辩论论点 Schema (v1.1)    │
│    ├── debate_quality_schema.py — 质检 Schema (v9.14.0)      │
│    ├── experience_schema.py    — 经验 Schema                 │
│    └── migrations.py           — 数据库迁移                  │
├──────────────────────────────────────────────────────────────┤
│                     存储层 (Storage)                          │
│  fdt_pg/    — PostgreSQL OLTP+OLAP (连接池/ORM/迁移)        │
│  fdt_cache/ — SQLite 本地增量缓存                            │
│  memory/    — 知识库与记忆系统 (50+ 品种/经验/日志/演化)      │
├──────────────────────────────────────────────────────────────┤
│                     基础设施层 (Infrastructure)               │
│  agents/    — 13 个 Agent 定义文档 (.md 角色文件)             │
│  config/    — 配置 (LLM/Agent 配置 + D3 Decode Control)      │
│  scripts/   — 80+ 辅助脚本 (质检/进化/风控/CLI/运维)          │
│  skills/    — 10 个子技能实现 (quant-daily 等)               │
│  schemas/   — 11 个 JSON Schema 契约                         │
│  scheduler/ — 旧版调度器 (保留为兼容层，新开发走 LangGraph)   │
│  docs/      — 文档体系 (Harness 规范/设计/流程图/Schema)     │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 执行流程（逐品种循环模式 v9.13.0）

```
P1: 数技源通道突破(trend_following)扫描 → 全品种信号+stats
  → P2: 闫判官调度（基于 stats 选品种，始终不做方向预判）
                                            ↓
        ┌──────────────── 逐品种循环 ─────────────────┐
        │  prepare_one_symbol (当前品种)              │
        │    ├─→ 链证源 (P3) ─→┐                      │
        │    ├─→ 观澜 (P3)   ─→ merge_research       │
        │    ├─→ 探源 (P3)   ─→↓                     │
        │    └─→ 读心 (P3)   ─→↓                     │
        │                     ↓                      │
        │    merge_research → (fast→verdict, else→辩论)│
        │    → 多头立论 → 空头立论 → 空头反驳         │
        │    → 多头反驳 → 空头结辩 → 多头结辩          │
        │    → 闫判官裁决 → 风控审核                  │
        │    → 质检 (PASS→store, FAIL+<2→重修)        │
        │    → store_per_symbol_result                │
        │    → route_next_symbol                      │
        │       ├─ 还有品种 → prepare_one_symbol      │
        │       └─ 全部完成 → aggregate_results        │
        └──────────────────────────────────────────┘
                                            ↓
                aggregate_results → 报告生成 (P6)
                → CTP 信号输出 → END
```

### 2.3 直接辩论模式（跳过扫描）

当 `FDT_DIRECT_DEBATE=true` 时启用：

```
load_cache → judge_direction → [逐品种循环] → ... → update_cache → END
```

### 2.4 Master Orchestrator 调度体系（v9.18.0+）

FDT 通过三个独立的 LangGraph 子图分别管理不同职责，由 Master Graph 统一编排：

```
┌──────────────────────────────────────────────────────────────────┐
│                     Master Orchestrator Graph                     │
│  check_time → dispatch → task_nodes → dispatch → ... → done     │
│                                                                   │
│  时间触发（工作日/每周/每天）| 数据触发（阈值+冷却期）             │
│  ────────────────────────────|────────────────────────────        │
│  daily_debate        (工作日19:15)  | validate_and_evolve        │
│  update_dominant     (工作日15:30)  | ml_training_check          │
│  auto_publish        (每天23:05)    | self_optimize_analysis     │
│  apm_scorecard       (每周一08:30)  | vibench_baseline           │
│  cluster_failures    (每周一08:00)  | d3_auto_light              │
│  discipline_enforce  (每周一08:45)  | data_collection            │
│  self_optimize_evolve(工作日15:35)  |                             │
│  self_optimize_verify(每周一08:50)  |                             │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 辩论完成后自动触发
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Debate Graph (辩论图)                         │
│  scan → judge → per-symbol-loop → aggregate → report → signal   │
├──────────────────────────────────────────────────────────────────┤
│                     Evolution Graph (自进化图)                    │
│  collect_metrics → apm_eval → decide_actions                     │
│    → [improve → calibrate → evolve → ml_train → ...] → complete │
└──────────────────────────────────────────────────────────────────┘
```

### 2.5 数据降级链

数据源优先级（自动降级）：

| 优先级 | 采集器 | 说明 |
|:------:|:-------|:------|
| 0 | DataCoreCollector | Data-Core 统一数据接口（最高优先级） |
| 1 | TDXCollector | 通达信本地 TQ-Local |
| 2 | WebFallbackCollector | 东方财富+新浪 |
| 3 | QMTCollector | QMT/xtquant |
| 4 | TqSdkCollector | 天勤量化（末位兜底，关闭偶发挂死已由超时保护） |

**熔断机制**: 每个采集器独立熔断器，连续失败 5 次后自动屏蔽，冷却时间 60 秒。
状态机：CLOSED（放行）→ OPEN（屏蔽 60s）→ HALF_OPEN（探测）→ CLOSED/OPEN

---

## 3. 核心模块详解

### 3.1 fdt_langgraph — LangGraph 图编排核心

FDT 包含 **3 个独立 LangGraph 子图**，复用 `state.py` / `agents.py` / `llm_provider.py` 等共享模块。

#### 3.1.1 子图总览

| 子图 | 模块 | 入口 | 用途 |
|:-----|:-----|:------|:------|
| Debate Graph | `graph.py` | `build_debate_graph(mode)` | 单次辩论执行（inner loop） |
| Master Graph | `master_graph.py` | `run_master_once()` / `run_master_daemon()` | 统一编排所有自动化任务 |
| Evolution Graph | `evolution_graph.py` | `run_evolution(source_trace_id)` | 自进化闭环（outer loop） |

#### 3.1.2 state.py — DebateState 状态定义

**DebateState** (TypedDict) — 辩论流程的全局状态容器，支持增量更新：

| 字段 | 类型 | 说明 |
|:-----|:------|:------|
| `trace_id` | str | 全链路追踪 ID |
| `timestamp` | datetime | 时间戳 |
| `mode` | Literal | 运行模式 (default/fast/deep_research/tournament) |
| `scan_results` | dict | P1 数技源扫描结果 |
| `scan_summary` | Optional[dict] | 扫描汇总 |
| `judge_direction` | Optional[dict] | P2 闫判官调度决策 |
| `selected_symbols` | list | 选中辩论的品种列表 |
| `dispatch_sources` | list | 需要的数据源列表 |
| `fdc_data` | dict | P2.5 FDC 预采集数据 |
| `fdc_data_status` | Optional[FdcDataStatus] | FDC 数据采集状态 |
| `chain_analysis` | Optional[dict] | P3 产业链分析结果 |
| `technical_data` | dict | P3 技术面分析结果 |
| `fundamental_data` | dict | P3 基本面分析结果 |
| `sentiment_data` | Optional[dict] | P3 新闻情绪分析结果 |
| `research_data` | Optional[dict] | P3 合并后的研究数据 |
| `bullish_arguments` | Annotated[list, operator.add] | P4_1 多头立论 |
| `bearish_arguments` | Annotated[list, operator.add] | P4_2 空头立论 |
| `bearish_rebuttal_arguments` | Annotated[list, operator.add] | P4_3 空头反驳 |
| `bullish_rebuttal_arguments` | Annotated[list, operator.add] | P4_4 多头反驳 |
| `bear_final_arguments` | Annotated[list, operator.add] | P4_5 空头结辩 |
| `bull_final_arguments` | Annotated[list, operator.add] | P4_6 多头结辩 |
| `data_sources` | list | 数据溯源清单 |
| `debate_round` | int | 辩论轮次 |
| `verdict` | Optional[dict] | P5 闫判官裁决 |
| `risk_check` | Optional[dict] | P5 风控审核 |
| `signal_output` | Optional[dict] | P6a CTP 信号输出 |
| `current_phase` | str | 当前阶段 (P0-P6) |
| `symbol_index` | int | **v9.13.0**: 当前品种索引（-1=未开始） |
| `per_symbol_results` | dict | **v9.13.0**: {symbol: {research, debate, verdict, risk}} |
| `quality_report` | Optional[dict] | **v9.14.0**: 质检报告 |
| `rework_counters` | dict | **v9.14.0**: {symbol: retry_count} 品种级重试 |
| `phase_timings` | list | **v9.14.0**: 各阶段耗时记录 |
| `quality_metrics` | Optional[dict] | **v9.14.0**: 自优化指标 |

**FdcSymbolData** (TypedDict) — 单品种 FDC 数据结构：

| 字段 | 说明 |
|:------|:------|
| `kline` | K线数据（bars + meta + summary） |
| `indicators` | 技术指标（values + available） |
| `term_structure` | 期限结构 |
| `spread` | 跨期价差 |
| `basis` | 基差 |
| `warrant` | 仓单数据 |
| `fundamental` | 基本面数据 |
| `position_ranking` | 持仓排名 |
| `f10_summary` | F10 覆盖率汇总 |
| `data_grades` | 数据质量等级 (PRIMARY/SECONDARY/LLM_GENERATED/DERIVED/UNKNOWN) |

**FdcDataStatus** (TypedDict) — FDC 采集状态：

| 字段 | 说明 |
|:------|:------|
| `enabled` | 是否启用 |
| `collected` | 是否已采集 |
| `total_symbols` | 总品种数 |
| `success_symbols` | 成功品种数 |
| `errors` | 错误信息 |
| `elapsed_seconds` | 耗时 |
| `kline_days` | K 线天数 |
| `f10_enabled` | F10 启用 |
| `position_ranking_enabled` | 持仓排名启用 |

#### 3.1.3 graph.py — 辩论图结构

**公开构建函数**:

| 函数 | 说明 |
|:------|:------|
| `build_debate_graph(mode)` | 构建完整辩论图（含 Checkpointer，支持 SQLite/PostgreSQL） |
| `build_debate_graph_no_checkpoint(mode)` | 构建无检查点的辩论图（支持 direct_debate 模式） |
| `build_debate_graph_with_profile(profile)` | 从 Profile 名称构建图 |

**路由函数**:

| 函数 | 说明 |
|:------|:------|
| `route_after_merge_research(state)` | P3 后决策：fast→verdict，否则→bullish_v1 |
| `route_after_quality_inspect(state)` | 质检后：FAIL+重试<2→重修，否则→存储 |
| `_get_current_symbol(state)` | 获取当前处理的品种代码 |
| `calculate_divergence(state)` | 计算多空分歧度 |

**图构建函数（v9.13.0+）**:

| 函数 | 说明 |
|:------|:------|
| `_register_per_symbol_loop(graph, mode)` | 注册逐品种循环流水线 |
| `_register_direct_debate_loop(graph, mode)` | 直接辩论模式 |
| `_get_p3_node_names(mode)` | 根据 mode 返回四源节点列表 |
| `_get_checkpointer()` | 获取检查点存储（SQLite 或 PostgreSQL） |

**图执行流程**:

```
scan → judge_direction → prepare_one_symbol
  → [chain/tech/fund/sent] (四源并行，单品种)
  → merge_research → (fast→verdict, else→bullish_v1)
  → bullish_v1 → bearish_v1 → bearish_rebuttal → bullish_rebuttal → bear_final → bull_final
  → verdict → risk_check → quality_inspect
    → (FAIL+重试<2→prepare_one_symbol 重修)
    → (PASS→store_per_symbol_result → route_next_symbol
      → 还有品种→prepare_one_symbol, 全部完成→aggregate_results)
  → aggregate_results → report → signal_output → END
```

#### 3.1.4 nodes.py — 辩论节点函数

**阶段节点** (按 P1-P6 顺序):

| 节点 | 函数 | 阶段 | 说明 |
|:------|:------|:-----|:------|
| 扫描 | `node_scan()` | P1 | 数技源策略扫描 |
| 调度 | `node_judge_direction()` | P2 | 闫判官调度（选品种，direction=neutral） |
| 单品种准备 | `node_prepare_one_symbol()` | P2.5 | **v9.13.0**: 提取当前品种+准备 FDC |
| 产业链 | `node_chain()` | P3 | 链证源分析 |
| 技术面 | `node_technical()` | P3 | 观澜分析（LLM） |
| 基本面 | `node_fundamental()` | P3 | 探源分析（LLM，含金十快讯） |
| 情绪分析 | `node_sentiment()` | P3 | 读心分析（LLM，金十+Web） |
| 合并研究 | `node_merge_research()` | P3 | 合并四源数据 |
| 多头立论 | `node_bullish_v1()` | P4_1 | 多头分析员（≥3 条论据） |
| 空头立论 | `node_bearish_v1()` | P4_2 | 空头分析员（≥3 条论据） |
| 空头反驳 | `node_bearish_rebuttal()` | P4_3 | 空头反驳多头 |
| 多头反驳 | `node_bullish_rebuttal()` | P4_4 | 多头反驳空头 |
| 空头结辩 | `node_bear_final()` | P4_5 | 空头最终陈述 |
| 多头结辩 | `node_bull_final()` | P4_6 | 多头最终陈述 |
| 裁决 | `node_verdict()` | P5 | 闫判官裁决（含交易参数） |
| 风控 | `node_risk_check()` | P5 | 风控明审核 |
| 质检 | `node_quality_inspect()` | P5.5 | **v9.14.0**: 辩论输出质检 |
| 存储单品种 | `node_store_per_symbol_result()` | P5.75 | **v9.13.0**: 存储品种结果 |
| 路由下一品种 | `node_route_next_symbol()` | P5.8 | **v9.13.0**: 路由下一品种 |
| 汇聚结果 | `node_aggregate_results()` | P5.9 | **v9.13.0**: 全部品种汇聚 |
| 报告 | `node_report()` | P6 | 明鉴秋生成 HTML 报告 |
| 信号输出 | `node_signal_output()` | P6a | CTP 信号输出 |
| 加载/更新缓存 | `node_load_cache/update_cache()` | - | 直接辩论模式 |

**报告生成函数**:

| 函数 | 说明 |
|:------|:------|
| `_write_scan_report()` | P1 信号扫描报告 |
| `_write_research_report()` | P3 研究报告 |
| `_write_verdict_report()` | P5 裁决报告 |
| `_write_signal_report()` | P6a CTP 信号报告 |
| `_render_html()` | 统一 HTML 渲染（暖灰商务风） |
| `_resolve_report_dir()` | 解析报告输出目录 |

**数据上下文构建函数**:

| 函数 | 说明 |
|:------|:------|
| `_build_fdc_technical_context()` | FDC 技术数据上下文（K线/指标/MA/区间/stats） |
| `_build_fdc_fundamental_context()` | FDC 基本面数据上下文（期限结构/基差/价差/仓单/持仓排名） |
| `_build_jin10_context()` | 金十快讯上下文（按品种自动搜索） |
| `_build_debate_context()` | 辩论上下文（整合多空论据） |

**辩论协议常量**:

| 常量 | 说明 |
|:------|:------|
| `ATTACK_DIMENSIONS` | 攻击维度（data_lag/logic_jump/ignore_chain/false_breakout/liquidity_trap） |
| `EVIDENCE_WEIGHT_FACTORS` | 证据权重因子 |
| `DEBATE_DIVERGENCE_THRESHOLDS` | 辩论分歧度阈值 |

#### 3.1.5 master_graph.py — Master Orchestrator 图

FDT 的统一编排层，替代外部 APScheduler 和 TRAE Schedule。

**覆盖 14 个自动化任务**:

| 任务 | 触发类型 | 调度时间 | 说明 |
|:------|:---------|:---------|:------|
| daily_debate | time | 工作日 19:15 | 日常辩论 + 自进化闭环 |
| update_dominant_mapping | time | 工作日 15:30 | 主力合约映射更新 |
| auto_publish | time | 每天 23:05 | 自动发布（版本自增+Git推送） |
| apm_scorecard | time | 每周一 08:30 | APM-CS 五轴评分卡 |
| cluster_failures | time | 每周一 08:00 | 失败模式聚类 |
| discipline_enforce | time | 每周一 08:45 | D4 纪律钳制 |
| self_optimize_evolve | time | 工作日 15:35 | Skillevolver 技能层进化 |
| self_optimize_verify | time | 每周一 08:50 | 自优化 A/B 验证 |
| validate_and_evolve | data | 冷却 1440min | 验证→校准→进化管道 |
| ml_training_check | data | 冷却 4320min | ML 训练条件检查 |
| self_optimize_analysis | data | 冷却 360min | SkillAdaptor 归因分析 |
| vibench_baseline | data | 冷却 10080min | ViBench 基线更新 |
| d3_auto_light | debate_record | 冷却 1440min | D3 Composure 自动点亮 |
| data_collection | time | (与 update_dominant_mapping 共存) | 数据采集 |

**Master Graph 执行流程**:

```
check_time → dispatch → task_node_1 → dispatch → task_node_2 → ... → done
     ↑                                                |
     └──────────────── 循环直到所有任务完成 ──────────────┘
```

- `node_check_time(state)`: 检查当前时间与数据条件，将所有到期任务加入 `task_queue`
- `node_dispatch(state)`: 从队列取出下一个任务，路由到对应执行节点
- `route_after_task(state)`: 任务完成后回到 dispatch 取下一个

**关键函数**:

| 函数/变量 | 说明 |
|:-----------|:------|
| `run_master_once(loop_id)` | 单次检查并运行到期任务 |
| `run_master_daemon(interval_seconds)` | 守护进程模式（默认每 60 秒检查） |
| `get_master_graph()` | 获取编译后的 master 图（全局单例） |
| `_write_heartbeat()` | 写入心跳文件，供 watchdog 检测 |

**`master_state.py` — Master 状态定义**:

| 字段 | 说明 |
|:------|:------|
| `loop_id` | 循环 ID |
| `phase` | 当前阶段 (idle/check_time/dispatch/task_running/done) |
| `current_task` | 当前执行的任务名称 |
| `task_queue` | 到期任务队列（由 node_check_time 填充） |
| `task_index` | 当前任务索引 |
| `schedules` | 调度注册表（14 个任务的配置） |
| `last_runs` | 本轮已运行记录（防重复） |
| `task_results` | 任务执行结果 `{task_name: {success, summary, ...}}` |
| `errors` | 非阻断错误列表 |
| `started_at / completed_at` | 时间戳 |

**调度注册表**存储在 `create_master_state()` → `_get_default_schedules()` 中，定义了每个任务的 `trigger_type`（time/data/debate_record）、`weekdays`、`hour:minute`、`data_path`、`threshold`、`cooldown_minutes` 等参数。

**`master_nodes.py` — Master 节点函数**:

| 函数 | 说明 |
|:------|:------|
| `node_check_time` | 检查时间/数据条件，标记到期任务 |
| `node_dispatch` | 调度分发 |
| `node_run_daily_debate` | 日常辩论（graph.ainvoke + evolution） |
| `node_run_update_dominant_mapping` | 更新主力合约映射（内联 Python） |
| `node_run_auto_publish` | 自动发布 |
| `node_run_apm_scorecard` | APM 评分卡 |
| `node_run_cluster_failures` | 失败模式聚类 |
| `node_run_discipline_enforce` | D4 纪律钳制 |
| `node_run_data_collection` | 数据采集 |
| `node_run_validate_and_evolve` | 验证→校准→进化管道 |
| `node_run_ml_training_check` | ML 训练条件检查 |
| `node_run_self_optimize_evolve/analysis/verify` | 自优化任务 |
| `node_run_vibench_baseline` | ViBench 基线更新 |
| `node_run_d3_auto_light` | D3 Composure 自动点亮 |

辅助工厂函数:
- `_make_script_node(task_name, script_path, ...)` — 简单脚本包装
- `_make_data_threshold_node(task_name, script_path, ...)` — 数据阈值节点
- `_run_script(script_rel, *args, timeout)` — 脚本运行工具
- `_load_json(rel_path)` — 安全 JSON 加载
- `_get_trigger_state()` / `_set_triggered(task_name)` — 触发状态持久化

#### 3.1.6 evolution_graph.py — 自进化图

**EvolutionState** (dict subclass) — 自进化状态：

| 字段 | 说明 |
|:------|:------|
| `trace_id` | 全链路追踪 ID |
| `phase` | 当前阶段 (idle/collecting/apm_eval/deciding/.../completed) |
| `source_trace_id` | 触发本次进化的辩论 trace_id |
| `collected_metrics` | 收集的质量指标（品藻/D3/D6） |
| `apm_scores` | APM-CS 五轴评分 (D1-D5) |
| `apm_overall` | 综合评分与退化标记 |
| `decisions` | 决策（need_improve/calibrate/evolve/ml_train） |
| `step_results` | 各步骤执行结果 |
| `errors` | 错误列表 |

**APM 退化阈值**:

| 轴 | 名称 | 阈值 | 说明 |
|:---:|:------|:----:|:------|
| D1 | Coherence | 0.5 | 裁决与论据一致性 |
| D2 | Acuity | 0.0 | 信号-噪音辨识力 |
| D3 | Composure | 0.3 | 波动率镇定度 |
| D4 | Discipline | 0.7 | 规则遵守度 |
| D5 | Reliability | 0.6 | 闭环完成率 |

**进化图执行流程**:

```
collect_metrics → apm_eval → decide_actions
    → [improve → calibrate → evolve → ml_train → ...] → complete → END
```

各步骤条件路由：
- `route_after_decide`: 优先顺序：improve → calibrate → evolve → ml → complete
- `route_after_improve`: calibrate → evolve → ml → complete
- `route_after_calibrate`: evolve → ml → complete
- `route_after_evolve`: ml → complete

**进化节点函数**:

| 节点 | 函数 | 说明 |
|:------|:------|:------|
| 收集指标 | `node_collect_metrics` | 读取 quality_report + generation_metrics + output_metrics |
| APM 评估 | `node_apm_eval` | 运行 apm_scorecard.py 或读取已有评分 |
| 决策 | `node_decide_actions` | 基于阈值+样本量决策 |
| 自改进 | `node_improve` | `self_improve.py --mode=analyze` |
| 校准权重 | `node_calibrate` | `calibrate_weights.py` |
| Agent 进化 | `node_evolve` | `evolve_agents.py` |
| ML 训练 | `node_ml_train` | `ml/trainer.py` |
| 完成 | `node_complete` | 写入 evolution_log.json |

**触发方式**:
- `run_evolution(source_trace_id)` — 独立运行
- `route_after_debate(debate_state)` — 辩论图 END 后的钩子（`FDT_RUN_EVOLUTION=true` 时自动触发）

#### 3.1.7 agents.py — Agent 执行器 + D3 Decode Control

**FdtAgentExecutor** — Agent 执行器：

| 方法 | 说明 |
|:------|:------|
| `__init__(agent_config)` | 初始化（支持字符串名称或配置字典） |
| `_apply_decode_config()` | **v9.15.0**: D3 Generation 解码控制 |
| `execute(prompt, trace_id, **kwargs)` | 执行 Agent（同步），支持 ToolMetrics 记录 |
| `run(prompt, trace_id, **kwargs)` | 异步包装 |
| `_call_llm(prompt, **kwargs)` | LLM API 调用（httpx，3 次重试，逐 Agent 配置） |
| `_resolve_llm_config(suffix, default)` | 逐 Agent 配置解析 |
| `_normalize_env_name(agent_name)` | Agent 名称→环境变量名 |
| `_load_from_registry(agent_name)` | 从 AgentRegistry 加载 |

**D3 Generation 解码控制**:
- 配置文件: `config/agents/decode_config.yaml`
- 覆盖字段: `temperature`, `max_tokens`
- 优先级: decode_config.yaml > 逐Agent环境变量 > 全局环境变量 > 默认值

**逐 Agent LLM 配置环境变量**:
- `FDT_LLM_<NAME>_API_KEY` — 覆盖全局 API Key
- `FDT_LLM_<NAME>_API_BASE` — 覆盖全局 API Base URL
- `FDT_LLM_<NAME>_MODEL` — 覆盖全局模型名称

（NAME 为 Agent 名称的大写+下划线格式）

**AgentRegistry** — 单例 Agent 注册表：

| 方法 | 说明 |
|:------|:------|
| `register(agent_name, executor)` | 注册 Agent |
| `get(agent_name)` | 获取已注册 Agent |
| `load_from_directory(dir)` | 从 agents/ 目录加载所有 .md 定义文件 |
| `_parse_agent_md(md_path)` | 解析 Agent Markdown 定义文件 |

**DebateAgentExecutor** — 便捷执行器：

| 方法 | 说明 |
|:------|:------|
| `execute_agent(agent_name, prompt, trace_id)` | 执行单个 Agent |
| `execute_parallel(tasks)` | 并行执行多个 Agent |
| `run_single(agent_name, context, ...)` | 单 Agent 便捷运行（G95） |

#### 3.1.8 llm_provider.py — 独立 LLM 客户端

切断 `fdt_langgraph` ↔ `scripts` 的设计层面循环依赖。

**FdtLlm** — 独立 LLM 客户端：

| 方法 | 说明 |
|:------|:------|
| `__init__(agent_type)` | 初始化，加载 `config/llm_config.yaml` |
| `_load_config(agent_type)` | 加载配置（支持 per_agent 覆盖） |
| `chat(prompt, system, temperature, max_tokens)` | LLM 聊天调用 |
| `chat_json(prompt, system, temperature)` | JSON 模式调用（自动剥离 ```json） |
| `check_available()` | 可用性检查 |

**Mock 模式**: `FDT_LLM_MOCK=true` 时启用（闫判官/风控专用 mock 模板）

**配置优先级**: `config/llm_config.yaml` per_agent > defaults > 硬编码默认值

#### 3.1.9 quality_inspector.py — 辩论输出质检

**v9.14.0 新增** — 纯函数无 IO：

| 函数 | 说明 |
|:------|:------|
| `validate_argument(data, symbol)` | 校验 P3 多/空论据 |
| `validate_verdict(data)` | 校验 P5 闫判官裁决 |
| `validate_risk(data)` | 校验 P5 风控审核 |
| `check_report_integrity(html_path)` | HTML 报告完整性检查 |

质检规则来源: `contracts/debate_quality_schema.py`

#### 3.1.10 health.py — 健康检查

**HealthChecker** — 健康检查器（单例）：

| 方法 | 说明 |
|:------|:------|
| `start_node(node_name)` | 记录节点开始时间 |
| `end_node(node_name)` | 记录节点结束时间 |
| `record_error(node_name, error)` | 记录节点错误 |
| `check_state_health(state)` | 状态健康度检查（trace_id/阶段/超时） |
| `check_graph_health(config)` | 图配置健康度检查 |
| `get_summary()` | 获取健康检查摘要 |

模块级便捷函数：`get_health_checker()`、`run_health_check(state, graph_config)`

#### 3.1.11 web_crawl_tool.py — Web + 金十 MCP 工具

LangChain @tool 封装层，暴露 11 个工具供 LLM Agent 调用：

| 工具 | 说明 |
|:------|:------|
| `langchain_fetch_quote` | 获取品种实时行情 |
| `langchain_fetch_kline` | 获取 K 线数据 |
| `langchain_search_news` | 搜索期货新闻 |
| `langchain_jin10_*` | 金十数据（快讯/资讯/日历/行情/K 线）共 8 个工具 |

#### 3.1.12 tools/registry.py — 工具注册中心

**ToolRegistry** — D2 Tool Phase 1：

| 方法 | 说明 |
|:------|:------|
| `register(name, module_path, description, ...)` | 注册工具 |
| `get_tool(name)` | 获取工具 |
| `list_tools(category)` | 按分类列出 |
| `record_call(name, success)` | 记录调用统计 |
| `get_stats()` / `get_summary()` | 统计获取 |

#### 3.1.13 single_symbol_report.py — 单品种报告

| 函数 | 说明 |
|:------|:------|
| `generate(state, trace_id, output_dir)` | 生成完整单品种报告 |
| `generate_body(state, sym)` | 生成报告 body（合并用） |
| `_extract_agent_output(state, agent_tag, sym)` | 提取指定 Agent 输出 |

---

### 3.2 futures_data_core — 期货数据核心引擎

#### 3.2.1 包级公开 API

| API | 说明 |
|:------|:------|
| `get_kline(symbol, period, days, source)` | 获取 K 线，自动降级 |
| `get_quote(symbol, source)` | 行情快照 |
| `batch_get_quotes(symbols)` | 批量行情 |
| `compute_indicators(data, names, **params)` | 技术指标（本地 numpy） |
| `get_adapter()` | 进程级 MultiSourceAdapter 单例 |
| `get_symbol(name)` / `is_known(name)` | 品种查询 |
| `list_exchanges()` / `list_symbols()` | 交易所/品种列表 |

#### 3.2.2 core/ — 核心层

| 模块 | 说明 |
|:------|:------|
| `multi_source_adapter.py` | 多源降级链适配器（5 级采集器自动降级+熔断） |
| `dominant_resolver.py` | 主力合约解析（品种→合约换月追踪） |
| `circuit_breaker.py` | A1 级熔断器（CLOSED→OPEN→HALF_OPEN） |
| `cache_store.py` | 多级缓存（Postgres/Redis/Memory） |
| `field_normalizer.py` | 字段标准化（信号/裁决/风控/方向） |
| `data_quality.py` | 数据质量评估 |
| `types.py` | 归一化数据载体（KlineBar/KlineData/QuoteData） |
| `symbol_registry.py` | 品种注册表 |

**MultiSourceAdapter** — 多源降级链适配器：

| 方法 | 说明 |
|:------|:------|
| `register(collector)` | 注册采集器 |
| `get_kline(symbol, period, days, source)` | 获取 K 线（自动降级） |
| `get_contract_kline(contract, period, days)` | 按合约代码精确查询 |
| `get_quote(symbol, source)` | 行情快照 |
| `batch_get_quotes(symbols)` | 批量行情（双源融合） |
| `get_all_active_contracts(variety)` | 获取所有活跃合约月份 |
| `source_health()` | 数据源熔断状态 |

**CircuitBreaker** — 熔断器状态机：

```
CLOSED（正常放行）→ 连续失败 ≥5 → OPEN（跳过，冷却 60s）
  → cooldown 到期 → HALF_OPEN（探测一次）
    → 成功 → CLOSED（清零失败计数）
    → 失败 → OPEN（重置冷却计时）
```

#### 3.2.3 collectors/ — 数据采集器

| 采集器 | 类名 | 优先级 | 说明 |
|:-------|:------|:------:|:------|
| DataCore | `DataCoreCollector` | 0 | Data-Core 统一数据接口 |
| TDX | `TDXCollector` | 1 | 通达信本地 TQ-Local |
| Web | `WebFallbackCollector` | 2 | 东方财富+新浪 |
| QMT | `QMTCollector` | 3 | QMT/xtquant |
| TqSdk | `TqSdkCollector` | 98 | 天勤量化（末位兜底） |

**BaseCollector** — 抽象基类：

| 方法 | 说明 |
|:------|:------|
| `check_available()` | 探测可用性（抽象） |
| `get_kline(symbol, period, days)` | 获取 K 线（抽象） |
| `get_quote(symbol)` | 行情快照（可选） |

#### 3.2.4 f10/ — F10 衍生品数据

| 模块 | 说明 |
|:------|:------|
| `jin10_mcp.py` | 金十 MCP 采集器（行情/K线/快讯/资讯/日历） |
| `term_structure.py` | 期限结构分析 |
| `spread.py` | 跨期价差计算 |
| `basis.py` | 基差计算 |
| `warrant.py` | 仓单数据采集 |
| `fundamentals.py` | 基本面数据（含 LLM 增强） |
| `position.py` | 持仓排名 |
| `macro.py` | 宏观数据（PMI/利率） |
| `sentiment.py` | 新闻情绪分析 |
| `exchange_scraper.py` | 交易所数据抓取 |
| `web_collector.py` / `web_collector_llm.py` | Web 采集器 |

#### 3.2.5 indicators/ — 技术指标

| 模块 | 说明 |
|:------|:------|
| `core.py` | 核心计算（compute_indicators + INDICATOR_NAMES） |
| `legacy_numpy.py` | numpy 纯函数实现 |
| `tdx_compat.py` | TDX 兼容接口 |

#### 3.2.6 mcp_client.py — MCP 协议客户端

**McpHttpClient** — 标准 MCP 协议 HTTP 客户端：

| 方法 | 说明 |
|:------|:------|
| `initialize()` | 初始化会话（协议版本 2025-11-25） |
| `list_tools()` / `list_resources()` | 列出工具/资源 |
| `call_tool(name, args)` | 调用工具 |
| `read_resource(uri)` | 读取资源 |

协议流程: `initialize → notifications/initialized → tools/list → tools/call`

---

### 3.3 contracts — 契约定义

#### 3.3.1 a2a_payload.py — A2A 数据信封

**A2APayload** (dataclass) — 统一数据输出信封：

| 字段 | 类型 | 说明 |
|:------|:------|:------|
| `type` | str | 数据类型标识 |
| `runtime_mode` | str | 运行模式（independent/llm_enhanced） |
| `meta` | dict | 元信息（等级/来源/时效） |
| `data` | dict | 纯业务数据 |
| `summary` | str | 自然语言描述（≤200 字） |
| `jsonrpc` | str | 协议版本（"2.0"） |
| `method` | str | 协议方法（"tasks/send"） |

**数据等级常量**:

| 常量 | 值 | 说明 | 优先级 |
|:------|:----|:------|:------:|
| `GRADE_PRIMARY` | PRIMARY | 一手数据（交易所直采） | 0 |
| `GRADE_SECONDARY` | SECONDARY | 二手数据（聚合/加工） | 1 |
| `GRADE_LLM` | LLM_GENERATED | LLM 生成（含推理） | 2 |
| `GRADE_DERIVED` | DERIVED | 衍生计算（指标/模型） | 3 |
| `GRADE_UNKNOWN` | UNKNOWN | 等级未确定 | 9 |

**快捷构造器**: `a2a_basis()`、`a2a_inventory()`、`a2a_debate()`、`a2a_scan_summary()`

#### 3.3.2 debate_argument_schema.py — 辩论论点 Schema

**ArgumentItem** (TypedDict) — 单条论据（v1.1）：

| 字段 | 类型 | 必填 | 说明 |
|:------|:------|:----:|:------|
| `id` | str | ✅ | 论据唯一 ID |
| `family` | StrategyFamily | ✅ | 策略族标签 (F1-F5) |
| `claim` | str | ✅ | 一句话可证伪断言 |
| `evidence` | str | ✅ | 数据支撑（数值+来源+日期） |
| `reasoning` | str | ✅ | 推理链 |
| `impact` | Literal | ✅ | 重要性 (HIGH/MEDIUM/LOW) |
| `rebuts` | Optional[list[str]] | - | 反驳的目标论点 ID 列表 |
| `rebuttal_type` | Optional[str] | - | 反驳类型 |
| `rebuttal_detail` | Optional[str] | - | 反驳拆解 |

**StructuredDebateArgument** (TypedDict) — 辩手输出顶层 JSON：

| 字段 | 说明 |
|:------|:------|
| `meta` | phase/agent_name/version/target_symbol |
| `arguments` | list[ArgumentItem] |

**StrategyFamily** 枚举:

| 值 | 说明 |
|:----|:------|
| F1 | 技术面量价（均线/ADX/RSI/BB/成交量） |
| F2 | 基本面供需（库存/基差/利润/供需平衡表） |
| F3 | 持仓资金（主力持仓/持仓量变化/净多空比） |
| F4 | 宏观政策（利率/贸易/地缘/产业政策） |
| F5 | 套利结构（跨期价差/跨品种价差/展期收益） |

#### 3.3.3 debate_quality_schema.py — 辩论质量 Schema

**v9.14.0 新增** — Phase 3 Data Governance：

| 类型 | 说明 |
|:------|:------|
| `QualityReport` | 质检报告（status: PASS/FAIL/SKIP + issues） |
| `QualityIssue` | 质检问题（field/message/severity） |
| `ArgumentSchema` | P3 论据 Schema |
| `VerdictSchema` | P5 裁决 Schema |
| `RiskSchema` | P5 风控 Schema |

校验规则：`ARGUMENT_RULES`（min_arguments=1）、`VERDICT_RULES`（6 个必填字段）、`RISK_RULES`（3 个必填字段）

#### 3.3.4 experience_schema.py — 经验 Schema

定义经验记录的结构化格式（配方+评分），用于自进化闭环存储与复用。

#### 3.3.5 migrations.py — 数据库迁移

数据库 Schema 迁移脚本管理。

---

### 3.4 data_source_adapter.py — 数据源适配层

统一 FDC ↔ Data-Core 接口。通过 `FDT_DATA_SOURCE` 环境变量控制（fdc/datacore）。

**核心函数**（22 个公开接口）：

| 分类 | 函数 | 说明 |
|:------|:------|:------|
| 行情 | `get_kline()` | 获取 K 线（自动降级） |
| | `get_contract_kline()` | 按合约获取 K 线 |
| | `get_quote()` | 行情快照 |
| | `batch_get_quotes()` | 批量行情 |
| F10 | `get_term_structure()`, `get_basis()`, `get_spread()`, `get_inventory()`, `get_position_ranking()`, `get_f10_data()` | F10 数据 |
| 金十 | `jin10_available()`, `jin10_list_flash()`, `jin10_search_flash()`, `jin10_list_news()`, `jin10_search_news()`, `jin10_get_news()`, `jin10_list_calendar()`, `jin10_get_quote()`, `jin10_get_kline()` | 金十 MCP 数据 |
| 管理 | `set_data_source()`, `get_data_source()` | 数据源管理 |

**适配层工作原理**:
```
调用方 → data_source_adapter.get_kline() → 动态加载模块 → 执行对应实现
                                              ↓
                              futures_data_core / datacore_adapter
```

---

### 3.5 fdt_pg — PostgreSQL 模块

PostgreSQL OLTP+OLAP 混合存储。

| 文件 | 说明 |
|:------|:------|
| `connection.py` | 连接管理（单例，QueuePool 10 最大连接） |
| `schema.py` | ORM 模型（DebateRecord/SignalHistory/ExperienceRecord） |
| `deploy.py` | 部署工具（init/health/migrate） |
| `migrations/` | 迁移脚本（按版本顺序） |

**环境变量**: `FDT_PG_URL`

---

### 3.6 scheduler — 旧调度引擎（兼容层）

保留为兼容层，新开发全部走 LangGraph Master Graph。

| 模块 | 说明 |
|:------|:------|
| `engine.py` | 调度发动机（heartbeat/trigger/task） |
| `triggers.py` | 触发器（TimeTrigger/DataTrigger/EventTrigger） |
| `tasks.py` | 任务注册（10 个预注册任务） |

---

### 3.7 skills/ — 子技能实现（10 个包）

| 技能包 | 说明 |
|:-------|:------|
| `quant-daily/` | 量化每日系统（8 策略引擎/回测/信号验证/ML/优化） |
| `commodity-chain-analysis/` | 产业链分析 |
| `debate-argument-builder/` | 辩论论据构建 |
| `debate-judge/` | 辩论裁决 |
| `debate-risk-manager/` | 风控管理（引擎/仓位/费用） |
| `debate-trading-planner/` | 交易规划（情景分析） |
| `fdt-spawn-debate/` | 辩论生成（spawn 子辩论） |
| `fundamental-data-collector/` | 基本面数据采集 |
| `futures-data-technician/` | 数据技术员 |
| `futures-trading-analysis/` | 期货交易分析（完整子系统） |
| `technical-analysis/` | 技术分析（交叉相关性/背离/量价） |

---

### 3.8 scripts/ — 辅助脚本（80+ 文件）

**核心工具包**:

| 子包/脚本 | 说明 |
|:-----------|:------|
| `core/fingerprint.py` | 指纹管理 |
| `core/trace_id.py` | trace_id 生成与管理（new_trace/current_trace/inject_trace_to_env） |
| `core/unified_logger.py` | 统一日志配置 |

**关键脚本**:

| 脚本 | 说明 |
|:------|:------|
| `fdt_cli.py` | CLI 入口（已在根目录有独立版本） |
| `pre_commit_harness_check.py` | Harness pre-commit 检查（从 YAML 加载规则） |
| `apm_scorecard.py` | APM-CS 五轴评分卡 |
| `self_improve.py` | 自改进分析 |
| `evolve_agents.py` | Agent 参数进化 |
| `calibrate_weights.py` | 权重校准 |
| `experience_recorder.py` | 经验记录 |
| `validate_verdicts.py` | 验证历史裁决 |
| `enforce_discipline.py` | D4 纪律钳制 |
| `cluster_failures.py` | 失败模式聚类 |
| `tool_metrics.py` | 工具调用效能追踪 |
| `memory_writer.py` / `memory_retriever.py` | 记忆读写 |
| `health_check.py` / `health_server.py` | 健康检查/服务 |
| `webui.py` | Web 管理界面 |

---

## 4. 关键类与函数

### 4.1 核心类速查

| 类 | 模块 | 说明 |
|:----|:------|:------|
| `DebateState` | `fdt_langgraph.state` | 辩论全局状态（TypedDict） |
| `FdcSymbolData` | `fdt_langgraph.state` | FDC 品种数据结构 |
| `FdcDataStatus` | `fdt_langgraph.state` | FDC 采集状态 |
| `EvolutionState` | `fdt_langgraph.evolution_state` | 自进化状态（dict subclass） |
| `FdtAgentExecutor` | `fdt_langgraph.agents` | Agent 执行器（逐Agent LLM 配置 + D3 Control） |
| `AgentRegistry` | `fdt_langgraph.agents` | Agent 注册表（单例） |
| `DebateAgentExecutor` | `fdt_langgraph.agents` | 便捷执行器（G95） |
| `FdtLlm` | `fdt_langgraph.llm_provider` | 独立 LLM 客户端 |
| `HealthChecker` | `fdt_langgraph.health` | 健康检查器 |
| `ToolRegistry` | `fdt_langgraph.tools.registry` | 工具注册中心 |
| `MultiSourceAdapter` | `futures_data_core.core.multi_source_adapter` | 多源降级链适配器 |
| `DominantResolver` | `futures_data_core.core.dominant_resolver` | 主力合约解析器 |
| `CircuitBreaker` | `futures_data_core.core.circuit_breaker` | 熔断器（A1 级） |
| `BaseCollector` | `futures_data_core.collectors.base` | 采集器抽象基类 |
| `McpHttpClient` | `futures_data_core.mcp_client` | MCP 协议 HTTP 客户端 |
| `A2APayload` | `contracts.a2a_payload` | 统一数据信封 |
| `ArgumentItem` | `contracts.debate_argument_schema` | 辩论论据结构（v1.1） |
| `StructuredDebateArgument` | `contracts.debate_argument_schema` | 辩手输出顶层 JSON |
| `QualityReport` | `contracts.debate_quality_schema` | 质检报告 |
| `PGConnection` | `fdt_pg.connection` | PostgreSQL 连接管理 |

### 4.2 核心函数速查

| 函数 | 模块 | 说明 |
|:------|:------|:------|
| `create_initial_state(trace_id, mode)` | `fdt_langgraph.state` | 创建初始 DebateState |
| `build_debate_graph(mode)` | `fdt_langgraph.graph` | 构建辩论图（含 Checkpointer） |
| `build_debate_graph_no_checkpoint(mode)` | `fdt_langgraph.graph` | 无检查点的辩论图 |
| `build_debate_graph_with_profile(profile)` | `fdt_langgraph.graph` | 从 Profile 构建图 |
| `calculate_divergence(state)` | `fdt_langgraph.graph` | 计算多空分歧度 |
| `run_master_once(loop_id)` | `fdt_langgraph.master_graph` | Master 单次检查 |
| `run_master_daemon(interval)` | `fdt_langgraph.master_graph` | Master 守护进程 |
| `run_evolution(source_trace_id)` | `fdt_langgraph.evolution_graph` | 运行自进化闭环 |
| `route_after_debate(debate_state)` | `fdt_langgraph.evolution_graph` | 辩论后触发进化钩子 |
| `validate_argument(data, symbol)` | `fdt_langgraph.quality_inspector` | P3 论据质检 |
| `validate_verdict(data)` | `fdt_langgraph.quality_inspector` | P5 裁决质检 |
| `validate_risk(data)` | `fdt_langgraph.quality_inspector` | P5 风控质检 |
| `node_scan(state)` | `fdt_langgraph.nodes` | P1 数技源扫描 |
| `node_judge_direction(state)` | `fdt_langgraph.nodes` | P2 闫判官调度 |
| `node_prepare_one_symbol(state)` | `fdt_langgraph.nodes` | P2.5 单品种准备（v9.13.0） |
| `node_merge_research(state)` | `fdt_langgraph.nodes` | P3 合并四源 |
| `node_verdict(state)` | `fdt_langgraph.nodes` | P5 闫判官裁决 |
| `node_risk_check(state)` | `fdt_langgraph.nodes` | P5 风控审核 |
| `node_quality_inspect(state)` | `fdt_langgraph.nodes` | P5.5 质检（v9.14.0） |
| `node_report(state)` | `fdt_langgraph.nodes` | P6 明鉴秋报告 |
| `get_kline(symbol, period, days, source)` | `data_source_adapter` | 获取 K 线 |
| `jin10_search_flash(keyword)` | `data_source_adapter` | 搜索金十快讯 |
| `jin10_list_calendar()` | `data_source_adapter` | 金十财经日历 |
| `normalize_signal_list(signals)` | `futures_data_core.core.field_normalizer` | 标准化信号 |
| `a2a_debate(symbol, decision, ...)` | `contracts.a2a_payload` | 构造裁决信封 |
| `new_trace(prefix)` | `scripts.core.trace_id` | 生成 trace_id |
| `current_trace()` | `scripts.core.trace_id` | 获取当前 trace_id |

---

## 5. 数据流与依赖关系

### 5.1 模块依赖关系

```
fdt_cli / fdt_api / fdt_daily_runner
    ↓
fdt_langgraph (graph → nodes → agents → state → health → quality_inspector → llm_provider)
    │   ├── master_graph / evolution_graph (独立子图)
    ↓
data_source_adapter
    ↓
futures_data_core (multi_source_adapter → collectors → f10 → indicators → mcp_client)
    ↓
contracts (a2a_payload → debate_argument_schema → debate_quality_schema)
    │
fdt_pg / fdt_cache / memory / schemas
```

**依赖说明**:
- `fdt_langgraph` 依赖 `data_source_adapter` 和 `contracts`
- `data_source_adapter` 依赖 `futures_data_core`（动态加载，支持 fdc/datacore 切换）
- `futures_data_core` 依赖 `contracts.a2a_payload` 输出数据信封
- `contracts` 为桥接层，重新导出 `skills/futures-trading-analysis/contracts/`
- 所有模块共享 `fdt_pg` / `fdt_cache` / `memory` 存储层
- `fdt_langgraph/llm_provider.py` 切断了对 `scripts.fdt_llm` 的依赖

### 5.2 数据流向

```
[输入层]
  ├── 环境变量配置 (FDT_*)
  ├── Agent 定义文档 (agents/*.md + config/agents/*.yaml)
  ├── D3 Decode Control (config/agents/decode_config.yaml)
  ├── LLM 配置 (config/llm_config.yaml)
  ├── 品种知识库 (memory/knowledge/)
  └── 数据源配置 (config/data_sources.yaml)

[编排层 — 逐品种循环流水线 (v9.13.0)]
  ├── P1: scan_all.py → trend_following(10子信号)扫描 → stats+scan_results+scan_summary
  ├── P2: 闫判官 → 基于 stats 选品种，direction=neutral → judge_direction + selected_symbols
  ├── 逐品种循环开始:
  │   ├── P2.5: prepare_one_symbol → 提取品种，FDC 数据准备
  │   ├── P3: 四源并行 → chain_analysis + technical_data + fundamental_data + sentiment_data
  │   ├── P4: 六阶段辩论 → bullish/bearish/rebuttal/final_arguments
  │   ├── P5: 闫判官裁决 + 风控审核 → verdict + risk_check
  │   ├── P5.5: 质检 → PASS→store, FAIL+重试<2→重修
  │   ├── P5.75: store_per_symbol_result → route_next_symbol
  ├── 逐品种循环结束:
  │   ├── P5.9: aggregate_results → 全部品种汇聚
  │   └── P6: 报告生成 + CTP 信号 → report_path + signal_output

[输出层]
  ├── HTML 报告文件 (debate_report_{trace_id}.html)
  ├── PostgreSQL 持久化 (DebateRecord/SignalHistory)
  ├── SQLite 缓存 (fdt_cache)
  └── 辩论历史记录 (memory/debates/)
```

### 5.3 数据降级链

```
请求 → MultiSourceAdapter → DataCoreCollector
                          ↓ 失败
                          → TDXCollector
                          ↓ 失败
                          → WebFallbackCollector
                          ↓ 失败
                          → QMTCollector
                          ↓ 失败
                          → TqSdkCollector
                          ↓ 全部失败
                          → 缓存 → CACHED
                          ↓ 缓存未命中
                          → UNAVAILABLE
```

每个采集器独立熔断器：连续失败 5 次 → 屏蔽 60 秒

### 5.4 外部依赖

| 依赖 | 用途 | 版本要求 |
|:------|:------|:---------|
| pandas | 数据处理 | ≥2.0 |
| numpy | 数值计算 | ≥1.24 |
| langgraph | 图编排与状态管理 | ≥0.2.0 |
| langgraph-checkpoint-sqlite | SQLite 状态持久化 | ≥0.1.0 |
| langgraph-checkpoint-postgres | PostgreSQL 状态持久化 | ≥0.1.0 |
| sqlalchemy | ORM | ≥2.0 |
| psycopg2-binary | PostgreSQL 驱动 | ≥2.9 |
| pydantic | 数据校验 | ≥2.0 |
| httpx | HTTP 客户端 | ≥0.27 |
| fastapi | API 服务 | ≥0.100 |
| uvicorn | ASGI 服务器 | ≥0.23 |
| lightgbm | ML 模型 | ≥4.0 |
| scikit-learn | 机器学习 | ≥1.3 |
| xgboost | ML 模型（扫描策略） | ≥2.0 |
| python-dotenv | 环境变量加载 | ≥1.0 |
| tenacity | 重试机制 | ≥8.0 |
| pyyaml | YAML 配置解析 | ≥6.0 |
| beautifulsoup4 | HTML 解析 | ≥4.12 |
| tqsdk | 天勤量化 SDK | ≥2.0 |
| langchain_core | LangChain 工具框架 | ≥0.3.0 |

---

## 6. 运行方式与配置

### 6.1 CLI 入口

```bash
# 单次辩论执行
python fdt_cli.py run [--mode default/fast/deep_research/tournament]

# Master Orchestrator 守护进程（替换 APScheduler）
python fdt_cli.py daemon [--interval 60]

# 数据库操作
python fdt_cli.py db init     # 初始化 Schema
python fdt_cli.py db health   # 健康检查

# Master 单次检查
python -c "from fdt_langgraph.master_graph import run_master_once; run_master_once()"

# 自进化独立运行
python -c "from fdt_langgraph.evolution_graph import run_evolution; run_evolution()"
```

### 6.2 API 入口

```bash
python fdt_api.py
```

**API 端点**:

| 端点 | 方法 | 说明 |
|:------|:------|:------|
| `/health` | GET | 健康检查 |
| `/api/v1/debate` | POST | 触发辩论（异步，返回 trace_id） |
| `/api/v1/debate/{trace_id}` | GET | 查询辩论状态 |
| `/api/v1/status` | GET | 任务运行统计 |

```bash
curl -X POST http://localhost:8000/api/v1/debate \
  -H "Content-Type: application/json" \
  -d '{"mode": "default"}'
```

### 6.3 环境变量

**核心 LLM 配置**:

| 变量 | 说明 | 默认值 |
|:------|:------|:-------|
| `FDT_LLM_API_KEY` | LLM 全局 API Key | 同 `OPENAI_API_KEY` |
| `FDT_LLM_API_BASE` | LLM 全局 API Base URL | `https://api.deepseek.com/v1` |
| `FDT_LLM_MODEL` | LLM 全局模型名称 | `deepseek-chat` |
| `FDT_LLM_MOCK` | Mock 模式（测试用） | `false` |

**逐 Agent LLM 覆盖**:

| 变量 | 说明 |
|:------|:------|
| `FDT_LLM_<NAME>_API_KEY` | 逐 Agent API Key（覆盖全局） |
| `FDT_LLM_<NAME>_API_BASE` | 逐 Agent API Base URL（覆盖全局） |
| `FDT_LLM_<NAME>_MODEL` | 逐 Agent 模型名（覆盖全局） |

**FDC 数据注入配置**:

| 变量 | 说明 | 默认值 |
|:------|:------|:-------|
| `FDT_FDC_INJECTION_ENABLED` | 启用 FDC 数据注入 | `true` |
| `FDT_FDC_KLINE_DAYS` | K线数据天数 | `120` |
| `FDT_FDC_F10_ENABLED` | 启用 F10 数据 | `true` |
| `FDT_FDC_POSITION_RANKING_ENABLED` | 启用持仓排名 | `true` |

**报告输出配置**:

| 变量 | 说明 | 默认值 |
|:------|:------|:-------|
| `FDT_REPORT_WORKSPACE` | 报告输出根目录（优先） | - |
| `FDT_DAILY_WORKSPACE` | 每日工作空间（降级） | - |
| `FDT_GENERATE_INTERMEDIATE_REPORTS` | 生成中间报告（research/verdict/signal） | `false` |

**运行模式配置**:

| 变量 | 说明 | 默认值 |
|:------|:------|:-------|
| `FDT_DIRECT_DEBATE` | 指定品种直接辩论模式 | `false` |
| `FDT_DEBATE_SYMBOLS` | 指定辩论品种列表（逗号分隔） | - |
| `FDT_RUN_EVOLUTION` | 辩论后自动触发进化 | `false` |
| `FDT_DATA_SOURCE` | 数据源类型（fdc/datacore） | `fdc` |
| `FDT_CHECKPOINTER` | Checkpointer 类型（pg/sqlite） | `sqlite` |

**金十 MCP 配置**:

| 变量 | 说明 |
|:------|:------|
| `JIN10_MCP_URL` | 金十 MCP 服务地址 |
| `JIN10_MCP_TOKEN` | 金十 MCP 认证 Token |
| `FDT_MCP_TIMEOUT` | MCP 客户端超时（秒，默认 30） |

**PostgreSQL 配置**:

| 变量 | 说明 |
|:------|:------|
| `FDT_PG_DSN` | PostgreSQL 连接字符串 |
| `FDT_PG_URL` | PostgreSQL 连接 URL（同 FDT_PG_DSN） |

**其他**:

| 变量 | 说明 | 默认值 |
|:------|:------|:-------|
| `FDT_CACHE_DIR` | 本地缓存目录 | `memory/fdt_cache` |
| `FDT_SCAN_MODE` | 扫描模式 | - |
| `FDT_STRATEGIES` | 指定策略列表 | - |
| `FDT_RISK_THRESHOLD` | CTP 信号风控阈值 | `yellow` |

### 6.4 运行模式

| 模式 | 说明 | 特点 |
|:------|:------|:------|
| `default` | 默认模式 | 完整流程：扫描→闫判官→四源并行→六阶段辩论→裁决→风控→质检→报告→CTP 信号 |
| `fast` | 快速模式 | 跳过辩论阶段（merge_research 后直接裁决） |
| `deep_research` | 深度研究 | 分歧度 > 0.7 时追加深度辩论 |
| `tournament` | 锦标赛模式 | 多轮辩论+投票（适用于重大决策） |

### 6.5 项目结构速览

```
FDT/
├── agents/                      # 13 个 Agent 配置文件 (.md)
├── config/                      # 配置文件（LLM/Agent/D3 Decode Control）
├── contracts/                   # 契约定义（A2A 数据信封/辩论 Schema/质检 Schema）
├── debate/                      # 辩论历史管理
├── docs/                        # 文档体系
│   └── harness/                 # Harness 工程规范（10 篇 + loop-contracts + schemas）
├── fdt_cache/                   # 本地 SQLite 增量缓存
├── fdt_langgraph/               # LangGraph 核心模块（3 子图）
├── fdt_pg/                      # PostgreSQL 模块
├── futures_data_core/           # 期货数据核心引擎
├── memory/                      # 知识库与记忆系统
├── scripts/                     # 80+ 辅助脚本
├── skills/                      # 10 个子技能实现
├── tests/                       # 1400+ 测试用例
├── fdt_cli.py                   # CLI 入口
├── fdt_api.py                   # FastAPI 入口
├── data_source_adapter.py       # 统一数据入口封装
├── pyproject.toml               # 项目元数据与构建配置
├── CLAUDE.md                    # 编码行为准则
├── CODE_WIKI.md                 # 技术百科全书（本文档）
└── README.md                    # 项目说明
```

---

## 7. 测试体系

### 7.1 测试目录结构

```
tests/
├── fdt_langgraph/               # LangGraph 核心测试（5 文件，43+ 用例）
├── strategies/                  # 策略测试（19 文件）
├── quant-daily/                 # 量化日常测试
├── commodity-chain/             # 产业链分析测试
├── debate-argument-builder/     # 辩论论据测试
├── debate-risk-manager/         # 风控测试
├── fdt-gate/                    # 质量门禁测试
├── fundamental-data-collector/  # 基本面采集测试
├── technical-analysis/          # 技术分析测试
├── contracts/                   # 契约测试
├── dominant-resolver/           # 主力合约解析测试
├── experience/                  # 经验记录测试
├── memory/                      # 记忆系统测试
├── pipeline/                    # 流水线测试
├── scheduler/                   # 调度引擎测试
├── validators/                  # 验证器测试
├── self-improve-enhanced/       # 自改进增强测试
└── conftest.py                  # 全局测试配置
```

合计：16 个测试子目录 / 1400+ 用例

### 7.2 测试命令

```bash
# 运行所有测试
python run_all_tests.py

# 运行特定模块测试
pytest tests/fdt_langgraph/ -v

# 运行基准对比测试
python scripts/run_benchmark.py --compare

# 运行金十 MCP 测试
pytest tests/fdt_langgraph/test_jin10_mcp.py -v
```

### 7.3 验证档位体系

| 档位 | 验证方式 | 适用场景 |
|:----:|:---------|:---------|
| L1 | Agent 自检 + JSON Schema | 报告型循环 |
| L2 | pytest 测试套件 | 中等风险 |
| L3 | 独立 Agent 审查 | 高风险 |

---

## 8. 开发规范

### 8.1 HARNESS 工程规范

项目遵循 HARNESS 工程规范，包含以下 10 篇核心文档 + 循环契约规范：

| # | 文档 | 内容 |
|:-:|:------|:------|
| 01 | [架构总览](docs/harness/01-architecture.md) | Harness 分层架构、组件关系图、数据流 |
| 02 | [生命周期](docs/harness/02-lifecycle.md) | 阶段定义、双层循环、循环契约 |
| 03 | [配置管理](docs/harness/03-configuration.md) | 配置文件清单、环境变量 |
| 04 | [错误恢复](docs/harness/04-resilience.md) | L1-L5 五层防线、降级策略 |
| 05 | [可观测性](docs/harness/05-observability.md) | 日志、指标、追踪 |
| 06 | [测试策略](docs/harness/06-testing.md) | 测试金字塔、契约校验 |
| 07 | [运维部署](docs/harness/07-operations.md) | 部署模式、版本历史 |
| 08 | [差距分析](docs/harness/08-gap-analysis.md) | 现状 vs 目标 |
| 09 | [晋级计划](docs/harness/09-advancement-plan.md) | 成熟度晋级路线 |
| 10 | [编码规范](docs/harness/10-coding-standards.md) | 文档先行、契约优先 |
| 11 | [循环契约规范](docs/harness/loop-contracts/README.md) | Loop Contract 六维度、验证档位 |

### 8.2 Commit 前 12 项检查

| # | 变更类型 | 对应文档 |
|:-:|:---------|:---------|
| 1 | 数据流/架构变更 | `docs/harness/01-architecture.md` |
| 2 | 阶段/文件名/产出物 | `02-lifecycle.md` / `04-resilience.md` |
| 3 | 新配置项 | `03-configuration.md` |
| 4 | 降级/熔断/超时 | `04-resilience.md` |
| 5 | 新指标/日志 | `05-observability.md` |
| 6 | 测试文件/用例数 | `06-testing.md` |
| 7 | 版本号和版本历史 | `07-operations.md` |
| 8 | 差距登记/关闭 | `08-gap-analysis.md` |
| 9 | 晋级里程碑 | `09-advancement-plan.md` |
| 10 | 流程文档同步 | `execution_modes_flowchart.md` / `business_flow.md` |
| 11 | 角色 MD 职责 | `agents/*.md` |
| 12 | 入口文档同步 | `CLAUDE.md` / `CODE_WIKI.md` / `README.md` |

### 8.3 反模式检测规则

| ID | 名称 | 严重度 | 检测条件 |
|:--:|:------|:------:|:---------|
| AP01 | 巨型 Prompt | P1 | AGENTS.md > 300 行 |
| AP02 | 跳过审核直接编码 | P0 | 无 plan/spec 直接提交 |
| AP03 | Rules 不维护 | P1 | harness-rules.yaml > 30 天未改 |
| AP04 | MCP 过度接入 | P2 | MCP 服务 > 10 个 |
| AP05 | Skill 不原子化 | P1 | 单 Skill > 200 行 |
| AP06 | 盲目信任 AI 输出 | P0 | 生产路径无独立验证 |
| AP07 | 循环无停止条件 | P0 | Loop Contract stop 为空 |
| AP08 | 多循环共写 STATE | P1 | 多 Loop 同 state 目录 |
| AP09 | Chat 历史当文档 | P2 | 知识仅在对话历史 |
| AP10 | 一个 PR 改所有 | P1 | PR > 20 文件 |

### 8.4 编码行为准则

1. **先思考，再编码** — 明确假设，列出多种解释
2. **简单至上** — 最小代码量，不写投机代码，不写过度的抽象和可配置性
3. **外科手术式修改** — 只动必须动的，只清理自己的烂摊子
4. **目标驱动执行** — 定义可验证的成功标准，循环验证直至达标
5. **HARNESS 工程规范优先** — 文档先行、契约优先、测试随重构

---

## 9. 附录

### A. 13 Agent 职责清单

| Agent | 职责 | 不做什么 |
|:------|:------|:---------|
| **数技源** | 跑 trend_following（10 子信号）管线产信号 | 不下方向结论 |
| **观澜** | 技术面分析（LLM 推理生成 TechnicalOutput） | 不判断多空 |
| **探源** | 基本面分析（LLM 推理生成 FundamentalStateVector） | 不判断多空 |
| **链证源** | 产业链关联分析 | 不下交易结论 |
| **读心** | 新闻情绪分析（LLM 推理生成 SentimentStateVector） | 不判断多空 |
| **多头分析员** | 独立列举 ≥3 条做多论据 | 禁止自行搜索 |
| **空头分析员** | 独立列举 ≥3 条做空论据 | 禁止自行搜索 |
| **闫判官** | P2 初判 + P5 终裁（含完整交易参数） | 不独立分析行情 |
| **副裁官** | 初审辩论输出，提取论点树（辅助评估） | 不独立判断 |
| **独立裁官** | 审计辩论一致性（不参与主流程） | 不参与裁决 |
| **风控明** | 直接基于闫判官 verdict 审核（green/yellow/red） | 不参与方向判断 |
| **品藻** | 辩论输出质检 + Schema 校验 + 内容安全过滤 | 不修改裁决内容 |
| **明鉴秋** | 选题/调度 + 汇总归档 + CTP 信号输出 | 不介入内容决策 |

### B. 策略管线

| 策略 | 类型 | 状态 | 说明 |
|:------|:------|:----:|:------|
| `trend_following` | 趋势跟踪 | 活跃 | **唯一活跃策略**，10 独立子信号（DC20/DC55/BB/Keltner/Supertrend/SAR/Chandelier/MACD/TSMOM/Dual Thrust） |
| `mean_reversion` | 价格反转 | 禁用 | RSI/CCI/BB 极端值回归 |
| `arbitrage` | 套利 | 禁用 | 跨品种产业链配对 Z-score |
| `pairs_reversion` | 配对回归 | 禁用 | EG 协整 + Hurst + KF z |
| `spread_reversion` | 近远月价差 | 禁用 | OU 拟合 + KF z |
| `basis_reversion` | 期现基差 | 禁用 | OU 拟合 + KF z |
| `macro_regime` | 宏观轮动 | 禁用 | 5 板块 46 品种制度切换 |
| `multi_factor` | 多因子加权 | 禁用 | 四维 13 因子评分 |

### C. 循环契约（Loop Contracts）

| 循环 ID | 名称 | 验证档位 | 权限 |
|:--------|:------|:---------|:-----|
| `daily-debate` | 每日自动辩论 | L3（独立 Agent 审查） | Write（含 CTP 信号） |
| `self-evolve` | 自进化闭环 | L2（测试套件） | Draft |
| `ml-training` | ML 模型训练循环 | L2（测试套件） | Draft |
| `health-check` | 健康自检循环 | L1（自检） | 只读 |
| `data-collection` | 数据采集循环 | L1（自检） | 只读 |

### D. 版本历史（v9.0+）

| 版本 | 核心变更 |
|:------|:---------|
| **v9.19.0** | Master Graph 稳定运行，14 个自动化任务全量在 LangGraph 中统一编排 |
| **v9.18.0** | Master Orchestrator Graph：全量自动化迁移至 LangGraph |
| **v9.14.0** | Phase 3 Data Governance：辩论输出质检+不合格退回重修 |
| **v9.13.0** | 逐品种独立辩论循环（prepare_one_symbol→四源→辩论→裁决→风控→store→route） |
| **v9.11.0** | 新闻情绪分析因子（读心 Agent）落地，P3 三源→四源并行 |
| **v9.10.0** | 金十数据 MCP 接入（mcp_client.py + jin10_mcp.py） |
| **v9.6.0** | Harness 工程全面升级（机读规则 + pre-commit + 10 条反模式） |
| **v9.5.0** | Loop Engineering 体系化（Loop Contract + 双层循环架构） |
| **v9.3.0** | 主力合约统一解析 + DataCore 集成 + 字段标准化 |
| **v9.1.0** | 本地增量缓存（fdt_cache/）+ 指定品种辩论模式 |
| **v9.0.0** | 六阶段攻防辩论（多头立论→空头结辩，来源可追溯） |

---

*文档版本: v9.19.0 | 最后更新: 2026-07-23 | 作者: FDT Contributors*