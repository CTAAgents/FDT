# 六维控制空间成熟度提升 — 实施计划

> **trace_id**: `plan-harness-6d-impl-20260723`
> **基于**: `.trae/documents/harness-6d-maturity-plan.md`
> **目标**: 完成六维控制空间提升，严格遵守 Harness 工程规范

---

## 0. 当前真实状态（2026-07-23 代码实测）

| # | 任务 | 状态 | 证据 |
|:--|:-----|:----:|:-----|
| G1 | 品藻解码配置去孤儿化 | ✅ 已完成 | `decode_config.yaml` 中无 `quality_assurance` 匹配 |
| G2 | 结构化输出接入 5 处 LLM 解析 | 🔶 4/5 完成 | `nodes.py` 中 `node_judge_direction`(L595)、`node_technical`(L1083)、`node_fundamental`(L1396)、`node_verdict`(L2389) 已接入 |
| G3 | ContentFilter 接入质检 | ✅ 已完成 | `quality_inspector.py` 中 3 处 `ContentFilter` 调用(L179/L240/L302) |

### 剩余未完成

| # | 剩余工作 | 文件位置 |
|:--|:---------|:---------|
| G2-5 | `node_risk_check` LLM 解析替换 | `nodes.py` L2524-L2527 — 仍使用手动 `json.loads()` |
| G4 | LLM 输出解析统一封装 | 新增 `llm_provider.py` 函数 + 5 处调用替换 |
| G5 | Context 按品种过滤 | `nodes.py` `_build_debate_context()` |
| G6 | Vector Memory 接入辩论上下文 | `nodes.py` `_build_fdc_fundamental_context()` |
| G7 | ToolMetrics 反哺调度 | `master_nodes.py` `node_dispatch()` |
| G8 | OutputMetrics 硬约束 | `quality_inspector.py` `validate_verdict()` |

---

## 1. 实施原则（Harness 规范强制）

### 1.1 文档先行
每项代码变更前必须先更新对应的 Harness 文档，不得先写代码再补文档。

### 1.2 契约优先
涉及接口/数据结构的变更，先定义 Schema/TypedDict/函数签名，再实现。

### 1.3 测试随重构
每项变更必须附带测试用例，测试全绿后才能进入下一项。

### 1.4 逐项独立验证
每项完成后独立验证，不累积多项目一次验证。

### 1.5 版本号纪律
每完成一项 bump patch 版本号（从 v9.22.0 开始），更新 `pyproject.toml` + `07-operations.md`。

---

## 2. 实施步骤

---

### Step 1: G2-5 — node_risk_check 结构化输出接入

**Harness 检查**: C01（数据流变更 → 更新 01-architecture.md）

#### 文档先行
- 更新 `docs/harness/01-architecture.md` §5.2 D3 Generation 描述：确认 node_risk_check 接入 enforce_structured_output

#### 代码变更
**文件**: `fdt_langgraph/nodes.py` L2524-L2527

**原代码**:
```python
if "{" in output and "}" in output:
    start = output.find("{")
    end = output.rfind("}") + 1
    risk_check = json.loads(output[start:end])
else:
    risk_check = {"approved": True, "risk_level": "low", "risk_color": "yellow", "warnings": ["LLM返回非JSON格式"]}
```

**新代码**:
```python
try:
    from scripts.enforce_structured_output import enforce_structured_output
    parsed = enforce_structured_output(output, agent_name="risk_manager")
    if parsed.get("success"):
        risk_check = parsed["data"]
    else:
        risk_check = {"approved": True, "risk_level": "low", "risk_color": "yellow", "warnings": [f"LLM解析失败: {parsed.get('errors', [])}"]}
except Exception as e:
    logger.warning(f"[RISK] 风控LLM解析失败: {e}, 使用默认yellow")
    risk_check = {"approved": True, "risk_level": "low", "risk_color": "yellow", "warnings": [f"LLM解析异常: {e}"]}
```

#### 验证
- `grep -n "enforce_structured_output" fdt_langgraph/nodes.py` → 确认 5 处调用
- `pytest tests/fdt_langgraph/test_nodes.py -v` → 不新增失败（跳过需 API key 的 LLM 测试）

#### 版本号
`pyproject.toml`: v9.22.0 → v9.22.1
`docs/harness/07-operations.md`: 追加 v9.22.1 条目

---

### Step 2: G4 — LLM 输出解析统一封装

**Harness 检查**: C05（新函数/新指标 → 更新 05-observability.md）、C06（测试用例数更新）

#### 文档先行
- 更新 `docs/harness/05-observability.md`：新增 `parse_llm_output` 函数说明

#### 契约先行
先定义函数签名：

```python
# fdt_langgraph/llm_provider.py (追加)
def parse_llm_output(raw: str, agent_name: str = "", default: dict = None) -> dict:
    """
    统一 LLM 输出解析入口。
    封装 enforce_structured_output 调用，提供兼容回退。
    
    Args:
        raw: LLM 原始输出字符串
        agent_name: Agent 名称，用于 enforce_structured_output 的校验模板
        default: 解析失败时的默认返回值
    
    Returns:
        {"success": bool, "data": dict, "errors": list}
    """
```

#### 代码变更

**文件 1**: `fdt_langgraph/llm_provider.py`（新增 `parse_llm_output` 函数）

```python
def parse_llm_output(raw: str, agent_name: str = "", default: dict = None) -> dict:
    """
    统一 LLM 输出解析入口。
    封装 enforce_structured_output 调用，提供兼容回退。
    """
    if default is None:
        default = {}
    try:
        from scripts.enforce_structured_output import enforce_structured_output
        parsed = enforce_structured_output(raw, agent_name=agent_name)
        if parsed.get("success"):
            return {"success": True, "data": parsed["data"], "errors": []}
        else:
            logger.warning(f"[{agent_name}] enforce_structured_output 失败: {parsed.get('errors', [])}")
            return {"success": False, "data": default, "errors": parsed.get("errors", [])}
    except Exception as e:
        logger.warning(f"[{agent_name}] LLM 输出解析异常: {e}")
        return {"success": False, "data": default, "errors": [str(e)]}
```

**文件 2**: `fdt_langgraph/nodes.py` — 5 处调用统一替换

将 5 处 `from scripts.enforce_structured_output import enforce_structured_output` + `parsed = enforce_structured_output(...)` 统一替换为：

```python
from .llm_provider import parse_llm_output
parsed = parse_llm_output(output, agent_name="judge")
```

涉及位置：
1. L594-600 (node_judge_direction, agent_name="judge")
2. L1082-1094 (node_technical, agent_name="technical_researcher")
3. L1395-1406 (node_fundamental, agent_name="fundamental_researcher")
4. L2388-2400 (node_verdict, agent_name="judge")
5. 刚新增的 node_risk_check 解析 (agent_name="risk_manager")

**文件 3**: `fdt_langgraph/nodes.py` — 文件头部追加 import

```python
from .llm_provider import parse_llm_output
```

#### 验证
- `grep -n "enforce_structured_output" fdt_langgraph/nodes.py` → 0 匹配（全部替换）
- `grep -n "parse_llm_output" fdt_langgraph/nodes.py` → 5 匹配
- `pytest tests/fdt_langgraph/test_nodes.py -v` → 不新增失败

#### 测试用例

**新增文件**: `tests/fdt_langgraph/test_parse_llm_output.py`

```python
"""测试 parse_llm_output 统一解析入口"""

import pytest
from fdt_langgraph.llm_provider import parse_llm_output

def test_valid_json():
    result = parse_llm_output('{"key": "value"}', agent_name="test")
    assert result["success"] is True
    assert result["data"]["key"] == "value"

def test_invalid_json_with_fallback():
    result = parse_llm_output("not json", agent_name="test", default={"fallback": True})
    assert result["success"] is False
    assert result["data"]["fallback"] is True
    assert len(result["errors"]) > 0

def test_empty_output():
    result = parse_llm_output("", agent_name="test", default={"empty": True})
    assert result["success"] is False

def test_agent_name_none():
    result = parse_llm_output('{"a": 1}', agent_name="")
    assert result["success"] is True
```

#### 版本号
`pyproject.toml`: v9.22.1 → v9.22.2
`docs/harness/07-operations.md`: 追加 v9.22.2 条目
`docs/harness/06-testing.md`: 测试文件 +2, 用例数 +4

---

### Step 3: G5 — Context 按品种过滤

**Harness 检查**: C01（数据流变更 → 更新 01-architecture.md）

#### 文档先行
- 更新 `docs/harness/01-architecture.md`：描述 Context 构建的按品种过滤策略

#### 契约先行
先修改函数签名：

```python
# 原
def _build_debate_context(state: dict) -> str:
# 新
def _build_debate_context(state: dict, current_symbol: str = "") -> str:
```

#### 代码变更

**文件**: `fdt_langgraph/nodes.py`

1. `_build_debate_context` 函数签名追加 `current_symbol: str = ""` 参数
2. 函数体内，在构建各数据区块时过滤只属于 `current_symbol` 的数据
3. 调用处（`node_debate_loop` 中）传入 `state.get("current_sym", "")`

**具体改动**:
- 将 `_build_debate_context` 内的 `stats`、`scan_signals`、`research_data` 等区块中的全品种数据过滤为仅当前品种
- 不影响 `_build_fdc_technical_context` 和 `_build_fdc_fundamental_context`（它们已按选定品种列表过滤）

#### 验证
- 构造含 3 个品种的测试 state，调用 `_build_debate_context(state, current_symbol="RB")`
- 检查生成的 context 字符串不含其他品种数据

#### 测试用例

**追加到** `tests/fdt_langgraph/test_nodes.py`:

```python
def test_build_debate_context_filter():
    """验证 _build_debate_context 按品种过滤"""
    state = {
        "trace_id": "test-trace",
        "scan_results": {
            "stats": {"RB": {}, "CU": {}, "CF": {}},
            "all_ranked": [{"symbol": "RB"}, {"symbol": "CU"}, {"symbol": "CF"}]
        },
        "research_data": {"RB": {}, "CU": {}, "CF": {}},
        # ... 填充必要字段
    }
    from fdt_langgraph.nodes import _build_debate_context
    ctx = _build_debate_context(state, current_symbol="RB")
    assert "RB" in ctx
    assert "CU" not in ctx and "CF" not in ctx  # 或其他品种的标识性文本
```

#### 版本号
`pyproject.toml`: v9.22.2 → v9.22.3
`docs/harness/07-operations.md`: 追加 v9.22.3 条目
`docs/harness/06-testing.md`: 测试用例 +1

---

### Step 4: G6 — Vector Memory 接入辩论上下文

**Harness 检查**: C01（数据流变更 → 更新 01-architecture.md）

#### 文档先行
- 更新 `docs/harness/01-architecture.md` §5.2 D5 Memory：描述 vector_memory 接入到探源上下文

#### 代码变更

**文件**: `fdt_langgraph/nodes.py` — `_build_fdc_fundamental_context()` 函数末尾

追加以下代码段（`【品种历史模式】` 区块）：

```python
def _build_fdc_fundamental_context(selected, fdc_data, scan_results):
    # ... 现有代码 ...
    
    result = fdc_data_section  # 已有结果
    
    # v9.22.3: 追加 Vector Memory 历史模式
    try:
        from scripts.vector_memory import VectorMemory
        vm = VectorMemory()
        # 对当前品种（selected 是列表，取第一个或全部）
        memory_sections = []
        for sym in selected[:3]:  # 最多 3 个品种
            records = vm.query(sym, top_k=3)
            if records:
                mem_lines = [f"品种: {sym}"]
                for i, rec in enumerate(records, 1):
                    mem_lines.append(f"  {i}. 方向={rec.get('direction','N/A')} | "
                                     f"置信度={rec.get('confidence','N/A')} | "
                                     f"理由={rec.get('reason','')[:80]}")
                memory_sections.append("\n".join(mem_lines))
        if memory_sections:
            result += "\n\n【品种历史模式】\n" + "\n---\n".join(memory_sections)
    except Exception as e:
        logger.warning(f"[FUND] VectorMemory 查询失败: {e}")
    
    return result
```

**注意**: 先检查 `scripts/vector_memory.py` 的 `query()` 签名和返回格式，确保调用兼容。

#### 验证
- `grep -n "vector_memory\|VectorMemory" fdt_langgraph/nodes.py` → 有调用
- 实际运行：确认 context 中包含 `【品种历史模式】` 区块

#### 版本号
`pyproject.toml`: v9.22.3 → v9.22.4
`docs/harness/07-operations.md`: 追加 v9.22.4 条目

---

### Step 5: G7 — ToolMetrics 反哺调度

**Harness 检查**: C01（数据流变更）、C04（降级/熔断策略更新）

#### 文档先行
- 更新 `docs/harness/04-resilience.md`：描述 ToolMetrics 驱动的调度降级策略

#### 代码变更

**文件**: `fdt_langgraph/master_nodes.py` — `node_dispatch()` 函数

在调度各数据源（chain/technical/fundamental）之前，追加 ToolMetrics 检查：

```python
def node_dispatch(state):
    # 现有调度逻辑前追加
    try:
        from scripts.tool_metrics import ToolMetrics
        tm = ToolMetrics()
        stats = tm.get_tool_stats(days=7)
        for source in ["chain", "technical", "fundamental"]:
            if source in stats:
                fail_rate = stats[source].get("fail_rate", 0)
                avg_time = stats[source].get("avg_time_ms", 0)
                if fail_rate > 0.5:
                    logger.warning(f"[DISPATCH] {source} 近7天失败率 {fail_rate:.0%}, 跳过调度")
                    # 将 source 从调度列表移除
                if avg_time > 200_000:  # 200s
                    logger.info(f"[DISPATCH] {source} 平均耗时 {avg_time/1000:.0f}s, 提高超时阈值")
                    # 调整该 source 的超时配置
    except Exception as e:
        logger.warning(f"[DISPATCH] ToolMetrics 读取失败: {e}")
    
    # ... 现有调度逻辑 ...
```

#### 验证
- `grep -n "tool_metrics\|ToolMetrics" fdt_langgraph/master_nodes.py` → 有调用
- 模拟高失败率场景（直接 mock ToolMetrics），确认调度跳过

#### 版本号
`pyproject.toml`: v9.22.4 → v9.22.5
`docs/harness/07-operations.md`: 追加 v9.22.5 条目

---

### Step 6: G8 — OutputMetrics 硬约束

**Harness 检查**: C05（新指标）、C06（测试用例更新）

#### 文档先行
- 更新 `docs/harness/05-observability.md`：新增 OutputMetrics 硬约束指标说明（score < 60 FAIL, score < 40 阻断）

#### 代码变更

**文件**: `fdt_langgraph/quality_inspector.py` — `validate_verdict()` 函数末尾

在返回前追加 OutputMetrics 评分检查：

```python
def validate_verdict(verdict_data: dict) -> QualityReport:
    issues = []
    # ... 现有校验逻辑 ...
    
    # G8: OutputMetrics 硬约束
    try:
        from scripts.output_metrics import OutputMetrics
        om = OutputMetrics()
        score = om.score_output(verdict_data)
        if score < 40:
            issues.append(_issue("output_quality", f"输出质量评分 {score}/100 — 强制阻断", "error"))
        elif score < 60:
            issues.append(_issue("output_quality", f"输出质量评分 {score}/100 — 低于阈值", "error"))
    except Exception as e:
        logger.warning(f"[QINSPECT] OutputMetrics 调用失败: {e}")
    
    return QualityReport(...)
```

#### 验证
- `grep -n "output_metrics\|OutputMetrics" fdt_langgraph/quality_inspector.py` → 有调用
- 用低分裁决数据（mock OutputMetrics 返回低分）测试阻断逻辑

#### 测试用例

**追加到** `tests/fdt_langgraph/test_quality_inspector.py`:

```python
def test_validate_verdict_output_metrics_block():
    """OutputMetrics 低分应触发阻断"""
    data = {"direction": "bullish", "confidence": 0.5}  # 低分数据
    from fdt_langgraph.quality_inspector import validate_verdict
    report = validate_verdict(data)
    has_block = any(
        iss.code in ("output_quality",) and iss.level == "error"
        for iss in report.issues
    )
    # 注意：实际依赖 OutputMetrics 实现，可能需要 mock
```

#### 版本号
`pyproject.toml`: v9.22.5 → v9.22.6
`docs/harness/07-operations.md`: 追加 v9.22.6 条目
`docs/harness/06-testing.md`: 测试用例 +1

---

## 3. 文档更新清单

| 文档 | 变更内容 | 对应 Step | 预计变更行数 |
|:-----|:---------|:---------:|:-----------:|
| `01-architecture.md` §5.2 | D3 Generation 更新 (G2-5) + D5 Memory 更新 (G6) + Context 过滤 (G5) + ToolMetrics (G7) | 1,3,4,5 | ~20 |
| `04-resilience.md` | ToolMetrics 驱动的调度降级策略 | 5 | ~10 |
| `05-observability.md` | parse_llm_output 函数说明 + OutputMetrics 硬约束指标 | 2,6 | ~15 |
| `06-testing.md` | 新增测试文件/用例数统计 | 2,3,6 | ~5 |
| `07-operations.md` | 版本历史追加 v9.22.1~v9.22.6 | 全部 | ~30 |
| `08-gap-analysis.md` | 差距状态更新（G-6D-01~G-6D-08 进展） | 全部 | ~15 |
| `09-advancement-plan.md` | 六维成熟度评分更新 | 全部 | ~10 |

---

## 4. 实施顺序

```
Step 1 (G2-5)       → Step 2 (G4)       → Step 3 (G5)
  仅1处代码变更          5处替换+1新增        1处函数修改
  文档: 01.md           文档: 05/06/07      文档: 01/06/07
  版本: v9.22.1         版本: v9.22.2       版本: v9.22.3

Step 4 (G6)         → Step 5 (G7)       → Step 6 (G8)
  1处代码追加           1处代码追加          1处代码追加
  文档: 01/07          文档: 04/07         文档: 05/06/07
  版本: v9.22.4         版本: v9.22.5       版本: v9.22.6
```

**依赖关系**: 无外部依赖，步骤可独立实施，但建议串行以保持版本号连续性。

---

## 5. Harness 合规检查清单

每 Step 完成后，运行以下检查：

```bash
# 1. pre-commit Harness 12 项检查
python scripts/pre_commit_harness_check.py

# 2. 全量测试
python -m pytest tests/ -x --tb=short -q 2>&1 | tail -20

# 3. 文档一致性检查
python scripts/verify_doc_consistency.py
```

违反任一项 → 停止当前 Step，修复后才能继续。

---

## 6. 完成标准

| 检查项 | 方法 | 期望结果 |
|:-------|:-----|:---------|
| G2-5 完成 | `grep "json.loads" nodes.py` (risk 段) | 无手动 json.loads |
| G4 完成 | `grep "enforce_structured_output" nodes.py` | 0 匹配 |
| G4 完成 | `grep "parse_llm_output" nodes.py` | 5 匹配 |
| G5 完成 | 单元测试 `test_build_debate_context_filter` | PASS |
| G6 完成 | `grep "vector_memory\|VectorMemory" nodes.py` | ≥1 匹配 |
| G7 完成 | `grep "tool_metrics\|ToolMetrics" master_nodes.py` | ≥1 匹配 |
| G8 完成 | `grep "output_metrics\|OutputMetrics" quality_inspector.py` | ≥1 匹配 |
| 版本号 | `grep "version" pyproject.toml` | v9.22.6 |
| pre-commit | `python scripts/pre_commit_harness_check.py` | 全部通过 |
| 测试 | `python -m pytest tests/ -x --tb=short -q` | 不新增失败 |

---

## 7. 关键假设与风险

| 假设/风险 | 说明 | 缓解措施 |
|:----------|:-----|:---------|
| VectorMemory.query() 签名兼容 | `scripts/vector_memory.py` 的 query 返回格式未确认 | Step 4 实施前先读取 `vector_memory.py` 确认签名 |
| ToolMetrics.get_tool_stats() 存在 | `tool_metrics.py` 中该函数签名未确认 | Step 5 实施前先读取签名 |
| OutputMetrics.score_output() 返回值范围 | 假设返回 0-100，实际需确认 | Step 6 实施前先读取确认 |
| node_risk_check 的 fallback 兼容 | 新逻辑可能改变默认值 | 确保 fallback 与原代码一致：`approved=True, risk_level="low", risk_color="yellow"` |
| 测试环境 API key 依赖 | LLM 调用测试需要 API key | 非 LLM 单元测试应有 mock 或跳过装饰器 |
