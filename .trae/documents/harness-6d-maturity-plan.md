# Harness 六维控制空间成熟度提升 — 实施计划

> **计划版本**: v1.0 | **trace_id**: plan-harness-6d-20260723 | **目标成熟度**: ★★★→★★★★★
> **关联文档**: `01-architecture.md §5.2`, `08-gap-analysis.md`, `09-advancement-plan.md`, `10-coding-standards.md`

---

## 1. 当前状态摘要

### 1.1 六维真实成熟度

| 维度 | 当前 | 目标 | 核心差距 |
|:-----|:----:|:----:|:---------|
| D1 Context | ★★★☆☆ | ★★★★☆ | 批量全量注入，无渐进式披露，无新鲜度检查 |
| D2 Tool | ★★★★☆ | ★★★★★ | ToolRegistry 注册表存根，metrics 不反哺路由 |
| D3 Generation | ★★★☆☆ | ★★★★★ | JSON 手动解析绕过管线，孤儿配置，filter 未接入 |
| D4 Orchestration | ★★★★★ | ★★★★★ | 已达生产级，无需提升 |
| D5 Memory | ★★★★☆ | ★★★★★ | vector_memory 存在但未接入辩论上下文 |
| D6 Output | ★★★★☆ | ★★★★★ | OutputMetrics 评分逻辑偏简单，未成为硬约束 |

### 1.2 关键发现（代码实测）

| 编号 | 发现 | 严重度 |
|:-----|:------|:------:|
| F01 | `enforce_structured_output.py`(362行) 存在但 `nodes.py` 5 处解析全部绕过 | P0 |
| F02 | `content_filter.py`(264行) 仅在 `quality_inspector.py` import 但从未调用 | P0 |
| F03 | `decode_config.yaml` 中 `quality_assurance` 配置是孤儿——品藻不调 LLM | P1 |
| F04 | `_repair_json()` 仅被 2/5 的 LLM 解析处调用 | P1 |
| F05 | `vector_memory.query()` 存在(306行)但 `fdt_langgraph/` 内无一调用 | P1 |
| F06 | `tool_metrics.record_call()` → `detect_anomalies()` 链路完整但不影响路由 | P2 |
| F07 | `_build_debate_context()` 全量品种数据注入，无当前品种过滤 | P2 |

---

## 2. 实施计划

### Phase 1 — 补漏洞（P0/P1 优先）

#### G1: 品藻解码配置去孤儿化

| 项 | 内容 |
|:---|:------|
| **问题** | `decode_config.yaml` 中 `quality_assurance` 有 temperature/max_tokens 配置，但品藻的质检(`node_quality_inspect`)和报告(`node_report`)均为纯 Python 函数，不调 LLM。该配置是死配置 |
| **改动文件** | `config/agents/decode_config.yaml` |
| **改动内容** | 删除 `quality_assurance` 整个配置节（行 191-207） |
| **验证** | `grep -n "quality_assurance" config/agents/decode_config.yaml` 返回空 |
| **Harness 检查** | C03: 配置项变更 → 更新 `03-configuration.md` |

#### G2: 结构化输出接入 5 处 LLM 解析

| 项 | 内容 |
|:---|:------|
| **问题** | `scripts/enforce_structured_output.py`（362行，含 auto_fix_json / Pydantic校验 / JSON Schema校验 / 升温重试）已实现但未被调用。`nodes.py` 5 处各自写 `json.loads()`，重复且脆弱 |
| **改动文件** | `fdt_langgraph/nodes.py` |
| **改动内容** | 在文件顶部 import `from scripts.enforce_structured_output import enforce_structured_output`。替换以下 5 处 `"{" in output → json.loads` 为 `enforce_structured_output(output, agent_name=...)`： |
| | ① `node_judge_direction`（~L595-603）→ `agent_name="judge"` |
| | ② `node_technical`（~L1083-1088）→ `agent_name="technical_researcher"` |
| | ③ `node_fundamental`（~L1383-1388）→ `agent_name="fundamental_researcher"` |
| | ④ `node_verdict`（~L2363-2365）→ `agent_name="judge"` |
| | ⑤ `node_risk_check`（~L2490-2493）→ `agent_name="risk_manager"` |
| **非功能性** | 函数签名兼容：`enforce_structured_output` 返回 `{"success": bool, "data": dict, ...}`，现有代码需从 `result["data"]` 取值。需兼容回退路径（当 `success=False` 时走原 fallback） |
| **验证** | 运行 `pytest tests/fdt_langgraph/test_nodes.py -v` 测试节点函数（跳过需 API key 的 LLM 测试） |
| **Harness 检查** | C01: 数据流变更 → 更新 `01-architecture.md` §5.2 D3 Generation 描述 |

#### G3: ContentFilter 接入质检

| 项 | 内容 |
|:---|:------|
| **问题** | `scripts/content_filter.py`（264行）已实现敏感词/合规检测/脱敏，但仅在 `quality_inspector.py` L270 import 了 `ContentFilter`，从未构造实例调用 |
| **改动文件** | `fdt_langgraph/quality_inspector.py` |
| **改动内容** | 在 `validate_verdict()` 和 `validate_risk()` 末尾各追加一次 `ContentFilter().filter()` 调用，将 `has_sensitive` 或 `blocked` 结果追加到 `QualityReport.issues` |
| **具体** | `validate_verdict` 返回前：`cf = ContentFilter(); result = cf.filter(json.dumps(data)); if result["blocked"]: issues.append(...)` |
| **验证** | 运行 `pytest tests/fdt_langgraph/test_quality_inspector.py -v` |
| **Harness 检查** | C05: 新指标/日志 → 更新 `05-observability.md` |

---

### Phase 2 — 提质量（P1/P2）

#### G4: LLM 输出解析统一入口

| 项 | 内容 |
|:---|:------|
| **问题** | 5 处解析代码重复，`_repair_json` 仅 2/5 处调用，新增 Agent 时会再写第 6 份 |
| **改动文件** | `fdt_langgraph/llm_provider.py`（新增函数） |
| **改动内容** | 新增 `parse_llm_output(raw: str, agent_name: str = "") -> dict` 函数，封装 `enforce_structured_output` 调用。`nodes.py` 5 处从直接调 `enforce_structured_output` 改为调 `parse_llm_output` |
| **验证** | 同上 G2 测试 |
| **Harness 检查** | C05, C06 |

#### G5: Context 按品种过滤

| 项 | 内容 |
|:---|:------|
| **问题** | `_build_debate_context()` 全量注入所有品种数据，辩论 prompt 膨胀 |
| **改动文件** | `fdt_langgraph/nodes.py` |
| **改动内容** | `_build_debate_context()` 追加 `current_symbol: str` 参数，只过滤该品种的数据。调用处传入 `state["symbol_index"]` 对应的品种 |
| **验证** | 检查生成的 context 字符串只含目标品种数据 |
| **Harness 检查** | C01 |

#### G6: Vector Memory 接入辩论上下文

| 项 | 内容 |
|:---|:------|
| **问题** | `scripts/vector_memory.py` 的 `query()` 方法已实现三层记忆检索+强制负样本，但 `fdt_langgraph/` 无一处调用 |
| **改动文件** | `fdt_langgraph/nodes.py` — `_build_fdc_fundamental_context()` 内 |
| **改动内容** | 追加 vector_memory 查询：`from scripts.vector_memory import VectorMemory; vm = VectorMemory(); records = vm.query(current_symbol, top_k=3)`，将返回的历史模式注入 context 的 `【品种历史模式】` 区块 |
| **验证** | 检查 context 是否包含历史模式区块 |
| **Harness 检查** | C01 |

---

### Phase 3 — 建闭环

#### G7: ToolMetrics 反哺调度

| 项 | 内容 |
|:---|:------|
| **问题** | `tool_metrics.record_call()` → `get_tool_stats()` → `detect_anomalies()` 链路完整但数据仅写文件，不影响调度 |
| **改动文件** | `fdt_langgraph/master_nodes.py` — `node_dispatch()` |
| **改动内容** | 调度前读取 `ToolMetrics.get_tool_stats()`：若某源最近失败率 > 50% 则跳过，若平均耗时 > 200s 则提高超时 |
| **验证** | 模拟高失败率场景，确认调度跳过 |
| **Harness 检查** | C01, C04 |

#### G8: OutputMetrics 硬约束

| 项 | 内容 |
|:---|:------|
| **问题** | `OutputMetrics.score_output()` 评分 0-100 但只记录日志，不影响任何决策 |
| **改动文件** | `fdt_langgraph/quality_inspector.py` — `validate_verdict()` |
| **改动内容** | 追加 `OutputMetrics.score_output()` 调用：score < 60 追加 FAIL issue；score < 40 强制阻断（即使重试未超限） |
| **验证** | 用低分裁决测试阻断逻辑 |
| **Harness 检查** | C05, C06 |

---

## 3. 实施顺序与依赖

```
Phase 1 (1-2天)          Phase 2 (3-5天)          Phase 3 (1-2周)
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ G1 删孤儿配置    │     │ G4 统一解析入口   │     │ G7 Metrics反哺  │
│ 依赖：无         │     │ 依赖：G2已完成    │     │ 依赖：无        │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│ G2 接结构化输出   │     │ G5 Context过滤   │     │ G8 硬约束       │
│ 依赖：无         │     │ 依赖：无         │     │ 依赖：G3已完成   │
├─────────────────┤     ├─────────────────┤     └─────────────────┘
│ G3 接内容过滤    │     │ G6 Memory接入    │
│ 依赖：无         │     │ 依赖：无         │
└─────────────────┘     └─────────────────┘
```

所有 Phase 1 任务**无外部依赖**，可并行实施。

---

## 4. 文档更新清单

按 Harness C01-C13 规则，每次代码变更须同步更新以下文档：

| 文档 | 变更内容 | 对应 G |
|:-----|:---------|:------:|
| `01-architecture.md` §5.2 | D3 Generation 实现描述更新（接入 enforce_structured_output） | G2 |
| `01-architecture.md` §5.2 | D5 Memory 实现描述更新（接入 vector_memory） | G6 |
| `01-architecture.md` §5.2 | D2 Tool 实现描述更新（metrics 反哺调度） | G7 |
| `03-configuration.md` | 删除 quality_assurance 配置引用 | G1 |
| `05-observability.md` | ContentFilter / OutputMetrics 硬约束指标 | G3, G8 |
| `06-testing.md` | 新增用例数统计 | 全部 |
| `07-operations.md` | 版本号 bump | 全部 |
| `08-gap-analysis.md` | 登记新差距 G-6D-01 至 G-6D-08 | 全部 |
| `09-advancement-plan.md` | 更新成熟度评分 | 全部 |

---

## 5. 版本号

当前版本 **v9.22.0**。每完成一个 Phase，bump patch 版本：

- Phase 1 完成 → **v9.22.1**
- Phase 2 完成 → **v9.22.2**
- Phase 3 完成 → **v9.22.3**

---

## 6. 验证方法

| 检查项 | 方法 |
|:-------|:------|
| G1 验收 | `grep "quality_assurance" config/agents/decode_config.yaml` → 无匹配 |
| G2 验收 | `pytest tests/fdt_langgraph/test_nodes.py -v` → 非 LLM 测试全绿 |
| G3 验收 | `pytest tests/fdt_langgraph/test_quality_inspector.py -v` → 全绿 |
| G4 验收 | `grep -n "enforce_structured_output" fdt_langgraph/nodes.py` → 5 处调用 |
| G5 验收 | 构造含多品种的 state 调用 `_build_debate_context(state, current_symbol="RB")` → 输出仅含 RB |
| G6 验收 | `grep -n "vector_memory\|VectorMemory" fdt_langgraph/nodes.py` → 有调用 |
| G7 验收 | `grep -n "tool_metrics\|ToolMetrics" fdt_langgraph/master_nodes.py` → 有调用 |
| G8 验收 | `grep -n "output_metrics\|OutputMetrics" fdt_langgraph/quality_inspector.py` → 有调用 |
| pre-commit | `python scripts/pre_commit_harness_check.py` → 全部通过 |
| 全量测试 | `python run_all_tests.py` → 不新增失败用例 |

---

## 7. 关键假设与决策

| 假设/决策 | 说明 |
|:----------|:------|
| **只补不拆** | 不重构现有代码结构，只在现有函数内追加调用 |
| **兼容回退** | 所有 `enforce_structured_output` 调用保留 `success=False` 时的原 fallback 路径 |
| **不新增 Agent** | 不新增 Agent 角色，品藻配置直接删除而非改为真 LLM 调用 |
| **成熟度自评** | Phase 3 完成后各维度自评：D2/D3/D5/D6 各提升 1★，D1 提升 1★，D4 维持 5★ |
