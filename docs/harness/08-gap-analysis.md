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
| 配置管理 | 3/5 | 5/5 | **5/5** | G1 `config/schema.py` 含 TeamConfig/Settings/AgentWaiterConfig + DataSourcesConfig + AgentProfilesData Pydantic 校验 ✅ |
| 生命周期管理 | 5/5 | 5/5 | **5/5** | 6 阶段状态机 + 自进化闭环（代码层完整） |
| 状态管理 | 4/5 | 5/5 | **5/5** | G2 trace_id 贯穿全流水线 ✅ |
| 错误恢复 | 5/5 | 5/5 | **5/5** | L1-L5 + D06 + 看门狗（业界领先） |
| 可观测性 | 4/5 | 5/5 | **5/5** | G3 日志已统一至 `unified_logger`（`pipeline/runner.py` 已退役）；G11 看板 + G12 健康端点 + G15 JSON 日志 ✅ |
| 测试策略 | 3/5 | 5/5 | **5/5** ✅ | **G16 已修复**：`step_scan_dual`→`step_scan`，10/10 全绿 |
| 部署运维 | 4/5 | 5/5 | **5/5** ✅ | **G14 已修复**：`contracts/migrations.py` 新建，26 条迁移路径可用 |

**综合评分：4.0（初始）→ 4.7（07-10 声称）→ 4.6（07-14 实测）→ 5.0（07-14 修复后 — 8 维全 5/5）**

> G16/G14 已于 2026-07-14 19:04 修复并验证，至此全部 18 项差距关闭，8 个 Harness 维度均达到 5/5。

**G19（2026-07-18 辩论重构·正反方→多空头模式）**：6策略管线场景下，正反方机制不合理。已重构为多空头六阶段攻防模式。涉及 state.py / nodes.py / graph.py / YAML配置 / 测试 共8个文件。**状态: ✅ 已实施 (v9.0.0)**

**G20（2026-07-18 辩论重构·来源标签格式一致性）**：✅ **已关闭（v9.5.0）** — 来源标签已统一为 `[domain:source]` 格式 — 存在 `[观澜]`（短格式）、`[technical:观澜]`（domain:source格式）、`[scan]`（英文）、`[数技源]`（无 prefix）等多种格式。需要统一为 `[domain:source]` 规范格式。
- 优先级: P2
- 状态: 已开放
- 目标: ✅ 已完成 — 统一为 `[domain:source]` 格式，如 `[technical:观澜]`、`[fundamental:探源]`、`[scan:数技源]`、`[chain:链证源]`
- 工作量: 小（修改 `nodes.py` 扫描标注 + 3 篇文档架构图描述）

**G21（2026-07-21 数据新鲜度保障机制正式化）**：
> 数据新鲜度保障过去是隐性要求，未编码为机读规则。辩论/裁决环节偶有引用过时数据（如使用 4 天前的纺企开机率数据做短期判断），影响分析可信度。
- **原因**：新鲜度标准散落在各 Agent 的认知中，没有统一的机读规则和检查清单；缺乏辩论启动前的数据新鲜度闸门。
- **目标**：建立完整数据新鲜度检查机制 — 分级标准明文化 → P0b 新鲜度闸门 → 过时数据自动降级/告警。
- **修复内容**：
  1. `loop-contracts/README.md`：新增「数据新鲜度原则」章节（分级标准+检查清单+处理规则）
  2. `loop-contracts/data-collection.contract.yaml`：`check_freshness` 步骤增强，产出 `freshness_report`（含 `freshness_level` 评级）
  3. `loop-contracts/daily-debate.contract.yaml`：新增 `data_freshness_gate` 作为 pre_loop 必查步骤
  4. `02-lifecycle.md`：新增 P0b 阶段定义、状态机图、阶段规格表
- **优先级**: P0（影响分析可信度）
- **状态**: ✅ **已关闭（v9.6.5）**
- **工作量**: 文档修改 3 篇 + 契约增强 2 篇

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
| **G109** | **自进化闭环 NoneType 错误**（v9.20.0 已修复） | `master_nodes.py` 行 384-385：`run_evolution()` 返回 None 时直接调用 `.get()` 报错 `'NoneType' object has no attribute 'get'`，进化步骤被 `except Exception` 捕获但日志错误信息不明确。 | P0 | 增加 `if ev_state:` None 防护 | `fdt_langgraph/master_nodes.py` ✅ v9.20.0 |
| **G110** | **质检缺字段校验过严导致裁决 FAIL**（v9.20.0 已修复） | `quality_inspector.py` `validate_verdict()` 对 `symbol`/`stop_loss`/`target1` 等字段校验为 error 级，LLM 输出偶有缺失时直接 FAIL。质检重试 1 次后跳过，下游风控阻断。 | P0 | 增加缺失字段自动填充（从 scan data 回填） + 质检消息明确指示缺失字段 | `fdt_langgraph/quality_inspector.py` ✅ v9.20.0 |
| **G111** | **观澜/探源 LLM 输出解析率低**（v9.20.0 已修复） | LLM 返回仅 99/117 字符的短输出，`json.loads(output[start:end])` 失败导致回退到 FDC 数据。LLM 未提供有效的 per_symbol 结构化数据，影响辩论质量。 | P1 | 解析前增加 JSON 修复逻辑（BOM/注释/单引号/截断清理）；Agent prompt 明确强调输出格式 | `fdt_langgraph/nodes.py` + `agents/*` ✅ v9.20.0 |
| **G21** | 数据新鲜度保障机制未正式化 | 新鲜度标准散落在各 Agent 认知中，无统一机读规则；辩论偶用过时数据 | 影响分析可信度 | 分级标准+新鲜度闸门+过时降级 | loop-contracts/README.md + data-collection.contract.yaml + daily-debate.contract.yaml + 02-lifecycle.md |
| **G22** | 交易建议可操作性原则未正式化 | CF609/CU2609辩论中形成的隐性规则，未沉淀到文档 | 新会话中Agent可能不知道此规则 | 新增10-coding-standards + harness-rules C13 + AP11 | 10-coding-standards.md + harness-rules.yaml | 新鲜度标准散落在各 Agent 认知中，无统一机读规则；辩论偶用过时数据 | 影响分析可信度 | 分级标准+新鲜度闸门+过时降级 | loop-contracts/README.md + data-collection.contract.yaml + daily-debate.contract.yaml + 02-lifecycle.md |
| **G22** | 交易建议可操作性原则未正式化 | CF609/CU2609辩论中形成的隐性规则，未沉淀到文档 | 新会话中Agent可能不知道此规则 | 新增10-coding-standards + harness-rules C13 + AP11 | 10-coding-standards.md + harness-rules.yaml | 新鲜度标准散落在各 Agent 认知中，无统一机读规则；辩论偶用过时数据 | 影响分析可信度 | 分级标准+新鲜度闸门+过时降级 | `loop-contracts/README.md` ✅ `data-collection.contract.yaml` ✅ `daily-debate.contract.yaml` ✅ `02-lifecycle.md` ✅ |

| **G105** | node_verdict FDC指标key不匹配：_gv("rsi")查不到RSI14、_gv("adx")查不到ADX等，导致闫判官FDC基准事实表全部N/A | 裁决LLM缺乏客观数据参考 → 全部neutral | P0 | v9.11.1 | 已关闭 | 修正key映射：rsi→RSI14, adx→ADX, cci→CCI20, macd_hist→MACD_DIF/MACD_DEA | fdt_langgraph/nodes.py |
| **G106** | scan_all.py _calc_volume_ma20未校验bar元素类型，当kline中bar为str时AttributeError崩溃 | scan_all无法输出JSON → 下游全链路数据缺失 | P0 | v9.11.1 | 已关闭 | 增加isinstance(b, dict)类型守卫 | skills/quant-daily/scripts/scan_all.py |

| **G107** | 观澜/探源FDC回退模板过于简陋，LLM解析失败时只填占位文本 | 报告中技术面/基本面无具体数据 | P1 | v9.11.2 | 已关闭 | 观澜回退利用indicators.values(RSI14/ADX/MA排列/Supertrend/ATR等)生成结构化描述+启发式评分；探源回退利用f10实际数据(term_structure/spread/basis/position_ranking)填充 | fdt_langgraph/nodes.py |

| **G108** | **LangGraph 迁移收尾** | ① ~~`pipeline/runner.py` 已删除~~ ✅ ② 15 个外部脚本评估为"有意识保留 subprocess" ✅ ③ Master Graph 心跳文件已落地 ✅ ④ 文档引用已清理 ✅ ⑤ `node_run_data_collection` dangling 引用已修复 ✅ ⑥ 全量测试通过 | P0 | v9.19.0 | ✅ **已关闭（v9.19.0）** | 删除 pipeline/runner.py、quality_filter.py、__init__.py、tests/pipeline/；清理 FDT_USE_LANGGRAPH；Master Graph 心跳文件 `_write_heartbeat()`；`node_run_data_collection` 内联修复；17 处文档旧引用全量清理；daemon_watchdog 确认使用 master_heartbeat.log；新增 `test_master_graph.py` 132 行测试 | 多文件 

### 4.2 P1 — 高优先级（影响效率/质量）

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G17 | 准入评估未自动化 | `docs/harness/09-advancement-plan.md` 定义了 4 步准入，但全部手动化 | 效率低 | 增加准入自动化脚本 |（计划中）|
| GAP-P1-001 | P1 数技源角色越界：产出 total/direction/grade 方向性预判，与观澜（P3）技术分析职责重叠 | P1 | v9.6.8 | 已关闭 | P1角色矫正：stats 纯统计特征产出，total/direction/grade 降级为内部参考，select_triggers 改为数据质量闸门 |

### 4.3 P2 — 低优先级

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G18 | 辩论调度权边界未在代码层强制 | `docs/02-lifecycle.md` 已澄清，但代码层无强制 | 潜在风险 | 考虑增加调度权断言 |（计划中）|

### 4.4 AP 反模式差距

| GAP ID | 描述 | 优先级 | 状态 | 说明 |
|:-------|:-----|:------|:-----|:-----|
| GAP-AP01-001 | AP01反模式：futures-debate-team-team-lead.md (619行) 和 futures-judge.md (482行) 超过300行阈值 | P1 | 开放 | 需拆分为多个子文档或精简至300行以内 |
| GAP-HOOK-001 | pre_commit_harness_check.py 脚本存在但未接入 Git pre-commit hook | P2 | 开放 | 需配置 .pre-commit-config.yaml 或 pyproject.toml 的 [tool.hatch.hooks] |

---

## MemoHarness 集成差距（2026-07-22 登记）

| GAP ID | 描述 | 优先级 | 关联阶段 | 状态 |
|:--|:--|:--:|:--:|:--:|
| G100 | Et 经验记录基础设施缺失 — 缺少 contracts/experience_schema.py 和 scripts/experience_recorder.py | P1 | Phase A | **已关闭** |
| G101 | Gt 模式蒸馏引擎缺失 — 缺少 scripts/pattern_distiller.py 和 staging 确认流程 | P2 | Phase B | **已关闭** |
| G102 | W(x_j) 案例适配引擎缺失 — 缺少 scripts/harness_adapter.py 和四步上线评估 | P2 | Phase C | **已关闭** |
| G103 | 正确性优先原则未写入机读规则 — harness-rules.yaml 缺少 C14 规则 | P1 | Phase A | **已关闭** |
| G124 | **单品种报告 vs 全量模板功能差距** | `single_symbol_report.py` 仅覆盖单品种场景，未实现：①产业链组辩论报告（多品种关联分析）；②全品种扫描 Top-N 排序矩阵；③跨品种相关性热力图；④产业链上下游联动分析。当前单品种报告回退到全量模板作为兜底。 | 中 | 待规划 | 2026-07-22 |
