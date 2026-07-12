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
| pipeline (runner) | ✅ | ✅ | — | — | — | 10 用例 (G5) |
| scheduler (engine) | ✅ | ✅ | — | — | — | 10 用例 (G6) |
| memory (writer/archiver) | ✅ | ✅ | — | — | — | 9 用例 (G8) |

> ✅ 全部补齐，43 用例全绿。2026-07-10 完成。

### 8.2 测试执行命令（v5.7 更新）

```bash
# 全部 Harness 测试
python -m pytest tests/pipeline/ tests/scheduler/ tests/memory/ tests/contracts/ -v --no-cov

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
| 测试文件数 | 23 | 26 | +3 (pipeline/scheduler/memory) |
| Harness 测试用例 | 0 | 43 | +43 |
| 覆盖率范围 | quant-daily/signals | skills+pipeline+scheduler+scripts | 4x 扩展 |
| 测试目录数 | 8 | 11 | +3 |
