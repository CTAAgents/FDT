# FDT Code Wiki — 期货辩论专家团技术文档

## 1. 项目概览

FDT（Futures Debate Team）是一套 **10-Agent 多角色交叉质询的 CTA 决策系统**。基于 LangGraph 构建，实现按需并行数据源、PostgreSQL OLTP+OLAP 混合存储、独立 CLI/FastAPI 入口。

**核心特性**:
- **NO_FUSION 策略管线**: 8 策略各自独立打分，方向冲突不融合
- **三层信号门禁**: 震荡市 + 去趋势 + P0-4 伪突破拦截，共 20+ 道校验
- **多空辩论机制**: 多头/空头分析员独立举证，闫判官裁决
- **自进化闭环**: T+1 回测验证 → 累计样本 → 校准权重 → 进化 Agent Prompt → ML 增量训练
- **LangGraph 架构**: 可配置并行数据源、条件路由、状态持久化

**版本**: v8.4.0

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
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
用户请求 / cron 触发 / API 调用
    │
    ▼
[FdtDebateGraph] ──→ DebateState (内存状态传递)
    │
    ├─ [scan] 数技源 ──→ state["scan_results"]
    │       │
    │       ▼
    │  [judge_direction] 闫判官 (选品种 + 定方向 + 调度决策)
    │       │
    │       ▼ (按需并行调度)
    │  ┌──────────────────────────────────────┐
    │  │      按需并行数据源 (Parallel)        │
    │  │  [链证源]   [观澜]     [探源]         │
    │  │  产业链     技术面     基本面          │
    │  └──────────────────────────────────────┘
    │       │
    │       ▼
    │  [merge_research] 合并分析结果
    │       │
    │       ▼
    │  [debate] 证真+慎思 ──→ 多空论据
    │       │
    │       ▼
    │  [verdict] 闫判官 ──→ 裁决+方案+风控
    │       │
    │       ▼
    └─ [report] 明鉴秋 ──→ HTML报告
```

---

## 3. 核心模块

### 3.1 fdt_langgraph — LangGraph 编排层

| 文件 | 职责 | 核心类/函数 |
|:-----|:-----|:-----------|
| `state.py` | 统一辩论状态定义 | `DebateState`, `create_initial_state()` |
| `graph.py` | 图结构定义与编译 | `build_debate_graph()`, `calculate_divergence()` |
| `nodes.py` | 节点函数实现 | `node_scan`, `node_debate`, `node_verdict` |
| `agents.py` | Agent 执行器 | `FdtAgentExecutor`, `AgentRegistry` |
| `health.py` | 健康检查与监控 | `HealthChecker`, `run_health_check()` |

**DebateState 字段**:

| 字段 | 类型 | 说明 |
|:-----|:-----|:-----|
| `trace_id` | str | 全链路追踪 ID |
| `timestamp` | datetime | 创建时间 |
| `mode` | str | 运行模式（default/fast/deep_research/tournament） |
| `scan_results` | dict | 扫描结果 |
| `judge_direction` | dict | 闫判官方向决策 |
| `selected_symbols` | list | 选中辩论品种 |
| `dispatch_sources` | list | 调度数据源列表 |
| `chain_analysis` | dict | 链证源分析结果 |
| `technical_data` | dict | 观澜技术面数据 |
| `fundamental_data` | dict | 探源基本面数据 |
| `bullish_arguments` | list | 多头论据 |
| `bearish_arguments` | list | 空头论据 |
| `verdict` | dict | 裁决结果 |
| `trading_plan` | dict | 交易方案 |
| `risk_check` | dict | 风控审核结果 |
| `report_path` | str | 报告路径 |

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
| `debate_verdicts` | 辩论裁决 |
| `trading_plans` | 交易方案 |
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
| `core` | 降级链、缓存、新鲜度、品种注册 | `MultiSourceAdapter`, `KlineData`, `QuoteData` |
| `collectors` | 数据采集器（TDX/TqSDK/QMT/Web） | `TDXCollector`, `TqSdkCollector`, `QMTCollector`, `WebFallbackCollector` |
| `f10` | F10 衍生品数据 | `get_term_structure()`, `compute_basis()`, `get_fundamental()` |
| `indicators` | 技术指标计算 | `compute_indicators()` |
| `cache` | 缓存管理 | `CacheStore` |

**采集器优先级**:
1. `TDXCollector` — 通达信本地 TQ-Local（第一数据源）
2. `TqSdkCollector` — 天勤量化（降级）
3. `QMTCollector` — QMT/xtquant（降级）
4. `WebFallbackCollector` — 东方财富+新浪（最后兜底）

### 3.4 pipeline — 流水线执行

| 文件 | 职责 |
|:-----|:-----|
| `runner.py` | 全自动零人工干预流水线（6步） |
| `quality_filter.py` | 信号质量过滤 |

**流水线步骤**:
1. 三生产者扫描（数技源 + 观澜 + 探源）
2. 产业链分析
3. 辩论品种精选
4. 数据适配
5. 报告生成
6. 历史记录 + ML 检查

### 3.5 scripts — 辅助脚本

| 文件 | 职责 |
|:-----|:-----|
| `run_debate.py` | 辩论主动驱动层 |
| `run_benchmark.py` | 基准对比测试 |
| `fdt_cli.py` | 命令行接口 |
| `fdt_api.py` | FastAPI 接口 |
| `extract_knowledge.py` | 知识萃取 |
| `evolve_agents.py` | Agent 进化 |
| `calibrate_weights.py` | 权重校准 |
| `validate_verdicts.py` | 裁决验证 |
| `unified_logger.py` | 统一日志 |

### 3.6 skills — 子技能

| 技能 | 职责 | 核心脚本 |
|:-----|:-----|:---------|
| `quant-daily` | 量化日扫描 | `scan_all.py`, `strategies/` |
| `commodity-chain-analysis` | 产业链分析 | `analyze_chain.py` |
| `technical-analysis` | 技术分析 | `run_l1l4_scan.py`, `support_resistance.py` |
| `fundamental-data-collector` | 基本面采集 | `run_factor_timing_scan.py` |
| `futures-trading-analysis` | 交易分析报告 | `phase3_generate_report.py` |

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

**功能**: Agent 执行器，负责加载 Agent 配置、调用 LLM、返回结构化输出。

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

### 4.4 build_debate_graph

**位置**: `fdt_langgraph/graph.py`

```python
def build_debate_graph(mode: str = "default") -> StateGraph
```

**功能**: 构建并编译 LangGraph 辩论图，支持 default/fast/deep_research/tournament 四种模式。

### 4.5 HealthChecker

**位置**: `fdt_langgraph/health.py`

```python
class HealthChecker:
    def check_state_health(self, state: DebateState) -> dict
    def check_graph_health(self, graph_config: dict) -> dict
    def get_summary(self) -> dict
```

**功能**: LangGraph 健康检查器，检测节点超时、异常状态、健康聚合输出。

### 4.6 PGConnection

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
| `default` | 默认模式 | 完整流程：扫描→闫判官→三源并行→辩论→裁决→方案→风控→报告 |
| `fast` | 快速模式 | 跳过辩论，直接裁决（适用于高频扫描） |
| `deep_research` | 深度研究 | 分歧>0.7时循环辩论（适用于复杂市场） |
| `tournament` | 锦标赛模式 | 多轮辩论+投票（适用于重大决策） |

### 5.2 A/B 切换

通过环境变量 `FDT_USE_LANGGRAPH` 控制运行模式：

```bash
# 旧模式（文件传递）
FDT_USE_LANGGRAPH=false python pipeline/runner.py

# LangGraph 模式（内存状态传递）
FDT_USE_LANGGRAPH=true python pipeline/runner.py
```

### 5.3 独立运行

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
| `FDT_PG_DSN` | PostgreSQL 连接字符串 | - |
| `FDT_USE_LANGGRAPH` | 是否使用 LangGraph 模式 | `false` |
| `FDT_CHECKPOINTER` | Checkpointer 类型（pg/sqlite） | `sqlite` |
| `FDT_SCAN_MODE` | 扫描模式（no-filter） | - |
| `FDT_STRATEGIES` | 指定策略列表 | - |

---

## 8. 目录结构

```
FDT/
├── agents/                    # Agent 配置文件（10个）
├── config/                    # 配置文件
├── contracts/                 # 契约定义（Schema）
├── debate/                    # 辩论历史管理
├── docs/                      # 文档
│   ├── harness/               # Harness 工程规范
│   ├── design/                # 设计文档
│   ├── schemas/               # JSON Schema
│   └── skills/                # 技能文档
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
│   ├── collectors/            # 采集器（TDX/TqSDK/QMT/Web）
│   ├── f10/                   # F10 衍生品数据
│   ├── indicators/            # 技术指标
│   └── cache/                 # 缓存
├── memory/                    # 知识库和记忆系统
├── pipeline/                  # 流水线执行
├── scripts/                   # 辅助脚本
├── skills/                    # 子技能实现
├── tests/                     # 测试用例
├── fdt_cli.py                 # CLI 入口
├── fdt_api.py                 # FastAPI 入口
├── pyproject.toml             # 项目配置
└── README.md                  # 项目说明
```

---

## 9. 测试覆盖

| 测试目录 | 测试文件数 | 测试用例数 | 说明 |
|:---------|:-----------|:-----------|:-----|
| `tests/fdt_langgraph/` | 7 | 81 | LangGraph 核心测试 |
| `tests/strategies/` | 14 | - | 策略管线测试 |
| `tests/quant-daily/` | 5 | - | 量化日扫描测试 |
| `tests/commodity-chain/` | 6 | - | 产业链分析测试 |
| `tests/debate-argument-builder/` | 1 | - | 辩论论据构建测试 |
| `tests/debate-risk-manager/` | 1 | - | 风控测试 |
| `tests/fdt-gate/` | 1 | - | 质量门禁测试 |
| `tests/scheduler/` | 2 | - | 调度器测试 |
| `tests/memory/` | 1 | - | 记忆系统测试 |
| `tests/validators/` | 4 | - | 信号验证器测试 |

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

---

## 11. 版本历史

| 版本 | 变更 |
|:-----|:-----|
| v8.4.0 | 完整 LangGraph 迁移完成 |
| v8.3.0 | LangGraph 架构支持、独立 CLI/FastAPI 入口 |
| v8.2.0 | PostgreSQL OLTP+OLAP 混合存储 |
| v8.1.8 | NO_FUSION 策略管线 |
| v8.0.0 | 去 WorkBuddy 依赖 |