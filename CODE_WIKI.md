# FDT Code Wiki — 期货辩论专家团技术文档

## 1. 项目概览

FDT（Futures Debate Team）是一套 **9-Agent 多角色交叉质询的 CTA 决策系统**。基于 LangGraph 构建，实现按需并行数据源、PostgreSQL OLTP+OLAP 混合存储、独立 CLI/FastAPI 入口。

**核心特性**:
- **NO_FUSION 策略管线**: 8 策略各自独立打分，方向冲突不融合
- **三层信号门禁**: 震荡市 + 去趋势 + P0-4 伪突破拦截，共 20+ 道校验
- **六阶段攻防辩论**: 多头只做多、空头只做空，来源可追溯
- **指定品种辩论模式**: 跳过 P1 扫描，直接从本地缓存加载数据进入 P2→P6 流程（`FDT_DIRECT_DEBATE=true`）
- **FDC 数据注入**: P2.5 阶段预采集所有选中品种的结构化数据（K线/指标/期限结构/基差/仓单/基本面/持仓排名）供子 Agent 使用
- **Data-Core 集成**: 统一 F10 数据入口，自动降级到原有采集器
- **主力合约统一解析**: `dominant_resolver` 统一主力合约判定与换月追踪
- **字段标准化**: `field_normalizer` 统一规范 8 类子 Agent 数据栏位（direction/oi/confidence/entry_price/grade 等）
- **本地增量缓存**: `fdt_cache/` SQLite 持久化层，按品种+数据类型缓存 K 线/基本面/基差，增量 UPSERT
- **报告层调度**: 明鉴秋按阶段产出 5 种独立 HTML 报告（扫描/研究/裁决/辩论/CTP 信号）
- **逐 Agent LLM 配置**: 每个子 Agent 可通过 `FDT_LLM_<NAME>_*` 环境变量独立指定不同 LLM
- **自进化闭环**: T+1 回测验证 → 累计样本 → 校准权重 → 进化 Agent Prompt → ML 增量训练
- **LangGraph 架构**: 可配置并行数据源、条件路由、状态持久化、断点恢复
- **Harness 工程规范**: 12 项 commit 前检查清单 + 10 条反模式检测规则

**版本**: v9.6.1

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                     L5 — 可观测性层 (Observability)                   │
│   APM-CS五轴 · 统一日志 · ViBench回放 · 失败聚类 · 自改进脚手架        │
├─────────────────────────────────────────────────────────────────────┤
│                     L4 — LangGraph 编排层 (Orchestration)            │
│   StateGraph · 条件边 · Checkpointer · 流式输出 · 多模式路由          │
├─────────────────────────────────────────────────────────────────────┤
│                     L3 — 通信契约层 (Contract)                        │
│   DebateState TypedDict · JSON Schema · agent-protocol v3.0          │
├─────────────────────────────────────────────────────────────────────┤
│                     L2 — 鲁棒性防线 (Resilience)                      │
│   L1产出校验 · L2熔断降级 · L3信号门 · L4路径发现 · L5健康自检        │
├─────────────────────────────────────────────────────────────────────┤
│                     L1 — 基础设施层 (Infrastructure)                   │
│   PostgreSQL · memory系统 · unified_logger · 独立CLI/FastAPI入口     │
│   · fdt_cache(SQLite增量缓存) · dominant_resolver · _datacore_bridge  │
│   · data_source_adapter(统一数据入口)                                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
用户请求 / cron 触发 / API 调用
    │
    ▼
[FdtDebateGraph] ──→ DebateState (内存状态传递)
    │
    ├─ 默认模式 (FDT_DIRECT_DEBATE=false) ───────────────┐
    │  │                                                   │
    │  ├─ [scan:数技源] ──→ state["scan_results"]         │ 指定品种辩论模式
    │  │       │                                           │ (FDT_DIRECT_DEBATE=true)
    │  │       ▼                                           │
    │  │  [judge_direction] 闫判官                        ├─ [load_cache] 从 fdt_cache/ 加载
    │  │       │                                           │       │
    │  │       ▼                                           │  [judge_direction] 闫判官
    │  │  [prepare_data] P2.5 FDC 数据准备                 │       │
    │  │       │                                           │  (进入标准 P3→P6 流程)
    │  │       ▼ (按需并行调度)                            │       │
    │  │  ┌────────────────────────────────────┐          │  [update_cache] 回写缓存
    │  │  │  按需并行数据源 (Parallel)         │          │
    │  │  │  [chain:链证源] [technical:观澜] [fundamental:探源]           │          │
    │  │  │  产业链   技术面  基本面           │          │
    │  │  └────────────────────────────────────┘          │
    │  │       │                                           │
    │  │       ▼                                           │
    │  │  [merge_research] 合并分析结果                    │
    │  │       │                                           │
    │  │       ▼                                           │
    │  │  [debate] 六阶段攻防 (串行交叉质询)               │
    │  │  多头立论(P4_1)→空头立论(P4_2)→空头驳论(P4_3)   │
    │  │  →多头驳论(P4_4)→空头结辩(P4_5)→多头结辩(P4_6) │
    │  │       │                                           │
    │  │       ▼                                           │
    │  │  [verdict] 闫判官 ──→ 裁决+完整交易参数          │
    │  │       │                                           │
    │  │       ▼                                           │
    │  │  [risk_check] 风控明 ──→ 风控审核                │
    │  │       │                                           │
    │  │       ▼                                           │
    │  └─ [report → signal_output] 明鉴秋                  │
    │          │                                            │
    │          ├─ P1: scan_report.html    ← 信号扫描       │
    │          ├─ P3: research_report.html ← 三源研究      │
    │          ├─ P5: verdict_report.html  ← 裁决+风控     │
    │          ├─ P6: report/debate_report ← 辩论最终报告  │
    │          └─ P6a: signal_report.html  ← CTP 信号      │
    │                                                       │
    └───────────────────────────────────────────────────────┘
```

---

## 3. 核心模块

### 3.1 fdt_langgraph — LangGraph 编排层

| 文件 | 职责 | 核心类/函数 |
|:-----|:-----|:-----------|
| `state.py` | 统一辩论状态定义 | `DebateState`, `create_initial_state()`, `FdcSymbolData`, `FdcDataStatus` |
| `graph.py` | 图结构定义与编译 | `build_debate_graph()`, `build_debate_graph_no_checkpoint()`, `_register_direct_debate_nodes()`, `_register_debate_nodes()` |
| `nodes.py` | 全部节点函数实现 | `node_scan`, `node_judge_direction`, `node_prepare_data`(P2.5), `node_chain`, `node_technical`, `node_fundamental`, `node_merge_research`, `node_bullish_v1`, `node_bearish_v1`, `node_bearish_rebuttal`, `node_bullish_rebuttal`, `node_bear_final`, `node_bull_final`, `node_verdict`, `node_risk_check`, `node_report`, `node_signal_output`, `node_load_cache`, `node_update_cache` |
| `agents.py` | Agent 执行器 | `FdtAgentExecutor`（逐Agent LLM 配置 `_normalize_env_name`/`_resolve_llm_config`）, `AgentRegistry` |
| `health.py` | 健康检查与监控 | `HealthChecker`, `run_health_check()` |

**DebateState 关键字段**:

| 字段 | 类型 | 说明 |
|:-----|:-----|:-----|
| `trace_id` | str | 全链路追踪 ID |
| `timestamp` | datetime | 创建时间 |
| `mode` | str | 运行模式（default/fast/deep_research/tournament） |
| `scan_results` | dict | 扫描结果 |
| `scan_summary` | Optional[dict] | 扫描汇总（报告层用） |
| `judge_direction` | dict | 闫判官方向决策 |
| `selected_symbols` | list | 选中辩论品种 |
| `dispatch_sources` | list | 调度数据源列表 |
| `fdc_data` | dict | FDC 数据采集结果（P2.5 预采集） |
| `fdc_data_status` | Optional[FdcDataStatus] | FDC 采集状态（成功率/耗时/数据质量等级） |
| `chain_analysis` | dict | 链证源分析结果 |
| `technical_data` | dict | 观澜技术面数据 |
| `fundamental_data` | dict | 探源基本面数据 |
| `research_data` | Optional[dict] | 三源合并研究数据 |
| `bullish_arguments` | list (Annotated) | 多头立论 (P4_1) |
| `bearish_arguments` | list (Annotated) | 空头立论 (P4_2) |
| `bearish_rebuttal_arguments` | list (Annotated) | 空头驳论 (P4_3) |
| `bullish_rebuttal_arguments` | list (Annotated) | 多头驳论 (P4_4) |
| `bear_final_arguments` | list (Annotated) | 空头结辩 (P4_5) |
| `bull_final_arguments` | list (Annotated) | 多头结辩 (P4_6) |
| `debate_round` | int | 辩论轮次计数器 |
| `data_sources` | list | 来源标记映射 |
| `verdict` | dict | 裁决结果（含 `overturn_scan` 标记） |
| `risk_check` | dict | 风控审核结果 |
| `signal_output` | dict | CTP 信号输出 |
| `scan_report_path` | Optional[str] | P1 信号扫描报告路径 |
| `research_report_path` | Optional[str] | P3 三源研究报告路径 |
| `verdict_report_path` | Optional[str] | P5 裁决+风控报告路径 |
| `report_path` | Optional[str] | P6 辩论最终报告路径 |
| `signal_report_path` | Optional[str] | P6a CTP 信号报告路径 |
| `current_phase` | str | 当前执行阶段 |
| `error` | Optional[str] | 错误信息 |
| `completed_phases` | list | 已完成阶段列表 |
| `phase_start_time` | Optional[float] | 阶段开始时间戳 |

### 3.2 fdt_pg — PostgreSQL 连接层

| 文件 | 职责 | 核心类 |
|:-----|:-----|:-------|
| `connection.py` | 数据库连接管理 | `PGConnection`, `PGConfig` |
| `schema.py` | ORM 模型定义 | 14 个 OLTP 表 + 3 个 OLAP 视图 |
| `deploy.py` | 部署工具 | `deploy()`, `migrate()`, `status()` |

**关键数据表**:

| 表名 | 用途 |
|:-----|:-----|
| `scan_signals` | 信号扫描结果 |
| `chain_analysis` | 产业链分析 |
| `technical_scores` | 技术面评分 |
| `fundamental_scores` | 基本面评分 |
| `debate_arguments` | 辩论论据 |
| `debate_verdicts` | 辩论裁决（含完整交易参数） |
| `risk_checks` | 风控审核 |
| `execution_followup` | 执行跟进 |

**OLAP 视图**:

| 视图名 | 用途 |
|:-------|:-----|
| `v_debate_summary` | 辩论汇总分析 |
| `v_signal_performance` | 信号绩效分析 |
| `v_agent_effectiveness` | Agent 效能分析 |

### 3.3 futures_data_core — 期货数据核心

| 子模块 | 职责 | 核心类/函数 |
|:-------|:-----|:-----------|
| `core` | 降级链、缓存、新鲜度、品种注册 | `MultiSourceAdapter`, `KlineData`, `QuoteData`, `CircuitBreaker`, `DataFreshnessMonitor`, `TxnStore`, `DominantResolver`, `FieldNormalizer`, `_datacore_bridge` |
| `collectors` | 数据采集器（TDX/QMT/TqSDK/Web/DataCore） | `TDXCollector`, `TqSdkCollector`, `QMTCollector`, `WebFallbackCollector`, `DataCoreCollector` |
| `f10` | F10 衍生品数据（期限结构/基差/基本面/持仓/价差） | `get_term_structure()`, `compute_basis()`, `get_fundamental()`, `get_position()`, `get_spread()` |
| `indicators` | 技术指标计算 | `compute_indicators()`, `trend_maturity()` |
| `cache` | F10 数据本地缓存 | `F10Cache`（基本面数据持久化） |
| `config` | 数据源配置 | `data_sources.yaml`, `symbol_map.yaml`, `settings.py` |

**采集器优先级** (v9.3.0 更新):
1. `DataCoreCollector` — Data-Core FDC（优先级 0，最高）
2. `TDXCollector` — 通达信本地 TQ-Local（优先级 1）
3. `WebFallbackCollector` — 东方财富 HTTP API（优先级 2）
4. `QMTCollector` — QMT/xtquant（优先级 3）
5. `TqSdkCollector` — 天勤量化（优先级 98，末位兜底）

### 3.4 data_source_adapter — 统一数据入口

| 文件 | 职责 | 核心函数 |
|:-----|:-----|:---------|
| `data_source_adapter.py` | 统一数据入口封装 | `get_kline()`, `compute_indicators()`, `get_term_structure()`, `get_spread()`, `get_basis()`, `get_warrant()`, `get_fundamental()`, `get_position_ranking()` |

**功能**: 将 futures_data_core 的底层采集器封装为统一的异步 API，供 `node_prepare_data` 调用。

### 3.5 pipeline — 流水线执行

| 文件 | 职责 |
|:-----|:-----|
| `runner.py` | 全自动零人工干预流水线（6步） |
| `quality_filter.py` | 信号质量过滤 |

**流水线步骤**:
1. 多策略并行扫描（数技源）或从 fdt_cache/ 加载（指定品种辩论模式）
2. 闫判官方向决策 + P2.5 FDC 数据准备
3. 产业链分析
4. 数据适配（链证源/观澜/探源三源并行）
5. 六阶段攻防辩论 → 裁决 → 风控
6. 报告生成 + CTP 信号输出

### 3.6 scripts — 辅助脚本

| 文件 | 职责 |
|:-----|:-----|
| `run_debate.py` | 辩论主动驱动层 |
| `run_benchmark.py` | 基准对比测试 |
| `fdt_cli.py` | 命令行接口 |
| `fdt_api.py` | FastAPI 接口 |
| `extract_knowledge.py` | 知识萃取 |
| `evolve_agents.py` | Agent 进化（8 维度参数自调整） |
| `calibrate_weights.py` | 权重校准 |
| `validate_verdicts.py` | 裁决验证 |
| `unified_logger.py` | 统一日志 |
| `pre_commit_harness_check.py` | Harness 规范预提交检查（从 harness-rules.yaml 加载规则） |

### 3.7 skills — 子技能

| 技能 | 职责 | 核心脚本 |
|:-----|:-----|:---------|
| `quant-daily` | 量化日扫描 | `scan_all.py`, `strategies/`, `backtest/`, `indicators/` |
| `commodity-chain-analysis` | 产业链分析 | `chains.py`, `config.py`, `debate.py`, `risk.py` |
| `technical-analysis` | 技术分析 | `divergence.py` |
| `fundamental-data-collector` | 基本面采集 | `web_collector.py`, `huishang_collector.py` |
| `debate-argument-builder` | 辩论论据构建 | `debater_tools.py` |
| `debate-judge` | 辩论评判逻辑 | `judge_tools.py` |
| `debate-risk-manager` | 风控引擎 | `fee_table.py` |
| `debate-trading-planner` | 交易规划 | SKILL.md |
| `fdt-spawn-debate` | 辩论 spawn 调度 | SKILL.md |
| `futures-data-technician` | 数据技术员 | SKILL.md |
| `futures-trading-analysis` | 交易分析报告 | `contracts/base.py`, `contracts/risk.py` |

### 3.8 主要版本特性

| 版本 | 特性 |
|:-----|:------|
| v9.6.1 | **G71 完全关闭 + 循环契约补全** — 8 文件手工注解补全 + ml-training/health-check 两份 Loop Contract |
| v9.6.0 | **Harness 工程全面升级** — 规范引擎化（harness-rules.yaml + pre-commit v2）、类型注解全量补充（580 函数）、5 个缺失规范维度补充、10 条反模式检测规则、G21/G22 设计文档 |
| v9.5.0 | **Loop Engineering 体系化** — 新增 Loop Contract 规范与 daily-debate 首份契约；架构文档添加 Loop Engineering 视角；README 增加 Harness & Loop Engineering 专章；差距分析登记 G20/G21/G22 |
| v9.4.3 | **G91 同品种多子信号合并方向覆盖 bug 修复** — `pipeline.py` Phase 4.8 引入 `_merge_acc` 累积器，消除后序信号权重偏高问题；新增 `TestSubSignalMerge` 4 用例 |
| v9.4.2 | **G89 debate_only 信号多空论据丢失修复 + G90 信号排序改为交易可靠性优先** — 修复 `phase3_generate_report.py` 补充逻辑遗漏 `bull_args`/`bear_args` 字段；信号排序改为 `置信度 × 盈亏比` |
| v9.4.1 | **G88 K 线数据链路根因修复（P0）** — 修复 `MultiSourceAdapter.get_kline()` 入口处的"自动主力解析" bug；`DominantResolver` 不再返回 `variety00` 这种不可识别的合约代码 |
| v9.4.0 | **G87 Data-Core F10 全面集成** — 新增 `_datacore_bridge.py`；改造 6 个 F10 模块入口；`compute_indicators` 优先路由 Data-Core 版；新增 2 个测试文件共 36 用例 |
| v9.3.0 | **G86 主力合约统一解析 + DataCore 集成 + 字段标准化** — 新增 `dominant_resolver.py`；新增 `DataCoreCollector`；新增 `field_normalizer.py`（统一规范 8 类子 Agent 数据栏位，覆盖 14 个不一致点） |
| v9.2.0 | **Loop Engineering 剥离** — 因子自演化移出 FDT 系统 |
| v9.1.0 | **本地增量缓存** — `fdt_cache/` SQLite 缓存层；指定品种辩论模式（跳过 P1 从缓存加载） |
| v9.0.0 | **六阶段攻防辩论** — 多头立论→空头立论→空头驳论→多头驳论→空头结辩→多头结辩；来源可追溯；闫判官可推翻数技源方向 |
| v8.9.0 | **交叉质询串行化 + 逐Agent LLM** — P4 拆分为串行三步骤；FDT_LLM_<NAME>_* 逐 Agent 独立模型配置；测试覆盖大幅提升 |
| v8.8.0 | **明鉴秋报告层调度** — 5 阶段独立 HTML 报告（信号扫描/三源研究/裁决风控/辩论/CTP 信号） |
| v8.7.0 | **架构精简** — 策执远合并到闫判官；CTP 信号输出；观澜/探源 LLM 推理 |
| v8.4.0 | **LangGraph 生产集成** — A/B 切换；PG+SQLite Checkpointer 降级 |
| v8.3.0 | **LangGraph 迁移** — StateGraph + 按需并行 + PostgreSQL OLTP+OLAP |
| v8.2.0 | **Harness 规范固化** — commit 前 12 项检查清单 |
| v8.1.8 | **NO_FUSION 策略管线** — 去融合工程 |
| v8.0.0 | **去 WorkBuddy 依赖** — 独立 CLI/FastAPI 入口 |

---

## 4. 关键类与函数

### 4.1 FdtAgentExecutor

**位置**: `fdt_langgraph/agents.py`

```python
class FdtAgentExecutor:
    def __init__(self, agent_config: Any)
    def execute(self, prompt: str, trace_id: str = "", **kwargs) -> Dict[str, Any]
    async def run(self, prompt: str, trace_id: str = "", **kwargs) -> Dict[str, Any]
```

**功能**: Agent 执行器，负责加载 Agent 配置、调用 LLM、返回结构化输出。支持逐 Agent 独立 LLM 配置（`FDT_LLM_<NAME>_*` 环境变量）。

### 4.2 AgentRegistry

**位置**: `fdt_langgraph/agents.py`

```python
class AgentRegistry:
    @classmethod
    def register(cls, agent_name: str, executor: FdtAgentExecutor)
    @classmethod
    def get(cls, agent_name: str) -> Optional[FdtAgentExecutor]
    @classmethod
    def load_from_directory(cls, agents_dir: str = "agents")
```

**功能**: Agent 注册中心，从 `agents/` 目录加载所有 Agent 配置。

### 4.3 MultiSourceAdapter

**位置**: `futures_data_core/core/multi_source_adapter.py`

```python
class MultiSourceAdapter:
    def __init__(self, collectors=None, cache=None)
    async def get_kline(self, symbol, period="daily", days=120, source="auto") -> A2APayload
    async def get_quote(self, symbol, source="auto") -> A2APayload
    async def batch_get_quotes(self, symbols) -> dict[str, dict]
    def source_health(self) -> dict
```

**功能**: 多源降级链适配器，自动按优先级尝试数据源，失败自动降级。

### 4.4 DominantResolver

**位置**: `futures_data_core/core/dominant_resolver.py`

```python
class DominantResolver:
    def resolve(self, variety: str) -> str
    def update_mapping(self) -> None
```

**功能**: 统一主力合约判定与换月追踪，从 `memory/dominant_map.json` 读取映射关系。

### 4.5 FieldNormalizer

**位置**: `futures_data_core/core/field_normalizer.py`

```python
def normalize_signal_list(signals: list) -> list
def normalize_verdict(verdict: dict) -> dict
def normalize_risk_check(risk_check: dict) -> dict
def normalize_direction_raw(direction: str) -> str
```

**功能**: 统一规范 8 类子 Agent 数据栏位（direction/oi/confidence/entry_price/grade 等），覆盖 14 个不一致点。

### 4.6 build_debate_graph

**位置**: `fdt_langgraph/graph.py`

```python
def build_debate_graph(mode: str = "default") -> StateGraph
```

**功能**: 构建并编译 LangGraph 辩论图，支持 default/fast/deep_research/tournament 四种模式。

### 4.7 HealthChecker

**位置**: `fdt_langgraph/health.py`

```python
class HealthChecker:
    def check_state_health(self, state: DebateState) -> dict
    def check_graph_health(self, graph_config: dict) -> dict
    def get_summary(self) -> dict
```

**功能**: LangGraph 健康检查器，检测节点超时、异常状态、健康聚合输出。

### 4.8 PGConnection

**位置**: `fdt_pg/connection.py`

```python
class PGConnection:
    @classmethod
    def initialize(cls)
    @classmethod
    def get_engine(cls) -> Engine
    @classmethod
    def health_check(cls) -> bool
```

**功能**: PostgreSQL 连接管理，支持异步连接池、健康检查。

---

## 5. 运行模式

### 5.1 模式说明

| 模式 | 说明 | 特点 |
|:-----|:-----|:-----|
| `default` | 默认模式 | 完整流程：扫描→闫判官→P2.5 FDC准备→三源并行→六阶段辩论→裁决→风控→报告→CTP信号 |
| `fast` | 快速模式 | 跳过辩论，直接裁决（适用于高频扫描） |
| `deep_research` | 深度研究 | 分歧>0.7时循环辩论（适用于复杂市场） |
| `tournament` | 锦标赛模式 | 多轮辩论+投票（适用于重大决策） |

### 5.2 指定品种辩论模式 (Direct Debate, v9.1.0)

跳过 P1 全量扫描，直接从 `fdt_cache/` 加载指定品种的缓存数据进入 P2→P6 流程：

```bash
set FDT_DIRECT_DEBATE=true
set FDT_DEBATE_SYMBOLS=SF,SM,SC
set FDT_CACHE_DIR=D:\FDTWorkspace\cache

python fdt_cli.py run
```

适用场景：快速复盘指定品种、只关注核心品种时节省扫描时间。

### 5.3 A/B 切换

通过环境变量 `FDT_USE_LANGGRAPH` 控制运行模式：

```bash
# 旧模式（文件传递）
FDT_USE_LANGGRAPH=false python pipeline/runner.py

# LangGraph 模式（内存状态传递）
FDT_USE_LANGGRAPH=true python pipeline/runner.py
```

### 5.4 独立运行

```bash
# CLI 单次辩论
python fdt_cli.py run --mode default

# CLI 守护模式（定时调度）
python fdt_cli.py daemon --cron "0 9 * * 1-5"

# API 服务
python fdt_api.py

# PostgreSQL 初始化
python fdt_cli.py db init

# PostgreSQL 健康检查
python fdt_cli.py db health
```

---

## 6. 依赖关系

### 6.1 核心依赖

```
pandas>=2.0          # 数据处理
numpy>=1.24          # 数值计算
python-dateutil>=2.8 # 日期处理
lightgbm>=4.0        # ML 模型
scikit-learn>=1.3    # ML 工具
tqdm>=4.65           # 进度条
httpx>=0.27          # HTTP 客户端
scipy>=1.11          # 统计计算
psutil>=5.9          # 系统监控
requests>=2.31       # HTTP 请求
pydantic>=2.0        # 数据验证
langgraph>=0.2.0     # LangGraph 编排
langgraph-checkpoint-sqlite>=0.1.0  # SQLite 检查点
sqlalchemy>=2.0      # ORM
psycopg2-binary>=2.9 # PostgreSQL 驱动
```

### 6.2 可选依赖

```
celery>=5.3          # 分布式任务
redis>=4.5           # 缓存
ray>=2.6             # 分布式计算
xgboost>=2.0         # ML 模型（可选）
pytest>=7.4          # 测试
black>=23.0          # 代码格式化
mypy>=1.5            # 类型检查
ruff>=0.1            # 代码检查
```

---

## 7. 环境变量

| 变量 | 说明 | 默认值 |
|:-----|:-----|:-------|
| `FDT_LLM_API_KEY` | LLM API Key | - |
| `FDT_LLM_API_BASE` | LLM API Base URL | `https://api.deepseek.com/v1` |
| `FDT_LLM_MODEL` | LLM 模型名称 | `deepseek-chat` |
| `FDT_LLM_<NAME>_API_KEY` | 逐 Agent API Key（覆盖全局，NAME 为 Agent 大写名称） | - |
| `FDT_LLM_<NAME>_API_BASE` | 逐 Agent Base URL（覆盖全局） | - |
| `FDT_LLM_<NAME>_MODEL` | 逐 Agent 模型名（覆盖全局） | - |
| `FDT_PG_DSN` | PostgreSQL 连接字符串 | - |
| `FDT_USE_LANGGRAPH` | 是否使用 LangGraph 模式 | `false` |
| `FDT_CHECKPOINTER` | Checkpointer 类型（pg/sqlite） | `sqlite` |
| `FDT_SCAN_MODE` | 扫描模式（no-filter） | - |
| `FDT_STRATEGIES` | 指定策略列表 | - |
| `FDT_DIRECT_DEBATE` | 指定品种辩论模式开关 | `false` |
| `FDT_DEBATE_SYMBOLS` | 指定辩论品种列表（逗号分隔） | - |
| `FDT_CACHE_DIR` | 本地缓存目录 | `memory/fdt_cache` |
| `FDT_GENERATE_SCAN_REPORT` | 是否生成扫描 HTML 报告 | `false` |
| `FDT_REPORT_WORKSPACE` | 报告输出工作空间根目录 | `tempfile.gettempdir()` |
| `FDT_DAILY_WORKSPACE` | 日报工作空间（FDT_REPORT_WORKSPACE 的备选） | - |
| `FDT_FDC_INJECTION_ENABLED` | 是否启用 FDC 数据注入（P2.5） | `true` |
| `FDT_FDC_KLINE_DAYS` | FDC K线数据天数 | `120` |
| `FDT_FDC_F10_ENABLED` | 是否启用 F10 数据采集 | `true` |
| `FDT_FDC_POSITION_RANKING_ENABLED` | 是否启用持仓排名采集 | `true` |
| `FDT_RISK_THRESHOLD` | CTP 信号风控阈值 | `yellow` |

---

## 8. 目录结构

```
FDT/
├── agents/                    # Agent 配置文件（11个）
├── config/                    # 配置文件
├── contracts/                 # 契约定义（Schema）
├── debate/                    # 辩论历史管理
├── docs/                      # 文档
│   ├── archive/               # 已归档的历史文档
│   ├── harness/               # Harness 工程规范（10篇 + loop-contracts/）
│   ├── designs/               # 设计文档
│   ├── schemas/               # JSON Schema
│   └── skills/                # 技能文档
├── fdt_cache/                 # 本地 SQLite 增量缓存
├── fdt_langgraph/             # LangGraph 核心模块
│   ├── state.py               # DebateState 定义
│   ├── graph.py               # 图结构
│   ├── nodes.py               # 节点函数
│   ├── agents.py              # Agent 执行器
│   └── health.py              # 健康检查
├── fdt_pg/                    # PostgreSQL 模块
│   ├── connection.py          # 连接管理
│   ├── schema.py              # ORM 模型
│   ├── deploy.py              # 部署工具
│   └── migrations/            # 数据库迁移
├── futures_data_core/         # 期货数据核心
│   ├── core/                  # 核心层（降级链、缓存、类型）
│   │   ├── backends/          # 后端存储（postgres/redis）
│   │   ├── dominant_resolver.py   # 主力合约解析
│   │   ├── field_normalizer.py    # 字段标准化
│   │   ├── _datacore_bridge.py    # Data-Core F10 桥接器
│   │   └── ...
│   ├── collectors/            # 采集器（TDX/QMT/TqSDK/Web/DataCore）
│   ├── f10/                   # F10 衍生品数据
│   ├── indicators/            # 技术指标
│   └── cache/                 # 缓存
├── memory/                    # 知识库和记忆系统
├── pipeline/                  # 流水线执行
├── scripts/                   # 辅助脚本
├── skills/                    # 子技能实现
├── tests/                     # 测试用例
├── data_source_adapter.py     # 统一数据入口封装（v9.3.0 新增）
├── fdt_cli.py                 # CLI 入口
├── fdt_api.py                 # FastAPI 入口
├── pyproject.toml             # 项目配置
└── README.md                  # 项目说明
```

---

## 9. 测试覆盖

| 测试目录 | 说明 |
|:---------|:-----|
| `tests/fdt_langgraph/` | LangGraph 核心测试（节点/状态/图/Agents/健康/E2E/报告/基准/A-B切换） |
| `tests/strategies/` | 策略管线测试（8 策略 × 独立打分，NO_FUSION） |
| `tests/quant-daily/` | 量化日扫描测试 |
| `tests/commodity-chain/` | 产业链分析测试 |
| `tests/contracts/` | 契约 Schema 测试（9 个 JSON Schema 校验） |
| `tests/debate-argument-builder/` | 辩论论据构建测试 |
| `tests/debate-risk-manager/` | 风控测试 |
| `tests/fdt-gate/` | 质量门禁测试（L1-L5 鲁棒性防线） |
| `tests/fundamental-data-collector/` | 基本面采集测试 |
| `tests/scheduler/` | 调度器测试 |
| `tests/memory/` | 记忆系统测试 |
| `tests/technical-analysis/` | 技术分析测试 |
| `tests/validators/` | 信号验证器测试 |
| `tests/self-improve-enhanced/` | 自改进测试 |
| `tests/pipeline/` | 流水线测试 |
| `tests/dominant-resolver/` | 主力合约解析测试（datacore_bridge/fdc_fallback/field_normalizer） |

---

## 10. 最佳实践

### 10.1 trace_id 全链路原则

所有模块、文档和日志必须贯穿 `trace_id`，确保可追溯性。

### 10.2 契约优先原则

先定义 Schema/TypedDict/接口契约，再实现代码。

### 10.3 测试随重构原则

每阶段先写测试，测试全绿才能进入下一阶段。

### 10.4 角色边界原则

Agent 职责不可越界，严格按照生命周期定义执行。

### 10.5 差距管理原则

重大技术债务必须登记到 `docs/harness/08-gap-analysis.md`，按 P0/P1/P2 优先级推进。

### 10.6 文档先行原则

Harness 文档 = design spec，测试 = validation spec，代码 = implementation。**改代码前先改文档**。

### 10.7 字段标准化原则

所有子 Agent 输出数据必须通过 `FieldNormalizer` 标准化，确保 direction/oi/confidence/entry_price/grade 等字段的一致性。

---

## 11. 版本历史

| 版本 | 变更 |
|:-----|:-----|
| v9.6.1 | G71 完全关闭 + 循环契约补全（ml-training/health-check） |
| v9.6.0 | Harness 工程全面升级：规范引擎化（harness-rules.yaml + pre-commit v2）、类型注解全量补充（580 函数）、5 个缺失规范维度补充、10 条反模式检测规则、G21/G22 设计文档 |
| v9.5.0 | Loop Engineering 体系化：新增 Loop Contract 规范与 daily-debate 首份契约；架构文档添加 Loop Engineering 视角 |
| v9.4.3 | G91 同品种多子信号合并方向覆盖 bug 修复；新增 `TestSubSignalMerge` 4 用例 |
| v9.4.2 | G89 debate_only 信号多空论据丢失修复 + G90 信号排序改为交易可靠性优先 |
| v9.4.1 | G88 K 线数据链路根因修复（P0）：修复 `MultiSourceAdapter.get_kline()` 入口处的"自动主力解析" bug |
| v9.4.0 | G87 Data-Core F10 全面集成：新增 `_datacore_bridge.py`；改造 6 个 F10 模块入口；新增 2 个测试文件共 36 用例 |
| v9.3.0 | G86 主力合约统一解析 + DataCore 集成 + 字段标准化：新增 `dominant_resolver.py`、`DataCoreCollector`、`field_normalizer.py` |
| v9.2.0 | Loop Engineering 剥离（因子自演化移出 FDT 系统）；文档归档与翻新 |
| v9.1.0 | 本地增量缓存 fdt_cache/；指定品种辩论模式 |
| v9.0.0 | 六阶段攻防辩论：多头立论→空头立论→空头驳论→多头驳论→空头结辩→多头结辩；来源可追溯；闫判官可推翻数技源方向 |
| v8.9.0 | 交叉质询串行化：P4 拆分为串行三步骤；逐Agent LLM 配置；测试覆盖大幅提升 |
| v8.8.0 | 明鉴秋报告层调度：5 阶段独立 HTML 报告输出 |
| v8.7.0 | 架构精简：策执远合并到闫判官；CTP 信号输出；观澜/探源 LLM 推理 |
| v8.4.0 | LangGraph 生产集成：A/B 切换；PG+SQLite 降级 |
| v8.3.0 | LangGraph 迁移完成：按需并行拓扑；PostgreSQL OLTP+OLAP |
| v8.2.0 | Harness 规范固化：12 项 commit 检查清单 |
| v8.1.8 | NO_FUSION 策略管线：去融合工程 |
| v8.0.0 | 去 WorkBuddy 依赖：独立 CLI/FastAPI 入口 |