# Futures Debate Team — 期货交易辩论专家团

一套 **9-Agent 多角色交叉质询的 CTA 决策系统**。基于 LangGraph 构建，实现按需并行数据源、PostgreSQL OLTP+OLAP 混合存储、独立 CLI/FastAPI 入口。

**v9.0.0 — 全网排名第 1 的中国期货 CTA 多Agent LLM 系统**

---

## 核心特性

- **🥇 中国期货 CTA 赛道第 1 名** — 全网唯一专注 62 品种的多Agent LLM 期货交易系统（[排名报告](docs/FDT_China_Ranking_Report_v1.0.md)）
- **9-Agent 辩论制衡** — 数技源/闫判官/链证源/观澜/探源/多头分析员/空头分析员/风控明/明鉴秋，边界钉死不越界
- **5 层鲁棒防线 (L1-L5)** — 产出校验→熔断降级→信号门禁→路径发现→健康自检，各 Agent 独立超时降级
- **自进化闭环** — T+1 验证 → 权重校准 → Agent Prompt 进化 → LightGBM 增量训练，无需人工标注
- **NO_FUSION 策略管线** — 8 策略各自独立打分，方向冲突不融合、不掩盖、不平均
- **三层信号门禁** — 震荡市(ADX+BB+KF) + 去趋势(Hurst+VR) + P0-4 伪突破拦截，共 20+ 道校验
- **六阶段攻防辩论** — 多头立论(P4_1)→空头立论(P4_2)→空头驳论(P4_3)→多头驳论(P4_4)→空头结辩(P4_5)→多头结辩(P4_6)，多头只做多、空头只做空，来源可追溯
- **观澜/探源 LLM 推理** — 技术面/基本面由 LLM 推理生成结构化 TechnicalOutput/FundamentalStateVector
- **CTP 信号输出** — 闫判官裁决→风控明审核→明鉴秋统一调度 CTP 交易指令
- **PostgreSQL OLTP+OLAP** — 分区表 + BRIN/GIN 索引 + 物化视图分析
- **LangGraph 架构** — 可配置并行数据源、条件路由、状态持久化、断点恢复
- **独立运行** — 去 WorkBuddy 依赖，支持 CLI/FastAPI 独立入口
- **1300+ 测试用例** — 19+ 测试文件，12 份 Harness 工程规范文档

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

curl http://localhost:8000/api/v1/debate/fdt-20260717-100000-12345
```

---

## 业务逻辑

每天开盘前，系统自动执行一套固定管道：

**数据采集 → 策略扫描 → 辩论 → 裁决（含交易参数）→ 风控 → 报告 → CTP 信号输出**

各环节独立运行，前序的输出是后序的输入。任何一个环节可单独重跑。

---

## 数据流

```
┌──────────────────────────────────────────────────┐
│ 数据层: FDC 统一数据引擎                          │
│ TQ-Local(主) → WebFallback(备) → QMT(备) → TqSDK(末位兜底)  │
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
│ 辩论层: 9 Agent 分工制衡 (LangGraph)             │
│ 数技源扫描 → 闫判官调度 → 三源并行(链证源/观澜/探源)│
│ → 六阶段攻防: 多头立论→空头立论→空头驳论→多头驳论│
│ → 空头结辩→多头结辩→闫判官裁决(含交易参数)→风控明审核│
│ → 报告生成 → CTP信号输出（v8.7.0）               │
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

## 9 Agent 辩论制衡

9 个 Agent 各司其职，**不越界、不重叠**：

| Agent | 职责 | 不做什么 |
|:------|:-----|:---------|
| 数技源 | 跑 8 策略管线产信号 | 不下方向结论 |
| 观澜 | 技术面分析（v8.6.0+ LLM 推理生成 TechnicalOutput） | 不判断多空 |
| 探源 | 基本面分析（v8.6.0+ LLM 推理生成 FundamentalStateVector） | 不判断多空 |
| 链证源 | 产业链关联分析 | 不下交易结论 |
| 多头分析员 | 独立列举 ≥3 条做多论据 | 不做空头分析 |
| 空头分析员 | 独立列举 ≥3 条做空论据 | 不做多头分析 |
| 闫判官 | 裁决方向+输出完整交易参数 | 不独立分析行情 |
| 风控明 | 直接基于闫判官 verdict 审核 | 不参与方向判断 |
| 明鉴秋 | 管道调度 + 报告生成 + CTP 信号输出（v8.7.0） | 不介入内容决策 |

---

## 自进化闭环

每轮辩论产出后自动触发反馈链：

**T+1 回测验证** → 累计 ≥5 条有效样本 → **校准评分权重** → **进化 Agent Prompt** → 累计 ≥50 样本 → **LightGBM 增量训练**

进化过程不依赖人工标注，用实际行情验证结果作为真值。

---

## 运行模式

| 模式 | 说明 | 特点 |
|:-----|:-----|:-----|
| `default` | 默认模式 | 完整流程：扫描→闫判官→三源并行→辩论→裁决(含交易参数)→风控→报告→CTP信号输出 |
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
├── agents/                    # Agent 配置文件（9个）
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
├── coordination_config.yaml   # 协调配置
├── pyproject.toml             # 项目配置
└── README.md                  # 项目说明
```

---

## 环境变量

| 变量 | 说明 | 默认值 |
|:-----|:-----|:-------|
| `FDT_LLM_API_KEY` | LLM 全局 API Key | - |
| `FDT_LLM_API_BASE` | LLM 全局 API Base URL | `https://api.deepseek.com/v1` |
| `FDT_LLM_MODEL` | LLM 全局模型名称 | `deepseek-chat` |
| `FDT_LLM_<NAME>_API_KEY` | 逐Agent API Key（覆盖全局） | - |
| `FDT_LLM_<NAME>_API_BASE` | 逐Agent API Base URL（覆盖全局） | - |
| `FDT_LLM_<NAME>_MODEL` | 逐Agent 模型名（覆盖全局） | - |
| `FDT_PG_DSN` | PostgreSQL 连接字符串 | - |
| `FDT_USE_LANGGRAPH` | 是否使用 LangGraph 模式 | `false` |
| `FDT_CHECKPOINTER` | Checkpointer 类型（pg/sqlite） | `sqlite` |
| `FDT_SCAN_MODE` | 扫描模式（no-filter） | - |
| `FDT_STRATEGIES` | 指定策略列表 | - |
| `FDT_RISK_THRESHOLD` | CTP 信号风控阈值（green/yellow/red） | `yellow` |
| `FDT_REPORT_WORKSPACE` | 用户指定工作空间根目录 | - |
| `FDT_DAILY_WORKSPACE` | 每日自动化任务工作空间 | - |

---

## 测试运行

```bash
# 运行所有测试
python run_all_tests.py

# 运行特定模块测试
pytest tests/fdt_langgraph/ -v

# 运行基准对比测试
python scripts/run_benchmark.py --compare

# 查看测试统计
# fdt_langgraph 测试: 5 文件 / 43 用例（六阶段辩论全绿）
# scripts 测试: 7 文件 / 474+ 用例
# 合计: 12+ 文件 / 1100+ 用例（42+ 测试全绿，G82 六阶段辩论测试已关闭）
```

---

## 技术文档

详细技术文档请参考：
- [Code Wiki](docs/CODE_WIKI.md) — 完整项目技术文档
- [架构总览](docs/harness/01-architecture.md) — Harness 工程规范
- [生命周期](docs/harness/02-lifecycle.md) — 阶段定义和状态机
- [配置说明](docs/harness/03-configuration.md) — 配置项和优先级
- [全球排名报告](docs/FDT_AI_Capabilities_Ranking_Report_v1.0.md) — 全网 AI 能力排名分析
- [中国排名报告](docs/FDT_China_Ranking_Report_v1.0.md) — 中国境内排名分析

---

## 版本历史

| 版本 | 变更 |
|:-----|:-----|
| **v9.0.0** | **辩论流程重大重构：正反方→多空头六阶段攻防模式**：① 多头只论证做多，空头只论证做空；② 六阶段辩论——多头立论(P4_1)→空头立论(P4_2)→空头驳论(P4_3)→多头驳论(P4_4)→空头结辩(P4_5)→多头结辩(P4_6)→闫判官裁决；③ 分析师中立化，来源可追溯（`[scan]/[technical:观澜]/[fundamental:探源]/[chain:链证源]`）；④ 闫判官可推翻数技源方向，新增 `overturn_scan` 标记；⑤ `calculate_divergence()` 修复遗漏反驳阶段置信度（G84）；⑥ 全量 Harness 文档同步六阶段架构（G83关闭）；版本号 bump 8.10.0→9.0.0 |
| **v8.9.0** | **辩论模式重构**：P4 从并行改为串行交叉质询（多头立论→空头质疑→多头反驳）；新增 `debate_round` 轮次计数器 + Reducer 自动合并；新增 `docs/TECH_STACK_DECISIONS.md`；graph.py 25%→93%，agents.py 71%→97%，health.py 0%→100% |
| **v8.8.8** | 🏆 **全网排名里程碑**：① 完成全网 AI 能力排名分析（8 维度 / 11 系统对比）② 中国期货 CTA 赛道第 1 名且全网唯一 ③ 6 项 S 级评分 ④ 更新 README 至 v8.8.8 |
| **v8.7.0** | 🎯 **架构精简 v2**：删除策执远角色，闫判官直接输出完整交易参数，风控明直接基于 verdict 审核，流程简化为 verdict → risk_check → report → signal_output → END |
| **v8.6.0** | 🎯 **架构精简 v1**：明鉴秋聚焦调度，删除 L1-L4 评分，新增 node_report/node_signal_output，观澜/探源 LLM 推理产出 TechnicalOutput/FundamentalStateVector |
| v8.5.4 | cov-3 候选模块测试覆盖（unified_logger / fdt_version / config_manager / fdt_llm 共 144 用例） |
| v8.5.3 | cov-2 任务：新增 178 个测试用例（fdt_paths / trace_id / confidence_utils） |
| v8.5.0 | FDC 数据注入架构 + 16 个 schema 增强 |
| v8.4.0 | 完整 LangGraph 迁移完成 |
| v8.3.0 | LangGraph 架构支持、独立 CLI/FastAPI 入口 |
| v8.2.0 | PostgreSQL OLTP+OLAP 混合存储 |
| v8.1.8 | NO_FUSION 策略管线 |
| v8.0.0 | 去 WorkBuddy 依赖 |
