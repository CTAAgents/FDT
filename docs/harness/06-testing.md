# 06 — 测试策略

## 1. 测试金字塔

```
                    ┌─────────────────┐
                    │   E2E / 回放     │  ViBench 历史回放 (20金标准案例)
                    │   顶层           │  pipeline 全流程测试
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  集成 / 契约     │  8个目录 × 16个测试文件
                    │  中层            │  JSON Schema 校验 + 门禁审计
                    │                  │  (v9.12.0: tests/scripts/ → tests/fdt_scripts_tests/)
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  单元 / 底层     │  各 skill 内函数级测试
                    │  基座            │  信号计算/风控引擎/数据采集
                    └─────────────────┘
```

## 2. 测试目录结构

```
tests/
├── commodity-chain/              # 产业链分析 (6个测试)
│   ├── conftest.py
│   ├── test_chain_full_analysis.py
│   ├── test_chains.py            # 链聚类/相关性
│   ├── test_config.py            # 配置加载
│   ├── test_debate.py            # 辩论接口
│   ├── test_risk.py              # 风控逻辑
│   └── test_screen.py            # 筛选逻辑
├── contracts/                    # 契约Schema (1个测试)
│   ├── conftest.py
│   └── test_contracts.py         # 9个JSON Schema校验
├── debate-argument-builder/      # 辩论论点 (1个测试)
│   ├── conftest.py
│   └── test_debater.py           # 论据构建逻辑
├── debate-risk-manager/          # 风控引擎 (1个测试)
│   ├── conftest.py
│   └── test_risk_manager.py      # 6层风控
├── [root]/                      # D3 Generation 解码控制 (2个测试文件)
│   ├── test_decode_control.py    # D3 decode_config + 结构化输出 + 内容过滤 + 质量度量 (43用例)
│   └── test_output_control.py    # D6 输出治理: 度量/版本化/反馈/审计
├── fdt-gate/                     # 质量门禁 (1个测试)
│   ├── conftest.py
│   └── test_quality_gate.py      # L1-L5鲁棒性防线
├── fdt_langgraph/                # LangGraph 节点/图/集成 (5测试文件, v9.0.0 +3节点测试 + final_arguments divergence)
│   ├── conftest.py
│   ├── test_nodes.py             # 节点单元测试 (+ 新节点 bearish_rebuttal/bear_final/bull_final)
│   ├── test_state.py             # 状态管理 (+ v9.0.0 六阶段字段: bearish_rebuttal_arguments 等5项)
│   ├── test_graph.py             # 图构建/Checkpointer/divergence (+ final_arguments divergence + debate节点注册)
│   ├── test_agents.py            # AgentExecutor/Registry/LLM (新增, 56用例)
│   ├── test_health.py            # 健康检查全覆盖 (新增, 42用例, 100%覆盖)
│   ├── test_e2e_integration.py   # 端到端集成
│   ├── test_e2e_report_layer.py  # 报告层端到端
│   ├── test_reports.py           # 报告层单元测试
│   ├── test_postgres_integration.py
│   ├── test_benchmark_comparison.py
│   └── test_integration_ab.py    # A/B 切换集成
├── fundamental-data-collector/   # 基本面采集 (1个测试)
│   ├── conftest.py
│   └── test_collector.py         # 供需/库存/利润
├── memory/                        # 记忆写入 (9个测试)
│   ├── conftest.py
│   └── test_writer.py             # Journal/Index/Record 原子性+去重
├── pipeline/                      # 流水线 (10个测试)
│   ├── conftest.py
│   └── test_runner.py             # 6阶段主流程+失败不阻断+trace注入
├── quant-daily/                  # 量化日评 (6个测试)
│   ├── conftest.py
│   ├── test_auto_train_orchestrator.py  # ML训练
│   ├── test_coverage_boost.py           # 覆盖率补充
│   ├── test_debate_brief.py             # 辩论精选
│   ├── test_debate_history.py           # 历史反馈
│   ├── test_keltner_wf.py               # Keltner通道
│   └── test_quality_filter.py           # 研报过滤
├── self-improve-enhanced/        # 自改进增强 (4个测试)
│   ├── conftest.py
│   ├── test_analyze_trajectory.py
│   ├── test_embodiskill_reflect.py
│   ├── test_skillevolver_evolution.py
│   └── test_verify_evolution.py
├── strategies/                    # 策略层测试 (19个测试, + TestSubSignalMerge 4用例 v9.4.3)
│   ├── conftest.py
│   ├── test_adapter.py
│   ├── test_arbitrage.py
│   ├── test_base_v2.py
│   ├── test_basis_reversion.py
│   ├── test_event_driven.py
│   ├── test_macro_regime.py
│   ├── test_mean_reversion.py
│   ├── test_ml_signal.py
│   ├── test_multi_factor.py
│   ├── test_pairs_reversion.py
│   ├── test_pipeline.py
│   ├── test_pipeline_e2e.py
│   ├── test_pipeline_nofilter.py
│   ├── test_pipeline_price_backfill.py
│   ├── test_spread_reversion.py
│   ├── test_strategy_pause.py
│   ├── test_trend_following.py
│   ├── test_turtle_system.py
│   └── test_vol_targeting.py
├── technical-analysis/           # 技术分析 (1个测试)
│   ├── conftest.py
│   └── test_technical.py         # 支撑阻力/形态
└── validators/                    # 验证器测试 (4个测试)
    ├── conftest.py
    ├── test_atr_vol_timing_enhanced.py
    ├── test_p0_4_raw_kline.py
    ├── test_select_triggers_filter.py
    └── test_volume_confirm_enhanced.py
├── fdt_cache/                     # 本地增量缓存 (G85 新增)
│   ├── conftest.py
│   ├── test_cache_read_write.py    # 缓存读写/过期/压缩测试
│   └── test_cache_integration.py   # 缓存与 LangGraph 集成测试
├── dominant-resolver/             # 主力合约解析 + DataCore 集成 + 字段标准化 (G86 新增)
│   ├── conftest.py
│   ├── test_dominant_resolver.py   # 换月判定/历史归档/合约解析测试 (28 用例)
│   ├── test_datacore_collector.py  # DataCore 采集器适配器测试 (14 用例)
│   ├── test_field_normalizer.py   # 字段标准化器测试 (25 用例)
│   ├── test_datacore_bridge.py    # DataCore F10 桥接器测试 (24 用例, v9.4.0 新增)
│   └── test_fdc_fallback.py       # FDC 降级兼容性测试 (v9.4.0 新增)
├── scripts/                       # 脚本层测试 (G92 新增, v9.6.2)
│   ├── conftest.py
│   └── test_validate_llm_output.py # LLM 输出质量校验器测试 (18 用例, 覆盖价格偏差/置信度/评分三维校验)
```

### 2.1 报告层测试 (v8.8.0+)

`tests/fdt_langgraph/test_reports.py` 覆盖明鉴秋报告层调度的五个阶段：

| 测试用例 | 覆盖阶段 | 验证内容 |
|:---------|:---------|:---------|
| `test_scan_report_written` | P1 | `node_scan` 产出 `scan_report_path`、HTML 文件存在、含 trace_id |
| `test_research_report_written` | P3 | `node_merge_research` 产出 `research_report_path`、含四源数据 |
| `test_verdict_report_written` | P5 | `node_risk_check` 产出 `verdict_report_path`、含裁决+风控 |
| `test_signal_report_written` | P6a | `node_signal_output` 产出 `signal_report_path`、含信号状态 |
| `test_debate_report_fallback` | P6 | `node_report` 在主脚本失败时 fallback 到工作空间 |
| `test_report_dir_uses_workspace_env` | 全阶段 | `FDT_REPORT_WORKSPACE` 环境变量生效 |
| `test_report_dir_fallback_to_temp` | 全阶段 | 无环境变量时回退到 `tempfile.gettempdir()` |
| `test_e2e_all_reports_generated` | E2E | 端到端验证 5 个报告路径全部有效 |
| `test_report_path_unique_per_phase` | 契约 | 5 个状态字段互不干扰，各有独立值 |

## 3. 测试框架配置

### 3.1 pytest 配置 (pyproject.toml)

```toml
[tool.pytest.ini_options]
testpaths = ["tests/quant-daily"]
addopts = "--cov=skills/quant-daily/scripts/signals --cov-report=term-missing"
```

### 3.2 测试运行器

`run_all_tests.py` 分 8 个目录依次执行，避免 conftest.py 的 sys.path 冲突：

```bash
# 运行全部测试
python run_all_tests.py

# 输出示例:
# === tests/commodity-chain ===
# 16 passed
# === tests/contracts ===
# 9 passed
# === tests/debate-argument-builder ===
# 4 passed
# ...
# Total: 49 passed, 0 failed (5门禁审计全100%)
```

### 3.3 依赖

```toml
[project.optional-dependencies]
dev = ["pytest>=7.4", "pytest-cov>=4.1"]
```

## 4. 契约测试

### 4.1 JSON Schema 校验

`tests/contracts/test_contracts.py` 对 9 个 JSON Schema 进行校验：

| Schema | 文件 | 生产者 | 消费者 |
|:-------|:-----|:-------|:-------|
| `ArgumentOutput` | `docs/schemas/ArgumentOutput.json` | 证真/慎思 | 闫判官 |
| `StructuredDebate` | `docs/schemas/StructuredDebate.json` | 证真/慎思 (v3) | 闫判官 |
| `OverallJudgment` | `docs/schemas/OverallJudgment.json` | 闫判官 | 明鉴秋 |
| `RiskOutput` | `docs/schemas/RiskOutput.json` | 风控明 | 闫判官 |
| `VerdictItem` | `docs/schemas/VerdictItem.json` | 闫判官 | 明鉴秋 |
| `ChainAnalysisOutput` | `docs/schemas/ChainAnalysisOutput.json` | 链证源 | 闫判官 |
| `ChainMetric` | `docs/schemas/ChainMetric.json` | 链证源 | 闫判官 |
| `DimensionItem` | `docs/schemas/DimensionItem.json` | 辩论维度 | 闫判官 |
| `EvidenceItem` | `docs/schemas/EvidenceItem.json` | 证据项 | 闫判官 |

### 4.2 校验规则

```python
# tests/contracts/test_contracts.py 核心校验项
□ schema 自身合法性 (Draft 2020-12)
□ required fields 不空
□ confidence ∈ [0, 1] 或 [0, 100]
□ 无 verdict 字段 (研究员输出红线)
□ meta.agent_name 与产出方一致
□ version 字段存在
```

## 5. 门禁审计 (Quality Gate)

### 5.1 五层门禁

`tests/fdt-gate/test_quality_gate.py` 实现 L1-L5 鲁棒性防线的门禁测试：

| 门禁 | 检查内容 | 通过条件 |
|:-----|:---------|:---------|
| L1 门禁 | `validate_agent_output.py` 存在且可执行 | 脚本存在 + import 成功 |
| L2 门禁 | `debate_orchestrator.py` 存在 + D06 降级逻辑可触发 | 脚本存在 + 降级路径覆盖 |
| L3 门禁 | `debate_trigger.json` 信号门检查逻辑正确 | 无信号时提前终止 |
| L4 门禁 | `phase3_generate_report.py` 支持 CLI 参数 | `--workspace` 参数可用 |
| L5 门禁 | `selfcheck.py` 存在且可执行 | 脚本存在 + import 成功 |

### 5.2 门禁通过率

README 声称"5门禁审计全100%"，即所有门禁测试均通过。

## 6. ViBench 基准测试

### 6.1 测试集

| 文件 | 路径 | 内容 |
|:-----|:-----|:-----|
| 金标准集 | `benchmarks/test_cases.json` | 20 个历史场景 (含信号/论据/裁决) |
| 基线指标 | `benchmarks/benchmark_baseline.json` | 基线准确率/coherence |
| 回放结果 | `benchmarks/benchmark_replay.json` | 最近一次回放结果 |

### 6.2 回放指标

| 指标 | 含义 | 计算方法 |
|:-----|:-----|:---------|
| `coherence_weighted_accuracy` | 一致性加权准确率 | 按 held_out_judge.coherence_score 加权的方向准确率 |
| `direction_accuracy` | 方向准确率 | 预测方向与实际方向一致的比例 |
| `signal_recall` | 信号召回率 | 正确识别的信号占所有有效信号的比例 |

### 6.3 CLI 接口

```bash
python scripts/run_benchmark.py --build    # 构建测试集 (从历史辩论提取)
python scripts/run_benchmark.py --run      # 运行基准 (新辩论 vs 基线)
python scripts/run_benchmark.py --replay   # 回放历史 (确定性结构一致性)
```

## 7. 覆盖率

### 7.1 当前覆盖率配置

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = "--cov=skills/quant-daily/scripts/signals --cov-report=term-missing"
```

覆盖率仅覆盖 `skills/quant-daily/scripts/signals/` 目录。

### 7.2 覆盖率 Gap

> **Gap**: 覆盖率配置仅覆盖 quant-daily 的 signals 目录，其他 skill (commodity-chain-analysis, debate-risk-manager 等) 的脚本无覆盖率统计。
>
> **改进建议**: 扩展 `--cov` 配置到所有 skill 的 scripts 目录。

## 8. 测试矩阵

### 8.1 测试类型 × 组件

| 组件 | 单元测试 | 集成测试 | 契约测试 | 门禁测试 | 基准回放 |
|:-----|:--------:|:--------:|:--------:|:--------:|:--------:|
| quant-daily | ✅ | ✅ | — | ✅ | ✅ |
| commodity-chain-analysis | ✅ | ✅ | ✅ | ✅ | — |
| debate-argument-builder | ✅ | — | ✅ | — | — |
| debate-risk-manager | ✅ | — | ✅ | ✅ | — |
| fundamental-data-collector | ✅ | — | — | — | — |
| technical-analysis | ✅ | — | — | — | — |
| contracts | ✅ | — | ✅ | — | — |
| fdt-gate (L1-L5) | — | — | — | ✅ | — |
| pipeline (runner) | ✅ | ✅ | — | — | — | — | — | 10 用例 ✅ |
| memory (writer/archiver) | ✅ | ✅ | — | — | — | — | — | 9 用例 |
| **dominant-resolver** | ✅ | ✅ | — | — | — | — | — | **75 用例** (28 dominant + 22 datacore + 25 normalizer, v9.3.0 新增) |
| **validators** | ✅ | — | — | — | — | **4 用例** |
| **strategies** | ✅ | ✅ | — | — | — | **19 用例 + 4 新增 (TestSubSignalMerge)** |
| **fdt_langgraph** | ✅ | ✅ | — | — | — | **99 用例** |

> ⚠️ **2026-07-14 整顿**：原「43 用例全绿」声明曾因 v6.3.0 重构后 `tests/pipeline/test_runner.py` mock 重命名函数失配而失真（5/10 失败）。**该问题已于 2026-07-14 19:04 修复**，当前 pipeline 10/10 全绿。

### 8.2 测试执行命令（v5.7 更新）

```bash
# 全部 Harness 测试
python -m pytest tests/ --ignore=tests/commodity-chain -v --no-cov
```

5. 覆盖率（慢）

```bash
python -m pytest tests/ --cov=scripts --cov=fdt_langgraph --cov-report=term-missing
```

# 仅门禁测试
python -m pytest tests/fdt-gate/ -v

# ViBench 回放
python scripts/run_benchmark.py --replay
```

## 9. 测试统计（G7 覆盖率扩展后）

| 指标 | v5.6 初始 | v5.7 最终 | v8.8.6 当前 |
|:-----|:--------:|:--------:|:-----------:|
| 测试文件数 | 23 | 26 | **60+ 文件 / 16 目录**（含 `fdt_langgraph` 10文件 + `strategies` 19文件 + `validators` 4文件） |
| Harness 测试用例 | 0 | 43 | fdt_langgraph 累计 **120+ 用例**（test_agents 58 + test_nodes 21 + test_reports 12 + test_parallel_dispatch 9 + test_e2e 18 + test_state 2 + test_pg 12 + test_benchmark 10 + test_health 9 + test_integration_ab 18） |
| 覆盖率范围 | quant-daily/signals | skills+pipeline+scheduler+scripts | 4x 扩展（`pyproject.toml` 已配置） |
| 测试目录数 | 8 | 11 | **16** |
| conftest.py 数 | — | 8 | **16** |

## 10. 验证器质量度量（v9.6.4+）

> **设计目标**: 通过量化指标衡量验证器的质量，确保验证器既不"漏放"错误输出，也不"误杀"正确输出

### 10.1 核心指标

| 指标 | 名称 | 定义 | 目标值 |
|:-----|:-----|:-----|:-------|
| `false_pass_rate` | 漏放率 | 验证器判定通过但实际错误的比例 | ≤ 1%（硬指标） |
| `false_block_rate` | 误杀率 | 验证器判定失败但实际正确的比例 | ≤ 5%（效率指标） |
| `true_positive_rate` | 真阳性率 | 验证器正确判定错误的比例 | ≥ 99% |
| `true_negative_rate` | 真阴性率 | 验证器正确判定通过的比例 | ≥ 95% |
| `precision` | 精确率 | 验证器标记为错误中实际错误的比例 | ≥ 95% |
| `recall` | 召回率 | 所有错误中被验证器捕获的比例 | ≥ 99% |

### 10.2 指标计算公式

```python
# 漏放率 = 漏放数 / 总验证数
false_pass_rate = false_pass_count / total_validations

# 误杀率 = 误杀数 / 总验证数  
false_block_rate = false_block_count / total_validations

# 真阳性率 = 正确拒绝数 / (正确拒绝数 + 漏放数)
true_positive_rate = true_reject_count / (true_reject_count + false_pass_count)

# 真阴性率 = 正确通过数 / (正确通过数 + 误杀数)
true_negative_rate = true_accept_count / (true_accept_count + false_block_count)
```

### 10.3 验证器质量等级

| 等级 | 漏放率 | 误杀率 | 说明 |
|:-----|:------:|:------:|:-----|
| **S** | < 0.5% | < 3% | 优秀，可用于生产环境 |
| **A** | < 1% | < 5% | 良好，可用于生产环境 |
| **B** | < 2% | < 10% | 合格，需持续改进 |
| **C** | ≥ 2% 或 ≥ 10% | — | 不合格，禁止用于生产 |

### 10.4 验证器清单与当前质量

| 验证器 | 路径 | 漏放率目标 | 误杀率目标 | 用途 |
|:-------|:-----|:----------:|:----------:|:-----|
| `validate_agent_output.py` | `scripts/` | ≤ 1% | ≤ 5% | Agent 输出格式校验 |
| `validate_verdicts.py` | `scripts/` | ≤ 1% | ≤ 5% | 裁决验证（方向+参数） |
| `validate_llm_output.py` | `scripts/` | ≤ 1% | ≤ 5% | LLM 输出质量校验（幻觉检测） |
| `validate_final_signals.py` | `scripts/` | ≤ 1% | ≤ 5% | 最终信号校验 |

### 10.5 质量监控机制

```bash
# 计算验证器质量指标
python scripts/validate_llm_output.py --scan scan.json --verdict verdict.json --stats llm_hallucination_stats.json

# 质量报告
cat llm_hallucination_stats.json | jq '{
  false_pass_rate: (.hallucinated_count / .total_verdicts * 100),
  false_block_rate: (.confidence_issues / .total_verdicts * 100),
  total_verdicts: .total_verdicts
}'
```

### 10.6 质量告警规则

| 告警级别 | 触发条件 | 响应动作 |
|:---------|:---------|:---------|
| **P0** | 漏放率 > 1% | 立即停止生产，修复验证器 |
| **P1** | 漏放率 > 0.5% | 24小时内修复 |
| **P1** | 误杀率 > 5% | 72小时内优化 |
| **P2** | 误杀率 > 3% | 记录差距，定期优化 |

## 11. LangGraph 并行节点测试策略 (v8.3.0+)

### 11.1 并行测试架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    LangGraph 并行测试体系                        │
├────────────────────┬────────────────────┬───────────────────────┤
│   节点单元测试      │   图集成测试        │   并行调度测试         │
├────────────────────┼────────────────────┼───────────────────────┤
│ node_scan          │ 全链路串行执行      │ 四源并行调度           │
│ node_chain         │ 条件分支路径        │ 双源并行调度           │
│ node_technical     │ 阶段状态流转        │ 单源调度               │
│ node_fundamental   │ trace_id 传递       │ 空调度（无信号）       │
│ node_merge_research│                     │                       │
│ node_debate        │                     │                       │
│ node_verdict       │                     │                       │
└────────────────────┴────────────────────┴───────────────────────┘
```

### 11.2 测试目录结构

```
tests/fdt_langgraph/
├── conftest.py                    # 测试配置 + mock 重 I/O 操作 (v8.3.0+)
├── test_nodes.py                  # 节点单元测试 (11 用例)
├── test_parallel_dispatch.py      # 并行调度测试
├── test_state.py                  # 状态管理测试 (2 用例)
├── test_e2e_integration.py        # 端到端集成测试
├── test_e2e_report_layer.py       # 报告层端到端快速验证 (v8.8.0+，1 用例)
├── test_reports.py                # 报告层单元测试 (v8.8.0+，12 用例)
├── test_postgres_integration.py   # PostgreSQL 集成测试
├── test_benchmark_comparison.py   # 基准对比测试
├── test_health.py                 # 健康检查测试
└── test_integration_ab.py         # A/B 切换集成测试 (v8.4.0+ G55，18 用例)
```

### 10.3 节点单元测试

| 测试项 | 节点 | 测试内容 | 断言 |
|:-------|:-----|:---------|:-----|
| `test_node_scan` | node_scan | 可插拔多策略扫描 | scan_results 包含策略键 |
| `test_node_chain` | node_chain | 产业链分析输出 | chain_analysis 不为空 |
| `test_node_technical` | node_technical | 技术面分析输出 | technical_data 不为空 |
| `test_node_fundamental` | node_fundamental | 基本面分析输出 | fundamental_data 不为空 |
| `test_node_merge` | node_merge_research | 四源数据合并 | research_data 包含四类数据 |
| `test_node_debate` | node_debate | 辩论论据生成 | bullish/bearish_arguments 不为空 |
| `test_node_verdict` | node_verdict | 裁决输出 | verdict 不为空 |

### 10.4 图集成测试

| 测试项 | 内容 | 断言 |
|:-------|:-----|:-----|
| `test_full_serial_path` | 默认模式全链路执行 | 所有阶段完成，无错误 |
| `test_fast_mode_skip_debate` | fast 模式跳过辩论 | 跳过 debate 节点 |
| `test_deep_research_mode` | deep_research 模式 | 分歧>0.7时进入深度辩论 |
| `test_trace_id_propagation` | trace_id 全链路传递 | 所有节点输出包含相同 trace_id |

### 10.5 并行调度测试

| 测试项 | 调度源 | 内容 | 断言 |
|:-------|:-------|:-----|:-----|
| `test_all_sources_parallel` | chain+technical+fundamental+sentiment | 四源并行执行 | 四个数据源节点都被调用 |
| `test_two_sources_parallel` | chain+technical | 双源并行执行 | 仅两个数据源节点被调用 |
| `test_single_source` | chain | 单源执行 | 仅 chain 节点被调用 |
| `test_no_signal_early_exit` | 无信号 | 提前终止 | 在 P1 信号检查阶段终止 |

### 10.6 PostgreSQL 集成测试

| 测试项 | 内容 | 断言 |
|:-------|:-----|:-----|
| `test_pg_connection` | 连接池初始化 | 连接成功，健康检查通过 |
| `test_pg_schema_create` | Schema 创建 | 所有表和视图创建成功 |
| `test_pg_crud` | CRUD 操作 | 插入/查询/更新/删除正常 |
| `test_pg_transaction` | 事务提交/回滚 | 提交成功，回滚正确 |

### 10.7 测试运行命令

```bash
# LangGraph 全部测试
python -m pytest tests/fdt_langgraph/ -v

# 仅并行调度测试
python -m pytest tests/fdt_langgraph/test_parallel_dispatch.py -v

# PostgreSQL 集成测试
python -m pytest tests/fdt_langgraph/test_pg_integration.py -v

# 带覆盖率
python -m pytest tests/fdt_langgraph/ --cov=fdt_langgraph --cov=fdt_pg --cov-report=term-missing
```

### 10.8 测试统计（v9.6.5）

| 指标 | 数量 |
|:-----|:-----|
| 测试文件数 | 12 |
| 测试用例总数 | 623 (99 langgraph + 144 scripts + 43 D3解码控制 + 20 D6输出控制 + 21 D5记忆+D2工具 + 66 data_adapter/cleaning + 28 structured_data + 222 其他) |
| 测试通过率 | 100% |
| conftest.py mock | 重 I/O 操作 mock (PostgreSQL 连接/数据采集/Agent spawn) |
| LangGraph 节点覆盖率 | 96% (nodes.py) |
| State 覆盖率 | 100% (state.py) |
| 并行调度场景覆盖率 | 100% (4/4) |
| A/B 切换集成测试 (G55) | 18 用例 (test_integration_ab.py，v8.4.0+ 新增) |
| scripts/ 测试 | **474 用例** (test_scripts.py，覆盖 **68 模块**) |
| **D3 解码控制** | **43 用例** (test_decode_control.py，配置/结构化约束/内容安全/质量监控) |
| **D6 输出控制** | **20 用例** (test_output_control.py，质量度量/版本化/反馈/审计) |
| **D5 记忆+D2 工具** | **21 用例** (test_memory_tool_control.py，知识图谱/召回/清理/注册/熔断) |
| **G93-G96 迁移** | **16 用例** (TestDebateProtocolV2 5 + TestAgentRunner 4 + TestCoordinator 7)

### 10.9 实际测试结果（2026-07-16）

```
tests/fdt_langgraph/test_nodes.py ............................. 21 passed
tests/fdt_langgraph/test_parallel_dispatch.py .................. 9 passed
tests/fdt_langgraph/test_state.py .............................. 2 passed
tests/fdt_langgraph/test_e2e_integration.py ................... 18 passed
tests/fdt_langgraph/test_postgres_integration.py .............. 12 passed
tests/fdt_langgraph/test_benchmark_comparison.py .............. 10 passed
tests/fdt_langgraph/test_health.py ............................. 9 passed
tests/fdt_langgraph/test_integration_ab.py .................... 18 passed

================= 99 passed, 1 warning in 5.08s =================
```

> **conftest.py mock 策略说明（v8.3.0+）**：`conftest.py` 对重 I/O 操作进行了 mock，确保测试在无 PostgreSQL / 无数据源 / 无 Agent spawn 的环境下可独立运行：
> - PostgreSQL 连接池 mock（`fdt_pg.connection`）
> - 数据采集 mock（`scan_all` / `futures_data_core` 采集器）
> - Agent spawn mock（`debate_orchestrator` 子进程调用）
> - LangGraph Checkpointer mock（SQLite 内存替代）

## 验证器质量度量

Loop 质量完全取决于所连接的可验证信号质量。验证器本身也需要被度量。

### 核心指标

| 指标 | 定义 | 硬性目标 | 说明 |
|------|------|:--------:|------|
| **漏放率 (false pass)** | 验证器通过但实际错误的比例 | ≈0% | 安全性指标，必须接近零 |
| **误杀率 (false block)** | 验证器拦截但实际正确的比例 | <20% | 效率指标，过高浪费 Token |

### 度量方法

1. 影子模式运行时，人工抽查 N 轮验证结果
2. 统计：漏放数 / 总数、误杀数 / 总数
3. 漏放率不达标 → 升级验证档位（如 L2→L3）
4. 误杀率过高 → 优化验证规则、增加白名单

### 晋级门槛中的验证器质量

| 晋级 | 验证器要求 |
|------|------------|
| L1→L2 | 影子模式 ≥5 轮，分诊准确率 ≥90% |
| L2→L3 | 连续 ≥20 次人工审查零回退，漏放率 ≈0，人工干预率 <10% |
| 降级 | 出现安全事件，或人工干预率连续两周 >30% |

### P1角色矫正测试用例（v9.6.8）

| 用例ID | 测试对象 | 描述 | 验证方法 |
|:-------|:---------|:-----|:---------|
| TC-STATS-001 | `_build_pure_stats()` | 验证stats对象不含direction/total/grade字段 | 构造含direction/total/grade的mock record，断言stats中无这三个key |
| TC-STATS-002 | `_build_pure_stats()` | 验证缺失字段时的默认值合理性 | 传入空dict+None kline，断言rsi_14默认50、adx_14默认25、volume_ma20_ratio默认0 |
| TC-STATS-003 | `_calc_volume_ma20()` | 验证20日均量计算正确性 | 传入21根K线，断言结果为前20根volume的均值 |
| TC-GATE-001 | `select_triggers()` | 验证无stats记录被过滤 | 传入含无stats记录的all_ranked，断言passed为空 |
| TC-GATE-002 | `select_triggers()` | 验证K线不足20根被过滤 | 传入n_bars=15的记录，断言passed为空 |
| TC-GATE-003 | `select_triggers()` | 验证零成交零持仓被过滤 | 传入volume=0,oi=0的记录，断言passed为空 |
| TC-GATE-004 | `select_triggers()` | 验证有效记录保留且按成交量排序 | 传入多条有效记录，断证passed长度正确且按volume降序 |
| TC-AUDIT-001 | `node_judge_direction` audit | 验证aligned判定：闫判官bear + P1 bear = aligned | 构造对应state，断言audit.deviation=="aligned" |
| TC-AUDIT-002 | `node_judge_direction` audit | 验证diverged判定：闫判官bull + P1 bear = diverged | 构造对应state，断言audit.deviation=="diverged" |
| TC-AUDIT-003 | `node_judge_direction` audit | 验证无selected_symbols时audit为空dict | 传入空symbols列表，断言audit=={} |


### 经验库测试（Phase A/B）

| 测试文件 | 用例数 | 覆盖范围 |
|:--|:--:|:--|
| tests/experience/test_recorder.py | 17 | Schema 验证 + 记录写入 + 索引更新 + 幂等保护 |
| tests/experience/test_distiller.py | 13 | 聚类 + 差异提取 + 置信度 + 安全阀 + 端到端 |
| tests/experience/test_adapter.py | 10+ | 检索 + 合并 + 边界检查（Phase C） |


###### `quality_inspector.py` / `debate_quality_schema.py` 测试（v9.20.2 新增）

| 测试文件 | 用例数 | 覆盖范围 |
|:--|:--:|:--|
| tests/fdt_langgraph/test_quality_inspector.py | 11 | validate_verdict float置信度 / 中文置信度 / 无symbol / normalized结构 / 越界告警 / 空数据 / VERDICT_RULES Schema校验 |

### `single_symbol_report.py` 测试需求（v9.6.9+ 新增）

| 测试项 | 优先级 | 说明 |
|:-------|:-------|:-----|
| `_fmt()` 浮点数截断 | P1 | 验证各种数量级浮点数的格式化（>10000, >100, <100, None, 异常输入） |
| `_extract_agent_output()` 辩论论据提取 | P1 | 验证从 reducer list 中正确提取指定 Agent 标签内容 |
| `_extract_args_from_list()` 六阶段论据提取 | P1 | 验证 bull_v1/bear_v1/rebut/final 各阶段正确提取 |
| `generate()` 完整报告生成 | P1 | Mock state 数据，验证 HTML 输出包含所有预期章节 |
| P1/P2 跳过逻辑 | P2 | 验证 stats 为空时 P1 隐藏，judge_direction 为 neutral 时 P2 隐藏 |
| 风控阻断原因展示 | P2 | 验证 risk_check 从 state 根和 signal_output 子字段双重提取 |
| 报告头重复检测 | P2 | 验证 `_render_html` header 与自定义 header 不重复 |

**目标**：新增 `tests/langgraph/test_single_symbol_report.py`，覆盖上述 7 项，目标覆盖率 ≥80%。

## 一致性元数据

| 代码文件/函数 | 文档章节 | 关键断言/可验证事实 | 检验方式 |
|:--------------|:---------|:-------------------|:---------|
| `tests/fdt_langgraph/` (5 个测试文件) | §1 测试金字塔 | 包含 test_nodes / state / graph / agents / health | `ls tests/fdt_langgraph/test_*.py` |
| `tests/fdt-gate/test_quality_gate.py` | §1 门禁 | G1-G5 质量门禁 + 17 个测试用例 | `grep -n "def test_" tests/fdt-gate/test_quality_gate.py` |
| `tests/fdt_langgraph/test_evolution_graph.py` | §2.3 | 27+2 个测试 (含 graph.invoke None fallback) | `grep -c "def test_" tests/fdt_langgraph/test_evolution_graph.py` |
| `tests/fdt_langgraph/test_quality_inspector.py` | §2.3 | 11 个测试 (validate_verdict 兼容 float 置信度) | `grep -c "def test_" tests/fdt_langgraph/test_quality_inspector.py` |
| `tests/fdt_langgraph/test_reports.py` | §2.3 报告层 | 12 个测试 (P1/P3/P5/P6/P6a) | `grep -c "def test_" tests/fdt_langgraph/test_reports.py` |
| `tests/contracts/test_contracts.py` | §3 契约测试 | 9 个 JSON Schema 校验 | `grep -c "def test_" tests/contracts/test_contracts.py` |
| `docs/schemas/` | §3 | 9 个 JSON Schema (Draft 2020-12) | `ls docs/schemas/*.json` |
| `scripts/validate_agent_output.py` | §4 验证器 | 漏放率 ≤1% / 误杀率 ≤5% | `grep -n "leak\|misclassify\|漏放\|误杀"` |
| `tests/experience/` | §4 经验库 | recorder(17) / distiller(13) / adapter(10+) | `ls tests/experience/test_*.py` |
| `pyproject.toml` | 全局 | pytest 配置 (coverage / asyncio_mode) | `grep -A5 "\[tool.pytest" pyproject.toml` |
