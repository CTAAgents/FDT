# Futures Debate Team — 期货交易辩论专家团

一套 **13-Agent 多角色交叉质询的 CTA 决策系统**。基于 LangGraph 构建，实现按需并行数据源、PostgreSQL OLTP+OLAP 混合存储、独立 CLI/FastAPI 入口。

**v9.25.0**

---

## 核心特性

### 多 Agent 辩论制衡
- **13-Agent 辩论制衡** — 11 核心 + 2 辅助评估（数技源/闫判官/链证源/观澜/探源/读心/多头分析员/空头分析员/风控明/明鉴秋/品藻 + 副裁官/独立裁官），边界钉死不越界
- **六阶段攻防辩论** — 多头立论(P4_1)→空头立论(P4_2)→空头驳论(P4_3)→多头驳论(P4_4)→空头结辩(P4_5)→多头结辩(P4_6)，辩手只做方向论证不自行搜索
- **四源并行 LLM 推理** — 技术面/基本面/产业链/新闻情绪由 LLM 推理生成结构化输出，任一源超时(300s)跳过其余继续
- **逐品种循环处理** — 每个品种独立走 P3→P4→P5→质检→存储的完整数据链，全部完成汇聚

### 数据与策略管线
- **NO_FUSION 策略管线** — trend_following 含 10 独立子信号，各自打分不融合；三层信号门禁（震荡市+去趋势+伪突破拦截）共 20+ 道校验
- **FDC 数据注入 (P2.5)** — 预采集所有选中品种的结构化数据（K线/指标/期限结构/基差/仓单/基本面/持仓排名）
- **5 级数据降级链** — TqSDK(0) → TDX/DataCore(1) → Web(2) → QMT(3)，每级独立熔断器
- **金十 MCP 数据源** — 标准 MCP 协议接入金十财经数据，8 工具覆盖行情/K线/快讯/资讯/财经日历
- **本地增量缓存** — `fdt_cache/` SQLite 持久化层，按品种+数据类型增量 UPSERT

### 质量与安全
- **辩论输出质量治理** — 不合格输出退回重修（最多 2 次），含 Schema 校验
- **品藻实时质检** — validate_argument/verdict/risk 三层次校验 + 内容安全过滤 + 报告排版核验
- **Maker-Checker 分离** — 闫判官裁决 + 风控明独立审核，杜绝自我验证偏差
- **ReAct 思维链 + 数据溯源铁律** — 每条论据包含完整推理链，数据超过 5 天禁止作为主论据

### 工程架构
- **LangGraph 4 子图架构** — Debate Graph（辩论执行）+ Master Graph（14 任务统一调度）+ Evolution Graph（自进化闭环）+ RHI Graph（递归 Harness 自优化），零第三方调度依赖
- **自进化闭环** — 品藻质检 + APM-CS 五轴评分(D1-D5) → 自改进提案 → 权重校准 → Agent 进化 → RHI pairwise Harness 自优化 → ML 增量训练
- **RHI 递归自进化** — 基于 pairwise 对比的 Harness 三层规范（Agent Candidates / Workflow / Auxiliary Rules）自动优化，四维评分（质检通过率/风控准确率/信号命中率/报告完整性），收敛阈值 ε=0.3
- **Harness 工程规范** — 13 项 commit 前检查 + 10 条反模式检测 + Loop Contract 循环契约 + 文档一致性三层保障
- **独立运行** — 去平台依赖，支持 CLI / FastAPI / LangGraph 守护进程三种入口

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

# 设置环境变量
export FDT_LLM_API_KEY="sk-xxx"         # DeepSeek / OpenAI API Key
export FDT_PG_DSN="postgresql://user:pass@localhost:5432/fdt"  # PostgreSQL（可选）
```

### 核心命令

| 命令 | 功能 |
|:-----|:------|
| `python fdt_cli.py run [--mode default/fast/deep_research/tournament] [--evolve]` | 单次辩论执行（可选自进化、RHI） |
| `python fdt_cli.py daemon [--interval 60]` | Master Orchestrator 守护进程模式 |
| `python fdt_cli.py master` | Master 单次检查到期任务 |
| `python fdt_cli.py evolve [--trace-id <id>]` | 独立运行自进化闭环 |
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
│ TqSDK(0) → TDX/DataCore(1) → WebFallback(2) → QMT(3) │
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
│ 辩论层: 13 Agent 分工制衡 (LangGraph)             │
│ 数技源扫描 → 闫判官调度 → P2.5 FDC数据准备        │
│ 金十快讯精选 → 四源并行(链证源/观澜/探源/读心)   │
│ → 六阶段攻防: 多头立论→空头立论→空头驳论→多头驳论│
│ → 空头结辩→多头结辩→闫判官裁决(含交易参数)→风控明审核│
│ → 品藻质检 → 报告生成 → CTP信号输出               │
└──────────────────────────────────────────────────┘
```

---

## 8 策略管线

| 策略 | 类型 | 状态 | 说明 |
|:-----|:-----|:----:|:------|
| `trend_following` | 趋势跟踪 | 活跃 | **唯一活跃策略**，10 子信号共振投票定方向 |
| `mean_reversion` | 价格反转 | 禁用 | RSI/CCI/BB 极端值回归（ADX<25 震荡市） |
| `arbitrage` | 套利 | 禁用 | 跨品种产业链配对 Z-score |
| `pairs_reversion` | 配对回归 | 禁用 | EG 协整 + Hurst + KF z |
| `spread_reversion` | 近远月价差 | 禁用 | OU 拟合 + KF z（价差偏离 > 2σ） |
| `basis_reversion` | 期现基差 | 禁用 | OU 拟合 + KF z（基差偏离 > 2σ） |
| `macro_regime` | 宏观轮动 | 禁用 | 5 板块 46 品种制度切换 |
| `multi_factor` | 多因子加权 | 禁用 | 四维 13 因子评分 |

---

## 13 Agent 辩论制衡

11 个核心 Agent + 2 个辅助评估 Agent，各司其职，**不越界、不重叠**：

| Agent | 职责 | 不做什么 |
|:------|:------|:---------|
| **数技源** | 跑 trend_following（10 子信号）管线产信号 | 不下方向结论 |
| **观澜** | 技术面分析（LLM 推理生成 TechnicalOutput） | 不判断多空 |
| **探源** | 基本面分析（LLM 推理生成 FundamentalStateVector） | 不判断多空 |
| **链证源** | 产业链关联分析 | 不下交易结论 |
| **读心** | 新闻情绪分析（LLM，金十+Web 多源） | 不判断多空 |
| **多头分析员** | 独立列举 ≥3 条做多论据 | 禁止自行搜索 |
| **空头分析员** | 独立列举 ≥3 条做空论据 | 禁止自行搜索 |
| **闫判官** | P2 初判 + P5 终裁（含完整交易参数） | 不独立分析行情 |
| **副裁官** | 初审辩论输出，提取论点树（辅助评估） | 不独立判断 |
| **独立裁官** | 审计辩论一致性（不参与主流程） | 不参与裁决 |
| **风控明** | 直接基于闫判官 verdict 审核（green/yellow/red） | 不参与方向判断 |
| **品藻** | 辩论输出质检 + Schema 校验 + 内容安全过滤 | 不修改裁决内容 |
| **明鉴秋** | 选题/调度 + 汇总归档 + CTP 信号输出 | 不介入内容决策 |

---

## 自进化闭环

FDT 的自进化 Outer Loop 由 **Evolution Graph (LangGraph 子图)** 驱动，包含**四层闭环 + RHI 递归自优化**：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    自进化闭环（Evolution Graph + RHI）                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  【实时层】每轮辩论                                                  │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │ 品藻实时质检 (validate_argument/verdict/risk)              │      │
│  │ D3 结构化输出校验 + D6 OutputMetrics + OutputAudit          │      │
│  └───────────────────────────────────────────────────────────┘      │
│                            ↓                                        │
│  【反馈层】APM 评估 → 条件触发                                     │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │ node_collect_metrics → node_apm_eval → node_decide_actions │      │
│  │ 各步骤条件路由:                                               │      │
│  │  APM退化 → improve → calibrate(≥5条) → evolve(≥5条)        │      │
│  │  → RHI(FDT_RHI=true) → ML训练(≥50条) → complete             │      │
│  └───────────────────────────────────────────────────────────┘      │
│                            ↓                                        │
│  【RHI 递归自优化层】pairwise 对比驱动                              │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │ HarnessSpec 三层规范 (Agent Candidates/Workflow/Rules)      │      │
│  │ → pairwaise_eval (四维评分:质检/风控/信号/报告)             │      │
│  │ → harness_optimizer (LLM生成方案) → apply_delta             │      │
│  │ → 收敛判断 (ε=0.3, max_iter=5)                              │      │
│  └───────────────────────────────────────────────────────────┘      │
│                            ↓                                        │
│  【监控层】每周一 APM-CS 五轴评分卡 (D1-D5)                         │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │ D1 Coherence: 裁决与论据一致性 / D2 Acuity: 信号-噪音辨识力 │      │
│  │ D3 Composure: 波动率镇定度 / D4 Discipline: 规则遵守度      │      │
│  │ D5 Reliability: 闭环完成率 / 每周失败聚类 (cluster_failures) │      │
│  └───────────────────────────────────────────────────────────┘      │
│                            ↓                                        │
│  【改进层】持续优化 + 全局 Harness RHI                             │
│  ┌───────────────────────────────────────────────────────────┐      │
│  │ APM 退化 → self_improve / rhi_global_cli CLI 工具          │      │
│  │ Generation/Tool/Output Metrics → 配置微调                   │      │
│  └───────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

进化过程不依赖人工标注，用实际行情验证结果作为真值。`FDT_RHI=true` 启用 RHI 分支。

---

## Harness 自进化体系

FDT 不仅用 AI 做交易决策，更用 AI **自动进化自身的工程规范**。整个 Harness 体系本身是一个可自优化的闭环——规范被编码为**机读规则**、通过 **pre-commit 强制检查**、由 **RHI 递归优化**。

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    Harness 自进化闭环 — 规范即代码，代码即规范                  │
│                                                                              │
│   ┌────────────────────┐     ┌──────────────────────┐                        │
│   │ 规范编码为机读规则    │────→│ pre-commit 自动强制检查  │──→ commit block    │
│   │ harness-rules.yaml  │     │ 13项规则 + 10条反模式  │    or pass          │
│   │ (C01-C13 + AP01-AP10)│     │ 每条规则: trigger/severity/scope │          │
│   └─────────┬──────────┘     └──────────┬───────────┘                        │
│             │                            │                                   │
│             │       ┌────────────────────┘                                   │
│             ▼       ▼                                                        │
│   ┌─────────────────────────────────────────┐                               │
│   │             文档一致性三层保障              │                               │
│   │  Layer 1: 每篇文档末尾 ## 一致性元数据 表格    │                               │
│   │  Layer 2: verify_doc_consistency.py 自动校验 │                               │
│   │  Layer 3: _data/*.yaml 数据驱动文档         │                               │
│   └──────────────────┬──────────────────────┘                               │
│                      │ 每月触发                                               │
│                      ▼                                                        │
│   ┌─────────────────────────────────────────────────────┐                    │
│   │         RHI 递归自优化 — 用 AI 改进 Harness 本身       │                    │
│   │                                                      │                    │
│   │  1. 采集基线: 质检通过率/风控准确率/信号命中率/报告完整度 │                    │
│   │  2. Pairwise 评估: 当前规范 vs 候选规范 四维对比评分    │                    │
│   │  3. Harness Optimizer (LLM): 生成三层规范改进方案      │                    │
│   │     ├─ Agent Candidates (角色指令/输出契约/LLM配置)    │                    │
│   │     ├─ Workflow (Contract+Hop: 步骤/超时/降级策略)     │                    │
│   │     └─ Auxiliary Rules (验收门禁/回退/通信/召回)       │                    │
│   │  4. Apply Delta: 修改 agents/*.md + config/*.yaml     │                    │
│   │  5. 收敛判断: improvement_rate < 0.3 或 max_iter=5    │                    │
│   └──────────────────┬──────────────────────────────────┘                    │
│                      │                                                       │
│                      ▼                                                       │
│              ┌──────────────────────┐                                        │
│              │ 全局 Harness RHI CLI │──→ 任何项目均可: init/status/step       │
│              │ rhi_global_cli.py   │     /history/install                    │
│              └──────────────────────┘                                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 三步进化机制

| 步骤 | 机制 | 触发 | 产出 |
|:-----|:------|:-----|:------|
| **检测** | harness-rules.yaml 机读规则 + pre-commit 自动扫描 | 每次 commit | JSON 结构化检查报告 |
| **校验** | 文档一致性三层保障 — 元数据/自动脚本/数据驱动 | commit 前或 docs/ 变更 | 一致性通过/失败 |
| **优化** | RHI recursive self-improvement — pairwise 四维评分 + LLM 方案 | FDT_RHI=true / 手动 | Harness 三层规范改进 |

### Harness 六维控制空间

| 维度 | FDT 实现 | 成熟度 |
|------|----------|:------:|
| **Context（上下文组装）** | `AGENTS.md` + 品种知识库 + Skill 渐进式披露 | ★★★★★ |
| **Tool（工具交互）** | 5 级数据降级链（含自动熔断）+ 8 策略管线 + CTP 交易接口 | ★★★★★ |
| **Generation（解码控制）** | 逐 Agent 解码配置 + 结构化输出 Pydantic+JSON Schema 双校验 + 内容安全过滤 | ★★★★★ |
| **Orchestration（工作流拓扑）** | LangGraph 4 子图编排 + 4 种运行模式 + 条件路由 | ★★★★★ |
| **Memory（跨调用状态持久化）** | PostgreSQL OLTP+OLAP + Checkpointer + 辩论日志 + 向量记忆 + 知识图谱 | ★★★★★ |
| **Output（输出处理）** | JSON Schema 校验 + 风控门控 + HTML 报告 + 质量评分 + 审计日志 | ★★★★★ |

### 三层循环结构

```
┌────────────────────────────────────────────────────────────┐
│  RHI Loop — 最外层：Harness 规范自进化                     │
│  Pairwise 四维评分 → Harness Optimizer(LLM) → Apply Delta │
│  → 收敛判断 (ε=0.3, max_iter=5)                           │
│  pre-commit 13项检查 + 文档一致性三层保障 作为质量门禁       │
└────────────────────────┬───────────────────────────────────┘
                         │ 每轮辩论后自动触发 (FDT_RHI=true)
                         ▼
┌────────────────────────────────────────────────────────────┐
│  Outer Loop — 中间层：跨会话交易策略进化                    │
│  collect_metrics → apm_eval → decide_actions               │
│  → improve(APM退化) → calibrate(≥5条) → evolve(≥5条)      │
│  → RHI → ml_train(≥50条) → complete                        │
└───────────────────────┬────────────────────────────────────┘
                        │ 每次辩论后触发
                        ▼
┌────────────────────────────────────────────────────────────┐
│  Inner Loop — 最内层：单次辩论攻防                          │
│  P1(扫描)→P2(调度)→P2.5(FDC)→P3(四源并行)→P4(六阶段)     │
│  →P5(裁决+风控)→P5.5(质检重修)→P6(报告+信号)              │
│  含 D06 降级、Maker-Checker 分离、分歧度控制、逐品种循环    │
└────────────────────────────────────────────────────────────┘
```

### 循环契约（Loop Contract）

| 循环 ID | 名称 | 验证档位 | 权限 |
|---------|------|----------|------|
| `daily-debate` | 每日自动辩论 (Inner) | L3（独立 Agent 审查） | Write（含 CTP 信号） |
| `self-evolve` | 自进化闭环 (Outer) | L2（测试套件） | Draft |
| `rhi-optimize` | Harness 递归自优化 (RHI) | L2（测试套件） | Draft |
| `ml-training` | ML 模型训练循环 | L2（测试套件） | Draft |
| `health-check` | 健康自检循环 | L1（自检） | 只读 |
| `data-collection` | 数据采集循环 | L1（自检） | 只读 |

详细契约定义见 [docs/harness/loop-contracts/](docs/harness/loop-contracts/README.md)。

### 关键设计理念

- **规范即代码**：harness-rules.yaml 是机读的编码化规则，同源码一起版本管理、一起审查
- **自指(self-referential)**：RHI 用 AI 改进 Harness，Harness 反过来约束 AI 行为，形成闭合进化环
- **三层收敛**：RHI(ε=0.3) → APM(退化阈值) → commit(pass/fail)，从慢到快三级反馈
- **全局可迁移**：`rhi_global_cli.py` 可将 Harness 自进化能力带到任意项目

---

## 运行模式

| 模式 | 说明 | 特点 |
|:-----|:-----|:-----|
| `default` | 默认模式 | 完整流程：扫描→闫判官→四源并行→六阶段辩论→裁决→风控→质检→报告→CTP 信号 |
| `fast` | 快速模式 | 跳过辩论，直接裁决（适用于高频扫描） |
| `deep_research` | 深度研究 | 分歧>0.7 时循环辩论（适用于复杂市场） |
| `tournament` | 锦标赛模式 | 多轮辩论+投票（适用于重大决策） |

---

## 项目结构

```
FDT/
├── agents/                    # Agent 配置文件（13个，11核心+2辅助）
├── config/                    # 配置文件（LLM/Agent/D3 Decode Control）
├── contracts/                 # 契约定义（A2A 数据信封/辩论 Schema/质检 Schema）
├── docs/                      # 文档体系
│   ├── archive/               # 已归档历史文档
│   └── harness/               # Harness 工程规范（10篇 + loop-contracts + schemas）
├── fdt_cache/                 # 本地 SQLite 增量缓存
├── fdt_langgraph/             # LangGraph 核心模块（3 子图）
├── fdt_pg/                    # PostgreSQL 模块
├── futures_data_core/         # 期货数据核心引擎
├── memory/                    # 知识库与记忆系统
├── scripts/                   # 80+ 辅助脚本
├── skills/                    # 10 个子技能实现
├── tests/                     # 1124 测试用例
├── fdt_cli.py                 # CLI 入口
├── fdt_api.py                 # FastAPI 入口
├── data_source_adapter.py     # 统一数据入口封装
├── pyproject.toml             # 项目配置（版本号真相源）
├── CLAUDE.md                  # 编码行为准则
├── CODE_WIKI.md               # 技术百科全书
└── README.md                  # 项目说明
```

---

## 环境变量

| 变量 | 说明 | 默认值 |
|:-----|:------|:-------|
| `FDT_LLM_API_KEY` | LLM 全局 API Key | - |
| `FDT_LLM_API_BASE` | LLM 全局 API Base URL | `https://api.deepseek.com/v1` |
| `FDT_LLM_MODEL` | LLM 全局模型名称 | `deepseek-chat` |
| `FDT_LLM_<NAME>_API_KEY` | 逐 Agent API Key（覆盖全局） | - |
| `FDT_LLM_<NAME>_API_BASE` | 逐 Agent API Base URL（覆盖全局） | - |
| `FDT_LLM_<NAME>_MODEL` | 逐 Agent 模型名（覆盖全局） | - |
| `FDT_PG_DSN` | PostgreSQL 连接字符串 | - |
| `FDT_CHECKPOINTER` | Checkpointer 类型（pg/sqlite） | `sqlite` |
| `FDT_DIRECT_DEBATE` | 指定品种辩论模式开关 | `false` |
| `FDT_DEBATE_SYMBOLS` | 指定辩论品种列表（逗号分隔） | - |
| `FDT_RUN_EVOLUTION` | 辩论后自动触发进化 | `false` |
| `FDT_DATA_SOURCE` | 数据源类型（fdc/datacore） | `fdc` |
| `FDT_REPORT_WORKSPACE` | 报告输出根目录（优先） | - |
| `FDT_DAILY_WORKSPACE` | 每日工作空间（降级） | - |
| `FDT_GENERATE_INTERMEDIATE_REPORTS` | 生成中间报告 | `false` |
| `FDT_RISK_THRESHOLD` | CTP 信号风控阈值 | `yellow` |
| `FDT_CACHE_DIR` | 本地缓存目录 | `memory/fdt_cache` |
| `FDT_FDC_INJECTION_ENABLED` | 启用 FDC 数据注入 | `true` |
| `FDT_FDC_KLINE_DAYS` | K 线数据天数 | `120` |
| `JIN10_MCP_URL` | 金十 MCP 服务地址 | `https://mcp.jin10.com/mcp` |
| `JIN10_MCP_TOKEN` | 金十 MCP 认证 Token | - |

---

## 测试运行

```bash
# 运行所有测试
python run_all_tests.py

# 运行特定模块测试
pytest tests/fdt_langgraph/ -v

# 运行 RHI 自优化测试
pytest tests/rhi/ -v

# 运行基准对比测试
python scripts/run_benchmark.py --compare

# 运行文档一致性检查
python scripts/verify_doc_consistency.py

# 查看测试统计
# 合计: 17 个测试目录 / 1400+ 用例
```

---

## 技术文档

### 三大入口文档

| 文档 | 定位 | 生命周期 |
|:-----|:-----|:---------|
| [CLAUDE.md](CLAUDE.md) | 编码行为准则 | 项目标准文件 |
| [CODE_WIKI.md](CODE_WIKI.md) | 技术百科全书 | 随项目全生命周期更新 |
| [README.md](README.md) | 项目说明 | 随项目全生命周期更新 |

### Harness 工程规范

- [架构总览](docs/harness/01-architecture.md) — Harness 分层架构、组件关系图、数据流
- [生命周期](docs/harness/02-lifecycle.md) — 阶段定义和状态机
- [配置说明](docs/harness/03-configuration.md) — 配置项和优先级
- [Harness 文档索引](docs/harness/README.md) — 全 10 篇工程规范清单

---

## 版本历史

| 版本 | 核心变更 |
|:-----|:---------|
| **v9.23.0** | 六维控制空间高ROI提升：D3 Schema约束+enforce_structured_output全量接入、G01模型差异化路由、C01 Token预算控制、C03扫描信号表去重；langgraph默认模式 |
| **v9.22.0** | RHI 完整落地：evolution_graph 集成 node_rhi 节点 + rhi_global_cli.py + 22 个 RHI 测试 |
| **v9.21.0** | MemoHarness+RHI 整合：HarnessSpec 契约 + Pairwise Evaluator + Harness Optimizer + RHI 子图 |
| **v9.20.2** | 文档一致性三层保障体系（结构化元数据 + 自动校验 + 数据驱动） |
| **v9.18.0** | Master Orchestrator Graph：全量自动化迁移至 LangGraph，零第三方调度依赖 |
| **v9.17.0** | 自进化闭环 Evolution Graph：APM-CS 五轴驱动的外循环 LangGraph 子图 |
| **v9.14.0** | Phase 3 Data Governance：辩论输出质检 + 不合格退回重修（最多 2 次） |
| **v9.13.0** | 逐品种独立辩论循环 + 品藻角色拆分 |
| **v9.11.0** | 新闻情绪分析因子（读心 Agent）落地，P3 三源→四源并行 |
| **v9.10.0** | 金十数据 MCP 接入（mcp_client.py + jin10_mcp.py） |
| **v9.6.0** | Harness 工程全面升级：机读规则 + pre-commit + 10 条反模式检测 |
| **v9.5.0** | Loop Engineering 体系化：Loop Contract + 三层循环架构 |
| **v9.3.0** | 主力合约统一解析 + DataCore 集成 + 字段标准化 |
| **v9.0.0** | 六阶段攻防辩论：多头立论→空头结辩，来源可追溯 |
