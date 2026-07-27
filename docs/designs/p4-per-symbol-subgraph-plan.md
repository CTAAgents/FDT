# P4 逐品种辩论循环 → LangGraph 子图重构计划

> 创建: 2026-07-26 | 目标版本: v0.13.0
> 关联: `fdt_langgraph/graph.py`, `fdt_langgraph/nodes.py`, `fdt_langgraph/state.py`
> 参考: evolution_graph.py 已有子图模式

---

## 1. 当前状态分析

### 1.1 主图现状

当前 `_register_per_symbol_loop()` 将**全部 23 个节点**注册在同一个 `StateGraph(DebateState)` 中：

```
scan → freshness_gate ──┬── [ALL_STALE] aggregate_results ─→ report → signal_output
                        └── [PASS] judge_direction ─→
                            
                            prepare_one_symbol
                              ├──→ chain
                              ├──→ technical    ← fan-out
                              ├──→ fundamental
                              └──→ sentiment
                              ↓
                            merge_research
                              ├── [fast 模式] verdict
                              └── [辩论模式] bullish_v1 → bearish_v1
                                              → bearish_rebuttal → bullish_rebuttal
                                              → bear_final → bull_final
                                              → verdict
                              ↓
                            right_side_check → risk_check → quality_inspect
                              ├── [FAIL+重试<2] → prepare_one_symbol (重修)
                              ├── [PASS] → store_per_symbol_result
                              │              ├── [还有品种] → prepare_one_symbol (下一品种)
                              │              └── [全部完成] → aggregate_results
                              └── [G19跳过] → aggregate_results
                            
                            aggregate_results → report → signal_output → END
```

### 1.2 问题

| 问题 | 影响 |
|:-----|:-----|
| **主图 23 个节点难以理解** | 新开发者需要理解全部节点关系才能修改任一部分 |
| **P4 循环与 P0/P1/P6 耦合在同一图中** | 修改循环逻辑（如增加质检通过条件）可能意外影响 report/signal 路径 |
| **`_register_direct_debate_loop()` 重复了几乎相同逻辑** | 20+ 行节点注册和 30+ 行边注册完全重复 |
| **无法单独测试 P4 循环** | 必须通过完整辩论流程，涉及 scan/freshness/external API |
| **mode 参数传递笨拙** | 通过函数参数 `_register_per_symbol_loop(graph, mode)` 注入，运行时不可变 |

---

## 2. 新架构：子图提取

### 2.1 边界划分

```
┌─────────────────────────────────────────────────────────────────┐
│                     主图 (debate_graph)                          │
│                                                                 │
│  scan → freshness_gate → judge_direction ──→                    │
│                                              │                  │
│                                    ┌─────────▼──────────┐       │
│                                    │ per_symbol_subgraph │       │
│                                    │  (StateGraph)       │       │
│                                    │                     │       │
│                                    │  prepare_one_symbol │       │
│                                    │  → P3 fan-out       │       │
│                                    │  → debate 6 节点    │       │
│                                    │  → verdict → risk   │       │
│                                    │  → quality → route  │       │
│                                    │  ↔ (循环直到全部)    │       │
│                                    │  → aggregate_results│       │
│                                    └─────────┬──────────┘       │
│                                              │                  │
│                                    aggregate_results            │
│                                              │                  │
│                                    report → signal_output → END │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 子图接口

```
/* 使用相同的 DebateState TypedDict */

输入:    state.selected_symbols = ["RB", "CU", "IF"]   // 待辩论品种列表
        state._original_symbols = ["RB", "CU", "IF"]   // 完整品种列表
        state.symbol_index = 0                          // 从第一个开始
        state.fdc_data = {...}                          // 已预采集的数据
        state.mode = "default"                          // 运行模式

输出:   state.per_symbol_results = {                    // 逐品种结果
            "RB": {verdict, risk, research, debate...},
            "CU": {verdict, risk, research, debate...},
            "IF": {verdict, risk, research, debate...},
        }
        state.verdict = combined_verdict                // 汇聚后裁决
        state.risk_check = combined_risk                // 汇聚后风控
        state.symbol_index >= len(selected_symbols)     // 全部完成

入口:   "prepare_one_symbol"
出口:   "aggregate_results"                             // 全部品种完成
        "G19_skip"                                      // 无有效品种跳过
```

### 2.3 子图内部节点

从主图移入子图的节点清单（**16 个节点**）：

| 类别 | 节点 | 函数 | 说明 |
|:-----|:-----|:-----|:-----|
| 数据准备 | `prepare_one_symbol` | `node_prepare_one_symbol` | 按 index 准备单个品种 |
| P3 四源 | `chain`, `technical`, `fundamental`, `sentiment` | `node_*` | 并行分析，fan-out |
| P3 汇聚 | `merge_research` | `node_merge_research` | 合并四源数据 |
| 辩论 6 节点 | `bullish_v1` → `bearish_v1` → `bearish_rebuttal` → `bullish_rebuttal` → `bear_final` → `bull_final` | `node_*` | 六阶段攻防 |
| 裁决 | `verdict` + `right_side_check` + `risk_check` | `node_*` | 终裁 + G98 + 风控 |
| 质检 | `quality_inspect` | `node_quality_inspect` | Schema 校验 |
| 存储/路由 | `store_per_symbol_result` | `node_store_per_symbol_result` | 存入结果 |
| 汇聚 | `aggregate_results` | `node_aggregate_results` | 全部完成后汇聚 |

留在主图的节点（**7 个节点**）：

| 节点 | 说明 |
|:-----|:-----|
| `scan` | P1 数技源扫描 |
| `freshness_gate` | P0b 新鲜度闸门 |
| `judge_direction` | P2 初判 |
| `report` | P6 报告生成 |
| `signal_output` | P6a CTP 信号 |
| `load_cache` | 直接辩论模式入口 |
| `update_cache` | 辩论后缓存更新 |

---

## 3. 实施步骤

### Phase 1: 创建子图模块（〈 1 天）

**新建文件**: `fdt_langgraph/per_symbol_graph.py`

```python
"""P4 逐品种辩论子图 — 从主图提取的独立 LangGraph 子图。

封装一个或多个品种的完整辩论流程（prepare_one_symbol → P3 → debate
→ verdict → risk → quality → aggregate_results），
可独立编译、独立测试、嵌入主图作为单节点。
"""

import logging
from langgraph.graph import END, StateGraph
from fdt_langgraph.state import DebateState

# 从 graph.py 导入所需的路由函数
from fdt_langgraph.graph import (
    _get_current_symbol,
    _get_p3_node_names,
    _should_skip_p3_source,
    route_after_merge_research,
    route_after_quality_inspect,
)
from fdt_langgraph.nodes import (
    node_prepare_one_symbol,
    node_chain, node_technical, node_fundamental, node_sentiment,
    node_merge_research,
    node_bullish_v1, node_bearish_v1,
    node_bearish_rebuttal, node_bullish_rebuttal,
    node_bear_final, node_bull_final,
    node_verdict, node_right_side_check, node_risk_check,
    node_quality_inspect, node_store_per_symbol_result,
    node_route_next_symbol, node_aggregate_results,
)

logger = logging.getLogger(__name__)


def _route_after_aggregate(state: DebateState) -> str:
    """子图出口路由：全部完成 → 正常退出；异常 → G19 跳过。"""
    symbols = state.get("_original_symbols", [])
    idx = state.get("symbol_index", 0)
    if idx >= len(symbols) or not symbols:
        return "__end__"   # 子图标准出口
    # 正常情况下 node_route_next_symbol 已处理完所有品种
    # 此路由仅作为保底
    return "__end__"


def build_per_symbol_subgraph(mode: str = "default") -> StateGraph:
    """构建逐品种辩论子图。

    Args:
        mode: 运行模式（影响 P3 源的选择）

    Returns:
        编译好的 StateGraph，可嵌入主图或独立运行。

    子图内部路由:
        prepare_one_symbol
          → [chain/tech/fund/sent] (fan-out)
          → merge_research
          → [fast] verdict / [debate] 6 辩论节点
          → verdict → right_side_check → risk_check → quality_inspect
          → [FAIL+重试<2] → prepare_one_symbol (重修)
          → [PASS] → store_per_symbol_result
            → [还有品种] → prepare_one_symbol (下一品种)
            → [全部完成] → aggregate_results → END
    """
    graph = StateGraph(DebateState)

    # ── 注册 16 个节点 ──
    graph.add_node("prepare_one_symbol", node_prepare_one_symbol)
    graph.add_node("chain", node_chain)
    graph.add_node("technical", node_technical)
    graph.add_node("fundamental", node_fundamental)
    graph.add_node("sentiment", node_sentiment)
    graph.add_node("merge_research", node_merge_research)
    graph.add_node("bullish_v1", node_bullish_v1)
    graph.add_node("bearish_v1", node_bearish_v1)
    graph.add_node("bearish_rebuttal", node_bearish_rebuttal)
    graph.add_node("bullish_rebuttal", node_bullish_rebuttal)
    graph.add_node("bear_final", node_bear_final)
    graph.add_node("bull_final", node_bull_final)
    graph.add_node("verdict", node_verdict)
    graph.add_node("right_side_check", node_right_side_check)
    graph.add_node("risk_check", node_risk_check)
    graph.add_node("quality_inspect", node_quality_inspect)
    graph.add_node("store_per_symbol_result", node_store_per_symbol_result)
    graph.add_node("aggregate_results", node_aggregate_results)

    graph.set_entry_point("prepare_one_symbol")
    graph.set_finish_point("aggregate_results")

    # ── P3 四源并行 ──
    p3_nodes = _get_p3_node_names(mode)
    for node_name in p3_nodes:
        graph.add_edge("prepare_one_symbol", node_name)
        graph.add_edge(node_name, "merge_research")

    # ── 辩论链条 ──
    graph.add_conditional_edges("merge_research", route_after_merge_research, {
        "bullish_v1": "bullish_v1",
        "verdict": "verdict",  # fast 模式跳过辩论
    })
    graph.add_conditional_edges("bullish_v1", lambda s: "bearish_v1", {"bearish_v1": "bearish_v1"})
    graph.add_conditional_edges("bearish_v1", lambda s: "bearish_rebuttal", {"bearish_rebuttal": "bearish_rebuttal"})
    graph.add_conditional_edges("bearish_rebuttal", lambda s: "bullish_rebuttal", {"bullish_rebuttal": "bullish_rebuttal"})
    graph.add_conditional_edges("bullish_rebuttal", lambda s: "bear_final", {"bear_final": "bear_final"})
    graph.add_conditional_edges("bear_final", lambda s: "bull_final", {"bull_final": "bull_final"})
    graph.add_conditional_edges("bull_final", lambda s: "verdict", {"verdict": "verdict"})

    # ── 裁决 + 风控 + 质检 ──
    graph.add_edge("verdict", "right_side_check")
    graph.add_edge("right_side_check", "risk_check")
    graph.add_edge("risk_check", "quality_inspect")

    # ── 质检路由：重修 / 存储 / 跳过 ──
    graph.add_conditional_edges("quality_inspect", route_after_quality_inspect, {
        "prepare_one_symbol": "prepare_one_symbol",
        "store_per_symbol_result": "store_per_symbol_result",
        "aggregate_results": "aggregate_results",
    })

    # ── 品种循环路由 ──
    graph.add_conditional_edges("store_per_symbol_result", node_route_next_symbol, {
        "prepare_one_symbol": "prepare_one_symbol",
        "aggregate_results": "aggregate_results",
    })

    return graph.compile()
```

### Phase 2: 简化主图（0.5 天）

**修改文件**: `fdt_langgraph/graph.py`

**目标**: 将原来 200+ 行的 `_register_per_symbol_loop` 和 `_register_direct_debate_loop` 合并为约 50 行。

**变更要点**:

```python
# graph.py 新增导入
from fdt_langgraph.per_symbol_graph import build_per_symbol_subgraph

# _register_per_symbol_loop → 替换为 _register_debate_graph
def _register_debate_graph(graph: StateGraph, mode: str) -> None:
    """注册辩论主图（含子图节点）。"""

    # ── 前置节点（7 个） ──
    graph.add_node("scan", node_scan)
    graph.add_node("freshness_gate", node_freshness_gate)
    graph.add_node("judge_direction", node_judge_direction)

    # ── P4 逐品种辩论子图（1 个节点替代原来 16 个节点 + 全部边） ──
    per_symbol_subgraph = build_per_symbol_subgraph(mode)
    graph.add_node("per_symbol_debate", per_symbol_subgraph)

    # ── 后置节点（3 个） ──
    graph.add_node("aggregate_results", node_aggregate_results)
    graph.add_node("report", node_report)
    graph.add_node("signal_output", node_signal_output)

    # ── 入口边 ──
    graph.set_entry_point("scan")
    graph.add_edge("scan", "freshness_gate")
    graph.add_conditional_edges("freshness_gate", _route_after_freshness, {
        "judge_direction": "judge_direction",
        "aggregate_results": "aggregate_results",
    })
    graph.add_edge("judge_direction", "per_symbol_debate")
    graph.add_edge("per_symbol_debate", "aggregate_results")
    graph.add_edge("aggregate_results", "report")
    graph.add_edge("report", "signal_output")
    graph.add_edge("signal_output", END)


def _register_direct_debate_graph(graph: StateGraph, mode: str) -> None:
    """直接辩论模式（跳过 scan，从 load_cache 进入）。"""
    graph.add_node("load_cache", node_load_cache)
    graph.add_node("update_cache", node_update_cache)

    per_symbol_subgraph = build_per_symbol_subgraph(mode)
    graph.add_node("per_symbol_debate", per_symbol_subgraph)

    graph.add_node("aggregate_results", node_aggregate_results)
    graph.add_node("report", node_report)
    graph.add_node("signal_output", node_signal_output)

    graph.set_entry_point("load_cache")
    graph.add_edge("load_cache", "judge_direction")
    graph.add_edge("judge_direction", "per_symbol_debate")
    graph.add_edge("per_symbol_debate", "aggregate_results")
    graph.add_edge("aggregate_results", "report")
    graph.add_edge("report", "signal_output")
    graph.add_edge("signal_output", "update_cache")
    graph.add_edge("update_cache", END)
```

### Phase 3: 更新 nodes.py 导出（0.1 天）

**修改文件**: `fdt_langgraph/nodes.py`

移除已移入子图的函数导出（如果外部没有引用），或保留别名。

```python
# nodes.py — 子图内节点继续从这里导出（保持向后兼容）
# 新增子图导出
from fdt_langgraph.per_symbol_graph import build_per_symbol_subgraph
```

### Phase 4: 更新所有调用方（0.3 天）

搜索所有 `build_debate_graph` 和 `build_debate_graph_no_checkpoint` 的调用处，确保新子图路径正确：

```bash
grep -rn "build_debate_graph\|_register_per_symbol_loop\|_register_direct_debate_loop" fdt_langgraph/ scripts/ tests/
```

---

## 4. 测试策略

### 4.1 子图独立测试

**新建文件**: `tests/fdt_langgraph/test_per_symbol_subgraph.py`

| 测试用例 | 验证点 |
|:---------|:-------|
| `test_single_symbol` | 1 个品种正常通过辩论全程，per_symbol_results 含 1 条记录 |
| `test_three_symbols` | 3 个品种全部完成，per_symbol_results 含 3 条记录 |
| `test_zero_symbols` | 空品种列表 → 直接到 aggregate_results，无辩论执行 |
| `test_quality_fail_retry` | 质检 FAIL → 重修 1 次后再通过 |
| `test_quality_fail_exhausted` | 质检 FAIL 2 次耗尽 → 跳过，不阻塞其他品种 |
| `test_fast_mode` | mode=fast → 跳过辩论 6 节点，直接 verdict |
| `test_g19_skip` | 全部品种质检 FAIL → G19 跳过整个子图 |

### 4.2 主图集成测试

**修改文件**: `tests/fdt_langgraph/test_graph.py`

| 测试用例 | 验证点 |
|:---------|:-------|
| `test_full_pipeline` | scan → freshness → judge → subgraph → report → signal 完整链路 |
| `test_direct_debate` | load_cache → judge → subgraph → report → update_cache 链路 |
| `test_freshness_gate_d06` | 新鲜度 FAIL → 绕过子图直接到 aggregate_results |

### 4.3 输出等价性测试

**核心验证**: 子图重构前后输出是否一致。

```python
# 使用 mock 数据分别运行旧图和子图，比较 verdict 输出
old_result = old_graph.invoke(mock_state)
new_result = new_graph.invoke(mock_state)
assert old_result["verdict"] == new_result["verdict"]
```

---

## 5. 迁移与回滚计划

### 5.1 部署步骤

```
Step 1: 创建 per_symbol_graph.py + 测试文件
Step 2: 在 graph.py 中注册新函数 _register_debate_graph()
Step 3: 添加环境变量开关 FDT_USE_PER_SYMBOL_SUBGRAPH=true/false
Step 4: 默认 false（旧代码），CI 中 true 跑全量测试
Step 5: 验证通过后默认 true
Step 6: 删除旧代码和开关
```

### 5.2 A/B 开关

```python
# graph.py
_USE_SUBGRAPH = os.environ.get("FDT_USE_PER_SYMBOL_SUBGRAPH", "false").lower() == "true"

def _register_per_symbol_loop(graph, mode):
    if _USE_SUBGRAPH:
        return _register_debate_graph(graph, mode)
    # ... 旧代码（保留）
```

### 5.3 回滚

```bash
# 回滚到无子图模式
export FDT_USE_PER_SYMBOL_SUBGRAPH=false
# 或 git 回退
git revert <commit-hash>
```

---

## 6. 工作量与优先级

| 阶段 | 内容 | 预计工时 | 风险 | 收益 |
|:-----|:-----|:--------|:-----|:-----|
| **Phase 1** | 创建子图模块 | ~3h | 低 | 独立测试能力 |
| **Phase 2** | 简化主图 | ~1.5h | 中 | 主图节点从 23→10（-56%） |
| **Phase 3** | 更新 nodes.py | ~0.5h | 低 | 干净导出 |
| **Phase 4** | 更新调用方 | ~1h | 低 | 兼容保障 |
| **测试** | 子图+集成+等价性 | ~3h | 低 | 质量保障 |
| **迁移** | A/B 开关+验证 | ~1h | 低 | 安全切换 |

**总计**: ~10 小时（1.5 天），风险低，收益明确。

---

## 7. 不做的优化（保持简单）

- ❌ **不做** `PerSymbolState` 新 TypedDict：直接复用 `DebateState`，减少类型兼容工作量
- ❌ **不拆** P3 四源为独立子图：P3 的 fan-out 模式简单，独立子图收益不大
- ❌ **不拆** 辩论 6 节点为子图：串行链没有循环，子图没有额外价值
- ❌ **不改** 节点函数签名：所有 `node_*` 函数保持 `async def node_*(state: DebateState) -> DebateState` 不变

---

## 8. 验证清单

| # | 验证项 | 验证方式 |
|:-:|:-------|:---------|
| 1 | 子图独立编译 | `python -c "from fdt_langgraph.per_symbol_graph import build_per_symbol_subgraph; g = build_per_symbol_subgraph(); print(len(g.nodes))"` |
| 2 | 主图编译 | `python -c "from fdt_langgraph.graph import build_debate_graph; g = build_debate_graph(); print(len(g.nodes))"` |
| 3 | 旧图节点数 | 当前 23 个 → 子图后主图 10 个 |
| 4 | 新图功能等价 | 用 mock 数据对比新老图输出 |
| 5 | Harness 12 项检查 | `python scripts/verification/pre_commit_harness_check.py` |
| 6 | 全部 pytest 通过 | `python -m pytest tests/ --ignore=tests/commodity-chain --no-cov -x` |
