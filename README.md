# Futures Debate Team — 期货交易辩论专家团

一套 **10-Agent 多角色交叉质询的 CTA 决策系统**。基于 LangGraph 构建，实现按需并行数据源、PostgreSQL OLTP+OLAP 混合存储、独立 CLI/FastAPI 入口。

**v9.16.0**

---

## 核心特性

- **10-Agent 辩论制衡** — 数技源/闫判官/链证源/观澜/探源/读心/多头分析员/空头分析员/风控明/明鉴秋/品藻，边界钉死不越界
- **5 层鲁棒防线 (L1-L5)** — 产出校验→熔断降级→信号门禁→路径发现→健康自检，各 Agent 独立超时降级
- **自进化闭环** — T+1 验证 → 权重校准 → Agent Prompt 进化 → LightGBM 增量训练，无需人工标注
- **NO_FUSION 策略管线** — 8 策略各自独立打分，方向冲突不融合、不掩盖、不平均
- **三层信号门禁** — 震荡市(ADX+BB+KF) + 去趋势(Hurst+VR) + P0-4 伪突破拦截，共 20+ 道校验
- **六阶段攻防辩论** — 多头立论(P4_1)→空头立论(P4_2)→空头驳论(P4_3)→多头驳论(P4_4)→空头结辩(P4_5)→多头结辩(P4_6)，多头只做多、空头只做空，来源可追溯
- **四源并行 LLM 推理** — 技术面/基本面/产业链/新闻情绪由 LLM 推理生成结构化输出
- **CTP 信号输出** — 闫判官裁决→风控明审核→明鉴秋统一调度 CTP 交易指令
- **PostgreSQL OLTP+OLAP** — 分区表 + BRIN/GIN 索引 + 物化视图分析
- **LangGraph 架构** — 可配置并行数据源、条件路由、状态持久化、断点恢复
- **独立运行** — 去平台依赖，支持 CLI/FastAPI 独立入口
- **FDC 数据注入 (P2.5)** — 预采集所有选中品种的结构化数据（K线/指标/期限结构/基差/仓单/基本面/持仓排名）供子 Agent 使用
- **金十 MCP 数据源** — 标准 MCP 协议接入金十财经数据（8 工具：行情/K线/快讯/资讯/财经日历），作为实时分析素材
- **新闻情绪分析因子** — 读心 Agent（第四分析因子），P3 阶段与链证源/观澜/探源并行，输出结构化 SentimentStateVector
- **主力合约统一解析** — `dominant_resolver` 统一主力合约判定与换月追踪
- **字段标准化** — `field_normalizer` 统一规范 8 类子 Agent 数据栏位
- **本地增量缓存** — `fdt_cache/` SQLite 持久化层，按品种+数据类型缓存 K 线/基本面/基差，增量 UPSERT
- **指定品种辩论模式** — 跳过 P1 扫描，直接从本地缓存加载数据进入辩论流程
- **Harness 工程规范** — 12 项 commit 前检查清单 + 10 条反模式检测规则 + Loop Contract 循环契约
- **ReAct 思维链机制** — 所有 Agent 按 Thought→Action→Observation 结构化记录推理过程，每条论据包含完整推理链（`reasoning_chain`/`analysis_chain`/`risk_chain`）
- **数据溯源铁律** — 每条论据必须包含 `source`、`data_date`、`data_staleness_days`，数据超过5天禁止作为主论据

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
│ Data-Core(0) → TDX(1) → WebFallback(2) → QMT(3) → TqSDK(98) │
│ 采集: 日线120天K线 / 实时报价 / 持仓排名 / 仓单   │
│       基差(100ppi) / 宏观(东方财富) / 跨期价差    │
│       期限结构 / 基本面(F10) / 持仓排名            │
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
│ 辩论层: 10 Agent 分工制衡 (LangGraph)             │
│ 数技源扫描 → 闫判官调度 → P2.5 FDC数据准备        │
│ 金十快讯精选 → → 四源并行(链证源/观澜/探源/读心) │
│ → 六阶段攻防: 多头立论→空头立论→空头驳论→多头驳论│
│ → 空头结辩→多头结辩→闫判官裁决(含交易参数)→风控明审核│
│ → 报告生成 → CTP信号输出                          │
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
| 观澜 | 技术面分析（LLM 推理生成 TechnicalOutput） | 不判断多空 |
| 探源 | 基本面分析（LLM 推理生成 FundamentalStateVector，含金十快讯素材） | 不判断多空 |
| 链证源 | 产业链关联分析 | 不下交易结论 |
| 读心 | 新闻情绪分析（LLM 推理生成 SentimentStateVector，金十+Web多源） | 不判断多空 |
| 多头分析员 | 独立列举 ≥3 条做多论据 | 不做空头分析 |
| 空头分析员 | 独立列举 ≥3 条做空论据 | 不做多头分析 |
| 闫判官 | 裁决方向+输出完整交易参数 | 不独立分析行情 |
| 风控明 | 直接基于闫判官 verdict 审核 | 不参与方向判断 |
| 明鉴秋 | 管道调度 + 报告生成 + CTP 信号输出 | 不介入内容决策 |

---

## 自进化闭环

每轮辩论产出后自动触发反馈链：

**T+1 回测验证** → 累计 ≥5 条有效样本 → **校准评分权重** → **进化 Agent Prompt** → 累计 ≥50 样本 → **LightGBM 增量训练**

进化过程不依赖人工标注，用实际行情验证结果作为真值。

---

## Harness & Loop Engineering

FDT 不仅仅是一个多 Agent 辩论系统，更是 **Harness Engineering 与 Loop Engineering 的生产级实践案例**。

### Harness 六维控制空间

FDT 的 Agent Harness 覆盖 MemoHarness 定义的全部六个控制维度：

| 维度 | FDT 实现 | 成熟度 |
|------|----------|:------:|
| **Context（上下文组装）** | `AGENTS.md` + 品种知识库 + Skill 渐进式披露 | ★★★★★ |
| **Tool（工具交互）** | 4 级数据降级链（含自动熔断）+ 8 策略管线 + CTP 交易接口 + `ToolMetrics` 工具调用效能追踪（pipeline 运行时集成） | ★★★★★ |
| **Generation（解码控制）** | 逐 Agent 解码配置（temperature/max_tokens/top_p）+ 结构化输出 Pydantic+JSON Schema 双校验 + 内容安全过滤 + 解码质量度量 + 失败升温重试 | ★★★★★ |
| **Orchestration（工作流拓扑）** | LangGraph 图编排 + 按需并行 + 4 种运行模式 + 条件路由 | ★★★★★ |
| **Memory（跨调用状态持久化）** | PostgreSQL OLTP+OLAP + Checkpointer + 辩论日志 + 向量记忆 + 知识图谱 + 过期清理与 journal 压缩 | ★★★★★ |
| **Output（输出处理）** | JSON Schema 校验 + 4 铁律 + 风控门控 + HTML 报告 + `OutputMetrics` 质量评分 + `OutputVersioning` 版本化 + `OutputAudit` 审计日志（全 pipeline 集成）| ★★★★★ |

### 双层循环结构

FDT 天然支持 Inner Loop（内循环）和 Outer Loop（外循环）：

```
┌─────────────────────────────────────────────────────┐
│  Outer Loop（外循环）— 跨会话持续进化                 │
│  T+1验证 → 权重校准 → Agent进化 → ML训练 → 注入下一轮 │
└───────────────────────┬─────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Inner Loop（内循环）— 单次辩论攻防                   │
│  P1→P2→P3→P4六阶段→P5裁决链→P6输出                    │
│  含 D06 降级、Maker-Checker 分离、分歧度控制          │
└─────────────────────────────────────────────────────┘
```

### 循环契约（Loop Contract）

每个自动化循环都有明确的六维度契约（TRIGGER / SCOPE / ACTION / BUDGET / STOP / REPORT）：

| 循环 ID | 名称 | 验证档位 | 权限 |
|---------|------|----------|------|
| `daily-debate` | 每日自动辩论 | **L3** (独立 Agent 审查) | Write（含 CTP 信号输出） |
| `self-evolve` | 自进化闭环 | L2 (测试套件) | Draft |
| `ml-training` | ML 模型训练循环 | L2 (测试套件) | Draft |
| `health-check` | 健康自检循环 | L1 (自检) | 只读 |
| `data-collection` | 数据采集循环 | L1 (自检) | 只读 |

详细契约定义见 [docs/harness/loop-contracts/](docs/harness/loop-contracts/README.md)。

### 10 篇 Harness 工程规范文档

FDT 将工程实践系统性地文档化，覆盖架构、生命周期、配置、鲁棒性、可观测性、测试、运维、差距分析、晋级计划、编码规范 10 个维度：

| # | 文档 | 内容 |
|:-:|:-----|:-----|
| 01 | [架构总览](docs/harness/01-architecture.md) | Harness 分层架构、组件关系图、数据流、Loop Engineering 视角 |
| 02 | [生命周期与编排](docs/harness/02-lifecycle.md) | 入口引导、6 阶段流水线、Agent 生成/销毁、自进化闭环、循环契约 |
| 03 | [配置管理](docs/harness/03-configuration.md) | 配置文件清单、环境变量、优先级覆盖链、校验机制 |
| 04 | [错误恢复与鲁棒性](docs/harness/04-resilience.md) | L1-L5 五层防线、S04 轮询协议、D06 降级、熔断 |
| 05 | [可观测性](docs/harness/05-observability.md) | APM-CS 五轴、统一日志、健康自检、ViBench 回放 |
| 06 | [测试策略](docs/harness/06-testing.md) | 测试金字塔、契约校验、门禁审计、覆盖率 |
| 07 | [运维与部署](docs/harness/07-operations.md) | 部署模式、调度器、看门狗、运维 Runbook |
| 08 | [差距分析与改进路线](docs/harness/08-gap-analysis.md) | 现状 vs 目标、缺失项清单、优先级排序 |
| 09 | [晋级计划](docs/harness/09-advancement-plan.md) | Harness 成熟度晋级路线、Phase 1-5 里程碑 |
| 10 | [编码规范](docs/harness/10-coding-standards.md) | 文档先行、契约优先、测试随重构、12 项 commit 纪律 |
| 11 | [循环契约规范](docs/harness/loop-contracts/README.md) | Loop Contract 六维度、验证档位、权限三档 |

### 关键设计理念

- **Maker-Checker 分离**：闫判官裁决 + 风控明独立审核，杜绝自我验证偏差（误接受率从 76.9% 降至 30.8%）
- **配方优于产物**：自进化记忆存"配方+评分"，不存产物本体，存储成本从 O(产物×轮数) 降到 O(配方×轮数)
- **验证器是瓶颈**：Loop 质量取决于可验证信号质量。接入真实行情验证 → 可测量提升；接入模型自评 → 几乎不动
- **每一次失败都是规则**：AGENTS.md 的每一行都追溯到一次真实失败。只在见过真实故障时加约束，只在能力足够时删约束

---

## 运行模式

| 模式 | 说明 | 特点 |
|:-----|:-----|:-----|
| `default` | 默认模式 | 完整流程：扫描→闫判官→四源并行→六阶段辩论→裁决(含交易参数)→风控→报告→CTP信号输出 |
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
├── contracts/                 # 契约定义（Schema，含 sentiment_state.py）
├── debate/                    # 辩论历史管理
├── docs/                      # 文档
│   ├── archive/               # 已归档的历史文档
│   ├── harness/               # Harness 工程规范（10篇 + README）
│   │   ├── designs/           # G21/G22 设计文档
│   │   ├── loop-contracts/    # 循环契约（5份）
│   │   ├── agent-protocol.md  # Agent 通信协议
│   │   ├── business_flow.md   # 业务流程
│   │   └── execution_modes_flowchart.md  # 执行模式流程图
│   ├── harness-templates/     # Harness 工程规范模板（harness-starter-kit）
│   ├── schemas/               # JSON Schema
│   └── skills/                # 技能文档
├── fdt_cache/                 # 本地 SQLite 增量缓存
├── fdt_langgraph/             # LangGraph 核心模块
│   ├── state.py               # DebateState 定义（含 FdcDataStatus）
│   ├── graph.py               # 图结构（含 P2.5 FDC 数据准备）
│   ├── nodes.py               # 节点函数（含 node_prepare_data）
│   ├── agents.py              # Agent 执行器（逐Agent LLM 配置）
│   └── health.py              # 健康检查
├── fdt_pg/                    # PostgreSQL 模块
│   ├── connection.py          # 连接管理
│   ├── schema.py              # ORM 模型
│   ├── deploy.py              # 部署工具
│   └── migrations/            # 数据库迁移
├── futures_data_core/         # 期货数据核心
│   ├── core/                  # 核心层（降级链、缓存、类型）
│   │   ├── dominant_resolver.py   # 主力合约解析
│   │   ├── field_normalizer.py    # 字段标准化
│   │   └── _datacore_bridge.py    # Data-Core F10 桥接器
│   ├── mcp_client.py          # MCP 协议通用 HTTP 客户端
│   ├── collectors/            # 采集器（TDX/QMT/TqSDK/Web/DataCore）
│   ├── f10/                   # F10 衍生品数据（含 jin10_mcp.py 金十采集器）
│   ├── indicators/            # 技术指标
│   └── cache/                 # 缓存
├── data_source_adapter.py     # 统一数据入口封装
├── memory/                    # 知识库和记忆系统
├── pipeline/                  # 流水线执行
├── scripts/                   # 辅助脚本
├── skills/                    # 子技能实现
├── tests/                     # 测试用例
├── fdt_cli.py                 # CLI 入口
├── fdt_api.py                 # FastAPI 入口
├── pyproject.toml             # 项目配置
├── CLAUDE.md                  # FDT 编码行为准则（项目标准文件）
├── CODE_WIKI.md               # 项目技术百科全书（理解项目基础）
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
| `FDT_DIRECT_DEBATE` | 指定品种辩论模式开关 | `false` |
| `FDT_DEBATE_SYMBOLS` | 指定辩论品种列表（逗号分隔） | - |
| `FDT_CACHE_DIR` | 本地缓存目录 | `memory/fdt_cache` |
| `FDT_FDC_INJECTION_ENABLED` | 是否启用 FDC 数据注入（P2.5） | `true` |
| `FDT_FDC_KLINE_DAYS` | FDC K线数据天数 | `120` |
| `FDT_FDC_F10_ENABLED` | 是否启用 F10 数据采集 | `true` |
| `FDT_FDC_POSITION_RANKING_ENABLED` | 是否启用持仓排名采集 | `true` |
| `JIN10_MCP_URL` | 金十 MCP 服务地址 | `https://mcp.jin10.com/mcp` |
| `JIN10_MCP_TOKEN` | 金十 MCP 认证 Token（Bearer） | - |
| `FDT_MCP_TIMEOUT` | MCP 客户端超时（秒） | `30` |

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
# strategies 测试: 19 文件
# scripts 测试: 7 文件 / 474+ 用例（68 模块）
# 合计: 13 个测试目录 / 69 文件 / 1400+ 用例
```

---

## 技术文档

### 三大入口文档（通用规范，适用于所有项目）

| 文档 | 定位 | 生命周期 |
|:-----|:-----|:---------|
| [CLAUDE.md](CLAUDE.md) | 编码行为准则 | 项目标准文件，不因开发环境变化而变化 |
| [CODE_WIKI.md](CODE_WIKI.md) | 技术百科全书 | 随项目全生命周期更新，理解项目基础 |
| [README.md](README.md) | 项目说明 | 随项目全生命周期更新，快速参考入口 |

### Harness 工程规范

- [架构总览](docs/harness/01-architecture.md) — Harness 分层架构、组件关系图、数据流
- [生命周期](docs/harness/02-lifecycle.md) — 阶段定义和状态机
- [配置说明](docs/harness/03-configuration.md) — 配置项和优先级
- [Harness 文档索引](docs/harness/README.md) — 全 10 篇工程规范清单

---

## 版本历史

| 版本 | 变更 |
|:-----|:-----|
| **v9.13.0** | **逐品种独立辩论循环** — 每个品种独立走完整数据链（prepare_one_symbol→四源→辩论→裁决→风控→store→route）；scan_all.py 程序化品种分组（同产品代码按成交量选主辩论品种）；闫判官不再判断相关性 |
| **v9.11.0** | **新闻情绪分析因子（读心）落地 — 第四分析因子 P3 并行** — 新增 `sentiment_state.py` 契约（SentimentStateVector）、`futures-news-sentiment-analyst.md` 读心 Agent、`node_sentiment()` 节点、`sentiment_data` 状态字段。P3 从三源并行升级为四源并行（链证源/观澜/探源/读心）。来源标记 `[sentiment:jin10]` / `[sentiment:web]`。25 个金十相关测试全绿。 |
| **v9.10.1** | **金十快讯精选注入探源** — `_SYMBOL_TO_KEYWORDS` 品种→中文关键词映射（41 品种）、`_build_jin10_context()` 按品种自动搜索金十快讯、去重格式化后注入 `node_fundamental` context。探源数据来源 §2 更新 + R07 金十快讯引用规范。 |
| **v9.10.0** | **金十数据 MCP 接入** — 标准 MCP 协议财经数据源。新增 `mcp_client.py` 通用 MCP HTTP 客户端（SSE 解析/会话管理/structuredContent优先）、`jin10_mcp.py` 金十采集器（8 工具）、`data_source_adapter` 适配接口、`web_crawl_tool` LangChain 封装。Harness 文档全线同步。 |
| **v9.6.8** | **Harness 文档整理 + 入口文档同步检查扩展** — ① harness-starter-kit 迁移到 `docs/harness-templates/`；② 设计文档、流程文档归入 `docs/harness/` 统一管理；③ 旧规范归档到 `docs/archive/`；④ C12 检查规则扩展为 `README.md|CODE_WIKI.md`，根目录三大入口文档（CLAUDE.md/CODE_WIKI.md/README.md）纳入同步检查机制，随项目全生命周期更新。 |
| **v9.6.5** | **G93-G96 LangGraph 迁移全部完成 + 配置 Schema 扩展** — coordinator.py→graph.py(G93)、debate_protocol_v2.py→nodes.py(G94)、agent_runner.py→agents.py(G95)、DuckDB→PostgreSQL JSON 迁移(G96)。3 个旧文件删除，16 个迁移测试全部通过。D2/D3/D5/D6 四维提升至 ★★★★★。新增 `DataSourcesConfig` + `AgentProfilesData` Pydantic 校验，覆盖全部 4 个配置文件。 |
| **v9.6.4** | **G71 完全关闭 + 循环契约补全 + ReAct 思维链集成** — 8 文件手工注解补全 + ml-training/health-check 两份 Loop Contract + 6 Agent 配置文件升级 v2.3（ReAct 思维链 + 数据溯源铁律） |
| **v9.6.0** | **Harness 工程全面升级** — 规范引擎化（harness-rules.yaml + pre-commit v2）、类型注解全量补充（580 函数）、5 个缺失规范维度补充、10 条反模式检测规则、G21/G22 设计文档 |
| **v9.5.0** | **Loop Engineering 体系化** — 新增 Loop Contract 规范与 daily-debate 首份契约；架构文档添加 Loop Engineering 视角；差距分析登记 G20/G21/G22 |
| **v9.4.3** | **G91 同品种多子信号合并方向覆盖 bug 修复** — `pipeline.py` Phase 4.8 引入 `_merge_acc` 累积器；新增 `TestSubSignalMerge` 4 用例 |
| **v9.4.2** | **G89/G90 修复** — debate_only 信号多空论据丢失修复；信号排序改为交易可靠性优先（置信度 × 盈亏比） |
| **v9.4.1** | **G88 K 线数据链路根因修复（P0）** — 修复 `MultiSourceAdapter.get_kline()` 入口处的"自动主力解析" bug |
| **v9.4.0** | **G87 Data-Core F10 全面集成** — 新增 `_datacore_bridge.py`；改造 6 个 F10 模块入口；新增 2 个测试文件共 36 用例 |
| **v9.3.0** | **G86 主力合约统一解析 + DataCore 集成 + 字段标准化** — 新增 `dominant_resolver.py`、`DataCoreCollector`、`field_normalizer.py` |
| **v9.2.0** | **Loop Engineering 剥离** — 因子自演化移出 FDT 系统；文档归档与翻新 |
| **v9.1.0** | **本地增量缓存** — `fdt_cache/` SQLite 缓存层；指定品种辩论模式（`FDT_DIRECT_DEBATE`） |
| **v9.0.0** | **六阶段攻防辩论** — 多头立论→空头立论→空头驳论→多头驳论→空头结辩→多头结辩；来源可追溯；闫判官可推翻数技源方向 |
| **v8.9.0** | **交叉质询串行化 + 逐Agent LLM** — P4 拆分为串行三步骤；FDT_LLM_<NAME>_* 逐 Agent 独立模型配置 |
| **v8.8.0** | **明鉴秋报告层调度** — 5 阶段独立 HTML 报告（信号扫描/三源研究/裁决风控/辩论/CTP 信号） |
| **v8.7.0** | **架构精简** — 策执远合并到闫判官；CTP 信号输出；观澜/探源 LLM 推理 |
| v8.4.0 | 完整 LangGraph 迁移完成 |
| v8.3.0 | LangGraph 架构支持、独立 CLI/FastAPI 入口 |
| v8.2.0 | PostgreSQL OLTP+OLAP 混合存储 |
| v8.1.8 | NO_FUSION 策略管线 |
| v8.0.0 | 去平台依赖，独立运行 |
