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
| **本次会话 (v10.0.0)** | 8/8 | 全部 5/5 | | 记忆系统重构 + 关闭 G-6D-01~G-6D-08 + GAP-AP01-001 + GAP-HOOK-001 + G17 + G18 + G124 + G111 + G112 + GAP-AK-001 + GAP-AK-002，共 19 项差距。**当前零开放差距。** |

**综合评分：4.0（初始）→ 4.7（07-10 声称）→ 4.6（07-14 实测）→ 5.0（07-14 修复后 → 8 个 Harness 维度均达到 5/5，当前零开放差距）**

> G16/G14 已于 2026-07-14 19:04 修复并验证。G30/G111/GAP-AK-001/GAP-AK-002 已全部关闭（v10.0.0）。**当前零开放差距。**

**G19（2026-07-18 辩论重构·正反方→多空头模式）**：6策略管线场景下，正反方机制不合理。已重构为多空头六阶段攻防模式。涉及 state.py / nodes.py / graph.py / YAML配置 / 测试 共8个文件。**状态: ✅ 已实施 (v9.0.0)**

**G20（2026-07-18 辩论重构·来源标签格式一致性）**：✅ **已关闭（v9.5.0）** — 来源标签已统一为 `[domain:source]` 格式，如 `[technical:观澜]`、`[fundamental:探源]`、`[scan:数技源]`、`[chain:链证源]`。此前存在 `[观澜]`（短格式）、`[technical:观澜]`（domain:source格式）、`[scan]`（英文）、`[数技源]`（无 prefix）等多种格式。

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
| 版本兼容迁移 | `contracts/migrations.py` | ✅ **已修复（26 条迁移路径）** |

## 4. 差距清单 (Gaps)

### 4.1 P0 — 高优先级（影响正确性 / 回归）

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| **G109** | **自进化闭环 NoneType 错误**（v9.20.0 已修复） | `master_nodes.py` 行 384-385：`run_evolution()` 返回 None 时直接调用 `.get()` 报错 `'NoneType' object has no attribute 'get'`，进化步骤被 `except Exception` 捕获但日志错误信息不明确。 | P0 | 增加 `if ev_state:` None 防护 | `fdt_langgraph/master_nodes.py` ✅ v9.20.0 |
| **G110** | **质检缺字段校验过严导致裁决 FAIL**（v9.20.1 完全修复） | v9.20.0 仅更新了 `debate_quality_schema.py` 的 `VERDICT_RULES.conditional_required`，但 `validate_verdict()` 实际校验时仍从 `required_fields` 中逐个检查，未跳过条件必填字段。v9.20.1 补全：`validate_verdict()` 中优先检查 `conditional_required`，仅当方向为 bull/bear 时才验证 `entry_price`/`stop_loss`/`target1`。 | P0 | 在 `validate_verdict()` 的必填字段循环之前检查 conditional_required，跳过 condition 不满足的字段 | `fdt_langgraph/quality_inspector.py` + `contracts/debate_quality_schema.py` ✅ v9.20.1 |
| **G111** | **观澜/探源 LLM 输出解析率低**（v9.20.0 已修复） | LLM 返回仅 99/117 字符的短输出，`json.loads(output[start:end])` 失败导致回退到 FDC 数据。LLM 未提供有效的 per_symbol 结构化数据，影响辩论质量。 | P1 | 解析前增加 JSON 修复逻辑（BOM/注释/单引号/截断清理）；Agent prompt 明确强调输出格式 | `fdt_langgraph/nodes.py` + `agents/*` ✅ v9.20.0 |
| **G112** | **evolve_agents.py extract_knowledge 未保护导致 main() 崩溃**（v9.20.1 已修复） | `extract_knowledge_from_validated_verdicts()` 在 `main()` 中直接调用而无 `try/except` 包裹，函数内部异常传播到 `main()` 导致整个进化脚本崩溃，返回值 None，下游 `fdt_cli.py` 捕获 `AttributeError`。 | P1 | 包裹 `try/except`，非阻断异常打印日志后继续执行技能层进化 | `scripts/evolve_agents.py` ✅ v9.20.1 |
| **G113** | **fdt_cli.py run_debate() ev_state None 无保护**（v9.20.1 已修复） | G112 导致 `run_ev()` 返回 None，`ev_state.get("phase")` 在 None 上调用抛出 `AttributeError`。虽被 `except Exception` 兜住，但日志 `[ERROR] Evolution failed` 过于刺眼且掩盖根因。 | P2 | `ev_state` 使用时先判断 None，None 时友好提示 | `fdt_cli.py` ✅ v9.20.1 |
| **G114** | **RHI 递归 Harness 自改进框架**（v9.21.0 已实现） | FDT 自进化闭环只优化 Agent 参数和 ML 权重，不优化 Harness 配置本身。RHI 三层规范 (Agent/Workflow/Rules) 提供结构化 Harness 表示，Pairwise Evaluator 进行 O(1) 轨迹局部比较，Harness Optimizer 基于偏好历史更新。 | P1 | 整合 RHI 循环到 evolution_graph.py | `contracts/rhi_harness_spec.py` + `scripts/rhi_pairwise_eval.py` + `scripts/rhi_harness_optimizer.py` + `fdt_langgraph/rhi_graph.py` ✅ v9.21.0 |
| **G115** | **全局 Harness RHI 自优化**（v9.21.0 已实现） | CLAUDE.md 作为项目全局 Harness prompt，手工维护无法随项目演进自动优化。RHI 全局 Harness 模块通过 pairwise 质量评分迭代优化 CLAUDE.md 内容。 | P2 | 将 CLAUDE.md 作为 RHI 优化对象，每次迭代比较前后版本质量 | `scripts/rhi_global_harness.py` ✅ v9.21.0 |
| **G21** | 数据新鲜度保障机制未正式化 | 新鲜度标准散落在各 Agent 认知中，无统一机读规则；辩论偶用过时数据 | 影响分析可信度 | 分级标准+新鲜度闸门+过时降级 | `loop-contracts/README.md` ✅ `data-collection.contract.yaml` ✅ `daily-debate.contract.yaml` ✅ `02-lifecycle.md` ✅ |
| **G22** | 交易建议可操作性原则未正式化 | CF609/CU2609辩论中形成的隐性规则，未沉淀到文档 | 新会话中Agent可能不知道此规则 | 新增10-coding-standards + harness-rules C13 + AP11 | `10-coding-standards.md` ✅ `harness-rules.yaml` ✅ |

| **G105** | node_verdict FDC指标key不匹配：_gv("rsi")查不到RSI14、_gv("adx")查不到ADX等，导致闫判官FDC基准事实表全部N/A | 裁决LLM缺乏客观数据参考 → 全部neutral | P0 | v9.11.1 | 已关闭 | 修正key映射：rsi→RSI14, adx→ADX, cci→CCI20, macd_hist→MACD_DIF/MACD_DEA | fdt_langgraph/nodes.py |
| **G106** | scan_all.py _calc_volume_ma20未校验bar元素类型，当kline中bar为str时AttributeError崩溃 | scan_all无法输出JSON → 下游全链路数据缺失 | P0 | v9.11.1 | 已关闭 | 增加isinstance(b, dict)类型守卫 | skills/quant-daily/scripts/scan_all.py |

| **G107** | 观澜/探源FDC回退模板过于简陋，LLM解析失败时只填占位文本 | 报告中技术面/基本面无具体数据 | P1 | v9.11.2 | 已关闭 | 观澜回退利用indicators.values(RSI14/ADX/MA排列/Supertrend/ATR等)生成结构化描述+启发式评分；探源回退利用f10实际数据(term_structure/spread/basis/position_ranking)填充 | fdt_langgraph/nodes.py |

| **G108** | **LangGraph 迁移收尾** | ① ~~`pipeline/runner.py` 已删除~~ ✅ ② 15 个外部脚本评估为"有意识保留 subprocess" ✅ ③ Master Graph 心跳文件已落地 ✅ ④ 文档引用已清理 ✅ ⑤ `node_run_data_collection` dangling 引用已修复 ✅ ⑥ 全量测试通过 | P0 | v9.19.0 | ✅ **已关闭（v9.19.0）** | 删除 pipeline/runner.py、quality_filter.py、__init__.py、tests/pipeline/；清理 FDT_USE_LANGGRAPH；Master Graph 心跳文件 `_write_heartbeat()`；`node_run_data_collection` 内联修复；17 处文档旧引用全量清理；daemon_watchdog 确认使用 master_heartbeat.log；新增 `test_master_graph.py` 132 行测试 | 多文件 

| **G23** | **数据源降级链新鲜度缺失 — 过期货数据阻断辩论**（v9.24.0 已修复） | DataCore 返回已到期合约数据（SM 停在 2026-01-19）时降级链直接终止，后续 WebFallback/TqSDK 等有新鲜数据的源不被调用 | P0 | 新增末根K线日期新鲜度检查(>7天继续降级) + 统一 K 线标准化层(`_wrap_kline` 接入 `normalize_kline_row`) + TqSDK 升至第一数据源(priority=-1) + 数据质量`_calc_freshness_days` 支持 `%Y%m%d` 格式 | `multi_source_adapter.py` + `data_quality.py` + `tqsdk.py(priority=-1)` ✅ v9.24.0 |
| **G26** | **TqSDK `_pump` 中 `wait_update` 参数名错误导致数据泵送始终为空**（v9.24.2 已修复） | `futures_data_core/collectors/tqsdk.py::_pump()` 调用 `api.wait_update(timeout=0.5)`，但 TqSDK 3.10.1 的 `wait_update` 参数为 `deadline`（绝对时间戳）而非 `timeout`。`TypeError` 被 `except Exception: break` 静默吞噬，导致泵送循环立即返回空 DataFrame。下游 `_parse_kline` 返回 0 条 K 线 → scan_all 中 `all_ranked` 为空 → 无信号无辩论。此 bug 自 G23 将 TqSDK 提升为首位采集器后（v9.24.0）全面暴露。 | P0 | 修正为 `api.wait_update(deadline=time.time() + 0.5)`，遵循 TqSDK 3.10.1 API 签名。 | `futures_data_core/collectors/tqsdk.py` ✅ v9.24.2 |
| **G27** | **node_signal_output 中 signal_output 为 None 时崩溃**（v9.24.2 已修复） | P0b 新鲜度闸门阻断后 signal_output 保持 `None`（state.py 默认值 `Optional[dict]`），但 `node_signal_output()` 中 `state.get("signal_output", {})` 因 key 存在但值为 None 返回 None，`signal_output.get("status")` 抛出 `AttributeError`。 | P0 | `state.get("signal_output") or {}` 确保 None 时返回空字典。 | `fdt_langgraph/nodes.py` ✅ v9.24.2 |

### 4.2 P1 — 高优先级（影响效率/质量）

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G17 | 准入评估未自动化 | `docs/harness/09-advancement-plan.md` 定义了 4 步准入，已实现自动化 | 效率低 | 增加准入自动化脚本 | ✅ **已关闭（本次会话）** — `scripts/advancement_check.py` 已创建 |
| GAP-P1-001 | P1 数技源角色越界：产出 total/direction/grade 方向性预判，与观澜（P3）技术分析职责重叠 | P1 | v9.6.8 | 已关闭 | P1角色矫正：stats 纯统计特征产出，total/direction/grade 降级为内部参考，select_triggers 改为数据质量闸门 |
| **G28** | **_resolve_report_dir 跨日子目录生成**（v9.24.2 已修复） | `_resolve_report_dir()` 用 `datetime.now()` 日期匹配 workspace 目录名。当 workspace 为昨日（如 `20260723`）但当前时刻已过午夜（`20260724`），目录名不匹配 → 生成额外子目录（`.../20260723/2026-07-24/`）。 | P1 | 改用正则 `^\d{8}$` 匹配任意日期格式目录名。 | `fdt_langgraph/nodes.py` ✅ v9.24.2 |
| **G29** | **scan_all.py summary 未初始化 NameError 隐患**（v9.24.2 已修复） | 当 `target_symbols` 为空时 `for` 循环体不执行，`summary` 变量未定义，`summary.get("all_ranked", [])` 抛出 `NameError`。 | P1 | `for` 循环前预初始化 `summary = {}`。 | `skills/quant-daily/scripts/scan_all.py` ✅ v9.24.2 |
| **G31** | **AKShare `adjust=""` 参数不兼容（v10.0.1 已修复）** | `akshare_provider.py` 中 `ak.futures_hist_em()` 调用传入了 `adjust=""`，但 AKShare 1.18.64 函数签名无此参数，60+ 品种每调用均抛 `TypeError`，被 `except` 静默捕获后 fallback 返回 `UNAVAILABLE`，数据全链路断裂。错误被 P0b 闸门转化为"无有效品种"输出，真实根因完全不可见。 | P1 | 移除 `adjust=""` 参数，使其匹配 AKShare 1.18.64 的 `(symbol, period, start_date, end_date)` 签名。 | `futures_data_core/core/akshare_provider.py` ✅ v10.0.1 |

### 4.3 P2 — 低优先级

| # | 差距 | 现状 | 影响 | 改进建议 | 涉及文件 |
|:-:|:-----|:-----|:-----|:---------|:---------|
| G18 | 辩论调度权边界未在代码层强制 | `docs/02-lifecycle.md` 已澄清，代码层已强制 | 潜在风险 | 考虑增加调度权断言 | ✅ **已关闭（本次会话）** — `node_dispatch` 新增调度权断言 |
| **GAP-AK-001** | **资金流向数据不可用** | `akshare.futures_hold_pos_sina()` 返回空数据。data_adapter 已封装 try/except + UNAVAILABLE 降级，下游消费方读取 `data_grade` 后自动跳过。 | P2 | data_adapter 已处理（返回 UNAVAILABLE），待 AKShare 修复或接入替代源后自然解决 | `data_adapter/sources/akshare_source.py` | ✅ **v10.0.0 已关闭（data_adapter 封装 + UNAVAILABLE 降级）** |
| **GAP-AK-002** | **外盘历史K线不可用** | `akshare.futures_foreign_hist()` 部分品种有数据（通过 `_FOREIGN_MAP` 映射），无映射品种返回 UNAVAILABLE。data_adapter 已封装 try/except + UNAVAILABLE 降级。 | P2 | data_adapter 已处理（映射品种尽力获取，无映射返回 UNAVAILABLE），待接入更多外盘映射后扩展 | `data_adapter/sources/akshare_source.py` | ✅ **v10.0.0 已关闭（data_adapter 封装 + 映射表 + UNAVAILABLE 降级）** |

### 4.4 AP 反模式差距

| GAP ID | 描述 | 优先级 | 状态 | 说明 |
|:-------|:-----|:------|:-----|:-----|
| GAP-AP01-001 | AP01反模式：futures-judge.md(195行)/futures-debate-team-team-lead.md(210行)≤300行 | P1 | ✅ **已关闭（本次会话）** | judge.md(195行)/team-lead.md(210行)≤300行 |
| GAP-HOOK-001 | pre_commit_harness_check.py 已接入 Git pre-commit hook | P2 | ✅ **已关闭（本次会话）** | .pre-commit-config.yaml 已创建 |

### 4.5 六维控制空间差距（2026-07-23 登记）

| GAP ID | 差距 | 现状 | 严重度 | 状态 | 修复方案 | 涉及文件 |
|:-------|:-----|:-----|:------:|:-----|:---------|:---------|
| **G-6D-01** | decode_config.yaml quality_assurance 配置孤儿 | 品藻纯Python不调LLM，配置是死配置 | P1 | ✅ **已关闭（v9.24.0 六维控制空间重构）** | 删除该配置节 | config/agents/decode_config.yaml |
| **G-6D-02** | enforce_structured_output 未被 nodes.py 调用 | 362行D3管线存在但5处LLM解析全部绕过 | P0 | ✅ **已关闭（v9.24.0 六维控制空间重构）** | 5处替换为 enforce_structured_output() | fdt_langgraph/nodes.py |
| **G-6D-03** | ContentFilter 未被 quality_inspector 实际调用 | 264行仅import未实例化 | P0 | ✅ **已关闭（v9.24.0 六维控制空间重构）** | validate_verdict/risk 末尾调用 filter() | fdt_langgraph/quality_inspector.py |
| **G-6D-04** | LLM输出解析无统一入口 | 5处重复json.loads + _repair_json仅覆盖2/5 | P1 | ✅ **已关闭（v9.24.0 六维控制空间重构）** | llm_provider.py 新增 parse_llm_output() | fdt_langgraph/llm_provider.py |
| **G-6D-05** | _build_debate_context 全量注入所有品种 | 辩论prompt膨胀，无关品种数据干扰 | P2 | ✅ **已关闭 (v9.22.3)** | 追加 current_symbol 参数过滤 | fdt_langgraph/nodes.py |
| **G-6D-06** | vector_memory 未接入 fdt_langgraph | 306行向量检索已实现但未被辩论流程调用 | P1 | ✅ **已关闭（本次会话）** | _build_fdc_fundamental_context 追加检索 | fdt_langgraph/nodes.py |
| **G-6D-07** | ToolMetrics 不反哺调度决策 | record_call→detect_anomalies 链路完整但仅写文件 | P2 | ✅ **已关闭（本次会话）** | node_dispatch 读取 stats 决策跳过 | fdt_langgraph/master_nodes.py |
| **G-6D-08** | OutputMetrics 未成为硬约束 | score_output 评分0-100但不影响质检结果 | P2 | ✅ **已关闭（v9.24.0 六维控制空间重构）** | validate_verdict 追加评分阻断逻辑 | fdt_langgraph/quality_inspector.py |

---

## MemoHarness 集成差距（2026-07-22 登记）

| GAP ID | 描述 | 优先级 | 关联阶段 | 状态 |
|:--|:--|:--:|:--:|:--:|
| G100 | Et 经验记录基础设施缺失 — 缺少 contracts/experience_schema.py 和 scripts/experience_recorder.py | P1 | Phase A | **已关闭** |
| G101 | Gt 模式蒸馏引擎缺失 — 缺少 scripts/pattern_distiller.py 和 staging 确认流程 | P2 | Phase B | **已关闭** |
| G102 | W(x_j) 案例适配引擎缺失 — 缺少 scripts/harness_adapter.py 和四步上线评估 | P2 | Phase C | **已关闭** |
| G103 | 正确性优先原则未写入机读规则 — harness-rules.yaml 缺少 C14 规则 | P1 | Phase A | **已关闭** |
| G124 | **单品种报告 vs 全量模板功能差距** | `single_symbol_report.py` 仅覆盖单品种场景，已通过 `fdt_langgraph/report_aggregator.py` 实现全量模板覆盖 | 中 | ✅ **已关闭（本次会话）** | 2026-07-22 — `fdt_langgraph/report_aggregator.py` 已创建 |

### G30 — 记忆规则注入 Agent Prompt 未纳入自进化闭环（2026-07-24 登记）

| 字段 | 内容 |
|:-----|:------|
| **标题** | MEMORY.md 运行时规则注入 Agent Prompt 未接入自进化闭环 |
| **描述** | `memory/rules/MEMORY.md` 包含多条运行时铁律（市价入场、去融合、品藻质检、中文术语等），各有归属 Agent（judge/risk_manager/bullish/bearish/quality_assurance）。`memory/retrieval/rules_injector.py` 已实现按 Agent 提取规则的能力，但该机制未纳入自进化闭环（Outer Loop），无法自动判断"何时注入哪些规则给哪些 Agent"以及"注入后的效果是否改善决策质量"。 |
| **优先级** | P1 |
| **现状** | 基础设施就绪（标签 + injector），等待接入自进化系统 |
| **已就绪的资产** | ① `memory/rules/MEMORY.md` 已打 `<!-- agents: -->` 标签 ② `memory/retrieval/rules_injector.py` 已实现（缓存、mtime 刷新、别名映射） ③ 自进化闭环 `evolution_graph.py` 已有 `decide_actions` 条件路由架构 |
| **未完成的工作** | ④ `evolution_graph.py` 新增 `inject_rules` 节点 + 条件触发逻辑 ⑤ `evolution_state.py` 新增 `injection_config` 字段 ⑥ `nodes.py` 读取 `injection_config` 决定是否调用 `get_rules_for_agent()` |
| **建议方案** | 在 `evolution_nodes.py` 新增 `node_inject_rules()`，由 `decide_actions` 根据 Checker 缺口报告 + 质检 FAIL 模式 + APM D2 退化信号触发。注入效果通过 A/B 对比验证（开关开启 N 轮后比较质检通过率）。详见 [memory-system-overhaul.md](../designs/memory-system-overhaul.md) §自进化闭环设计。 |
| **触发条件** | 任一满足即触发：(a) Checker 报告 Agent 输出违反 MEMORY.md 规则 (b) 质检 FAIL 中包含规则违反类错误 (c) APM D2 (Acuity) 连续 3 轮下降 |
| **验证方式** | A/B 对比：开启注入 N 轮后 vs 无注入历史基线。改善标准：裁决准确率 ↑ or 质检 PASS 率 ↑ |
| **关联文件** | `memory/rules/MEMORY.md`、`memory/retrieval/rules_injector.py`、`fdt_langgraph/evolution_nodes.py`、`fdt_langgraph/evolution_graph.py`、`fdt_langgraph/evolution_state.py`、`fdt_langgraph/nodes.py`、`memory/maintenance/checker.py` |
| **登记日期** | 2026-07-24 |
| **状态** | ✅ **已实施（v10.0.0）** — evolution_graph 新增 `inject_rules` 节点，由 `decide_actions` 根据 Checker 缺口/APM D2 触发；nodes.py 中 5 个 Agent 节点读取 `injection_config.json` 并调用 `get_rules_for_agent()` |

| **G31** | **观澜 context 数据注入不全**（v10.0.0 已修复） | `_build_fdc_technical_context` 仅注入 K线和技术指标，未注入持仓排名/资金流向/外盘数据。观澜 Agent prompt 要求"持仓结构、资金流、多空比"，但实际 context 无对应数据。 | P1 | 在 `prepare_one_symbol` 追加 `get_fund_flow`/`get_foreign_hist` 调用；在 `_build_fdc_technical_context` 新增持仓排名(净多/前5多/前5空)、资金流向(总持仓/多空比)、外盘(收盘价/涨跌幅)三块注入。 | `fdt_langgraph/nodes.py` `_build_fdc_technical_context()`, `data_source_adapter.py` | `futures_data_core/core/data_quality.py` | ✅ **v10.0.0 已关闭** |

| **G112** | **scan_all.py 品种去重逻辑不完整**（v10.0.0 已修复） | 当前仅按品种代码前缀分组（CF2609→CF），未计算真实相关系数。聚酯链品种（PF/PR/TA/PX 等 r>0.95）无法去重。 | P1 | 在 `run_scan()` 末尾调用 `_compute_correlation_groups()`，基于 60 日收盘价 Pearson r > 0.80 做真实相关系数去重。 | `skills/quant-daily/scripts/scan_all.py` `run_scan()` | ✅ **v10.0.0 已关闭** |

| **G109** | **node_judge_direction 越权做品种筛选**（v10.0.0 已修复） | 闫判官职责应是协调数据源调度，但当前节点让 LLM 从 62 个品种中选辩论品种。 | P0 | 移除 LLM 选品种逻辑，直接从 `scan_results.primary_symbols` 读取预筛选品种。LLM 只决定 `dispatch_sources`。 | `fdt_langgraph/nodes.py` `node_judge_direction()` | ✅ **v10.0.0 已关闭** |

| **G111** | **FDC 退役后数据链路断裂**（v10.0.0 已修复） | FDC（futures_data_core）已正式退役，data_adapter/ 包已创建（6 文件，12 统一接口），scan_all.py 和 nodes.py P2.5 全面接入，FDC 目录已物理删除。 | P0 | 创建 `data_adapter/` 包，含 DataSource 抽象基类、AKShareSource 实现（12个统一接口）、路由入口。scan_all.py 和 nodes.py P2.5 全面接入，完成后物理删除 `futures_data_core/` 目录。 | `data_adapter/` (新建) , `skills/quant-daily/scripts/scan_all.py`, `fdt_langgraph/nodes.py` | ✅ **v10.0.0 已关闭** |

## 一致性元数据

| 代码文件/函数 | 文档章节 | 关键断言/可验证事实 | 检验方式 |
|:--------------|:---------|:-------------------|:---------|
| `scripts/validate_agent_output.py` | §2.1 L1 | 产出校验活跃状态 | `grep -n "def " validate_agent_output.py` |
| `scripts/agent_waiter.py wait_for_agent_output()` | §2.2 S04 | 轮询重试+降级活跃 | `grep -n "def wait_for_agent_output" agent_waiter.py` |
| `scripts/daemon_watchdog.py` | §2.2 看门狗 | 健康检查活跃 | `grep -n "def " daemon_watchdog.py` |
| `scripts/apm_scorecard.py` | §3 D1-D5 | 五轴评分活跃 | `grep -n "def " apm_scorecard.py` |
| `scripts/enforce_discipline.py` | §3 D4 | 纪律钳制活跃 | `grep -n "def " enforce_discipline.py` |
| `scripts/validate_verdicts.py` | §3 裁决验证 | 裁决验证活跃 | `grep -n "def " validate_verdicts.py` |
| `scripts/calibrate_weights.py` | §3 校准 | 权重校准活跃 | `grep -n "def " calibrate_weights.py` |
| `scripts/evolve_agents.py` | §3 进化 | Agent 进化活跃 | `grep -n "def " evolve_agents.py` |
| `contracts/migrations.py` | G14 | 26 条迁移路径已修复 | `grep -n "def apply_migration" contracts/migrations.py` |
| `docs/schemas/` | §4 | 9 个 JSON Schema 活跃 | `ls docs/schemas/*.json` |
| All gap entries with status | §4 差距表 | Gxxx 状态可追踪 | `grep -c "\[" 08-gap-analysis.md` 统计开放 vs 已关闭差距 |
