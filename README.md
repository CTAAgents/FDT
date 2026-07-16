# Futures Debate Team — 期货交易辩论专家团

一套 **10-Agent 多角色交叉质询的 CTA 决策系统**。基于 LangGraph 构建，实现按需并行数据源、PostgreSQL OLTP+OLAP 混合存储、独立 CLI/FastAPI 入口。

**v8.4.0 — 完整 LangGraph 迁移完成**

---

## 核心特性

- **NO_FUSION 策略管线**: 8 策略各自独立打分，方向冲突不融合、不掩盖、不平均
- **三层信号门禁**: 震荡市(ADX+BB+KF) + 去趋势(Hurst+VR) + P0-4 伪突破拦截，共 20+ 道校验
- **多空辩论机制**: 多头/空头分析员独立举证，闫判官裁决
- **自进化闭环**: T+1 回测验证 → 累计样本 → 校准权重 → 进化 Agent Prompt → ML 增量训练
- **LangGraph 架构**: 可配置并行数据源、条件路由、状态持久化、断点恢复
- **独立运行**: 去 WorkBuddy 依赖，支持 CLI/FastAPI 独立入口

---

## 快速开始

### 环境准备

```bash
# 核心依赖
pip install pandas numpy httpx psutil requests

# API 服务
pip install fastapi uvicorn jinja2

# LangGraph
pip install langgraph langgraph-checkpoint-sqlite

# PostgreSQL
pip install sqlalchemy psycopg2-binary

# 可选：分布式
# pip install celery redis

# 设置环境变量
export FDT_LLM_API_KEY="sk-xxx"         # DeepSeek / OpenAI API Key
export FDT_PG_DSN="postgresql://user:pass@localhost:5432/fdt"  # PostgreSQL（可选）
```

### 核心命令

| 命令 | 功能 |
|:-----|:------|
| `python fdt_cli.py run [--mode default/fast/deep_research/tournament]` | 单次辩论执行 |
| `python fdt_cli.py daemon --cron "<expr>"` | 定时调度模式 |
| `python fdt_cli.py db init` | 初始化 PostgreSQL Schema |
| `python fdt_cli.py db health` | PostgreSQL 健康检查 |
| `python fdt_api.py` | FastAPI HTTP 服务 |

### API 接口

| 端点 | 方法 | 说明 |
|:-----|:-----|:-----|
| `/health` | GET | 健康检查 |
| `/api/v1/debate` | POST | 触发辩论（异步） |
| `/api/v1/debate/{trace_id}` | GET | 查询辩论状态 |
| `/api/v1/status` | GET | 任务运行统计 |

```bash
# API 使用示例
curl -X POST http://localhost:8000/api/v1/debate \
  -H "Content-Type: application/json" \
  -d '{"mode": "default"}'

curl http://localhost:8000/api/v1/debate/fdt-20260716-100000-12345
```

---

## 业务逻辑

每天开盘前，系统自动执行一套固定管道：

**数据采集 → 策略扫描 → 辩论 → 裁决 → 方案 → 风控 → 报告**

各环节独立运行，前序的输出是后序的输入。任何一个环节可单独重跑。

---

## 数据流

```
┌──────────────────────────────────────────────────┐
│ 数据层: FDC 统一数据引擎                          │
│ TQ-Local(主) → TqSDK(备) → QMT(备) → Web降级链   │
│ 采集: 日线120天K线 / 实时报价 / 持仓排名 / 仓单   │
│       基差(100ppi) / 宏观(东方财富) / 跨期价差    │
└──────────────────────┬───────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────┐
│ 策略层: 8 策略并行扫描 | NO_FUSION                │
│ 各策略独立打分，方向冲突不融合，全部送给辩论        │
│ 三层门禁: 震荡市(ADX+BB+KF) + 去趋势(Hurst+VR)   │
│          + P0-4 伪突破 19 种校验模式               │
└──────────────────────┬───────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────┐
│ 辩论层: 10 Agent 分工制衡 (LangGraph)            │
│ 数技源扫描 → 闫判官调度 → 三源并行(链证源/观澜/探源)│
│ → 多空辩论 → 闫判官裁决 → 策执远方案 → 风控明审核 │
└──────────────────────────────────────────────────┘
```

---

## 8 策略管线

| 策略 | 类型 | 做什么 | 触发条件 |
|:-----|:-----|:-------|:---------|
| `trend_following` | 趋势跟踪 | 10 子信号共振投票定方向 | 每日扫描，28 品种活跃 |
| `mean_reversion` | 价格反转 | RSI/CCI/BB 极端值回归 | ADX<25 震荡市 + KF 无偏移 |
| `arbitrage` | 套利 | 跨品种产业链配对 Z-score | 配对品种均活跃 |
| `pairs_reversion` | 配对回归 | EG 协整 + Hurst + KF z | 两腿均非趋势型 |
| `spread_reversion` | 近远月价差 | OU 拟合 + KF z | 价差偏离 > 2σ |
| `basis_reversion` | 期现基差 | OU 拟合 + KF z | 基差偏离 > 2σ |
| `macro_regime` | 宏观轮动 | 5 板块 46 品种制度切换 | 宏观信号到位 |
| `multi_factor` | 多因子加权 | 四维 13 因子评分 | 每日扫描，12 品种 |

均值回归四策略（`mean_reversion` + `pairs_reversion` + `spread_reversion` + `basis_reversion`）构成完整的做空做多覆盖。

---

## 10 Agent 辩论制衡

10 个 Agent 各司其职，**不越界、不重叠**：

| Agent | 职责 | 不做什么 |
|:------|:-----|:---------|
| 数技源 | 跑 8 策略管线产信号 | 不下方向结论 |
| 观澜 | 技术分析（支撑/阻力/POC） | 不判断多空 |
| 探源 | 基本面分析（产业链数据） | 不判断多空 |
| 链证源 | 产业链关联分析 | 不下交易结论 |
| 多头分析员 | 独立列举 ≥3 条做多论据 | 不做空头分析 |
| 空头分析员 | 独立列举 ≥3 条做空论据 | 不做多头分析 |
| 闫判官 | 在多空论据中裁决方向 | 不独立分析行情 |
| 策执远 | 制定可执行交易方案 | 不改裁决方向 |
| 风控明 | 6 层风控红线审核 | 不参与方向判断 |
| 明鉴秋 | 管道调度 + 报告归档 | 不介入内容决策 |

---

## 自进化闭环

每轮辩论产出后自动触发反馈链：

**T+1 回测验证** → 累计 ≥5 条有效样本 → **校准评分权重** → **进化 Agent Prompt** → 累计 ≥50 样本 → **LightGBM 增量训练**

进化过程不依赖人工标注，用实际行情验证结果作为真值。

---

## 运行模式

| 模式 | 说明 | 特点 |
|:-----|:-----|:-----|
| `default` | 默认模式 | 完整流程：扫描→闫判官→三源并行→辩论→裁决→方案→风控→报告 |
| `fast` | 快速模式 | 跳过辩论，直接裁决（适用于高频扫描） |
| `deep_research` | 深度研究 | 分歧>0.7时循环辩论（适用于复杂市场） |
| `tournament` | 锦标赛模式 | 多轮辩论+投票（适用于重大决策） |

### A/B 切换

通过环境变量 `FDT_USE_LANGGRAPH` 控制运行模式：

```bash
# 旧模式（文件传递）
FDT_USE_LANGGRAPH=false python pipeline/runner.py

# LangGraph 模式（内存状态传递，推荐）
FDT_USE_LANGGRAPH=true python pipeline/runner.py
```

---

## 项目结构

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
│   ├── skills/                # 技能文档
│   └── CODE_WIKI.md           # Code Wiki 技术文档
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

## 环境变量

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

## 测试运行

```bash
# 运行所有测试
python run_all_tests.py

# 运行特定模块测试
pytest tests/fdt_langgraph/ -v

# 运行基准对比测试
python scripts/run_benchmark.py --compare
```

---

## 技术文档

详细技术文档请参考：
- [Code Wiki](docs/CODE_WIKI.md) — 完整项目技术文档
- [架构总览](docs/harness/01-architecture.md) — Harness 工程规范
- [生命周期](docs/harness/02-lifecycle.md) — 阶段定义和状态机
- [配置说明](docs/harness/03-configuration.md) — 配置项和优先级

---

## 版本历史

| 版本 | 变更 |
|:-----|:-----|
| v8.4.0 | 完整 LangGraph 迁移完成 |
| v8.3.0 | LangGraph 架构支持、独立 CLI/FastAPI 入口 |
| v8.2.0 | PostgreSQL OLTP+OLAP 混合存储 |
| v8.1.8 | NO_FUSION 策略管线 |
| v8.0.0 | 去 WorkBuddy 依赖 |