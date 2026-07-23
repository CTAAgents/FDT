# FDT Code Wiki — 期货辩论专家团技术百科全书

> **版本**: v9.18.0 | **最后更新**: 2026-07-23 | **定位**: 理解项目的技术基础文档

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

---

## 1. 项目概述

### 1.1 项目定位

**FDT (Futures Debate Team)** 是一套基于 **LangGraph** 构建的 **11-Agent 多角色交叉质询的 CTA 决策系统**。通过多 Agent 辩论制衡机制，实现期货市场的智能分析与交易信号生成。

### 1.2 核心特性

| 特性 | 说明 |
|:-----|:-----|
| 11-Agent 辩论制衡 | 数技源/闫判官/链证源/观澜/探源/读心/多头分析员/空头分析员/风控明/明鉴秋/品藻，另 2 辅助评估 Agent |
| 六阶段攻防辩论 | 多头立论→空头立论→空头驳论→多头反驳→空头结辩→多头结辩，辩手只做方向论证不自行搜索 |
| 逐品种循环处理 | v9.13.0 新增，每个品种独立循环执行 P3→P4→P5→质检→存储，全部完成汇聚 |
| 辩论输出质量治理 | v9.14.0 新增，Phase 3 Data Governance，不合格输出退回重修（最多2次） |
| 四源并行 LLM 推理 | 技术面/基本面/产业链/新闻情绪并行分析，任一源超时(300s)跳过其余继续 |
| NO_FUSION 零融合 | 通道突破(trend_following)含10子信号独立产出不融合；闫判官不做方向预判(始终neutral)，策略方向不入辩论层，仅品种入选辩论 |
| 自进化闭环 | LangGraph Evolution Graph 驱动：辩论完成后自动触发（`FDT_RUN_EVOLUTION=true`），或 `python fdt_cli.py evolve` 独立运行。基于 APM-CS 五轴评分卡(D1-D5)条件触发改进步骤：APM 退化→self_improve 提案，验证样本≥5→校准权重，总样本≥5→Agent 进化，新样本≥50→ML 增量训练。全部在 LangGraph 框架内运行，不依赖外部调度器 |
| 高置信入口门禁 | grade∈{STRONG,WATCH} 或 |total|≥40 进入辩论候选池（DEBATE_ENTRY_MIN_ABS=40） |
| 假突破拦截 | P0-4 六种验证器（raw_kline/volume_confirm/atr_vol_timing/trend_direction/stability/entity_quality）+ 全局 data_quality/crowding |

### 1.3 当前版本

**v9.18.0** — Master Orchestrator Graph：全量自动化迁移至 LangGraph，统一编排辩论/进化/数据采集/APM/发布，纯 Python datetime 调度，零第三方依赖。`fdt_cli.py daemon` 模式替换 APScheduler 为 LangGraph 守护进程。

---

## 2. 整体架构

### 2.1 系统分层

```
┌─────────────────────────────────────────────────────────────┐
│                    应用层 (Application)                      │
│  fdt_cli.py | fdt_api.py | fdt_daily_runner.py | pipeline/ │
├─────────────────────────────────────────────────────────────┤
│                    编排层 (Orchestration)                    │
│  fdt_langgraph/ (LangGraph)                                │
│    ├── graph.py      — 图结构定义与路由（含逐品种循环）      │
│    ├── nodes.py      — 节点函数（业务逻辑 + 报告生成）       │
│    ├── state.py      — 状态定义 (DebateState)               │
│    ├── agents.py     — Agent 执行器 + Decode Control        │
│    ├── health.py     — 健康检查                             │
│    ├── llm_provider.py — 独立 LLM 客户端（切断 scripts 依赖）│
│    ├── quality_inspector.py — 辩论输出质量质检器            │
│    ├── single_symbol_report.py — 单品种辩论报告生成器       │
│    ├── web_crawl_tool.py — Web 基本面采集 + 金十 MCP 工具   │
│    └── tools/registry.py — 工具注册中心                     │
├─────────────────────────────────────────────────────────────┤
│                    适配层 (Adapter)                         │
│  data_source_adapter.py — FDC ↔ Data-Core 统一接口         │
├─────────────────────────────────────────────────────────────┤
│                    数据层 (Data)                            │
│  futures_data_core/ — 期货数据核心                          │
│    ├── core/         — 多源降级链、缓存、类型、熔断器        │
│    ├── collectors/   — 数据采集器 (DataCore/TDX/QMT/TqSDK/Web) │
│    ├── f10/          — F10 衍生品数据（含金十MCP）          │
│    └── indicators/   — 技术指标                             │
├─────────────────────────────────────────────────────────────┤
│                    契约层 (Contracts)                       │
│  contracts/          — A2A数据信封、辩论论点Schema、质检Schema│
├─────────────────────────────────────────────────────────────┤
│                    存储层 (Storage)                         │
│  fdt_pg/    — PostgreSQL OLTP+OLAP                        │
│  memory/    — 知识库与记忆系统                             │
│  fdt_cache/ — SQLite 本地增量缓存                          │
├─────────────────────────────────────────────────────────────┤
│                    基础设施层 (Infrastructure)              │
│  schemas/   — JSON Schema 契约                             │
│  config/    — 配置文件（LLM/Agent 配置）                    │
│  agents/    — Agent 定义文档（13 个 .md 角色文件）           │
│  skills/    — 子技能实现                                   │
│  scripts/   — 辅助脚本                                     │
│  scheduler/ — 定时调度引擎 + 任务注册表                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 执行流程（逐品种循环模式 v9.13.0）

```
P1: 数技源通道突破(trend_following)扫描 → 全品种信号+stats
  → P2: 闫判官调度（基于stats选品种，始终不做方向预判）
                                            ↓
        ┌──────────────── 逐品种循环 ────────────────┐
        │  prepare_one_symbol (当前品种)              │
        │    ├─→ 链证源 (P3) →┐                       │
        │    ├─→ 观澜 (P3)   → merge_research        │
        │    ├─→ 探源 (P3)   →↓                      │
        │    └─→ 读心 (P3)   →↓                      │
        │                     ↓                      │
        │    merge_research → (fast→verdict, else→辩论)│
        │    → 多头立论 → 空头立论 → 空头反驳          │
        │    → 多头反驳 → 空头结辩 → 多头结辩           │
        │    → 闫判官裁决 → 风控审核                   │
        │    → 质检 (PASS→store, FAIL+<2→重修)         │
        │    → store_per_symbol_result                │
        │    → route_next_symbol                      │
        │       ┌─ 还有品种 → prepare_one_symbol      │
        │       └─ 全部完成 → aggregate_results        │
        └────────────────────────────────────────────┘
                                            ↓
                aggregate_results → 报告生成 (P6)
                → CTP 信号输出 → END
```

### 2.3 直接辩论模式（跳过扫描）

当 `FDT_DIRECT_DEBATE=true` 时启用：
```
load_cache → judge_direction → [逐品种循环] → ... → update_cache → END
```

### 2.4 数据降级链

数据源优先级（自动降级）：

| 优先级 | 采集器 | 说明 |
|:------:|:-------|:-----|
| 0 | DataCoreCollector | Data-Core 统一数据接口（最高优先级） |
| 1 | TDXCollector | 通达信本地 TQ-Local |
| 2 | WebFallbackCollector | 东方财富+新浪（2026-07-15 调整至 TqSDK 前） |
| 3 | QMTCollector | QMT/xtquant |
| 4 | TqSdkCollector | 天勤量化（末位兜底，关闭偶发挂死已由超时保护） |

**熔断机制**: 每个采集器独立熔断器，连续失败 5 次后自动屏蔽，冷却时间 60 秒。

---

## 3. 核心模块详解

### 3.1 fdt_langgraph — LangGraph 编排核心

#### 3.1.1 state.py — 状态定义

**DebateState** (TypedDict) — 辩论流程的全局状态容器：

| 字段 | 类型 | 说明 |
|:-----|:-----|:-----|
| `trace_id` | str | 全链路追踪 ID |
| `timestamp` | datetime | 时间戳 |
| `mode` | Literal | 运行模式 (default/fast/deep_research/tournament) |
| `scan_results` | dict | 数技源扫描结果 |
| `scan_summary` | Optional[dict] | 扫描汇总 |
| `judge_direction` | Optional[dict] | 闫判官方向预判 |
| `selected_symbols` | list | 选中辩论的品种列表 |
| `dispatch_sources` | list | 需要的数据源列表 |
| `fdc_data` | dict | FDC 预采集数据 |
| `fdc_data_status` | Optional[FdcDataStatus] | FDC 数据采集状态 |
| `chain_analysis` | Optional[dict] | 产业链分析结果 |
| `technical_data` | dict | 技术面分析结果 |
| `fundamental_data` | dict | 基本面分析结果 |
| `sentiment_data` | Optional[dict] | 新闻情绪分析结果（读心 Agent） |
| `research_data` | Optional[dict] | 合并后的研究数据 |
| `bullish_arguments` | Annotated[list, operator.add] | P4_1 多头立论论据 |
| `bearish_arguments` | Annotated[list, operator.add] | P4_2 空头立论论据 |
| `bearish_rebuttal_arguments` | Annotated[list, operator.add] | P4_3 空头反驳论据 |
| `bullish_rebuttal_arguments` | Annotated[list, operator.add] | P4_4 多头反驳论据 |
| `bear_final_arguments` | Annotated[list, operator.add] | P4_5 空头结辩论据 |
| `bull_final_arguments` | Annotated[list, operator.add] | P4_6 多头结辩论据 |
| `data_sources` | list | 数据溯源清单 |
| `debate_round` | int | 辩论轮次 |
| `verdict` | Optional[dict] | 闫判官裁决 |
| `risk_check` | Optional[dict] | 风控审核结果 |
| `signal_output` | Optional[dict] | CTP 信号输出 |
| `scan_report_path` | Optional[str] | P1 信号扫描报告路径 |
| `research_report_path` | Optional[str] | P3 研究报告路径 |
| `verdict_report_path` | Optional[str] | P5 裁决报告路径 |
| `report_path` | Optional[str] | P6 辩论报告路径 |
| `signal_report_path` | Optional[str] | P6a CTP 信号报告路径 |
| `current_phase` | str | 当前阶段 (P0-P6) |
| `error` | Optional[str] | 错误信息 |
| `completed_phases` | list | 已完成阶段列表 |
| `phase_start_time` | Optional[float] | 阶段开始时间 |
| `symbol_index` | int | **v9.13.0**: 当前处理品种索引（-1=未开始） |
| `per_symbol_results` | dict | **v9.13.0**: {symbol: {research, debate, verdict, risk}} |
| `_original_symbols` | list | **v9.13.0**: 完整品种列表备份 |
| `associated_symbols` | dict | **v9.13.0**: {primary_symbol: [associated_symbols]} 关联品种 |
| `quality_report` | Optional[dict] | **v9.14.0**: 当前质检结果 QualityReport |
| `rework_counters` | dict | **v9.14.0**: {symbol: retry_count} 品种级重试计数 |
| `rework_pending_symbols` | list | **v9.14.0**: 待退回重修的品种列表 |
| `phase_timings` | list | **v9.14.0**: [PhaseTiming] 各阶段耗时记录 |
| `quality_metrics` | Optional[dict] | **v9.14.0**: 自优化指标 QualityMetrics |

**FdcSymbolData** (TypedDict) — 单个品种的 FDC 数据结构：

| 字段 | 说明 |
|:-----|:-----|
| `kline` | K线数据（bars + meta + summary） |
| `indicators` | 技术指标（values + available） |
| `term_structure` | 期限结构 |
| `spread` | 跨期价差 |
| `basis` | 基差 |
| `warrant` | 仓单数据 |
| `fundamental` | 基本面数据 |
| `position_ranking` | 持仓排名 |
| `f10_summary` | F10 覆盖率汇总（available_fields/total_fields/coverage_pct） |
| `data_grades` | 数据质量等级（PRIMARY/SECONDARY/LLM_GENERATED/DERIVED/UNKNOWN） |

**FdcDataStatus** (TypedDict) — FDC 数据采集状态：

| 字段 | 说明 |
|:-----|:-----|
| `enabled` | 是否启用 FDC |
| `collected` | 是否已采集 |
| `total_symbols` | 总品种数 |
| `success_symbols` | 成功采集数 |
| `errors` | 错误信息 |
| `elapsed_seconds` | 耗时（秒） |
| `kline_days` | K线天数 |
| `f10_enabled` | 是否启用 F10 数据 |
| `position_ranking_enabled` | 是否启用持仓排名 |

#### 3.1.2 graph.py — 图结构与路由

**核心函数**:

| 函数 | 说明 |
|:-----|:-----|
| `build_debate_graph(mode)` | 构建完整辩论图（含 Checkpointer，支持 SQLite/PostgreSQL） |
| `build_debate_graph_no_checkpoint(mode)` | 构建无检查点的辩论图（支持 direct_debate 模式） |
| `build_debate_graph_with_profile(profile)` | 从 Profile 名称构建图（default/fast/deep_research/tournament） |
| `calculate_divergence(state)` | 计算多空分歧度（支持 v9.0 六阶段辩论） |
| `route_after_merge_research(state)` | P3 合并后路由决策（fast 模式跳过辩论直接裁决） |
| `route_after_quality_inspect(state)` | **v9.14.0**: 质检后路由（FAIL+重试<2→重修，否则→存储） |
| `_get_checkpointer()` | 获取检查点存储（SQLite 或 PostgreSQL） |

**图构建函数（v9.13.0 逐品种循环）**:

| 函数 | 说明 |
|:-----|:-----|
| `_register_per_symbol_loop(graph, mode)` | 注册逐品种循环流水线：scan → judge → [per-symbol: prepare→P3→辩论→裁决→风控→质检→store→route] → aggregate → report |
| `_register_direct_debate_loop(graph, mode)` | 直接辩论模式：load_cache → judge → [per-symbol loop] → update_cache |
| `_get_p3_node_names(mode)` | 根据 mode 返回需要激活的四源节点列表（chain/technical/fundamental/sentiment） |

**图执行流程（逐品种循环）**:

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

**路由函数**:

| 函数 | 说明 |
|:-----|:-----|
| `route_after_merge_research(state)` | P3 后决策：fast→verdict, 否则→bullish_v1 |
| `route_after_quality_inspect(state)` | 质检后决策：FAIL+重试<2→重修, 否则→存储 |
| `_get_current_symbol(state)` | 获取当前处理的品种代码 |

#### 3.1.3 nodes.py — 业务节点函数

**阶段节点**:

| 节点 | 函数 | 阶段 | 说明 |
|:-----|:-----|:-----|:-----|
| 扫描 | `node_scan()` | P1 | 数技源策略扫描（调用 scan_all.py，生成全品种信号） |
| 调度 | `node_judge_direction()` | P2 | 闫判官调度决策（基于 stats 特征判断方向和辩论品种） |
| 单品种准备 | `node_prepare_one_symbol()` | P2.5 | **v9.13.0**: 从 selected_symbols 中取出当前品种，准备 FDC 数据 |
| 产业链 | `node_chain()` | P3 | 链证源分析（调用 commodity-chain-analysis） |
| 技术面 | `node_technical()` | P3 | 观澜分析（LLM 推理，基于 FDC 技术数据） |
| 基本面 | `node_fundamental()` | P3 | 探源分析（LLM 推理，含金十快讯素材） |
| 情绪分析 | `node_sentiment()` | P3 | 读心分析（LLM 推理，金十+Web 多源新闻） |
| 合并研究 | `node_merge_research()` | P3 | 合并四源数据，准备辩论上下文 |
| 多头立论 | `node_bullish_v1()` | P4_1 | 多头分析员（列举 ≥3 条做多论据） |
| 空头立论 | `node_bearish_v1()` | P4_2 | 空头分析员（列举 ≥3 条做空论据） |
| 空头反驳 | `node_bearish_rebuttal()` | P4_3 | 空头反驳多头论据 |
| 多头反驳 | `node_bullish_rebuttal()` | P4_4 | 多头反驳空头论据 |
| 空头结辩 | `node_bear_final()` | P4_5 | 空头最终陈述 |
| 多头结辩 | `node_bull_final()` | P4_6 | 多头最终陈述 |
| 裁决 | `node_verdict()` | P5 | 闫判官裁决（输出完整交易参数：方向/入场/止损/目标/仓位） |
| 风控 | `node_risk_check()` | P5 | 风控明审核（风险等级判定、阻断机制） |
| 质检 | `node_quality_inspect()` | P5.5 | **v9.14.0**: 辩论输出质检（PASS/FAIL/SKIP，不合格退回重修） |
| 存储单品种 | `node_store_per_symbol_result()` | P5.75 | **v9.13.0**: 存储单品种裁决结果到 per_symbol_results |
| 路由下一品种 | `node_route_next_symbol()` | P5.8 | **v9.13.0**: 判断是否还有品种待处理 |
| 汇聚结果 | `node_aggregate_results()` | P5.9 | **v9.13.0**: 全部品种完成后汇总 |
| 报告 | `node_report()` | P6 | 明鉴秋报告（综合辩论结果生成 HTML 报告） |
| 信号输出 | `node_signal_output()` | P6a | CTP 信号输出（风控通过后生成交易信号） |
| 加载缓存 | `node_load_cache()` | - | 直接辩论模式：从缓存加载数据 |
| 更新缓存 | `node_update_cache()` | - | 直接辩论模式：更新缓存 |

**报告生成函数**（明鉴秋报告层调度）:

| 函数 | 说明 |
|:-----|:-----|
| `_write_scan_report()` | P1 信号扫描报告（品种/总分/ADX/RSI/价格/ATR/阶段） |
| `_write_research_report()` | P3 研究报告（产业链/技术面/基本面/情绪分析四源汇总） |
| `_write_verdict_report()` | P5 裁决报告（闫判官裁决 + 风控审核明细 + 新品种信号表） |
| `_write_signal_report()` | P6a CTP 信号报告（信号状态/风控等级/交易参数/全部清单） |
| `_render_html()` | 统一 HTML 报告模板（暖灰商务风，从 CSS 模板加载） |
| `_load_template_css()` | 从 docs/report-template/report_css.html 加载 CSS |
| `_resolve_report_dir()` | 解析报告输出目录（FDT_REPORT_WORKSPACE > FDT_DAILY_WORKSPACE > temp） |

**数据上下文构建函数**:

| 函数 | 说明 |
|:-----|:-----|
| `_build_fdc_technical_context()` | FDC 技术数据上下文（K线/指标/MA/区间/数技源 stats） |
| `_build_fdc_fundamental_context()` | FDC 基本面数据上下文（期限结构/基差/价差/仓单/持仓排名） |
| `_build_jin10_context()` | 金十快讯上下文（按品种自动搜索金十快讯） |
| `_build_debate_context()` | 辩论上下文（整合多空论据用于反驳阶段） |

**辩论协议常量**:

| 常量 | 说明 |
|:-----|:-----|
| `ATTACK_DIMENSIONS` | 攻击维度（data_lag/logic_jump/ignore_chain/false_breakout/liquidity_trap） |
| `EVIDENCE_WEIGHT_FACTORS` | 证据权重因子（timeliness:0.30/reliability:0.25/historical_winrate:0.25/regime_match:0.20） |
| `DEBATE_DIVERGENCE_THRESHOLDS` | 辩论分歧度阈值（skip_cross_examination:0.2/deep_debate:0.7） |

#### 3.1.4 agents.py — Agent 执行器 + Decode Control

**FdtAgentExecutor** — Agent 执行器类：

| 方法 | 说明 |
|:-----|:-----|
| `__init__(agent_config)` | 初始化（支持字符串名称或配置字典），自动加载 decode_config.yaml |
| `_apply_decode_config()` | **v9.15.0**: D3 Generation 解码控制，用 decode_config.yaml 覆盖 temperature/max_tokens |
| `execute(prompt, trace_id, **kwargs)` | 执行 Agent（同步），返回含 output/error/metadata 的 dict |
| `run(prompt, trace_id, **kwargs)` | 执行 Agent（异步包装，内部调用 execute） |
| `_call_llm(prompt, **kwargs)` | 调用 LLM API（httpx 客户端，支持重试） |
| `_resolve_llm_config(suffix, default)` | 解析逐 Agent LLM 配置（优先级：逐Agent环境变量 > 全局环境变量 > 默认值） |
| `_normalize_env_name(agent_name)` | 将 Agent 名称转换为环境变量命名格式 |

**D3 Generation 解码控制**:
- 配置文件: `config/agents/decode_config.yaml`
- 覆盖字段: `temperature`, `max_tokens`
- 优先级: decode_config.yaml > 逐Agent环境变量 > 全局环境变量 > 默认值

**逐 Agent LLM 配置环境变量**:
- `FDT_LLM_<NAME>_API_KEY` — 覆盖全局 API Key
- `FDT_LLM_<NAME>_API_BASE` — 覆盖全局 API Base URL
- `FDT_LLM_<NAME>_MODEL` — 覆盖全局模型名称

**AgentRegistry** — Agent 注册表（单例模式）：

| 方法 | 说明 |
|:-----|:-----|
| `register(agent_name, executor)` | 注册 Agent |
| `get(agent_name)` | 获取已注册的 Agent |
| `load_from_directory(dir)` | 从 agents/ 目录加载所有 .md Agent 定义文件 |
| `_parse_agent_md(md_path)` | 解析 Agent Markdown 定义文件（提取 role 和 system_prompt） |

#### 3.1.5 llm_provider.py — 独立 LLM 客户端

切断 `fdt_langgraph` ↔ `scripts` 的设计层面循环依赖。

**FdtLlm** — 独立 LLM 客户端：

| 方法 | 说明 |
|:-----|:-----|
| `__init__(agent_type)` | 初始化，从 config/llm_config.yaml 加载配置 |
| `_load_config(agent_type)` | 加载 LLM 配置（支持 per_agent 覆盖） |
| `chat(prompt, system, temperature, max_tokens)` | LLM 聊天调用（支持 Mock 模式） |

**Mock 模式**：`FDT_LLM_MOCK=true` 时启用模拟回复（闫判官/风控专用 mock 模板）。

**LLM 配置优先级**: `config/llm_config.yaml` per_agent > defaults > 硬编码默认值

#### 3.1.6 quality_inspector.py — 辩论输出质量质检器

**v9.14.0 新增** — Phase 3 Data Governance，纯函数无 IO。

| 函数 | 说明 |
|:-----|:-----|
| `validate_argument(data, symbol)` | 校验 P3 多头/空头论据数据（必填字段/类型/数量/置信度范围） |
| `validate_verdict(data)` | 校验 P4 闫判官裁决（必填字段/方向有效值/价格范围/置信度格式） |
| `validate_risk(data)` | 校验 P5 风控审核（必填字段/风险等级有效值/阻断逻辑） |
| `check_report_integrity(html_path)` | 检查 HTML 报告文件完整性（文件大小/基本结构） |

**质检规则来源**: `contracts/debate_quality_schema.py`（ARGUMENT_RULES / VERDICT_RULES / RISK_RULES）

#### 3.1.7 single_symbol_report.py — 单品种辩论报告

从 FDT state 中提取单品种辩论结果，生成精简 HTML 报告。

| 函数 | 说明 |
|:-----|:-----|
| `generate(state, trace_id, output_dir)` | 生成完整单品种报告 |
| `generate_body(state, sym)` | 生成单品种报告 body 部分（用于合并到最终报告） |
| `_extract_agent_output(state, agent_tag, sym)` | 从辩论论据中提取指定 Agent 的输出文字 |

#### 3.1.8 web_crawl_tool.py — Web 采集 + 金十 MCP 工具

LangChain @tool 封装层，暴露以下工具供 LLM Agent 调用：

| 工具名 | 说明 |
|:-------|:-----|
| `langchain_fetch_quote` | 获取品种实时行情 |
| `langchain_fetch_kline` | 获取品种 K 线数据 |
| `langchain_search_news` | 搜索最新期货行业新闻 |
| `langchain_jin10_list_flash` | 金十快讯列表（支持分页） |
| `langchain_jin10_search_flash` | 金十快讯关键字搜索 |
| `langchain_jin10_list_news` | 金十资讯列表 |
| `langchain_jin10_search_news` | 金十资讯搜索 |
| `langchain_jin10_get_news` | 金十资讯详情 |
| `langchain_jin10_list_calendar` | 金十财经日历 |
| `langchain_jin10_get_quote` | 金十行情（XAUUSD/USOIL等） |
| `langchain_jin10_get_kline` | 金十分时/K线数据 |

底层实现委托给 `futures_data_core.f10.web_collector` 和 `data_source_adapter`。

#### 3.1.9 health.py — 健康检查

**HealthChecker** — 健康检查器：

| 方法 | 说明 |
|:-----|:-----|
| `start_node(node_name)` | 记录节点开始时间 |
| `end_node(node_name)` | 记录节点结束时间，计算耗时 |
| `record_error(node_name, error)` | 记录节点错误（含时间戳） |
| `check_state_health(state)` | 检查状态健康度（trace_id/phase/超时检测） |
| `check_graph_health(config)` | 检查图配置健康度（节点/入口点/慢节点检测） |
| `get_summary()` | 获取健康检查摘要（总节点数/已完成/进行中/总耗时/错误数） |

**模块级便捷函数**:

| 函数 | 说明 |
|:-----|:-----|
| `get_health_checker()` | 获取全局健康检查器单例 |
| `run_health_check(state, graph_config)` | 运行健康检查（状态健康 + 图健康 + 摘要） |

#### 3.1.10 tools/registry.py — 工具注册中心

**ToolRegistry** — 工具注册中心（D2 Tool Phase 1）：

| 方法 | 说明 |
|:-----|:-----|
| `register(name, module_path, description, ...)` | 注册一个工具（含分类/版本/标签/依赖） |
| `get_tool(name)` | 获取工具信息 |
| `list_tools(category)` | 列出所有工具，支持按分类过滤 |
| `record_call(name, success)` | 记录工具调用统计 |
| `get_stats()` | 获取调用统计 |
| `get_summary()` | 获取注册汇总（总数/分类/统计） |

---

### 3.2 futures_data_core — 数据核心

#### 3.2.1 包级公开 API

| API | 说明 |
|:----|:-----|
| `get_kline(symbol, period, days, source)` | 获取 K 线数据，自动降级 |
| `get_quote(symbol, source)` | 获取行情快照 |
| `batch_get_quotes(symbols)` | 批量获取行情快照 |
| `compute_indicators(data, names, **params)` | 计算技术指标（本地 numpy 实现） |
| `get_adapter()` | 返回进程级 MultiSourceAdapter 单例 |
| `reset_adapter()` | 重置适配器单例（测试隔离） |
| `get_symbol(name)` / `is_known(name)` | 品种查询 |
| `list_exchanges()` / `list_symbols()` | 交易所/品种列表 |
| `evaluate(data, ...)` | 数据新鲜度评估 |

#### 3.2.2 core/ — 核心层

| 模块 | 说明 |
|:-----|:-----|
| `multi_source_adapter.py` | 多源降级链适配器（5 级采集器自动降级 + 熔断器） |
| `dominant_resolver.py` | 主力合约解析（品种代码→合约代码转换与换月追踪） |
| `circuit_breaker.py` | A1 级熔断器（状态机：CLOSED→OPEN→HALF_OPEN） |
| `cache_store.py` | 多级缓存（Postgres/Redis/Memory） |
| `field_normalizer.py` | 字段标准化（信号/裁决/风控/方向） |
| `data_freshness.py` | 数据新鲜度评估与等级计算 |
| `data_quality.py` | 数据质量评估（F10/指标/金十上下文） |
| `types.py` | 归一化数据载体（KlineBar/KlineData/QuoteData） |
| `symbol_registry.py` | 品种注册表（查询/校验/重载） |

**MultiSourceAdapter** — 多源降级链适配器：

| 方法 | 说明 |
|:-----|:-----|
| `register(collector)` | 注册/追加一个采集器 |
| `get_kline(symbol, period, days, source)` | 获取 K 线（自动降级，逐源尝试+熔断） |
| `get_contract_kline(contract, period, days)` | 按合约代码精确查询（跳过主力解析） |
| `get_quote(symbol, source)` | 获取行情快照 |
| `batch_get_quotes(symbols)` | 批量获取行情（双源融合） |
| `get_all_active_contracts(variety)` | 获取品种所有活跃合约月份 |
| `source_health()` | 获取各数据源熔断状态 |

**CircuitBreaker** — 熔断器状态机：

```
CLOSED（正常放行）→ 连续失败 ≥5 → OPEN（跳过该源，进入冷却60s）
  → cooldown 到期 → HALF_OPEN（放行一次探测）
    → 成功 → CLOSED（清零失败计数）
    → 失败 → OPEN（重置冷却计时）
```

#### 3.2.3 collectors/ — 数据采集器

| 采集器 | 类名 | 优先级 | 说明 |
|:-------|:-----|:------:|:-----|
| DataCore | `DataCoreCollector` | 0 | Data-Core 统一数据接口 |
| TDX | `TDXCollector` | 1 | 通达信本地 TQ-Local |
| Web | `WebFallbackCollector` | 2 | 东方财富+新浪（原为 4，2026-07-15 提前） |
| QMT | `QMTCollector` | 3 | QMT/xtquant |
| TqSdk | `TqSdkCollector` | 98 | 天勤量化（末位兜底） |

**BaseCollector** — 采集器抽象基类：

| 方法 | 说明 |
|:-----|:-----|
| `check_available()` | 探测当前环境是否可用（抽象方法） |
| `get_kline(symbol, period, days)` | 获取 K 线数据（抽象方法） |
| `get_quote(symbol)` | 获取行情快照（可选实现） |

**CollectorType** 运行模式枚举：`INDEPENDENT` / `LLM_ENHANCED` / `LLM_DRIVEN`

#### 3.2.4 f10/ — F10 衍生品数据

| 模块 | 说明 |
|:-----|:-----|
| `jin10_mcp.py` | 金十 MCP 采集器（行情/K线/快讯/资讯/财经日历） |
| `term_structure.py` | 期限结构分析 |
| `spread.py` | 跨期价差计算 |
| `basis.py` | 基差计算 |
| `warrant.py` | 仓单数据采集 |
| `fundamentals.py` | 基本面数据（含 LLM 增强采集） |
| `position.py` | 持仓排名数据 |
| `macro.py` | 宏观数据（PMI/利率等） |
| `sentiment.py` | 新闻情绪分析数据 |
| `exchange_scraper.py` | 交易所数据抓取 |
| `huishang.py` | 徽商期货数据接口 |
| `dce_api.py` | 大商所 API 接口 |
| `web_collector.py` | Web 数据采集器 |
| `web_collector_llm.py` | LLM 增强的 Web 数据采集器 |

#### 3.2.5 indicators/ — 技术指标

| 模块 | 说明 |
|:-----|:-----|
| `core.py` | 指标计算核心（compute_indicators + INDICATOR_NAMES） |
| `legacy_numpy.py` | numpy 纯函数实现（与 scan_all.py 完全兼容） |
| `tdx_compat.py` | TDX 兼容接口 |

#### 3.2.6 mcp_client.py — MCP 协议客户端

**McpHttpClient** — 标准 MCP 协议 HTTP 客户端：

| 方法 | 说明 |
|:-----|:-----|
| `initialize()` | 初始化会话（协议版本 2025-11-25） |
| `list_tools()` / `list_resources()` | 列出可用工具/资源 |
| `call_tool(name, args)` | 调用工具 |
| `read_resource(uri)` | 读取资源 |

协议流程: `initialize → notifications/initialized → tools/list → tools/call`

---

### 3.3 contracts — 契约定义

#### 3.3.1 a2a_payload.py — A2A 数据信封

**A2APayload** (dataclass) — 统一数据输出信封（Agent-to-Agent 协议规范）：

| 字段 | 类型 | 说明 |
|:-----|:-----|:-----|
| `type` | str | 数据类型标识（如 `"fdc.basis"` / `"fdt.debate"`） |
| `runtime_mode` | str | 运行模式（`"independent"` / `"llm_enhanced"`） |
| `meta` | dict | 元信息（数据等级、来源、时效等） |
| `data` | dict | 纯业务数据 |
| `summary` | str | 自然语言描述（≤200字） |
| `jsonrpc` | str | 协议版本（默认 `"2.0"`） |
| `method` | str | 协议方法（默认 `"tasks/send"`） |

**数据等级常量**:

| 常量 | 值 | 说明 | 优先级 |
|:-----|:---|:-----|:------:|
| `GRADE_PRIMARY` | `"PRIMARY"` | 一手数据（交易所直采） | 0 |
| `GRADE_SECONDARY` | `"SECONDARY"` | 二手数据（聚合/加工） | 1 |
| `GRADE_LLM` | `"LLM_GENERATED"` | LLM 生成（含推理） | 2 |
| `GRADE_DERIVED` | `"DERIVED"` | 衍生计算（指标/模型） | 3 |
| `GRADE_UNKNOWN` | `"UNKNOWN"` | 等级未确定 | 9 |

**快捷构造器**:

| 函数 | 说明 |
|:-----|:-----|
| `a2a_basis(symbol, spot_price, futures_price, source)` | 构造基差数据信封 |
| `a2a_inventory(symbol, inventory, change_pct, source)` | 构造库存数据信封 |
| `a2a_debate(symbol, decision, confidence, reasoning, entry, stop_loss, target)` | 构造辩论裁决信封 |
| `a2a_scan_summary(total_symbols, triggered, generated_at)` | 构造扫描汇总信封 |

#### 3.3.2 debate_argument_schema.py — 辩论论点 Schema

**ArgumentItem** (TypedDict) — 单条论据（v1.1 · 2026-07-15 机制重构）：

| 字段 | 类型 | 必填 | 说明 |
|:-----|:-----|:----:|:-----|
| `id` | str | ✅ | 论据唯一 ID（如 `"多头-D3"`） |
| `family` | StrategyFamily | ✅ | 策略族标签 (F1-F5) |
| `claim` | str | ✅ | 一句话可证伪断言 |
| `evidence` | str | ✅ | 数据支撑（数值+来源+日期） |
| `reasoning` | str | ✅ | 推理链 |
| `impact` | Literal["HIGH", "MEDIUM", "LOW"] | ✅ | 重要性 |
| `rebuts` | Optional[list[str]] | - | 反驳的目标论点 ID 列表 |
| `rebuttal_type` | Optional[str] | - | 反驳类型（因果倒置/数据过时/样本偏差/推理跳跃/忽视反证/直接质疑证据） |
| `rebuttal_detail` | Optional[str] | - | 反驳的具体拆解 |

**ArgumentRound** (TypedDict) — 一轮辩论发言：

| 字段 | 类型 | 说明 |
|:-----|:-----|:-----|
| `round` | str | 轮次标识（如 `"RB_20260709_r1"`） |
| `speaker` | Literal["bullish", "bearish"] | 发言人：多头/空头 |
| `phase` | Literal["opening", "rebuttal", "free_debate", "final"] | 辩论阶段 |
| `target` | Optional[str] | 反驳阶段引用的对方论点 ID |
| `arguments` | list[ArgumentItem] | 本轮论点列表（最少 2 条，最多 5 条） |
| `concedes` | Optional[list[str]] | 承认对方有效的论点 ID 列表 |
| `family_coverage` | Optional[int] | 本轮论据覆盖的策略族数 |

**StructuredDebateArgument** (TypedDict) — 辩手输出的顶层 JSON 结构：

| 字段 | 类型 | 说明 |
|:-----|:-----|:-----|
| `meta` | dict | 包含 phase/agent_name/version/target_symbol |
| `arguments` | list[ArgumentItem] | 论点列表 |

**StrategyFamily** (Literal) — 策略族枚举：

| 值 | 说明 |
|:---|:-----|
| `F1` | 技术面量价：均线/ADX/RSI/BB/成交量等 |
| `F2` | 基本面供需：库存/基差/利润/供需平衡表 |
| `F3` | 持仓资金：主力持仓/持仓量变化/净多空比 |
| `F4` | 宏观政策：利率/贸易/地缘/产业政策 |
| `F5` | 套利结构：跨期价差/跨品种价差/展期收益 |

#### 3.3.3 debate_quality_schema.py — 辩论质量校验 Schema

**v9.14.0 新增** — Phase 3 Data Governance 标准定义：

| 类型 | 说明 |
|:-----|:-----|
| `QualityReport` | 质检报告（status: PASS/FAIL/SKIP + issues 列表） |
| `QualityIssue` | 质检问题（field/message/severity） |
| `ArgumentSchema` | P3 论据 Schema（symbol/arguments/confidence/source_refs） |
| `VerdictSchema` | P4 裁决 Schema（symbol/direction/entry/stop_loss/target/confidence） |
| `RiskSchema` | P5 风控 Schema（symbol/risk_level/approved/warnings） |

**ARGUMENT_RULES**: required_fields=["symbol", "arguments", "confidence"], min_arguments=1, max_arguments=10
**VERDICT_RULES**: required_fields=["symbol", "direction", "confidence", "entry_price", "stop_loss", "target1"]
**RISK_RULES**: required_fields=["symbol", "risk_level", "approved"]

#### 3.3.4 experience_schema.py — 经验数据 Schema

定义经验记录的结构化格式，用于自进化闭环中的经验存储和复用。

#### 3.3.5 migrations.py — 数据库迁移

数据库 Schema 迁移脚本管理。

---

### 3.4 data_source_adapter.py — 数据源适配层

统一 FDC ↔ Data-Core 接口。通过 `FDT_DATA_SOURCE` 环境变量控制：

| 值 | 说明 |
|:---|:-----|
| `fdc`（默认）| 使用 `futures_data_core` 包 |
| `datacore` | 使用 `datacore.fdc_compat` 包 |

**环境变量配置**:

| 环境变量 | 说明 | 默认值 |
|:---------|:-----|:------:|
| `FDT_DATA_SOURCE` | 适配器数据源类型 | `fdc` |
| `FDT_FDC_INJECTION_ENABLED` | 是否启用 FDC 数据注入（P2.5 节点） | `true` |
| `FDT_DATA_CORE_API_URL` | Data-Core API 地址 | `http://localhost:8080` |

**核心函数**:

| 函数 | 说明 |
|:-----|:-----|
| `get_kline(symbol, period, days, source)` | 获取 K 线数据（自动降级） |
| `get_contract_kline(contract, period, days, source)` | 按合约代码获取 K 线 |
| `get_quote(symbol, source)` | 获取行情快照 |
| `batch_get_quotes(symbols)` | 批量获取行情 |
| `get_term_structure(symbol)` | 获取期限结构 |
| `get_basis(symbol)` | 获取基差 |
| `get_spread(symbol)` | 获取跨期价差 |
| `get_inventory(symbol)` | 获取库存 |
| `get_position_ranking(symbol)` | 获取持仓排名 |
| `get_jin10_news(symbol)` | 获取金十快讯 |
| `get_f10_data(symbol)` | 获取 F10 综合数据 |
| `jin10_available()` | 金十 MCP 是否可用 |
| `jin10_list_flash(cursor)` | 获取金十快讯列表 |
| `jin10_search_flash(keyword, cursor)` | 搜索金十快讯 |
| `jin10_list_news(cursor)` | 获取金十资讯列表 |
| `jin10_search_news(keyword, cursor)` | 搜索金十资讯 |
| `jin10_get_news(news_id)` | 获取金十资讯详情 |
| `jin10_list_calendar()` | 获取金十财经日历 |
| `jin10_get_quote(code)` | 获取金十行情 |
| `jin10_get_kline(code, time, count)` | 获取金十 K 线 |
| `set_data_source(source)` | 动态切换数据源（测试用） |

**内部辅助函数**:

| 函数 | 说明 |
|:-----|:-----|
| `get_data_source()` | 返回当前数据源名称 |
| `_get_source_module()` | 根据环境变量动态加载数据源模块 |

**适配层工作原理**:
```
调用方 → data_source_adapter.get_kline() → 动态加载模块 → 执行对应实现
                                              ↓
                              futures_data_core / datacore_adapter
```

---

### 3.5 fdt_pg — PostgreSQL 模块

PostgreSQL OLTP+OLAP 数据库模块。

| 文件 | 说明 |
|:-----|:-----|
| `connection.py` | 连接管理（单例模式，支持连接池） |
| `schema.py` | ORM 模型定义（DebateRecord/SignalHistory/ExperienceRecord） |
| `deploy.py` | 部署工具（数据库初始化、迁移执行） |
| `migrations/` | 数据库迁移脚本（按版本顺序） |

**PGConfig**: 从环境变量读取配置（PG_HOST/PG_PORT/PG_DATABASE/PG_USERNAME/PG_PASSWORD）
**PGConnection**: 连接池管理（QueuePool, 10 最大连接）

**环境变量**: `FDT_PG_URL` — PostgreSQL 连接 URL

---

### 3.6 ~~pipeline 模块包含全自动零人工干预流水线，现已完全被 LangGraph 图编排替代（见 §3.8）。~~

---

### 3.7 scheduler — 定时调度引擎

#### 3.7.1 engine.py — 心跳发动机

**SchedulerEngine** — 调度发动机：

| 参数 | 说明 |
|:-----|:-----|
| `triggers` | 触发器列表（默认用 `get_default_triggers()`） |
| `heartbeat_interval` | 心跳间隔秒数（默认60） |
| `max_tasks_per_beat` | 每次心跳最多触发的任务数（默认3） |

**运行模式**:
- `run_forever()` — 后台守护进程，每60秒心跳
- `run_once()` — 单次检查，适合集成到自循环前置

**心跳循环**: `[启动] → 每60秒 → 检查所有触发器 → 触发匹配的任务 → 记录日志`

#### 3.7.2 triggers.py — 触发器定义

| 类型 | 说明 |
|:-----|:-----|
| `TimeTrigger` | 按时间/星期触发（如：工作日19:15） |
| `DataTrigger` | 按数据量触发（如：≥50条新样本训练ML） |
| `EventTrigger` | 按事件触发（如：新K线就绪、辩论完成） |

每个触发器返回 `(should_fire: bool, reason: str)`。

#### 3.7.3 tasks.py — 预注册任务

| 任务 | 说明 |
|:-----|:-----|
| `daily_debate()` | 日常辩论全量管道（4步：扫描→准备数据→报告生成→复制到工作空间），由 TRAE Schedule 每日 20:15 触发 |
| `validate_and_evolve()` | 自进化闭环（验证裁决→校准权重→Agent参数进化→ML训练检查），由 scheduler DataTrigger 在新裁决数据后自动触发 |
| `self_optimize_analyze()` | 自改进分析（self_improve.py --mode=analyze），由 DataTrigger 触发 |
| `self_optimize_evolve()` | 自改进进化（skillevolver_evolution.py），由 TimeTrigger 触发 |
| `self_optimize_verify()` | 自改进验证（verify_evolution.py --ab-test），由 TimeTrigger 触发 |
| `auto_publish()` | 自动发布（版本号自增 + Git推送） |
| `update_dominant_mapping()` | 更新主力合约映射表 |
| `apm_scorecard()` | APM 五轴评分卡计算 |
| `test_daily_debate()` | 测试用日常辩论 |

**任务注册机制**: `@register_task(name)` 装饰器 → `_task_registry` 字典 → `get_task(name)` 查找

**调度架构**:
- 所有自动化任务由 `fdt_langgraph/master_graph.py` Master Orchestrator Graph 驱动（纯 Python datetime 调度，零第三方依赖）
- 守护进程: `python fdt_cli.py daemon [--interval 60]`（LangGraph `run_master_daemon()` 循环，替代了外部 APScheduler）
- 单次检查到期任务: `python fdt_cli.py master`
- 原有 `scheduler/` 目录保留为兼容层，新开发全部走 LangGraph

---

## 4. 关键类与函数

### 4.1 核心类速查

| 类 | 模块 | 说明 |
|:---|:-----|:-----|
| `DebateState` | `fdt_langgraph.state` | 辩论流程全局状态（TypedDict，支持增量更新） |
| `FdcSymbolData` | `fdt_langgraph.state` | FDC 品种数据结构（K线/指标/期限结构/基差/仓单/持仓排名） |
| `FdcDataStatus` | `fdt_langgraph.state` | FDC 数据采集状态 |
| `FdtAgentExecutor` | `fdt_langgraph.agents` | Agent 执行器（支持逐 Agent LLM 配置 + D3 Decode Control） |
| `AgentRegistry` | `fdt_langgraph.agents` | Agent 注册表（单例，从 agents/ 目录加载） |
| `FdtLlm` | `fdt_langgraph.llm_provider` | 独立 LLM 客户端（切断 scripts 依赖，支持 Mock 模式） |
| `HealthChecker` | `fdt_langgraph.health` | 健康检查器（节点耗时/错误追踪/状态健康检查） |
| `ToolRegistry` | `fdt_langgraph.tools.registry` | 工具注册中心（注册/发现/统计） |
| `MultiSourceAdapter` | `futures_data_core.core.multi_source_adapter` | 多源降级链适配器（支持 5 级数据源自动降级） |
| `DominantResolver` | `futures_data_core.core.dominant_resolver` | 主力合约解析器 |
| `CircuitBreaker` | `futures_data_core.core.circuit_breaker` | 熔断器（A1 级，CLOSED→OPEN→HALF_OPEN 状态机） |
| `BaseCollector` | `futures_data_core.collectors.base` | 采集器抽象基类 |
| `McpHttpClient` | `futures_data_core.mcp_client` | MCP 协议 HTTP 客户端 |
| `A2APayload` | `contracts.a2a_payload` | 统一数据信封（Agent-to-Agent 协议） |
| `ArgumentItem` | `contracts.debate_argument_schema` | 辩论论据结构（v1.1，含策略族标签和反驳类型） |
| `ArgumentRound` | `contracts.debate_argument_schema` | 一轮辩论发言结构 |
| `StructuredDebateArgument` | `contracts.debate_argument_schema` | 辩手输出顶层 JSON 结构 |
| `QualityReport` | `contracts.debate_quality_schema` | 质检报告（PASS/FAIL/SKIP + issues） |
| `HealthChecker` | `fdt_langgraph.health` | LangGraph 健康检查器 |
| `PGConnection` | `fdt_pg.connection` | PostgreSQL 连接管理（单例+连接池） |
| `SchedulerEngine` | `scheduler.engine` | 调度发动机（心跳/触发/任务执行） |

### 4.2 核心函数速查

| 函数 | 模块 | 说明 |
|:-----|:-----|:-----|
| `build_debate_graph(mode)` | `fdt_langgraph.graph` | 构建辩论图（含 Checkpointer） |
| `build_debate_graph_no_checkpoint(mode)` | `fdt_langgraph.graph` | 构建无检查点的辩论图（支持 direct_debate） |
| `build_debate_graph_with_profile(profile)` | `fdt_langgraph.graph` | 从 Profile 名称构建图 |
| `calculate_divergence(state)` | `fdt_langgraph.graph` | 计算多空分歧度 |
| `route_after_merge_research(state)` | `fdt_langgraph.graph` | P3 合并后路由决策 |
| `route_after_quality_inspect(state)` | `fdt_langgraph.graph` | 质检后路由决策 |
| `create_initial_state(trace_id, mode)` | `fdt_langgraph.state` | 创建初始状态 |
| `validate_argument(data, symbol)` | `fdt_langgraph.quality_inspector` | P3 论据质检 |
| `validate_verdict(data)` | `fdt_langgraph.quality_inspector` | P4 裁决质检 |
| `validate_risk(data)` | `fdt_langgraph.quality_inspector` | P5 风控质检 |
| `check_report_integrity(html_path)` | `fdt_langgraph.quality_inspector` | HTML 报告完整性检查 |
| `node_scan(state)` | `fdt_langgraph.nodes` | P1 数技源策略扫描 |
| `node_judge_direction(state)` | `fdt_langgraph.nodes` | P2 闫判官调度决策 |
| `node_prepare_one_symbol(state)` | `fdt_langgraph.nodes` | P2.5 单品种数据准备（v9.13.0） |
| `node_merge_research(state)` | `fdt_langgraph.nodes` | P3 合并四源数据 |
| `node_verdict(state)` | `fdt_langgraph.nodes` | P5 闫判官裁决 |
| `node_risk_check(state)` | `fdt_langgraph.nodes` | P5 风控审核 |
| `node_quality_inspect(state)` | `fdt_langgraph.nodes` | P5.5 辩论输出质检（v9.14.0） |
| `node_store_per_symbol_result(state)` | `fdt_langgraph.nodes` | P5.75 存储单品种结果（v9.13.0） |
| `node_route_next_symbol(state)` | `fdt_langgraph.nodes` | P5.8 路由下一品种（v9.13.0） |
| `node_aggregate_results(state)` | `fdt_langgraph.nodes` | P5.9 全部品种汇聚（v9.13.0） |
| `node_report(state)` | `fdt_langgraph.nodes` | P6 明鉴秋报告 |
| `run_health_check(state, graph_config)` | `fdt_langgraph.health` | 运行健康检查 |
| `get_kline(symbol, period, days, source)` | `data_source_adapter` | 获取 K 线（自动降级） |
| `jin10_search_flash(keyword, cursor)` | `data_source_adapter` | 搜索金十快讯 |
| `jin10_list_flash(cursor)` | `data_source_adapter` | 金十快讯列表 |
| `jin10_list_calendar()` | `data_source_adapter` | 金十财经日历 |
| `normalize_signal_list(signals)` | `futures_data_core.core.field_normalizer` | 标准化信号列表 |
| `normalize_verdict(verdict)` | `futures_data_core.core.field_normalizer` | 标准化裁决输出 |
| `a2a_debate(symbol, decision, ...)` | `contracts.a2a_payload` | 构造辩论裁决信封 |
| `a2a_scan_summary(total_symbols, ...)` | `contracts.a2a_payload` | 构造扫描汇总信封 |
| `new_trace(prefix)` | `scripts.core.trace_id` | 生成新的 trace_id |
| `current_trace()` | `scripts.core.trace_id` | 获取当前 trace_id |
| `inject_trace_to_env()` | `scripts.core.trace_id` | 注入 trace_id 到环境变量（子进程透传） |

---

## 5. 数据流与依赖关系

### 5.1 模块依赖关系

```
fdt_cli / fdt_api / fdt_daily_runner
    ↓
fdt_langgraph (graph → nodes → agents → state → health → quality_inspector → llm_provider)
    ↓
data_source_adapter
    ↓
futures_data_core (multi_source_adapter → collectors → f10 → indicators → mcp_client)
    ↓
contracts (a2a_payload → debate_argument_schema → debate_quality_schema)
    ↓
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
  ├── P1: scan_all.py → trend_following(10子信号)扫描 → stats+scan_results+scan_summary（闫判官只看 stats 不看策略方向）
  ├── P2: 闫判官 → 基于 stats 选品种，始终返回 neutral（不做方向预判）→ judge_direction + selected_symbols
  ├── 逐品种循环开始:
  │   ├── P2.5: prepare_one_symbol → 取出当前品种，FDC 数据准备
  │   ├── P3: 四源并行分析 → chain_analysis + technical_data + fundamental_data + sentiment_data
  │   ├── P4: 六阶段辩论 → bullish/bearish/rebuttal/final_arguments
  │   ├── P5: 闫判官裁决 + 风控审核 → verdict + risk_check
  │   ├── P5.5: 质检 → PASS→store, FAIL+重试<2→重修
  │   └── P5.75: store_per_symbol_result → route_next_symbol
  ├── 逐品种循环结束:
  │   ├── P5.9: aggregate_results → 全部品种汇聚
  │   └── P6: 报告生成 + CTP 信号 → report_path + signal_output

[输出层]
  ├── HTML 报告文件 (scan/research/verdict/signal/debate_report)
  ├── CTP 交易信号 (signal_output)
  ├── PostgreSQL 持久化 (DebateRecord/SignalHistory)
  ├── SQLite 缓存 (fdt_cache)
  └── 辩论历史记录 (memory/debates/)
```

### 5.3 数据降级链

```
请求 → MultiSourceAdapter → DataCoreCollector → PRIMARY
                          ↓ 失败
                          → TDXCollector → PRIMARY
                          ↓ 失败
                          → WebFallbackCollector → DAILY
                          ↓ 失败
                          → QMTCollector → DAILY
                          ↓ 失败
                          → TqSdkCollector → DAILY
                          ↓ 全部失败
                          → 缓存 → CACHED
                          ↓ 缓存未命中
                          → UNAVAILABLE
```

每个采集器独立熔断器：连续失败 5 次 → 屏蔽 60 秒

### 5.4 外部依赖

| 依赖 | 用途 | 版本 |
|:-----|:-----|:-----|
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
| apscheduler | 定时调度 | ≥3.10 |
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

# 定时调度模式
python fdt_cli.py daemon --cron "<expr>"

# 数据库操作
python fdt_cli.py db init    # 初始化 Schema
python fdt_cli.py db health  # 健康检查
```

### 6.2 API 入口

```bash
python fdt_api.py
```

**API 端点**:

| 端点 | 方法 | 说明 |
|:-----|:-----|:-----|
| `/health` | GET | 健康检查 |
| `/api/v1/debate` | POST | 触发辩论（异步，返回 trace_id） |
| `/api/v1/debate/{trace_id}` | GET | 查询辩论状态 |
| `/api/v1/status` | GET | 任务运行统计 |

### 6.3 环境变量

**核心配置**:

| 变量 | 说明 | 默认值 |
|:-----|:-----|:-------|
| `FDT_LLM_API_KEY` | LLM API Key | 同 `OPENAI_API_KEY` |
| `FDT_LLM_API_BASE` | LLM API Base URL | `https://api.deepseek.com/v1` |
| `FDT_LLM_MODEL` | LLM 模型名称 | `deepseek-chat` |
| `FDT_PG_DSN` | PostgreSQL 连接字符串 | - |
| `FDT_CHECKPOINTER` | Checkpointer 类型 (`sqlite` / `pg`) | `sqlite` |
| `FDT_DIRECT_DEBATE` | 指定品种直接辩论模式 | `false` |
| `FDT_DEBATE_SYMBOLS` | 指定辩论品种列表 | - |
| `FDT_DATA_SOURCE` | 数据源类型 (`fdc` / `datacore`) | `fdc` |
| `FDT_LLM_MOCK` | LLM Mock 模式（测试用） | `false` |

**逐 Agent LLM 配置**:
- `FDT_LLM_<NAME>_API_KEY`
- `FDT_LLM_<NAME>_API_BASE`
- `FDT_LLM_<NAME>_MODEL`

**FDC 数据注入配置**:

| 变量 | 说明 | 默认值 |
|:-----|:-----|:-------|
| `FDT_FDC_INJECTION_ENABLED` | 启用 FDC 数据注入 | `true` |
| `FDT_FDC_KLINE_DAYS` | K线数据天数 | `120` |
| `FDT_FDC_F10_ENABLED` | 启用 F10 数据 | `true` |
| `FDT_FDC_POSITION_RANKING_ENABLED` | 启用持仓排名 | `true` |

**报告输出配置**:

| 变量 | 说明 |
|:-----|:-----|
| `FDT_REPORT_WORKSPACE` | 报告输出根目录（优先） |
| `FDT_DAILY_WORKSPACE` | 每日工作空间（降级） |
| `FDT_GENERATE_INTERMEDIATE_REPORTS` | 是否生成中间报告（research/verdict/signal） |

**金十 MCP 配置**:

| 变量 | 说明 |
|:-----|:-----|
| `JIN10_MCP_URL` | 金十 MCP 服务地址 |
| `JIN10_MCP_TOKEN` | 金十 MCP 认证 Token |

### 6.4 运行模式

| 模式 | 说明 | 特点 |
|:-----|:-----|:-----|
| `default` | 默认模式 | 完整流程：扫描→闫判官→四源并行→六阶段辩论→裁决→风控→质检→报告→CTP 信号输出 |
| `fast` | 快速模式 | 跳过辩论阶段（merge_research 后直接裁决） |
| `deep_research` | 深度研究 | 分歧度 > 0.7 时追加深度辩论 |
| `tournament` | 锦标赛模式 | 多轮辩论+投票（适用于重大决策） |

---

## 7. 测试体系

### 7.1 测试目录结构

```
tests/
├── fdt_langgraph/      # LangGraph 核心测试（5 文件，43+ 用例）
├── strategies/         # 策略测试（19 文件）
├── quant-daily/        # 量化日常测试（scan_all/debate/history）
├── commodity-chain/     # 产业链分析测试
├── debate-argument-builder/ # 辩论论据测试
├── debate-risk-manager/ # 风控测试
├── fdt-gate/           # 质量门禁测试
├── fundamental-data-collector/ # 基本面采集测试
├── technical-analysis/  # 技术分析测试
├── contracts/          # 契约测试
├── dominant-resolver/  # 主力合约解析测试
├── experience/         # 经验记录测试
├── memory/             # 记忆系统测试
├── pipeline/           # 流水线测试
├── scheduler/          # 调度引擎测试
├── validators/         # 验证器测试
└── conftest.py         # 全局测试配置
```

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

项目遵循 HARNESS 工程规范，包含以下文档：

| # | 文档 | 内容 |
|:-:|:-----|:-----|
| 01 | [架构总览](docs/harness/01-architecture.md) | Harness 分层架构、组件关系图 |
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

1. 数据流/架构变更 → [01-architecture.md](docs/harness/01-architecture.md)
2. 阶段/文件名/产出物 → [02-lifecycle.md](docs/harness/02-lifecycle.md) / [04-resilience.md](docs/harness/04-resilience.md)
3. 新配置项 → [03-configuration.md](docs/harness/03-configuration.md)
4. 降级/熔断/超时 → [04-resilience.md](docs/harness/04-resilience.md)
5. 新指标/日志 → [05-observability.md](docs/harness/05-observability.md)
6. 测试文件和用例数 → [06-testing.md](docs/harness/06-testing.md)
7. 版本号和版本历史 → [07-operations.md](docs/harness/07-operations.md)
8. 差距登记/关闭 → [08-gap-analysis.md](docs/harness/08-gap-analysis.md)
9. 晋级里程碑 → [09-advancement-plan.md](docs/harness/09-advancement-plan.md)
10. 流程文档同步 → [execution_modes_flowchart.md](docs/harness/execution_modes_flowchart.md) / [business_flow.md](docs/harness/business_flow.md)
11. 角色 MD 职责 → [agents/](agents/)
12. 入口文档同步 → [CLAUDE.md](CLAUDE.md) / [CODE_WIKI.md](CODE_WIKI.md) / [README.md](README.md)

### 8.3 反模式检测规则

| ID | 名称 | 严重度 |
|:--:|:-----|:------:|
| AP01 | 巨型 Prompt | P1 |
| AP02 | 跳过审核直接编码 | P0 |
| AP03 | Rules 不维护 | P1 |
| AP04 | MCP 过度接入 | P2 |
| AP05 | Skill 不原子化 | P1 |
| AP06 | 盲目信任 AI 输出 | P0 |
| AP07 | 循环无停止条件 | P0 |
| AP08 | 多循环共写 STATE | P1 |
| AP09 | Chat 历史当文档 | P2 |
| AP10 | 一个 PR 改所有 | P1 |

### 8.4 编码行为准则

1. **先思考，再编码** — 明确假设，列出多种解释
2. **简单至上** — 最小代码量，不写投机代码
3. **外科手术式修改** — 只动必须动的，清理自己的烂摊子
4. **目标驱动执行** — 定义可验证的成功标准
5. **HARNESS 优先** — 文档先行、契约优先、测试随重构

---

## 附录

### A. 11 Agent 职责清单

| Agent | 职责 | 不做什么 |
|:------|:-----|:---------|
| 数技源 | 跑 trend_following（10 子信号）管线产信号 | 不下方向结论 |
| 观澜 | 技术面分析（LLM 推理生成 TechnicalOutput） | 不判断多空 |
| 探源 | 基本面分析（LLM 推理生成 FundamentalStateVector，含金十快讯素材） | 不判断多空 |
| 链证源 | 产业链关联分析 | 不下交易结论 |
| 读心 | 新闻情绪分析（LLM 推理生成 SentimentStateVector，金十+Web 多源） | 不判断多空 |
| 多头分析员 | 独立列举 ≥3 条做多论据 | 不做空头分析 |
| 空头分析员 | 独立列举 ≥3 条做空论据 | 不做多头分析 |
| 闫判官 | 裁决方向 + 输出完整交易参数 | 不独立分析行情 |
| 风控明 | 直接基于闫判官 verdict 审核 | 不参与方向判断 |
| 品藻 | 辩论输出质检 + Schema 校验 + 内容安全过滤 + 报告排版核验 | 不修改裁决内容 |
| 明鉴秋 | 选题/调度 + 汇总归档 + CTP 信号输出 | 不介入内容决策 |

另有 2 个辅助评估 Agent：**副裁官**（初审辩论输出，提取论点树）和**独立裁官**（审计辩论一致性，不参与主流程）。

### B. 策略管线（实际运行）

| 策略 | 类型 | 说明 |
|:-----|:-----|:------|
| `trend_following` | 趋势跟踪 | **唯一活跃策略**，内含 10 独立子信号（DC20/DC55/BB/Keltner/Supertrend/SAR/Chandelier/MACD/TSMOM/Dual Thrust），独立产 RawSignal 不融合 |

其余 9 个策略（multi_factor/ml_signal/event_driven/arbitrage/mean_reversion/pairs_reversion/spread_reversion/basis_reversion/macro_regime）因数据源或模型未就绪，已在 settings.py 中永久禁用。详见 [skills/quant-daily/scripts/config/settings.py](file:///d:/Programs/FDT/skills/quant-daily/scripts/config/settings.py) 第 16-26 行。|

### C. 循环契约

| 循环 ID | 名称 | 验证档位 | 权限 |
|:--------|:-----|:---------|:-----|
| `daily-debate` | 每日自动辩论 | L3 | Write |
| `self-evolve` | 自进化闭环 | L2 | Draft |
| `ml-training` | ML 模型训练 | L2 | Draft |
| `health-check` | 健康自检 | L1 | 只读 |
| `data-collection` | 数据采集 | L1 | 只读 |

---

*文档版本: v9.16.0 | 最后更新: 2026-07-23 | 作者: FDT Contributors*