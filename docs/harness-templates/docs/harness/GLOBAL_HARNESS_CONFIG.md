# 本机全局 Harness 配置

> **版本**: v9.22.0
> **日期**: 2026-07-23
>
> 本文件定义本机（`D:\HarnessStarterKit\`）全局 Harness 的完整配置体系。
> 全局 Harness 是跨项目的工程规范统一入口，整合 **RHI (Recursive Harness Self-Improvement)** +
> **MemoHarness** 两套学术方案，以 A+B 统一架构驱动配置自进化。
>
> - RHI: [arXiv:2607.15524](https://arxiv.org/abs/2607.15524)
> - MemoHarness: [arXiv:2607.14159](https://arxiv.org/abs/2607.14159)

---

## 目录

1. [概述](#1-概述)
2. [目录结构与职责](#2-目录结构与职责)
3. [配置架构](#3-配置架构)
4. [A+B 统一架构](#4-ab-统一架构)
5. [自动部署机制](#5-自动部署机制)
6. [多项目管理](#6-多项目管理)
7. [版本与更新策略](#7-版本与更新策略)
8. [使用指南](#8-使用指南)
9. [参考](#9-参考)

---

## 1. 概述

### 1.1 什么是本机全局 Harness？

本机全局 Harness 是存储在 `D:\HarnessStarterKit\` 的工程规范模板系统，作为 **本机所有项目的统一配置入口**。它定义了四层配置：

| 层 | 内容 | 存储位置 |
|:---|:-----|:---------|
| **L0 — 编码行为准则** | 先思考/简单至上/外科手术/目标驱动 | `CLAUDE.md` |
| **L1 — 工程规范** | 文档先行/契约优先/测试随重构/版本号纪律 | `CLAUDE.md` (Harness 工程规范章节) |
| **L2 — 机读规则** | 13 条 commit 前检查规则 + 10 条反模式 | `docs/harness/harness-rules.yaml` |
| **L3 — 结构化数据** | 版本号、配置变更记录等易变数据 | `docs/harness/_data/*.yaml` |

### 1.2 为什么需要全局 Harness？

| 问题 | 无全局 Harness | 有全局 Harness |
|:-----|:--------------|:--------------|
| 新项目规范初始化 | 每次手动重写 CLAUDE.md | 一键部署，自动复制模板 |
| 规范一致性 | 各项目各自演进，逐渐偏离 | 全局模板统一，项目可扩展不可覆盖 |
| 规范进化 | 各项目自生自灭 | RHI 自进化驱动全局模板持续改进 |
| 项目管理 | 逐个检查项目规范 | 从 Starter Kit 统一管理 |

---

## 2. 目录结构与职责

### 2.1 完整文件布局

```
D:\HarnessStarterKit\                     # 本机全局 Harness 根目录
│
├── CLAUDE.md                             # [核心] 全局编码行为准则 + Harness 工程规范
│
├── README.md                             # [入口] Starter Kit 使用说明
│
├── docs\
│   └── harness\
│       ├── README.md                     # [索引] Harness 文档索引
│       ├── GLOBAL_HARNESS_CONFIG.md      # [本文件] 全局 Harness 配置详解
│       ├── RHI_GLOBAL_HARNESS.md         # [参考] RHI 自进化框架详解
│       ├── harness-rules.yaml            # [机读] 13 条检查规则 + 10 条反模式
│       └── _data\
│           └── version.yaml              # [数据] 版本号真相源
│
└── scripts\
    ├── deploy_harness.py                 # [部署] 一键部署到项目
    ├── pre_commit_harness_check.py       # [检查] 12 项 commit 前检查
    ├── verify_doc_consistency.py         # [校验] 文档一致性校验
    └── rhi_global_setup.py              # [进化] RHI 自优化脚本
```

### 2.2 文件职责矩阵

| 文件 | 职责 | 变更频率 | 关联文件 |
|:-----|:-----|:--------:|:---------|
| `CLAUDE.md` | 编码行为准则 + Harness 规范 | 中 | 被所有项目引用 |
| `harness-rules.yaml` | 机读检查规则定义 | 低 | `pre_commit_harness_check.py` 加载 |
| `version.yaml` | 版本号真相源 | 中 | 各文档通过引用使用 |
| `pre_commit_harness_check.py` | 从 YAML 加载规则并执行检查 | 低 | `harness-rules.yaml` |
| `verify_doc_consistency.py` | 校验文档一致性元数据中的断言 | 低 | `docs/harness/*.md` (Layer 1) |
| `deploy_harness.py` | 将模板文件复制到目标项目 | 低 | 所有模板文件 |
| `rhi_global_setup.py` | RHI 自进化引擎 | 中 | `.rhi/history.json` |

---

## 3. 配置架构

### 3.1 三层配置模型

```
┌──────────────────────────────────────────────────────────────────┐
│                  三层配置模型                                      │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Layer 1: 文档配置（人类可读）                                  │  │
│  │  CLAUDE.md — 行为准则 + 工程规范                               │  │
│  │  docs/harness/*.md — 各专题文档                                 │  │
│  │  └── 每篇文档末尾包含 ## 一致性元数据 表格                       │  │
│  └──────────────────┬──────────────────────────────────────────┘  │
│                     │ 引用                                         │
│                     ▼                                              │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Layer 2: 机读配置（机器可解析）                                │  │
│  │  harness-rules.yaml — 检查规则 + 反模式                         │  │
│  │  └── pre_commit_harness_check.py 加载执行                       │  │
│  └──────────────────┬──────────────────────────────────────────┘  │
│                     │ 引用                                         │
│                     ▼                                              │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Layer 3: 结构化数据（易变数据隔离）                            │  │
│  │  _data/version.yaml — 版本号                                   │  │
│  │  _data/*.yaml — 路由表/Agent 入口等                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Layer 1: 文档配置 — CLAUDE.md

全局 CLAUDE.md 包含两个主要部分：

**第一部分：通用编码行为准则（4 条）**
- 先思考，再编码
- 简单至上
- 外科手术式修改
- 目标驱动执行

**第二部分：Harness 工程规范**
- 7 项核心原则（文档先行/契约优先/测试随重构/trace_id/角色边界/差距管理/版本号纪律）
- 13 项 commit 前检查清单（含 C15 文档一致性校验）
- 文档一致性三层保障体系
- 11 条反模式自查
- RHI 自进化入口说明

### 3.3 Layer 2: 机读配置 — harness-rules.yaml

```yaml
version: "1.0"
description: "Harness 工程规范检查规则"

checks:
  - id: C01    # 架构变更 → 01-architecture.md
  - id: C02    # 生命周期 → 02-lifecycle.md
  - id: C03    # 配置项 → 03-configuration.md
  - id: C04    # 降级/熔断 → 04-resilience.md
  - id: C05    # 可观测性 → 05-observability.md
  - id: C06    # 测试 → 06-testing.md
  - id: C07    # 版本号 bump → pyproject.toml
  - id: C08    # 差距登记 → 08-gap-analysis.md
  - id: C09    # 晋级计划 → 09-advancement-plan.md
  - id: C10    # 流程文档 → flowcharts
  - id: C11    # 角色职责 → agents/*.md
  - id: C12    # 入口文档 → CLAUDE.md/CODE_WIKI.md/README.md
  - id: C15    # 文档一致性校验

anti_patterns:
  - id: AP01   # 巨型 Prompt (P1)
  - id: AP02   # 跳过审核直接编码 (P0)
  - id: AP03   # Rules 不维护 (P1)
  - id: AP04   # MCP 过度接入 (P2)
  - id: AP05   # Skill 不原子化 (P1)
  - id: AP06   # 盲目信任 AI 输出 (P0)
  - id: AP07   # 循环无停止条件 (P0)
  - id: AP08   # 多循环共写 STATE (P1)
  - id: AP09   # Chat 历史当文档 (P2)
  - id: AP10   # 一个 PR 改所有 (P1)
```

检查类型分为：
- `file_modified` — 检测到代码变更时检查
- `version_check` — 版本号 bump 检查
- `gap_check` — 差距登记检查
- `process_check` — 流程性检查

严重度分级：
- **P0** — 强制：必须通过才可 commit
- **P1** — 建议：需要更新，但不阻断 commit
- **P2** — 一般：推荐性改进

### 3.4 Layer 3: 结构化数据 — _data/*.yaml

`version.yaml` 存储易变的版本号配置，各文档通过引用保持同步：

```yaml
version: "0.0.0"          # 项目版本号（需与 pyproject.toml 一致）
version_source: "pyproject.toml"  # 真相源声明
```

当代码变更导致版本号变化时，仅需更新此文件，所有引用此文件的文档自动保持一致。

---

## 4. A+B 统一架构

### 4.1 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                   本机全局 Harness 配置 — A+B 统一架构                  │
│                                                                     │
│  ┌────────────────────────────────────┐                             │
│  │  A: RHI 搜索算法                     │                             │
│  │  ─────────────────────               │                             │
│  │  每次 step 执行:                      │                             │
│  │  1. 读取当前 CLAUDE.md                │                             │
│  │  2. 四维评分 → score_current         │                             │
│  │  3. pairwise 比较 vs prev score      │                             │
│  │  4. 计算改进率 sⁱ                     │                             │
│  │  5. sⁱ < 0.3 → 收敛，停止            │                             │
│  │  6. 记录到 .rhi/history.json         │                             │
│  └──────────┬─────────────────────────┘                             │
│             │ 提供评分维度                                              │
│             ▼                                                        │
│  ┌────────────────────────────────────┐                             │
│  │  B: MemoHarness 评分框架            │                             │
│  │  ─────────────────────               │                             │
│  │  六维控制空间 (D1-D6) → 四维映射      │                             │
│  │                                     │                             │
│  │  D1 Context      → memory_coverage  │                             │
│  │  D2 Tool         → (项目扩展)        │                             │
│  │  D3 Generation   → (项目扩展)        │                             │
│  │  D4 Orchestration→ consistency      │                             │
│  │  D5 Memory       → memory_coverage  │                             │
│  │  D6 Output       → clarity + rules  │                             │
│  └──────────┬─────────────────────────┘                             │
│             │ 存储历史                                                   │
│             ▼                                                        │
│  ┌────────────────────────────────────┐                             │
│  │  .rhi/history.json                  │                             │
│  │  ├─ versions[] — 各版本评分快照        │                             │
│  │  ├─ preferences[] — pairwise 偏好     │                             │
│  │  ├─ improvement_rate — 改进率         │                             │
│  │  └─ converged — 收敛标记              │                             │
│  └────────────────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 RHI 算法流程（A 方案）

RHI 采用 **轨迹局部 pairwise 比较**，每次 step 只比较当前版本与上一版本，时间复杂度 O(1)。

```
Algorithm: Recursive Harness Self-Improvement (全局 Harness 配置版)

输入: CLAUDE.md 路径 P, 最大轮次 N=5, 停止阈值 ε=0.3
初始化: .rhi/history.json（不存在则创建）
首次执行: 四维评分 → 记录 version 0

循环 i = 1..N:
  1. 读取 CLAUDE.md 当前内容
  2. 四维评分 → score_current
  3. pairwise 比较:
     delta = score_current - score_previous
     preference = "improve" (delta > +0.02)
                 | "regress" (delta < -0.02)
                 | "tie" (otherwise)
  4. 改进率 sⁱ = improve 次数 / 总比较次数
  5. 若 sⁱ < 0.3 且比较次数 ≥ 2 → 收敛，停止
  6. 记录版本快照
  7. (用户/LLM 修改 CLAUDE.md) → 下一轮

返回: 最优版本号及评分
```

### 4.3 MemoHarness 评分维度映射（B 方案）

| MemoHarness 维度 | 全局评分维度 | 权重 | 评分逻辑 |
|:-----------------|:------------|:----:|:---------|
| D1 Context | `memory_coverage` | 0.30 | CLAUDE.md 是否引用 memory/knowledge |
| D2 Tool | — | — | 项目自定义扩展 |
| D3 Generation | — | — | 项目自定义扩展 |
| D4 Orchestration | `consistency` | 0.20 | 是否引用 Harness 文档/README |
| D5 Memory | `memory_coverage` (与 D1 共享) | (已计入) | — |
| D6 Output | `clarity` + `rule_completeness` | 0.20+0.30 | 行数适度 + 检查清单/反模式齐全 |

**项目扩展**：可在 `rhi_global_setup.py` 的 `_score_claude()` 中增加 D2 Tool 和 D3 Generation 的评分逻辑，覆盖完整的 MemoHarness 六维空间。

### 4.4 停止条件

| 条件 | 阈值 | 说明 |
|:-----|:----:|:------|
| 改进率收敛 | ε=0.3 | 连续改进次数不足 30%，配置趋于稳定 |
| 最大轮次 | N=5 | 防止无限循环 |
| 手动收敛 | `converged: true` | 人工确认后标记，不再触发自进化 |

### 4.5 本机全局 vs 项目级 RHI 对比

| 维度 | 本机全局 (`D:\HarnessStarterKit\`) | 项目级 (`<project>/.rhi/`) |
|:-----|:----------------------------------|:---------------------------|
| 优化对象 | 全局 CLAUDE.md（模板） | 项目 CLAUDE.md（派生） |
| 影响范围 | 所有新部署的项目 | 当前项目 |
| 触发主体 | 手动维护 Starter Kit 时 | 项目自动部署 + 项目开发者 |
| 版本跟踪 | `version.yaml` + `RHI_GLOBAL_HARNESS.md` | `.rhi/history.json` |
| 部署关系 | **上游**：全局优化 → 部署到项目 | **下游**：接收全局模板 + 项目专属调整 |

---

## 5. 自动部署机制

### 5.1 部署流程

```
全局 Harness (D:\HarnessStarterKit\)             目标项目 (<project>/)
                               │
                               │ 自动/手动部署
                               ▼
┌─────────────────┐                       ┌──────────────────────┐
│ CLAUDE.md       │──────────────────────▶│ CLAUDE.md            │
│                 │   (复制 + 项目专属扩展) │ (基础模板 + 项目规则)  │
│ docs/harness/   │──────────────────────▶│ docs/harness/        │
│  ├─ README.md   │                       │  ├─ README.md        │
│  ├─ harness-    │                       │  ├─ harness-rules.yaml│
│  │  rules.yaml  │                       │  └─ (01~09各文档)*   │
│  └─ _data/      │                       │                      │
│                 │                       │ scripts/             │
│ scripts/        │──────────────────────▶│  ├─ pre_commit_      │
│  ├─ pre_commit_ │                       │  │  harness_check.py  │
│  │  harness_    │                       │  ├─ verify_doc_      │
│  │  check.py    │                       │  │  consistency.py   │
│  ├─ verify_doc_ │                       │  └─ rhi_global_      │
│  │  consistency │                       │     setup.py         │
│  │  .py         │                       │                      │
│  └─ rhi_global_ │                       └──────────────────────┘
│     setup.py    │
└─────────────────┘
  * 项目专属文档（01-09）需项目自行创建
```

### 5.2 自动部署（TRAE 首次会话触发）

每次在 TRAE IDE 中开始新项目会话时，系统自动执行：

1. 检测项目根目录是否存在 `CLAUDE.md`（内容含 Harness 规范）或 `docs/harness/` 目录
2. 如果不存在：
   a. 从 `D:\HarnessStarterKit\CLAUDE.md` 复制到项目根目录
   b. 创建 `docs/harness/` 目录，复制 `harness-rules.yaml` 和 `README.md`
   c. 如果项目有 `scripts/` 目录，复制 `pre_commit_harness_check.py`
   d. 告知用户："Harness 工程规范已自动部署到本项目的 CLAUDE.md / docs/harness/"
3. 如果已存在，记录当前项目 Harness 规范的版本状态

### 5.3 手动部署

```bash
# 从项目根目录执行
python D:\HarnessStarterKit\scripts\deploy_harness.py
```

`deploy_harness.py` 执行：
1. 复制 `CLAUDE.md` 到目标项目（如果不存在）
2. 复制 `docs/harness/README.md` 和 `docs/harness/harness-rules.yaml`
3. 复制 `scripts/pre_commit_harness_check.py` 和 `scripts/verify_doc_consistency.py`
4. 可选：复制 `scripts/rhi_global_setup.py` 启用 RHI 自进化

### 5.4 项目专属扩展规则

项目部署后，开发者可以在模板基础上增补项目专属内容，**不可删除或修改模板基础规则**：

| 操作 | 允许 | 示例 |
|:-----|:----:|:------|
| 追加 Agent 列表 | ✅ | 在 CLAUDE.md 末尾添加项目 Agent 清单 |
| 追加项目架构说明 | ✅ | 添加项目架构图、模块说明 |
| 追加项目专属规则 | ✅ | FDT 的 NO_FUSION 零融合原则 |
| 创建 01-09 文档 | ✅ | 使用 YAML 中的模板创建 |
| 修改核心原则 | ❌ | 不能删除"文档先行"原则 |
| 跳过检查清单 | ❌ | 不能删除 C01-C15 检查项 |

---

## 6. 多项目管理

### 6.1 本机项目清单

| 项目 | 根目录 | Harness 状态 |
|:-----|:-------|:------------|
| FDT | `D:\Programs\FDT\` | 已部署 v9.20.2（完整 13 文档 + RHI） |
| 其他项目 | — | 首次 TRAE 会话自动部署 |

### 6.2 一致性保障

```
┌─────────────────────────────────────────┐
│  D:\HarnessStarterKit\                    │
│  (全局配置真相源)                           │
│  ├─ CLAUDE.md ──────────┐                 │
│  ├─ harness-rules.yaml ─┤                 │
│  └─ rhi_global_setup.py ┤                 │
└─────────────────────────┼────────────────┘
                          │ 部署
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Project A    │ │ Project B    │ │ FDT          │
│ CLAUDE.md    │ │ CLAUDE.md    │ │ CLAUDE.md    │
│ (模板+规则A) │ │ (模板+规则B) │ │ (模板+13 doc)│
│ harness-     │ │ harness-     │ │ harness-     │
│ rules.yaml   │ │ rules.yaml   │ │ rules.yaml   │
└──────────────┘ └──────────────┘ └──────────────┘
```

### 6.3 一致性检查机制

| 机制 | 触发 | 检查内容 | 工具 |
|:-----|:-----|:---------|:-----|
| 自动部署检查 | 新项目首次会话 | 模板是否存在 | TRAE 自动规则 |
| pre-commit 检查 | 每次 commit 前 | 13 项检查清单 | `pre_commit_harness_check.py` |
| 文档一致性校验 | `docs/harness/` 变更后 | 元数据断言 | `verify_doc_consistency.py` |
| RHI 状态检查 | 手动运行 | CLAUDE.md 质量评分 | `rhi_global_setup.py status` |

### 6.4 全局配置更新后的同步策略

当本机 `D:\HarnessStarterKit\` 的配置更新时：

1. **模板更新**：直接修改 `D:\HarnessStarterKit\` 下的文件
2. **项目同步**：
   - 新项目：自动获取最新模板
   - 已有项目：手动运行 `deploy_harness.py` 更新，或逐项目选择性合并
3. **版本跟踪**：`docs/harness/_data/version.yaml` 记录配置版本，项目可判断是否需要同步
4. **RHI 进化**：全局模板的 RHI 自进化会持续优化 CLAUDE.md 内容，项目通过重新部署获取改进

---

## 7. 版本与更新策略

### 7.1 版本号体系

| 编号 | 版本 | 说明 |
|:-----|:-----|:------|
| 全局 Harness | v9.22.0 | `version.yaml` 记录（当前项目 version） |
| 机读规则 | v1.0 | `harness-rules.yaml` 的 `version` 字段 |
| RHI 框架 | v9.22.0 | `RHI_GLOBAL_HARNESS.md` 版本 |

### 7.2 更新触发条件

| 条件 | 示例 | 更新内容 |
|:-----|:-----|:---------|
| 新检查规则 | 新增 C15 文档一致性校验 | `harness-rules.yaml` + `CLAUDE.md` |
| 新反模式 | 新增 AP11 | `harness-rules.yaml` + `CLAUDE.md` |
| RHI 自进化 | 评分提升 > 0.02 | `CLAUDE.md` 内容优化 |
| 流程改进 | 部署流程优化 | `deploy_harness.py` |
| 文档修正 | 描述不准确 | 对应 `.md` 文件 |

### 7.3 更新流程

```
1. 修改模板文件 (D:\HarnessStarterKit\)
   │
2. 运行 pre-commit 检查
   │  python scripts/pre_commit_harness_check.py
   │
3. 运行文档一致性校验
   │  python scripts/verify_doc_consistency.py
   │
4. 运行 RHI step（如果涉及 CLAUDE.md 变更）
   │  python scripts/rhi_global_setup.py step
   │
5. bump 版本号
   │  更新 docs/harness/_data/version.yaml
   │
6. 同步到各项目（选择性执行）
   │  python D:\HarnessStarterKit\scripts\deploy_harness.py -p <project_path>
   │
7. commit + push（镜像目录同步）
   ```

---

## 8. 使用指南

### 8.1 日常使用

```bash
# 查看当前 CLAUDE.md 的 RHI 评分
python scripts/rhi_global_setup.py status

# 修改 CLAUDE.md 后记录评分变化
python scripts/rhi_global_setup.py step

# 初始化 RHI（首次使用）
python scripts/rhi_global_setup.py init

# 部署到新项目
python D:\HarnessStarterKit\scripts\deploy_harness.py -p D:\Projects\NewProject
```

### 8.2 配置维护

| 场景 | 操作 | 频率 |
|:-----|:-----|:----:|
| 新增检查规则 | 更新 `harness-rules.yaml` | 需要时 |
| 修改行为准则 | 更新 `CLAUDE.md` | 季度/半年 |
| RHI 自进化 | 运行 `rhi_global_setup.py step` | 每次 CLAUDE.md 修改后 |
| 部署到新项目 | 自动或手动运行 `deploy_harness.py` | 每次新项目 |
| 文档一致性校验 | 运行 `verify_doc_consistency.py` | `docs/harness/` 变更后 |

### 8.3 最佳实践

1. **全局模板保持精简** — CLAUDE.md 控制在 150-200 行，项目专属内容在项目级扩展
2. **机读规则先于文档** — 新增规范先写入 `harness-rules.yaml`，再同步到文档
3. **数据驱动文档** — 易变配置存入 `_data/*.yaml`，文档通过引用保持同步
4. **RHI 定期执行** — 每次修改 CLAUDE.md 后运行一次 `step`，让评分自然收敛
5. **镜像同步机制** — FDT 项目的 `docs/harness-templates/` 是全局模板的镜像副本，部署时保持一致

### 8.4 故障排除

| 问题 | 原因 | 解决 |
|:-----|:-----|:-----|
| pre-commit 检查失败 | `docs/harness/` 文档未同步 | 运行 `verify_doc_consistency.py` 查看具体失败断言 |
| RHI 评分低 | CLAUDE.md 缺少关键引用 | 添加 memory/knowledge 引用 + 检查清单 + 反模式 |
| 部署失败 | 目标项目路径错误 | 使用绝对路径 + 确认目标目录存在 |
| RHI 不收敛 | 每次 step 评分大幅波动 | 检查 CLAUDE.md 是否频繁大幅修改，尝试小步迭代 |

---

## 9. 参考

### 9.1 论文

| 论文 | 链接 | 在本框架中的角色 |
|:-----|:-----|:----------------|
| Recursive Harness Self-Improvement | [arXiv:2607.15524](https://arxiv.org/abs/2607.15524) | A 方案：O(1) 轨迹局部搜索 |
| MemoHarness: Agent Harnesses That Learn from Experience | [arXiv:2607.14159](https://arxiv.org/abs/2607.14159) | B 方案：六维控制空间 + 经验存储 |

### 9.2 相关文件

| 文件 | 位置 | 说明 |
|:-----|:-----|:------|
| `CLAUDE.md` | `D:\HarnessStarterKit\` | 全局行为准则 + Harness 规范 |
| `README.md` | `D:\HarnessStarterKit\` | Starter Kit 使用说明 |
| `harness-rules.yaml` | `D:\HarnessStarterKit\docs\harness\` | 13 条机读检查规则 + 10 条反模式 |
| `RHI_GLOBAL_HARNESS.md` | `D:\HarnessStarterKit\docs\harness\` | RHI 自进化框架详解 |
| `deploy_harness.py` | `D:\HarnessStarterKit\scripts\` | 一键部署脚本 |
| `pre_commit_harness_check.py` | `D:\HarnessStarterKit\scripts\` | commit 前自动检查 |
| `verify_doc_consistency.py` | `D:\HarnessStarterKit\scripts\` | 文档一致性校验 |
| `rhi_global_setup.py` | `D:\HarnessStarterKit\scripts\` | RHI 自进化引擎 |

### 9.3 镜像目录

| 位置 | 说明 |
|:-----|:------|
| `D:\HarnessStarterKit\` | **真相源**：全局模板的主存储位置 |
| `D:\Programs\FDT\docs\harness-templates\` | **FDT 镜像**：FDT 项目内的全局模板副本 |

---

## 一致性元数据

| 代码文件/函数 | 文档章节 | 关键断言/可验证事实 | 检验方式 |
|:--------------|:---------|:-------------------|:---------|
| `D:\HarnessStarterKit\CLAUDE.md` | §3.2 | 包含"先思考，再编码"等 4 条行为准则 | `grep -c "先思考，再编码"` |
| `D:\HarnessStarterKit\docs\harness\harness-rules.yaml` | §3.3 | 包含 C01-C15 检查规则 | `grep -c "id: C" harness-rules.yaml` |
| `D:\HarnessStarterKit\docs\harness\_data\version.yaml` | §7.1 | version 字段格式为语义化版本 | `grep -E 'version: "[0-9]+\.[0-9]+\.[0-9]+"'` |
| `D:\HarnessStarterKit\scripts\rhi_global_setup.py` | §4.2 | 包含 `_score_claude()` 评分函数 | `grep -q "def _score_claude"` |
| `D:\HarnessStarterKit\scripts\deploy_harness.py` | §5.3 | 存在且可执行 | `test -f deploy_harness.py` |
| `D:\Programs\FDT\docs\harness-templates\` | §9.3 | 镜像目录存在且与 `D:\HarnessStarterKit\` 一致 | `diff -rq dir1 dir2` |

> **文档维护**：本文件由 `D:\HarnessStarterKit\` 提供，随全局 Harness 框架版本同步更新。
> 各项目可将其复制到自己的 `docs/harness/` 目录并补充项目专属的配置说明。
