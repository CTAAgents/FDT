# FDT Code Wiki — 期货辩论专家团技术百科全书

> **版本**: v9.11.2 | **最后更新**: 2026-07-22 | **定位**: 理解项目的技术基础文档

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

**FDT (Futures Debate Team)** 是一套基于 **LangGraph** 构建的 **10-Agent 多角色交叉质询的 CTA 决策系统**。通过多 Agent 辩论制衡机制，实现期货市场的智能分析与交易信号生成。

### 1.2 核心特性

| 特性 | 说明 |
|:-----|:-----|
| 10-Agent 辩论制衡 | 数技源/闫判官/链证源/观澜/探源/读心/多头分析员/空头分析员/风控明/明鉴秋 |
| 六阶段攻防辩论 | 多头立论→空头立论→空头驳论→多头驳论→空头结辩→多头结辩 |
| 四源并行 LLM 推理 | 技术面/基本面/产业链/新闻情绪并行分析 |
| NO_FUSION 策略管线 | 8 策略独立打分，方向冲突不融合 |
| 自进化闭环 | T+1 验证 → 权重校准 → Agent 进化 → ML 增量训练 |
| 三层信号门禁 | 震荡市检测 + 去趋势 + P0-4 伪突破拦截 |
| 5 层鲁棒防线 | 产出校验→熔断降级→信号门禁→路径发现→健康自检 |

### 1.3 版本历史

| 版本 | 关键变更 |
|:-----|:---------|
| v9.11.0 | 新闻情绪分析因子落地，P3 四源并行 |
| v9.10.0 | 金十数据 MCP 接入 |
| v9.6.0 | Harness 工程规范全面升级 |
| v9.0.0 | 六阶段攻防辩论模式 |
| v8.4.0 | LangGraph 迁移完成 |

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
│    ├── graph.py      — 图结构定义与路由                      │
│    ├── nodes.py      — 节点函数（业务逻辑）                  │
│    ├── state.py      — 状态定义 (DebateState)               │
│    ├── agents.py     — Agent 执行器                        │
│    └── health.py     — 健康检查                            │
├─────────────────────────────────────────────────────────────┤
│                    适配层 (Adapter)                         │
│  data_source_adapter.py — FDC ↔ Data-Core 统一接口         │
├─────────────────────────────────────────────────────────────┤
│                    数据层 (Data)                            │
│  futures_data_core/ — 期货数据核心                          │
│    ├── core/         — 多源降级链、缓存、类型、熔断器        │
│    ├── collectors/   — 数据采集器 (TDX/QMT/TqSDK/Web/Datacore) │
│    ├── f10/          — F10 衍生品数据（含金十MCP）          │
│    └── indicators/   — 技术指标                            │
├─────────────────────────────────────────────────────────────┤
│                    契约层 (Contracts)                       │
│  contracts/          — A2A数据信封、辩论论点Schema          │
├─────────────────────────────────────────────────────────────┤
│                    存储层 (Storage)                         │
│  fdt_pg/    — PostgreSQL OLTP+OLAP                        │
│  memory/    — 知识库与记忆系统                             │
│  fdt_cache/ — SQLite 本地增量缓存                          │
├─────────────────────────────────────────────────────────────┤
│                    基础设施层 (Infrastructure)              │
│  schemas/   — JSON Schema 契约                             │
│  config/    — 配置文件                                     │
│  agents/    — Agent 定义文档                               │
│  skills/    — 子技能实现                                   │
│  scripts/   — 辅助脚本                                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
数据采集 (P1) → 策略扫描 → 闫判官调度 (P2) → FDC数据准备 (P2.5)
                                            ↓
              ┌───────────┬───────────┬───────────┬───────────┐
              ▼           ▼           ▼           ▼
          链证源       观澜         探源       读心 (P3)
              │           │           │           │
              └───────────┴───────────┴───────────┘
                          ↓
              合并研究数据 → 多头立论 (P4_1) → 空头立论 (P4_2)
                          → 空头反驳 (P4_3) → 多头反驳 (P4_4)
                          → 空头结辩 (P4_5) → 多头结辩 (P4_6)
                          ↓
                      闫判官裁决 (P5) → 风控审核 → 报告生成 → CTP信号输出 (P6)
```

### 2.3 数据降级链

数据源优先级（自动降级）：

| 优先级 | 采集器 | 说明 |
|:------:|:-------|:-----|
| 0 | DataCoreCollector | Data-Core 统一数据接口（最高优先级） |
| 1 | TDXCollector | 通达信本地 TQ-Local |
| 2 | TqSdkCollector | 天勤量化 |
| 3 | QMTCollector | QMT/xtquant |
| 4 | WebFallbackCollector | 东方财富+新浪（最后兜底） |

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
| `build_debate_graph_no_checkpoint(mode)` | 构建无检查点的辩论图（快速执行） |
| `build_debate_graph_with_profile(profile)` | 从 Profile 名称构建图（default/fast/deep_research/tournament） |
| `calculate_divergence(state)` | 计算多空分歧度（支持 v9.0 六阶段辩论） |
| `route_after_merge_research(state)` | P3 合并后路由决策（fast 模式跳过辩论直接裁决） |
| `_get_checkpointer()` | 获取检查点存储（SQLite 或 PostgreSQL） |

**图节点注册**:

| 函数 | 说明 |
|:-----|:-----|
| `_register_common_nodes()` | P1/P2/P2.5/P5/P6 公共节点（扫描/调度/数据准备/裁决/风控/报告/信号输出） |
| `_register_p3_nodes()` | P3 四源并行节点（链证源/观澜/探源/读心），支持按模式选择性注册 |
| `_register_debate_nodes()` | P4 六阶段辩论节点（多头立论→空头立论→空头反驳→多头反驳→空头结辩→多头结辩） |
| `_register_direct_debate_nodes()` | 跳过 P1 扫描的直接辩论模式（load_cache → judge_direction → ... → update_cache） |

**图执行流程**:

```
scan → judge_direction → prepare_data → [chain/technical/fundamental/sentiment] → merge_research
                                        ↓ (并行)
merge_research → (fast模式→verdict, 否则→bullish_v1)
bullish_v1 → bearish_v1 → bearish_rebuttal → bullish_rebuttal → bear_final → bull_final → verdict
verdict → risk_check → report → signal_output → END
```

#### 3.1.3 nodes.py — 业务节点函数

**阶段节点**:

| 节点 | 函数 | 阶段 | 说明 |
|:-----|:-----|:-----|:-----|
| 扫描 | `node_scan()` | P1 | 数技源策略扫描（调用 scan_all.py，生成全品种信号） |
| 调度 | `node_judge_direction()` | P2 | 闫判官调度决策（基于 stats 特征判断方向和辩论品种） |
| 数据准备 | `node_prepare_data()` | P2.5 | FDC 预采集数据（K线/指标/期限结构/基差/仓单/基本面/持仓排名） |
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
| 报告 | `node_report()` | P6 | 明鉴秋报告（综合辩论结果生成 HTML 报告） |
| 信号输出 | `node_signal_output()` | P6a | CTP 信号输出（风控通过后生成交易信号） |
| 加载缓存 | `node_load_cache()` | - | 直接辩论模式：从缓存加载数据 |
| 更新缓存 | `node_update_cache()` | - | 直接辩论模式：更新缓存 |

**报告生成函数**（v8.8.0 明鉴秋报告层调度）:

| 函数 | 说明 |
|:-----|:-----|
| `_write_scan_report()` | P1 信号扫描报告（品种/总分/ADX/RSI/价格/ATR/阶段） |
| `_write_research_report()` | P3 研究报告（产业链/技术面/基本面/情绪分析四源汇总） |
| `_write_verdict_report()` | P5 裁决报告（闫判官裁决 + 风控审核明细） |
| `_write_signal_report()` | P6a CTP 信号报告（信号状态/风控等级/交易参数） |
| `_render_html()` | 统一 HTML 报告模板（暗黑主题） |
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

#### 3.1.4 agents.py — Agent 执行器

**FdtAgentExecutor** — Agent 执行器类：

| 方法 | 说明 |
|:-----|:-----|
| `__init__(agent_config)` | 初始化（支持字符串名称或配置字典） |
| `execute(prompt, trace_id, **kwargs)` | 执行 Agent（同步），返回含 output/error/metadata 的 dict |
| `run(prompt, trace_id, **kwargs)` | 执行 Agent（异步包装，内部调用 execute） |
| `_call_llm(prompt, **kwargs)` | 调用 LLM API（httpx 客户端，支持重试） |
| `_resolve_llm_config(suffix, default)` | 解析逐 Agent LLM 配置（优先级：逐Agent环境变量 > 全局环境变量 > 默认值） |
| `_normalize_env_name(agent_name)` | 将 Agent 名称转换为环境变量命名格式 |

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

**DebateAgentExecutor** — 辩论 Agent 执行器：

| 方法 | 说明 |
|:-----|:-----|
| `__init__()` | 初始化，自动加载 agents/ 目录中的所有 Agent |
| `execute_agent(agent_name, prompt, trace_id, **kwargs)` | 执行单个 Agent |
| `execute_parallel(tasks)` | 并行执行多个 Agent（tasks 为 dict 列表） |
| `run_single(agent_name, context, output, system_override, temperature, max_tokens, json_mode)` | 运行单个 Agent（简易接口，调用 fdt_llm.FdtLlm） |

#### 3.1.5 health.py — 健康检查

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

**健康检查输出字段**:

| 字段 | 说明 |
|:-----|:-----|
| `status` | healthy 或 degraded |
| `n_issues` | 问题数量 |
| `issues` | 问题列表（level/rule/msg） |
| `node_durations` | 各节点耗时（秒） |
| `n_errors` | 错误数量 |
| `errors` | 错误列表（node/error/timestamp） |

---

### 3.2 futures_data_core — 数据核心

#### 3.2.1 core/multi_source_adapter.py — 多源降级链

**MultiSourceAdapter** — 多源降级链适配器：

| 方法 | 说明 |
|:-----|:-----|
| `__init__(collectors, cache, resolver)` | 初始化（可选自定义采集器、缓存、主力解析器） |
| `register(collector)` | 注册/追加一个采集器（保持优先级有序） |
| `get_kline(symbol, period, days, source)` | 获取 K 线（自动降级，支持指定数据源） |
| `get_contract_kline(contract, period, days, source)` | 按合约代码精确查询 K 线（不经过主力解析） |
| `get_quote(symbol, source)` | 获取行情快照（自动降级） |
| `batch_get_quotes(symbols)` | 批量获取行情快照（双源融合用） |
| `get_all_active_contracts(variety)` | 获取品种所有活跃合约月份 |
| `source_health()` | 获取各数据源熔断状态（closed/open/half_open） |

**数据源优先级**（2026-07-15 调整）:
1. `DataCoreCollector` — Data-Core 统一数据接口（最高优先级）
2. `TDXCollector` — 通达信本地 TQ-Local
3. `TqSdkCollector` — 天勤量化
4. `QMTCollector` — QMT/xtquant
5. `WebFallbackCollector` — 东方财富+新浪（最后兜底）

**熔断机制**:
- 每个采集器独立熔断器（`CircuitBreaker`）
- 连续失败 5 次后自动屏蔽（`failure_threshold=5`）
- 冷却时间 60 秒（`cooldown=60.0`）

**数据等级约定**:
- `tdx_tq_local` / `tqsdk` / `qmt_xtquant` 成功 → `PRIMARY`
- 其他实时源成功 → `DAILY`
- 缓存命中 → `CACHED`
- 全部失败 → `UNAVAILABLE`

#### 3.2.2 core/dominant_resolver.py — 主力合约解析

统一主力合约判定与换月追踪，支持品种代码到合约代码的转换。

#### 3.2.3 core/field_normalizer.py — 字段标准化

统一规范各 Agent 输出字段：

| 函数 | 说明 |
|:-----|:-----|
| `normalize_signal_list(signals)` | 标准化信号列表（direction/total/grade/confidence） |
| `normalize_verdict(verdict)` | 标准化裁决输出 |
| `normalize_risk_check(risk_check)` | 标准化风控审核输出 |
| `normalize_direction_raw(direction)` | 标准化方向字段（统一 bull/bear/neutral） |

#### 3.2.4 core/circuit_breaker.py — 熔断器

实现 A1 级数据源熔断保护，支持 `state()` 查询和 `record_success()` / `record_failure()` 记录。

#### 3.2.5 core/cache_store.py — 缓存存储

Redis/PostgreSQL/Memory 多级缓存存储，支持 K 线和行情数据的缓存读写。

#### 3.2.6 f10/ — F10 衍生品数据

| 模块 | 说明 |
|:-----|:-----|
| `jin10_mcp.py` | 金十 MCP 采集器（8 工具：行情/K线/快讯/资讯/财经日历） |
| `term_structure.py` | 期限结构分析 |
| `spread.py` | 跨期价差计算 |
| `basis.py` | 基差计算（期货价格 vs 现货价格） |
| `warrant.py` | 仓单数据采集 |
| `fundamental.py` | 基本面数据 |
| `position.py` | 持仓排名数据 |
| `macro.py` | 宏观数据（PMI/利率等） |
| `sentiment.py` | 新闻情绪分析数据 |
| `exchange_scraper.py` | 交易所数据抓取 |
| `huishang.py` | 徽商期货数据接口 |
| `dce_api.py` | 大商所 API 接口 |
| `web_collector.py` | Web 数据采集器 |
| `web_collector_llm.py` | LLM 增强的 Web 数据采集器 |

#### 3.2.7 indicators/ — 技术指标

| 模块 | 说明 |
|:-----|:-----|
| `core.py` | 指标计算核心 |
| `legacy_numpy.py` | numpy 纯函数实现（与 scan_all.py 完全兼容） |
| `tdx_compat.py` | TDX 兼容接口 |
| `trend_maturity.py` | 趋势成熟度指标 |

#### 3.2.8 collectors/ — 数据采集器

| 采集器 | 类名 | 说明 |
|:-------|:-----|:-----|
| DataCore | `DataCoreCollector` | Data-Core 统一数据接口 |
| TDX | `TDXCollector` | 通达信本地 TQ-Local |
| TqSdk | `TqSdkCollector` | 天勤量化 SDK |
| QMT | `QMTCollector` | QMT/xtquant |
| Web | `WebFallbackCollector` | 东方财富+新浪（兜底） |

#### 3.2.9 mcp_client.py — MCP 协议客户端

标准 MCP 协议 HTTP 客户端，支持：
- SSE 解析
- 会话管理
- structuredContent 优先
- 标准协议流程（initialize → notifications/initialized → tools/list/resources/list → tools/call）

---

### 3.3 contracts — 契约定义

#### 3.3.1 a2a_payload.py — A2A 数据信封

**A2APayload** (dataclass) — 统一数据输出信封（符合 Agent-to-Agent 协议规范）：

| 字段 | 类型 | 说明 |
|:-----|:-----|:-----|
| `type` | str | 数据类型标识（如 `"fdc.basis"` / `"fdt.debate"`） |
| `runtime_mode` | str | 运行模式（`"independent"` / `"llm_enhanced"`） |
| `meta` | dict | 元信息（数据等级、来源、时效等） |
| `data` | dict | 纯业务数据 |
| `summary` | str | 自然语言描述（≤200字） |
| `jsonrpc` | str | 协议版本（默认 `"2.0"`） |
| `method` | str | 协议方法（默认 `"tasks/send"`） |

**方法**:

| 方法 | 说明 |
|:-----|:-----|
| `to_dict()` | 序列化为普通 dict，确保必备 meta 键存在 |
| `to_json(**kw)` | 序列化为 JSON 字符串 |

**运行模式常量**:
- `RUNTIME_INDEPENDENT` — 纯数据，无 LLM 参与
- `RUNTIME_LLM` — LLM 参与分析/合成

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

**RebuttalType** (Literal) — 反驳类型枚举：

| 值 | 说明 |
|:---|:-----|
| `因果倒置` | 因果关系颠倒 |
| `数据过时` | 使用过期数据 |
| `样本偏差` | 样本选择有偏差 |
| `推理跳跃` | 逻辑推理不连贯 |
| `忽视反证` | 忽略反面证据 |
| `直接质疑证据` | 直接质疑证据的可靠性 |

#### 3.3.3 experience_schema.py — 经验数据 Schema

定义经验记录的结构化格式，用于自进化闭环中的经验存储和复用。

#### 3.3.4 migrations.py — 数据库迁移

数据库 Schema 迁移脚本管理。

---

### 3.4 data_source_adapter.py — 数据源适配层

统一 FDC ↔ Data-Core 接口，支持按环境变量切换数据源实现，实现无缝迁移。

**环境变量配置**:

| 环境变量 | 说明 | 默认值 |
|:---------|:-----|:------:|
| `FDT_DATA_SOURCE_ADAPTER` | 适配器模块名 | `futures_data_core` |
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
| `jin10_search_flash(symbol)` | 搜索金十快讯 |
| `jin10_list_news(symbol)` | 获取金十资讯列表 |

**内部辅助函数**:

| 函数 | 说明 |
|:-----|:-----|
| `_get_source_module()` | 根据环境变量动态加载数据源模块 |
| `_get_fdc_instance()` | 获取 FDC 单例实例 |

**适配层工作原理**:
```
调用方 → data_source_adapter.get_kline() → 动态加载模块 → 执行对应实现
                                              ↓
                              futures_data_core / datacore_adapter
```

---

### 3.5 fdt_pg — PostgreSQL 模块

PostgreSQL OLTP+OLAP 数据库模块，用于存储辩论记录、信号历史、经验数据等。

| 文件 | 说明 |
|:-----|:-----|
| `connection.py` | 连接管理（单例模式，支持连接池） |
| `schema.py` | ORM 模型定义（DebateRecord/SignalHistory/ExperienceRecord） |
| `deploy.py` | 部署工具（数据库初始化、迁移执行） |
| `migrations/` | 数据库迁移脚本（按版本顺序） |

**环境变量**:
- `FDT_PG_URL` — PostgreSQL 连接 URL（默认：`postgresql://postgres:postgres@localhost:5432/fdt`）

---

### 3.6 pipeline — 流水线执行

**runner.py** — 全自动零人工干预流水线（v8.8.0 重构）：

**核心函数**:

| 函数 | 说明 |
|:-----|:-----|
| `main()` | 全自动管道主流程入口 |
| `run_langgraph_pipeline(trace_id)` | LangGraph 模式执行 |
| `run_subprocess_pipeline(trace_id)` | subprocess 模式执行（回退） |
| `clean_xgboost_warning()` | 清理 XGBoost 警告 |

**流水线步骤**:

| 步骤 | 函数 | 说明 |
|:-----|:-----|:-----|
| Step 1 | `step_scan()` | 通道突破信号生成（调用 scan_all.py） |
| Step 2 | `step_chain_analysis()` | 产业链分析（调用 commodity-chain-analysis） |
| Step 3 | `step_debate_brief()` | 辩论品种精选（闫判官调度） |
| Step 4 | `step_assemble_intermediate()` | 数据适配（FDC 数据注入） |
| Step 5 | `step_generate_report()` | 深度分析报告（明鉴秋报告层） |
| Step 6 | `step_record_history()` | 历史记录 + ML 检查（持久化到 PostgreSQL） |

**A/B 切换机制**:
- `FDT_USE_LANGGRAPH=true` → LangGraph 模式（优先）
- LangGraph 模式不可用时自动回退到 subprocess 模式

**trace_id 全链路**:
- 生成 trace_id 后注入所有子进程环境变量
- 贯穿：扫描 → 辩论 → 裁决 → 风控 → 报告 → 信号输出

---

## 4. 关键类与函数

### 4.1 核心类速查

| 类 | 模块 | 说明 |
|:---|:-----|:-----|
| `DebateState` | `fdt_langgraph.state` | 辩论流程全局状态（TypedDict，支持增量更新） |
| `FdcSymbolData` | `fdt_langgraph.state` | FDC 品种数据结构（K线/指标/期限结构/基差/仓单/持仓排名） |
| `FdcDataStatus` | `fdt_langgraph.state` | FDC 数据采集状态（enabled/collected/sources/errors） |
| `FdtAgentExecutor` | `fdt_langgraph.agents` | Agent 执行器（支持逐 Agent LLM 配置） |
| `AgentRegistry` | `fdt_langgraph.agents` | Agent 注册表（单例，从 agents/ 目录加载） |
| `DebateAgentExecutor` | `fdt_langgraph.agents` | 辩论 Agent 执行器（支持并行执行） |
| `HealthChecker` | `fdt_langgraph.health` | 健康检查器（节点耗时/错误追踪/状态健康检查） |
| `MultiSourceAdapter` | `futures_data_core.core.multi_source_adapter` | 多源降级链适配器（支持 5 级数据源自动降级） |
| `DominantResolver` | `futures_data_core.core.dominant_resolver` | 主力合约解析器（品种代码→合约代码转换） |
| `CircuitBreaker` | `futures_data_core.core.circuit_breaker` | 熔断器（A1 级数据源熔断保护） |
| `A2APayload` | `contracts.a2a_payload` | 统一数据信封（Agent-to-Agent 协议规范） |
| `ArgumentItem` | `contracts.debate_argument_schema` | 辩论论据结构（v1.1，含策略族标签和反驳类型） |
| `ArgumentRound` | `contracts.debate_argument_schema` | 一轮辩论发言结构 |
| `StructuredDebateArgument` | `contracts.debate_argument_schema` | 辩手输出顶层 JSON 结构 |

### 4.2 核心函数速查

| 函数 | 模块 | 说明 |
|:-----|:-----|:-----|
| `build_debate_graph(mode)` | `fdt_langgraph.graph` | 构建辩论图（含 Checkpointer） |
| `build_debate_graph_no_checkpoint(mode)` | `fdt_langgraph.graph` | 构建无检查点的辩论图 |
| `build_debate_graph_with_profile(profile)` | `fdt_langgraph.graph` | 从 Profile 名称构建图 |
| `calculate_divergence(state)` | `fdt_langgraph.graph` | 计算多空分歧度 |
| `route_after_merge_research(state)` | `fdt_langgraph.graph` | P3 合并后路由决策 |
| `create_initial_state(trace_id, mode)` | `fdt_langgraph.state` | 创建初始状态 |
| `node_scan(state)` | `fdt_langgraph.nodes` | P1 数技源策略扫描 |
| `node_judge_direction(state)` | `fdt_langgraph.nodes` | P2 闫判官调度决策 |
| `node_prepare_data(state)` | `fdt_langgraph.nodes` | P2.5 FDC 数据准备 |
| `node_merge_research(state)` | `fdt_langgraph.nodes` | P3 合并四源数据 |
| `node_verdict(state)` | `fdt_langgraph.nodes` | P5 闫判官裁决 |
| `node_risk_check(state)` | `fdt_langgraph.nodes` | P5 风控审核 |
| `node_report(state)` | `fdt_langgraph.nodes` | P6 明鉴秋报告 |
| `run_health_check(state, graph_config)` | `fdt_langgraph.health` | 运行健康检查 |
| `get_kline(symbol, period, days, source)` | `data_source_adapter` | 获取 K 线（自动降级） |
| `get_contract_kline(contract, period, days, source)` | `data_source_adapter` | 按合约代码获取 K 线 |
| `get_quote(symbol, source)` | `data_source_adapter` | 获取行情快照 |
| `jin10_search_flash(symbol)` | `data_source_adapter` | 搜索金十快讯 |
| `normalize_signal_list(signals)` | `futures_data_core.core.field_normalizer` | 标准化信号列表 |
| `normalize_verdict(verdict)` | `futures_data_core.core.field_normalizer` | 标准化裁决输出 |
| `a2a_debate(symbol, decision, ...)` | `contracts.a2a_payload` | 构造辩论裁决信封 |
| `a2a_scan_summary(total_symbols, ...)` | `contracts.a2a_payload` | 构造扫描汇总信封 |

---

## 5. 数据流与依赖关系

### 5.1 模块依赖关系

```
fdt_cli / fdt_api / fdt_daily_runner
    ↓
fdt_langgraph (graph → nodes → agents → state → health)
    ↓
data_source_adapter
    ↓
futures_data_core (multi_source_adapter → collectors → f10 → indicators → mcp_client)
    ↓
contracts (a2a_payload → debate_argument_schema)
    ↓
fdt_pg / fdt_cache / memory / schemas
```

**依赖说明**:
- `fdt_langgraph` 依赖 `data_source_adapter` 和 `contracts`
- `data_source_adapter` 依赖 `futures_data_core`（动态加载）
- `futures_data_core` 依赖 `contracts.a2a_payload` 输出数据信封
- 所有模块共享 `fdt_pg` / `fdt_cache` / `memory` 存储层

### 5.2 数据流向

```
[输入层]
  ├── 环境变量配置 (FDT_*)
  ├── Agent 定义文档 (agents/*.md)
  ├── 品种知识库 (memory/knowledge/)
  ├── 数据源配置 (config/data_sources.yaml)
  └── LLM 配置 (config/llm.yaml)

[处理层 — 六阶段流水线]
  ├── P1: scan_all.py → 策略扫描 → scan_results + scan_summary
  ├── P2: 闫判官 → 方向预判 + 品种选择 → judge_direction + selected_symbols
  ├── P2.5: FDC 预采集 → fdc_data + fdc_data_status
  ├── P3: 四源并行分析 → chain_analysis + technical_data + fundamental_data + sentiment_data
  ├── P4: 六阶段辩论 → bullish_arguments + bearish_arguments + rebuttal_arguments + final_arguments
  ├── P5: 闫判官裁决 + 风控审核 → verdict + risk_check
  └── P6: 报告生成 + CTP 信号 → report_path + signal_output

[输出层]
  ├── HTML 报告文件 (scan/research/verdict/signal)
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
                          → TqSdkCollector → PRIMARY
                          ↓ 失败
                          → QMTCollector → PRIMARY
                          ↓ 失败
                          → WebFallbackCollector → SECONDARY
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
| python-dotenv | 环境变量加载 | ≥1.0 |
| tenacity | 重试机制 | ≥8.0 |
| pyyaml | YAML 配置解析 | ≥6.0 |
| aiofiles | 异步文件操作 | ≥23.0 |
| beautifulsoup4 | HTML 解析 | ≥4.12 |
| lxml | XML/HTML 解析器 | ≥5.0 |
| tqsdk | 天勤量化 SDK | ≥2.0 |

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
| `/api/v1/debate` | POST | 触发辩论（异步） |
| `/api/v1/debate/{trace_id}` | GET | 查询辩论状态 |
| `/api/v1/status` | GET | 任务运行统计 |

### 6.3 环境变量

**核心配置**:

| 变量 | 说明 | 默认值 |
|:-----|:-----|:-------|
| `FDT_LLM_API_KEY` | LLM API Key | - |
| `FDT_LLM_API_BASE` | LLM API Base URL | `https://api.deepseek.com/v1` |
| `FDT_LLM_MODEL` | LLM 模型名称 | `deep_research-chat` |
| `FDT_PG_DSN` | PostgreSQL 连接字符串 | - |
| `FDT_USE_LANGGRAPH` | 是否使用 LangGraph | `false` |
| `FDT_CHECKPOINTER` | Checkpointer 类型 | `sqlite` |
| `FDT_DIRECT_DEBATE` | 指定品种辩论模式 | `false` |
| `FDT_DEBATE_SYMBOLS` | 指定辩论品种列表 | - |

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

**金十 MCP 配置**:

| 变量 | 说明 |
|:-----|:-----|
| `JIN10_MCP_URL` | 金十 MCP 服务地址 |
| `JIN10_MCP_TOKEN` | 金十 MCP 认证 Token |

### 6.4 运行模式

| 模式 | 说明 | 特点 |
|:-----|:-----|:-----|
| `default` | 默认模式 | 完整流程 |
| `fast` | 快速模式 | 跳过辩论，直接裁决 |
| `deep_research` | 深度研究 | 分歧>0.7时循环辩论 |
| `tournament` | 锦标赛模式 | 多轮辩论+投票 |

---

## 7. 测试体系

### 7.1 测试目录结构

```
tests/
├── fdt_langgraph/      # LangGraph 核心测试（43+ 用例）
├── strategies/         # 策略测试（19 文件）
├── scripts/            # 脚本测试（68 模块，474+ 用例）
├── commodity-chain/     # 产业链分析测试
├── debate-argument-builder/ # 辩论论据测试
├── debate-risk-manager/ # 风控测试
├── fdt-gate/           # 质量门禁测试
├── fundamental-data-collector/ # 基本面采集测试
├── technical-analysis/  # 技术分析测试
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

### A. 10 Agent 职责清单

| Agent | 职责 | 不做什么 |
|:------|:-----|:---------|
| 数技源 | 跑 8 策略管线产信号 | 不下方向结论 |
| 观澜 | 技术面分析（LLM） | 不判断多空 |
| 探源 | 基本面分析（LLM，含金十快讯） | 不判断多空 |
| 链证源 | 产业链关联分析 | 不下交易结论 |
| 读心 | 新闻情绪分析（LLM） | 不判断多空 |
| 多头分析员 | 列举 ≥3 条做多论据 | 不做空头分析 |
| 空头分析员 | 列举 ≥3 条做空论据 | 不做多头分析 |
| 闫判官 | 裁决方向 + 输出交易参数 | 不独立分析行情 |
| 风控明 | 审核闫判官 verdict | 不参与方向判断 |
| 明鉴秋 | 管道调度 + 报告生成 + CTP 信号 | 不介入内容决策 |

### B. 8 策略管线

| 策略 | 类型 | 触发条件 |
|:-----|:-----|:---------|
| `trend_following` | 趋势跟踪 | 每日扫描，28 品种 |
| `mean_reversion` | 价格反转 | ADX<25 震荡市 + KF 无偏移 |
| `arbitrage` | 套利 | 配对品种均活跃 |
| `pairs_reversion` | 配对回归 | 两腿均非趋势型 |
| `spread_reversion` | 近远月价差 | 价差偏离 > 2σ |
| `basis_reversion` | 期现基差 | 基差偏离 > 2σ |
| `macro_regime` | 宏观轮动 | 宏观信号到位 |
| `multi_factor` | 多因子加权 | 每日扫描，12 品种 |

### C. 循环契约

| 循环 ID | 名称 | 验证档位 | 权限 |
|:--------|:-----|:---------|:-----|
| `daily-debate` | 每日自动辩论 | L3 | Write |
| `self-evolve` | 自进化闭环 | L2 | Draft |
| `ml-training` | ML 模型训练 | L2 | Draft |
| `health-check` | 健康自检 | L1 | 只读 |
| `data-collection` | 数据采集 | L1 | 只读 |

---

*文档版本: v9.11.2 | 最后更新: 2026-07-22 | 作者: FDT Contributors*