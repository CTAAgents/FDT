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
├── commodity-chain/              # 产业链分析 (5个测试)
│   ├── conftest.py
│   ├── test_chains.py            # 链聚类/相关性
│   ├── test_config.py            # 配置加载
│   ├── test_debate.py            # 辩论接口
│   ├── test_risk.py              # 风控逻辑
│   └── test_screen.py            # 筛选逻辑
├── contracts/                    # 契约Schema (1个测试)
│   └── test_contracts.py         # 9个JSON Schema校验
├── debate-argument-builder/      # 辩论论点 (1个测试)
│   ├── conftest.py
│   └── test_debater.py           # 论据构建逻辑
├── debate-risk-manager/          # 风控引擎 (1个测试)
│   ├── conftest.py
│   └── test_risk_manager.py      # 6层风控
├── fdt-gate/                     # 质量门禁 (1个测试)
│   ├── conftest.py
│   └── test_quality_gate.py      # L1-L5鲁棒性防线
├── fundamental-data-collector/   # 基本面采集 (1个测试)
│   ├── conftest.py
│   └── test_collector.py         # 供需/库存/利润
├── quant-daily/                  # 量化日评 (5个测试)
│   ├── conftest.py
│   ├── test_auto_train_orchestrator.py  # ML训练
│   ├── test_coverage_boost.py           # 覆盖率补充
│   ├── test_debate_brief.py             # 辩论精选
│   ├── test_debate_history.py           # 历史反馈
│   └── test_quality_filter.py           # 研报过滤
└── technical-analysis/           # 技术分析 (1个测试)
    ├── conftest.py
    └── test_technical.py         # 支撑阻力/形态
├── memory/                        # 记忆写入 (9个测试)
│   ├── conftest.py
│   └── test_writer.py             # Journal/Index/Record 原子性+去重
├── pipeline/                      # 流水线 (10个测试，⚠️ G16: 5/10 失效)
│   ├── conftest.py
│   └── test_runner.py             # 6阶段主流程+失败不阻断+trace注入
├── scheduler/                     # 调度器 (10个测试)
│   ├── conftest.py
│   └── test_engine.py             # 触发器匹配+防重复
└── self-improve-enhanced/        # 自改进增强
    ├── conftest.py
    └── test_*.py
```

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
| contracts | ✅ | — | ✅ | — | — | 14 用例 (G14) |
| fdt-gate (L1-L5) | — | — | — | ✅ | — |
| pipeline (runner) | ✅ | ✅ | — | — | — | 10 用例 (⚠️ G16: 5/10 失效) |
| scheduler (engine) | ✅ | ✅ | — | — | — | 10 用例 (G6) |
| memory (writer/archiver) | ✅ | ✅ | — | — | — | 9 用例 (G8) |
| **validators** (v6.3.2 新增) | ✅ | — | — | — | — | **9 用例** (G19: V2/V3 增强 + select_triggers filter) |

> ⚠️ **2026-07-14 整顿**：原「43 用例全绿」声明曾因 v6.3.0 重构后 `tests/pipeline/test_runner.py` mock 重命名函数失配而失真（5/10 失败）。**该问题已于 2026-07-14 19:04 修复**，当前 pipeline 10/10 全绿。

### 8.2 测试执行命令（v5.7 更新）

```bash
# 全部 Harness 测试
python -m pytest tests/pipeline/ tests/scheduler/ tests/memory/ tests/contracts/ tests/validators/ -v --no-cov

# 带覆盖率（已扩展到全 skill）
python -m pytest tests/ --cov=skills --cov=pipeline --cov=scheduler --cov=scripts --cov-report=term-missing

# 仅门禁测试
python -m pytest tests/fdt-gate/ -v

# ViBench 回放
python scripts/run_benchmark.py --replay
```

## 9. 测试统计（G7 覆盖率扩展后）

| 指标 | v5.6 初始 | v5.7 最终 | 变化 |
|:-----|:--------:|:--------:|:----:|
| 测试文件数 | 23 | 26 | 当前实际 **24 文件 / 12 目录**（含 memory/pipeline/scheduler/self-improve-enhanced） |
| Harness 测试用例 | 0 | 43 | 原 43；**当前 pipeline 5/10 失效(G16)，全绿声明不成立** |
| 覆盖率范围 | quant-daily/signals | skills+pipeline+scheduler+scripts | 4x 扩展（`pyproject.toml` 已配置） |
| 测试目录数 | 8 | 11 | 当前实际 **12** |

## 10. LangGraph 并行节点测试策略 (v8.3.0+)

### 10.1 并行测试架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    LangGraph 并行测试体系                        │
├────────────────────┬────────────────────┬───────────────────────┤
│   节点单元测试      │   图集成测试        │   并行调度测试         │
├────────────────────┼────────────────────┼───────────────────────┤
│ node_scan          │ 全链路串行执行      │ 三源并行调度           │
│ node_chain         │ 条件分支路径        │ 双源并行调度           │
│ node_technical     │ 阶段状态流转        │ 单源调度               │
│ node_fundamental   │ trace_id 传递       │ 空调度（无信号）       │
│ node_merge_research│                     │                       │
│ node_debate        │                     │                       │
│ node_verdict       │                     │                       │
└────────────────────┴────────────────────┴───────────────────────┘
```

### 10.2 测试目录结构

```
tests/fdt_langgraph/
├── conftest.py                    # 测试配置 + mock 重 I/O 操作 (v8.3.0+)
├── test_nodes.py                  # 节点单元测试
├── test_parallel_dispatch.py      # 并行调度测试
├── test_state.py                  # 状态管理测试
├── test_e2e_integration.py        # 端到端集成测试
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
| `test_node_merge` | node_merge_research | 三源数据合并 | research_data 包含三类数据 |
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
| `test_all_sources_parallel` | chain+technical+fundamental | 三源并行执行 | 三个数据源节点都被调用 |
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

### 10.8 测试统计（v8.3.0+）

| 指标 | 数量 |
|:-----|:-----|
| 测试文件数 | 8 |
| 测试用例总数 | 99 |
| 测试通过率 | 100% (99/99) |
| conftest.py mock | 重 I/O 操作 mock (PostgreSQL 连接/数据采集/Agent spawn) |
| LangGraph 节点覆盖率 | 96% (nodes.py) |
| State 覆盖率 | 100% (state.py) |
| 并行调度场景覆盖率 | 100% (4/4) |
| A/B 切换集成测试 (G55) | 18 用例 (test_integration_ab.py，v8.4.0+ 新增) |

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
