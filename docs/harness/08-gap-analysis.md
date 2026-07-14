# 08 — 差距分析与改进路线

> **状态声明（2026-07-14 整顿）**：本文件在 2026-07-10 曾断言「15 项差距全部修复、成熟度 4.7/5.0」。
> 经 2026-07-14 对代码与测试的真实核查，该结论存在两处失真：① **G14（Agent 产出版本迁移）从未真正落地**（`contracts/migrations.py` 至今不存在）；② 2026-07-14 的 v6.3.0 数技源信号+分析师能力重构**未同步更新 Harness 文档与 pipeline 测试**，导致「43 用例全绿」在重构后已不成立（实测 pipeline 5/10 失败）。
> 本版基于证据重新评估，并以 G16/G17 两项新差距登记近期工作引入的回归。

## 1. 评估方法论

按照 Agent/LLM Harness 工程范式的 8 个维度，对 FDT 现状进行系统性评估：

| 维度 | 评估标准 |
|:-----|:---------|
| 入口与引导 | 启动入口清晰性、模式划分、初始化流程 |
| 配置管理 | 配置集中化、校验机制、优先级覆盖链 |
| 生命周期管理 | 阶段流转、Agent 生成/销毁、状态机 |
| 状态管理 | 持久化机制、并发安全、恢复能力 |
| 错误恢复 | 检测/降级/恢复链路完整性 |
| 可观测性 | 指标/日志/追踪三维度覆盖度 |
| 测试策略 | 测试金字塔完整性、覆盖率、门禁 |
| 部署与运维 | 部署模式、Runbook、版本管理 |

## 2. 成熟度评分（2026-07-14 实测复核）

> 列说明：**修复前** = 初始评估；**07-10 评估** = 当时声称的修复后；**当前(07-14)** = 本次代码/测试实测复核。

| 维度 | 修复前 | 07-10 评估 | 当前(07-14 实测) | 关键依据 |
|:-----|:------:|:----------:|:----------------:|:---------|
| 入口与引导 | 4/5 | 5/5 | **5/5** | G4 bootstrap 动态版本（`get_fdt_version()` 读取 pyproject）✅ |
| 配置管理 | 3/5 | 5/5 | **5/5** | G1 `config/schema.py` 含 TeamConfig/Settings/AgentWaiterConfig Pydantic 校验 ✅ |
| 生命周期管理 | 5/5 | 5/5 | **5/5** | 6 阶段状态机 + 自进化闭环（代码层完整） |
| 状态管理 | 4/5 | 5/5 | **5/5** | G2 trace_id 贯穿全流水线 ✅ |
| 错误恢复 | 5/5 | 5/5 | **5/5** | L1-L5 + D06 + 看门狗（业界领先） |
| 可观测性 | 4/5 | 5/5 | **5/5** | G3 `pipeline/runner.py` 已用 `unified_logger`；G11 看板 + G12 健康端点 + G15 JSON 日志 ✅ |
| 测试策略 | 3/5 | 5/5 | **3/5** ⚠️ | **G16 回归**：v6.3.0 重构后 `tests/pipeline/test_runner.py` 仍引用已重命名的 `step_scan_dual`，实测 5/10 失败 |
| 部署运维 | 4/5 | 5/5 | **4/5** ⚠️ | **G14 未落地**：`contracts/migrations.py` 缺失；G9 drain + G10 兼容矩阵 + G12 健康端点 ✅ |

**综合评分：4.0（初始）→ 4.7（07-10 声称）→ 当前约 4.6/5.0（实测）**

> 说明：当前 4.6 仍高于初始 4.0，但**「全部完成 / 4.7」的断言不准确**——它既高估了 G14（从未落地），又未预见 G16 在 07-14 重构后引入的测试回归。剩余 3 项开放差距（G14/G16/G17）阻塞真正 5/5。

## 3. 已有能力清单 (Strengths)

### 3.1 错误恢复 — 业界领先

| 能力 | 实现文件 | 成熟度 |
|:-----|:---------|:-------|
| L1 产出校验 | `validate_agent_output.py` | ✅ 完整 |
| L2 熔断降级 | `debate_orchestrator.py` + D06 | ✅ 完整 |
| L3 信号门 | `daily_debate.py`（读 `full_scan_summary_{date}.json`） | ✅ 完整 |
| L4 路径自发现 | `phase3_generate_report.py` v3.2 | ✅ 完整 |
| L5 健康自检 | `selfcheck.py` | ✅ 完整 |
| S04 轮询协议 | `agent_waiter.py` | ✅ 完整 |
| 看门狗 | `daemon_watchdog.py` | ✅ 完整 |

### 3.2 可观测性 — APM-CS 五轴

| 轴 | 实现文件 | 成熟度 |
|:---|:---------|:-------|
| D1 一致性 | held-out judge + `compute_heldout_coherence()` | ✅ 完整 |
| D2 辨识力 | `validate_verdicts.py` (Spearman + 成本感知PnL) | ✅ 完整 |
| D3 镇定度 | `apm_scorecard.py` (stop~ADX回归) | ✅ 完整 |
| D4 纪律 | `enforce_discipline.py` (R13/R14/R-resonance) | ✅ 完整 |
| D5 可靠性 | `apm_scorecard.py` (fresh完成率) | ✅ 完整 |

### 3.3 自进化闭环

| 能力 | 实现文件 | 成熟度 |
|:-----|:---------|:-------|
| 裁决验证 | `validate_verdicts.py` | ✅ 完整 |
| 权重校准 | `calibrate_weights.py` | ✅ 完整 |
| Agent进化 | `evolve_agents.py` | ✅ 完整 |
| ML训练 | `ml/trainer.py` | ✅ 完整 |
| 品种×策略矩阵 | `update_matrix.py` | ✅ 完整 |
| 自改进脚手架 | `self_improve.py` | ✅ proposal模式 |

### 3.4 通信契约

| 能力 | 实现文件 | 成熟度 |
|:-----|:---------|:-------|
| JSON Schema (9个) | `docs/schemas/` | ✅ Draft 2020-12 |
| TypedDict 契约 | `contracts/debate_argument_schema.py` | ✅ 完整 |
| A2A 桥接 | `contracts/a2a_payload.py` | ✅ 完整（v6.2 新增） |
| 通信协议文档 | `docs/agent-protocol.md` v3.0 | ✅ 完整 |
| 版本兼容迁移 | `contracts/migrations.py` | ⚠️ **未实现**（见 G14） |

## 4. 差距清单 (Gaps)

### 4.1 P0 — 高优先级（影响正确性 / 回归）

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| **G16** | pipeline 测试随重构失效 | `tests/pipeline/test_runner.py` mock `step_scan_dual`，但 v6.3.0 已将 Step1 重构为数技源信号+观澜/探源按需 `step_scan()`，函数名不存在 → 实测 5/10 失败 | 「43 用例全绿」声明失真；重构回归无门禁拦截 | 将 `step_scan_dual` 改为 `step_scan` 并补充数技源+分析师文件存在性断言；纳入 CI 回归 | `tests/pipeline/test_runner.py` |
| **G17** | Harness 文档未随重构同步 | v6.3.0/6.3.1 重构后，所有 Harness 文档仍写 v5.7.0、数据流为单生产者、库存/脚本计数过期 | 文档与代码长期背离，误导运维与后续重构 | 建立「代码重构 → Harness 文档同步」纪律与检查清单（见 §5 Phase 5） | `docs/harness/*.md` |
| **G18** | 流程文档未对齐当前架构 | `execution_modes_flowchart.md` 写 v5.12.1、单生产者 scan_all、未体现三分析师供弹与闫判官判断调度；链证源角色边界（无调度权）未固化 | 流程文档与代码/角色长期背离，易被误解为「链证源是调度者」 | 刷新 `execution_modes_flowchart.md`(v4.1/6.3.1)+`business_flow.md`+`futures-chain-analyst.md`+`02-lifecycle.md` 对齐新流程；钉死「闫判官调度权 / 链证源无调度权」 | `docs/execution_modes_flowchart.md` `docs/business_flow.md` `agents/futures-chain-analyst.md` `docs/harness/02-lifecycle.md` |

### 4.2 P1 — 中优先级（影响可维护性）

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G14 | 缺 Agent 产出版本迁移 | `contracts/migrations.py` 被引用但文件不存在；仅 `debate_argument_schema.py`/`a2a_payload.py` | schema 版本升级时无自动迁移路径，向后兼容无保障 | 实现 `apply_migration(skill_type, data, target_version)` + 补齐 MIGRATION_REGISTRY | 新建 `contracts/migrations.py` |
| G5 | pipeline 集成测试 | 测试存在但 **已失效**（见 G16） | 同 G16 | 随 G16 一并修复 | `tests/pipeline/` |
| G6 | scheduler 集成测试 | `tests/scheduler/` 存在（10 用例） | 需随架构复核是否覆盖数技源信号+分析师能力调度 | 复核 `scheduler/tasks.py daily_debate()` Step1 数技源信号+分析师能力路径 | `tests/scheduler/` |
| G7 | 覆盖率扩展 | `pyproject.toml` 已覆盖 skills+pipeline+scheduler+scripts | — | 维持 | `pyproject.toml` |
| G8 | memory 集成测试 | `tests/memory/` 存在（9 用例） | — | 维持 | `tests/memory/` |
| G9 | graceful drain | `scheduler/engine.py` 已实现 drain | — | 维持 | `scheduler/engine.py` |
| G10 | API 兼容矩阵 | `docs/compatibility-matrix.md` 存在 | 需随版本追加 6.0–6.3.1 | 追加版本依赖记录 | `docs/compatibility-matrix.md` |

### 4.3 P2 — 低优先级（改善体验）

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G11 | 监控看板 | `scripts/dashboard.py` 存在 | — | 维持 | `scripts/dashboard.py` |
| G12 | 健康端点 | `scripts/health_server.py` 存在 | — | 维持 | `scripts/health_server.py` |
| G13 | 熔断阈值可配置 | `config/schema.py` 含 `AgentWaiterConfig`，从 `team_config.json` 读取 | — | 维持 | `config/schema.py` |
| G15 | 结构化日志 | `unified_logger.py` 支持 JSON 格式 | — | 维持 | `unified_logger.py` |

> **已关闭（本次复核确认）**：G1（config/schema.py 校验）、G2（trace_id）、G3（pipeline 已用 unified_logger）、G4（bootstrap 动态版本）。`03-configuration.md §6` 与 `05-observability.md §3.4` 中关于 G1/G3 的「缺失」注记已过时，已在本轮整顿中校正。

## 5. 改进路线图

### Phase 1–4（2026-07-10，基本完成，仅 G14 存疑）

G1-G13、G15 已落地；G14 经本次复核确认**未落地**（见 §4.2），不计入已完成项。

### Phase 5（2026-07-14 新增）：重构同步纪律 + 测试回归修复

```
G17 文档同步纪律 ──→ 建立「代码重构 → Harness 文档同步」检查清单
     │
     ▼
G16 pipeline 测试修复 ──→ step_scan_dual → step_scan + 数技源+分析师断言
     │
     ▼
G14 版本迁移落地 ──→ contracts/migrations.py (28 条路径)
     │
     ▼
G10 兼容矩阵追补 ──→ 6.0–6.3.1 版本依赖记录
```

**预期收益**：文档与代码一致性恢复；CI 门禁能拦截重构回归；schema 升级有向后兼容保障。

**G17 文档同步检查清单（每次重构后必查）**：

| 检查项 | 对应文档 |
|:-----|:-----|
| 架构/数据流变更是否反映 | `01-architecture.md §3` |
| 阶段状态机/文件名变更是否反映 | `02-lifecycle.md` / `04-resilience.md` |
| 启动入口/版本号是否反映 | `07-operations.md §5` |
| 配置/脚本/技能/测试计数是否刷新 | `README.md` 快速参考 / `06-testing.md` |
| 既有测试是否随函数重命名同步 | `tests/**` |
| 版本历史是否追加 | `07-operations.md §5.2` / `.version_history.json` |

## 6. Harness 工程规范对照表（2026-07-14 修正）

| Harness 维度 | FDT 现状 | 规范要求 | Gap |
|:-------------|:---------|:---------|:----|
| **入口点** | bootstrap.py (3模式) | 明确的入口 + 模式选择 + 初始化 | ✅ 达标 |
| **配置注入** | 多文件 + 环境变量 + `config/schema.py` 校验 | 集中化 + schema校验 + 优先级链 | ✅ 达标（G1 已落地） |
| **生命周期** | 6阶段 + 自进化闭环 | 明确的状态机 + 阶段门禁 | ✅ 达标（代码层） |
| **Agent 管理** | spawn + S04轮询 + D06降级 | 生成/监控/销毁/超时/恢复 | ✅ 达标 |
| **状态持久化** | 文件 + SQLite + 线程锁 | 原子写入 + 并发安全 + 恢复 | ✅ 达标 |
| **错误恢复** | L1-L5 + D06 + 看门狗 | 检测/重试/降级/熔断/恢复 | ✅ 业界领先 |
| **通信契约** | JSON Schema + TypedDict + A2A | 格式约束 + 版本兼容 + 校验 | ⚠️ **G14 版本迁移未实现** |
| **可观测性** | APM-CS + 日志 + 回放 + 看板 + 健康端点 | 指标/日志/追踪三维度 | ✅ 达标 |
| **测试** | 12 目录 / 24 文件 | 金字塔完整 + 覆盖率高 + 随重构维护 | ⚠️ **G16 pipeline 5/10 失败** |
| **部署** | 单机 + 分布式 | 多模式 + Runbook + 版本管理 | ✅ 达标（G14 除外） |
| **文档** | README + protocol + schemas + 10 Harness 文档 | 架构/API/运维文档与代码同步 | ⚠️ **G17 文档未随 v6.3.x 同步** |

## 7. 总结（2026-07-14 整顿）

**当前成熟度约 4.6/5.0，仍有 3 项开放差距（G14 / G16 / G17）。**

2026-07-10 的「15 项全部修复、4.7/5.0」结论经本次实测复核需修正：

| 项 | 真实状态 |
|:---|:-----|
| G1/G2/G3/G4 | ✅ 确已落地（此前文档残留的「缺失」注记已校正） |
| G5 pipeline 测试 | ⚠️ **已失效**（v6.3.0 重构后 `step_scan_dual` 失配，5/10 失败）→ 归入 G16 |
| G14 版本迁移 | ⚠️ **从未落地**（`contracts/migrations.py` 不存在），原「28 条路径」声明不成立 |
| 文档一致性 | ⚠️ **G17**：v6.3.0/6.3.1 重构未同步 Harness 文档（版本号/数据流/计数全部过期） |

**待办（需代码层改动，按归位铁律需授权后执行）**：
1. **G16**：修复 `tests/pipeline/test_runner.py` 的 `step_scan_dual → step_scan` 并补充数技源+分析师断言，恢复「全绿」门禁。
2. **G14**：实现 `contracts/migrations.py` 版本迁移（28 条路径）。
3. **G17**：将本文件登记的检查清单固化为重构 SOP；后续每次重构强制同步 `docs/harness/`。

**已随本文档完成的文档整顿**：版本号统一为 v6.3.1、`01 §3.1` 与 `04 §2.3` 数据流改为数技源信号+分析师能力、`03 §6` 校正 G1、`05 §3.4` 校正 G3、`06` 库存/测试计数刷新、`07 §5` 版本历史追加 6.0–6.3.1、`README.md` 快速参考计数刷新；**G18 流程文档刷新**：`execution_modes_flowchart.md`(v4.1/6.3.1，数技源信号+分析师能力 + 闫判官判断调度 + 链证源无调度权)、`business_flow.md`(P1.5/P2 边界)、`futures-chain-analyst.md`(无调度权)、`02-lifecycle.md`(P1.5/P2 调度权边界) 全部对齐新流程。
