# FDT 迁移至 LangGraph 实施计划

## 文档信息

| 项 | 值 |
|:---|:---|
| **版本** | v1.0 |
| **创建日期** | 2026-07-16 |
| **适用范围** | Futures Debate Team v8.2.0 |
| **状态** | 草案待评审 |

---

## 1. 现状分析

### 1.1 当前架构概览

FDT 当前是一个基于**文件传递 + 轮询机制**的多Agent协作系统：

```
┌─────────────────────────────────────────────────────────────┐
│                     当前 FDT 架构                            │
├─────────────────────────────────────────────────────────────┤
│  Bootstrap → Scheduler → Pipeline Runner                    │
│         │              │                                    │
│         ▼              ▼                                    │
│  Coordinator (yaml配置) → Agent Runner (LLM调用)            │
│         │              │                                    │
│         └──────────────┼────────────────────────────────────┘
│                        ▼                                    │
│              文件传递 (.json) + S04轮询                      │
│              ┌───────────────────────┐                      │
│              │ 10 Agent 串行执行     │                      │
│              │ (数技源→研究员→辩手→   │                      │
│              │  闫判官→策略师→风控)   │                      │
│              └───────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 当前核心组件

| 组件 | 文件 | 职责 | 问题 |
|:-----|:-----|:-----|:-----|
| **Coordinator** | `scripts/coordinator.py` | 从 YAML 加载拓扑，调度 Agent | 仅调度不执行，实际逻辑由 spawn 外部完成 |
| **Pipeline Runner** | `pipeline/runner.py` | 6步全自动流水线 | 基于 subprocess 调用脚本，耦合度高 |
| **Agent Runner** | `scripts/agent_runner.py` | 单 Agent LLM 调用 | 文件传递通信，轮询等待效率低 |
| **Debate Protocol** | `scripts/debate_protocol_v2.py` | 三轮辩论逻辑 | 硬编码规则，难以扩展 |
| **协调配置** | `coordination_config.yaml` | Agent 定义 + 拓扑 | 静态配置，运行时不可变 |
| **状态持久化** | `memory/*.json` | 辩论记录 + 进化参数 | 文件锁 + SQLite，并发安全复杂 |

### 1.3 当前通信机制

**S04 轮询协议**（问题核心）：

```
明鉴秋 → spawn Agent → 写 .tmp → rename → SendMessage
   │                          │
   └───────── poll_file_ready() ← 每15s检查，15min超时
```

**问题清单**：

| 问题 | 影响 | 严重度 |
|:-----|:-----|:-------|
| 文件传递延迟 | 每步最少等待 15s 轮询间隔 | 高 |
| 轮询机制低效 | 15min 超时内最多 60 次无效检查 | 高 |
| 协调器不执行 | `delegated_to_spawn` 状态误导 | 高 |
| 静态拓扑 | 无法动态调整执行顺序 | 中 |
| 无状态管理 | 状态分散在多个 JSON 文件 | 高 |
| 重试逻辑简单 | 固定重试 2 次，无指数退避 | 中 |

---

## 2. LangGraph 迁移价值

### 2.1 LangGraph 核心优势

| 特性 | LangGraph 能力 | FDT 收益 |
|:-----|:--------------|:---------|
| **有状态图** | `StateGraph` + `TypedDict` | 统一状态管理，消除文件传递 |
| **条件边** | `.add_conditional_edges()` | 动态路由，支持多模式切换 |
| **持久化** | `checkpointer` (SQLite/Redis) | 开箱即用的状态持久化 |
| **并发执行** | `start_node` + `end_node` | 并行 Agent 执行 |
| **中断/恢复** | 断点续跑 | 故障恢复，节省 LLM 调用 |
| **流式输出** | `StreamingMode.STREAM_UPDATES` | 实时辩论进度 |
| **可观测性** | `get_state_history()` | 完整执行轨迹追溯 |
| **工具调用** | `ToolNode` | Agent 工具集成 |

### 2.2 迁移后的架构

```
┌─────────────────────────────────────────────────────────────┐
│                     LangGraph 架构                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              FdtDebateGraph (StateGraph)              │  │
│  │                                                       │  │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────────────┐    │  │
│  │  │ scan    │───→│ research │───→│ debate (并行)   │    │  │
│  │  │ node    │    │ node     │    │ (bull+bear)     │    │  │
│  │  └─────────┘    └─────────┘    └────────┬────────┘    │  │
│  │                                         │              │  │
│  │                                         ▼              │  │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────────────┐    │  │
│  │  │ report  │←───│ risk    │←───│ judgment        │    │  │
│  │  │ node    │    │ node     │    │ node            │    │  │
│  │  └─────────┘    └─────────┘    └─────────────────┘    │  │
│  │                                                       │  │
│  │  State: {                                             │  │
│  │    scan_results: {...},                               │  │
│  │    research_data: {...},                              │  │
│  │    debate_args: {bull: [...], bear: [...]},           │  │
│  │    verdict: {...},                                    │  │
│  │    trading_plan: {...},                               │  │
│  │    risk_check: {...}                                  │  │
│  │  }                                                    │  │
│  │                                                       │  │
│  │  Checkpointer → SQLite / Redis                        │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Agent 执行层 (FdtAgentExecutor)           │  │
│  │  ├─ 读取 config/agents/*.yaml                        │  │
│  │  ├─ 调用 FdtLlm.chat()                               │  │
│  │  └─ 返回结构化输出                                    │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 预期收益

| 维度 | 当前 | 迁移后 | 改进 |
|:-----|:-----|:-------|:-----|
| **执行效率** | 每步最少 15s 轮询 | 即时状态传递 | 减少 90%+ 等待时间 |
| **代码复杂度** | 10+ 脚本文件 | 统一图定义 | 减少 60% 代码量 |
| **可维护性** | 硬编码流程 | 声明式图定义 | 新增模式只需修改图 |
| **可观测性** | 文件日志 | 状态历史 API | 实时追踪 + 回放 |
| **容错能力** | D06 降级 | checkpointer 恢复 | 断点续跑 |

---

## 3. 迁移策略

### 3.1 渐进式迁移（推荐）

采用**双轨并行 + 逐步替换**策略，确保业务不中断：

```
Phase 1: 基础设施层 (LangGraph 集成)
    ↓
Phase 2: 核心辩论流程 (P1-P5 迁移)
    ↓
Phase 3: 流水线 + 调度器 (P0+P6 迁移)
    ↓
Phase 4: 自进化闭环 (验证+校准+进化)
    ↓
Phase 5: 完全切换 + 旧代码清理
```

### 3.2 模块映射

| 现有模块 | LangGraph 对应 | 迁移优先级 |
|:---------|:--------------|:-----------|
| `coordinator.py` | `StateGraph` + `conditional_edges` | P0 |
| `debate_protocol_v2.py` | 图节点 + 条件路由 | P0 |
| `agent_runner.py` | `ToolNode` / `FunctionNode` | P1 |
| `pipeline/runner.py` | 外层工作流图 | P2 |
| `scheduler/engine.py` | LangGraph + 调度器集成 | P3 |
| `memory/*.json` | `checkpointer` | P1 |

---

## 4. 实施步骤

### Phase 1: 基础设施层（1周）

**目标**：集成 LangGraph，建立状态管理基础

#### 4.1.1 依赖安装

```bash
pip install langgraph langgraph-checkpoint-sqlite
```

更新 `pyproject.toml`：

```toml
[project.dependencies]
# ... 现有依赖 ...
"langgraph>=0.2.0",
"langgraph-checkpoint-sqlite>=0.1.0",
```

#### 4.1.2 定义全局状态

创建 `langgraph/state.py`：

```python
from typing import TypedDict, Optional, Literal
from datetime import datetime

class DebateState(TypedDict):
    trace_id: str
    timestamp: datetime
    mode: Literal["default", "fast", "deep_research", "tournament"]
    
    # P1: 扫描结果
    scan_results: dict
    scan_summary: Optional[dict]
    
    # P1.5: 产业链分析
    chain_analysis: Optional[dict]
    
    # P2: 闫判官方向指定
    judge_direction: Optional[dict]
    selected_symbols: list
    
    # P3: 研究员供弹
    technical_data: dict
    fundamental_data: dict
    
    # P4: 辩论论据
    bullish_arguments: list
    bearish_arguments: list
    
    # P5: 裁决链
    verdict: Optional[dict]
    trading_plan: Optional[dict]
    risk_check: Optional[dict]
    
    # P6: 输出
    report_path: Optional[str]
    
    # 控制状态
    current_phase: str
    error: Optional[str]
    completed_phases: list
```

#### 4.1.3 创建 Agent 执行器

创建 `langgraph/agents.py`：

```python
from typing import Optional
from scripts.fdt_llm import FdtLlm
from config.schemas import AgentConfig

class FdtAgentExecutor:
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.llm = FdtLlm(agent_type=agent_name)
        self.config = self._load_config(agent_name)
    
    def _load_config(self, agent_name: str) -> dict:
        import yaml
        from pathlib import Path
        cfg_path = Path("config") / "agents" / f"{agent_name}.yaml"
        if not cfg_path.exists():
            return {}
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    
    async def run(self, context: str, json_mode: bool = True) -> dict:
        system_prompt = self.config.get("system_prompt", "")
        if json_mode:
            reply = self.llm.chat_json(context, system=system_prompt)
        else:
            reply = self.llm.chat(context, system=system_prompt)
        return reply
```

### Phase 2: 核心辩论流程（2周）

**目标**：将 P1-P5 迁移到 LangGraph

#### 4.2.1 创建图节点

创建 `langgraph/nodes.py`：

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from .state import DebateState
from .agents import FdtAgentExecutor

# ── P1: 扫描节点 ──
async def node_scan(state: DebateState) -> DebateState:
    from skills.quant_daily.scripts.scan_all import run_scan
    scan_results = run_scan()
    return {**state, "scan_results": scan_results, "current_phase": "P1"}

# ── P1.5: 产业链分析节点 ──
async def node_chain_analysis(state: DebateState) -> DebateState:
    from skills.commodity_chain_analysis.scripts.chains import analyze_chain
    chain_data = analyze_chain(state["selected_symbols"])
    return {**state, "chain_analysis": chain_data, "current_phase": "P1.5"}

# ── P2: 闫判官方向指定 ──
async def node_judge_direction(state: DebateState) -> DebateState:
    judge = FdtAgentExecutor("judge")
    context = f"扫描结果: {state['scan_results']}"
    verdict = await judge.run(context)
    return {
        **state, 
        "judge_direction": verdict,
        "selected_symbols": verdict.get("symbols", []),
        "current_phase": "P2"
    }

# ── P3: 研究员并行供弹 ──
async def node_research(state: DebateState) -> DebateState:
    technical = FdtAgentExecutor("technical_researcher")
    fundamental = FdtAgentExecutor("fundamental_researcher")
    
    tech_context = f"分析品种: {state['selected_symbols']}"
    fund_context = f"分析品种: {state['selected_symbols']}"
    
    tech_result = await technical.run(tech_context)
    fund_result = await fundamental.run(fund_context)
    
    return {
        **state,
        "technical_data": tech_result,
        "fundamental_data": fund_result,
        "current_phase": "P3"
    }

# ── P4: 多空辩论 ──
async def node_debate(state: DebateState) -> DebateState:
    bullish = FdtAgentExecutor("bullish_analyst")
    bearish = FdtAgentExecutor("bearish_analyst")
    
    context = f"""
    技术面: {state['technical_data']}
    基本面: {state['fundamental_data']}
    产业链: {state['chain_analysis']}
    """
    
    bull_result = await bullish.run(context)
    bear_result = await bearish.run(context)
    
    return {
        **state,
        "bullish_arguments": bull_result.get("arguments", []),
        "bearish_arguments": bear_result.get("arguments", []),
        "current_phase": "P4"
    }

# ── P5: 裁决 ──
async def node_verdict(state: DebateState) -> DebateState:
    judge = FdtAgentExecutor("judge")
    context = f"""
    多头论据: {state['bullish_arguments']}
    空头论据: {state['bearish_arguments']}
    """
    verdict = await judge.run(context)
    
    strategist = FdtAgentExecutor("trading_strategist")
    plan = await strategist.run(f"裁决: {verdict}")
    
    risk_manager = FdtAgentExecutor("risk_manager")
    risk_check = await risk_manager.run(f"方案: {plan}")
    
    return {
        **state,
        "verdict": verdict,
        "trading_plan": plan,
        "risk_check": risk_check,
        "current_phase": "P5"
    }

# ── P6: 报告生成 ──
async def node_report(state: DebateState) -> DebateState:
    from skills.futures_trading_analysis.scripts.phase3_generate_report import generate
    report_path = generate(state)
    return {**state, "report_path": report_path, "current_phase": "P6"}
```

#### 4.2.2 定义图结构

创建 `langgraph/graph.py`：

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from .state import DebateState
from .nodes import (
    node_scan, node_chain_analysis, node_judge_direction,
    node_research, node_debate, node_verdict, node_report
)

def build_debate_graph(mode: str = "default") -> StateGraph:
    """构建辩论图"""
    
    graph = StateGraph(DebateState)
    
    # 添加节点
    graph.add_node("scan", node_scan)
    graph.add_node("chain_analysis", node_chain_analysis)
    graph.add_node("judge_direction", node_judge_direction)
    graph.add_node("research", node_research)
    graph.add_node("debate", node_debate)
    graph.add_node("verdict", node_verdict)
    graph.add_node("report", node_report)
    
    # 添加边
    graph.set_entry_point("scan")
    
    graph.add_edge("scan", "chain_analysis")
    graph.add_edge("chain_analysis", "judge_direction")
    graph.add_edge("judge_direction", "research")
    graph.add_edge("research", "debate")
    graph.add_edge("debate", "verdict")
    graph.add_edge("verdict", "report")
    graph.add_edge("report", END)
    
    # 条件边：快速模式跳过辩论
    def should_skip_debate(state: DebateState) -> str:
        if state["mode"] == "fast":
            return "verdict"
        return "debate"
    
    graph.add_conditional_edges("research", should_skip_debate)
    
    # 条件边：深度研究模式增加辩论轮次
    def should_deep_debate(state: DebateState) -> str:
        if state["mode"] == "deep_research":
            divergence = calculate_divergence(state)
            if divergence > 0.7:
                return "debate"
        return "verdict"
    
    graph.add_conditional_edges("debate", should_deep_debate)
    
    # 持久化
    memory = SqliteSaver.from_conn_string("memory/langgraph.db")
    graph = graph.compile(checkpointer=memory)
    
    return graph
```

#### 4.2.3 条件路由逻辑

```python
def calculate_divergence(state: DebateState) -> float:
    """计算分歧度"""
    bull_score = sum(arg.get("confidence", 0) for arg in state["bullish_arguments"])
    bear_score = sum(arg.get("confidence", 0) for arg in state["bearish_arguments"])
    total = bull_score + bear_score
    if total == 0:
        return 0.0
    return abs(bull_score - bear_score) / total
```

### Phase 3: 流水线 + 调度器（1周）

**目标**：迁移 P0 自进化前置和 P6 归档，集成调度器

#### 4.3.1 自进化前置节点

```python
async def node_self_evolution(state: DebateState) -> DebateState:
    """自进化前置：验证→校准→进化"""
    from scripts.validate_verdicts import validate
    from scripts.calibrate_weights import calibrate
    from scripts.evolve_agents import evolve
    
    validation = validate(state.get("execution_followup", {}))
    calibration = calibrate(validation) if validation.get("validated_count", 0) >= 5 else None
    evolution = evolve(calibration) if calibration else None
    
    return {
        **state,
        "validation_result": validation,
        "calibration_result": calibration,
        "evolution_result": evolution
    }
```

#### 4.3.2 调度器集成

```python
from scheduler.engine import SchedulerEngine
from langgraph.graph import StateGraph

class LangGraphScheduler(SchedulerEngine):
    def __init__(self, graph: StateGraph):
        super().__init__()
        self.graph = graph
    
    async def run_daily_debate(self, trace_id: str, mode: str = "default"):
        """触发每日辩论"""
        initial_state = {
            "trace_id": trace_id,
            "timestamp": datetime.now(),
            "mode": mode,
            "completed_phases": [],
            "error": None
        }
        
        async for event in self.graph.astream(initial_state):
            for node, state in event.items():
                self._logger.info(f"[{node}] {state.get('current_phase', '?')}")
                if state.get("error"):
                    self._logger.error(f"错误: {state['error']}")
                    break
        
        final_state = self.graph.get_state(trace_id)
        return final_state
```

### Phase 4: 自进化闭环（1周）

**目标**：将 ML 训练、权重校准、Agent 进化集成到图中

#### 4.4.1 ML 训练节点

```python
async def node_ml_training(state: DebateState) -> DebateState:
    """ML 模型训练"""
    from ml.trainer import TrainingOrchestrator
    
    orch = TrainingOrchestrator()
    result = orch.run_daily_check(len(state.get("selected_symbols", [])))
    
    return {**state, "ml_training_result": result}
```

### Phase 5: 完全切换 + 清理（0.5周）

**目标**：验证所有功能正常，清理旧代码

#### 4.5.1 验证清单

| 验证项 | 方法 | 成功标准 |
|:-------|:-----|:---------|
| 图编译 | `graph.compile()` | 无异常 |
| 状态持久化 | `get_state_history()` | 完整历史记录 |
| 条件路由 | 测试 fast/deep_research 模式 | 正确跳过/增加辩论 |
| 断点恢复 | 中途停止后继续 | 从断点恢复 |
| LLM 调用 | 实际调用验证 | Agent 产出正常 |
| 报告生成 | 运行完整流程 | HTML 报告产出 |

#### 4.5.2 旧代码清理

```bash
# 标记待删除文件
git mv scripts/coordinator.py scripts/coordinator.py.deprecated
git mv pipeline/runner.py pipeline/runner.py.deprecated
git mv scripts/debate_protocol_v2.py scripts/debate_protocol_v2.py.deprecated
```

---

## 5. 风险评估

### 5.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:-----|:-----|:---------|
| LangGraph 版本兼容性 | 中 | 高 | 锁定版本号，CI 测试 |
| LLM 调用异步化 | 中 | 中 | 保持同步/异步双接口 |
| 状态序列化 | 低 | 高 | 使用 Pydantic 验证 |
| 并发执行冲突 | 低 | 中 | 使用 checkpointer 锁 |

### 5.2 业务风险

| 风险 | 概率 | 影响 | 缓解措施 |
|:-----|:-----|:-----|:---------|
| 迁移期间业务中断 | 低 | 高 | 双轨并行，逐步切换 |
| 辩论结果不一致 | 中 | 高 | 运行基准测试对比 |
| 性能回归 | 中 | 中 | 监控执行时间 |
| 历史数据迁移 | 低 | 中 | 编写迁移脚本 |

### 5.3 风险缓解计划

```
双轨并行策略：
┌─────────────────────────────────────────────┐
│  Week 1-3: 新系统开发 + 测试                 │
│  ├─ 不影响现有业务                           │
│  └─ 验证新系统输出与旧系统一致               │
├─────────────────────────────────────────────┤
│  Week 4: 并行运行                           │
│  ├─ 旧系统继续生产                           │
│  └─ 新系统同步运行，对比结果                 │
├─────────────────────────────────────────────┤
│  Week 5: 切换                              │
│  ├─ 新系统上线                              │
│  └─ 旧系统保留一周回滚窗口                   │
└─────────────────────────────────────────────┘
```

---

## 6. 验证方案

### 6.1 单元测试

```python
# tests/langgraph/test_graph.py
import pytest
from langgraph.graph import StateGraph
from langgraph.state import DebateState

def test_graph_compile():
    graph = build_debate_graph()
    assert graph is not None

def test_state_validation():
    state = DebateState(
        trace_id="test-001",
        timestamp=datetime.now(),
        mode="default",
        scan_results={},
        scan_summary=None,
        chain_analysis=None,
        judge_direction=None,
        selected_symbols=[],
        technical_data={},
        fundamental_data={},
        bullish_arguments=[],
        bearish_arguments=[],
        verdict=None,
        trading_plan=None,
        risk_check=None,
        report_path=None,
        current_phase="P0",
        error=None,
        completed_phases=[]
    )
    assert isinstance(state, dict)

@pytest.mark.asyncio
async def test_node_scan():
    state = DebateState(...)
    result = await node_scan(state)
    assert "scan_results" in result
```

### 6.2 集成测试

```bash
# 运行基准测试对比
python scripts/run_benchmark.py --run --langgraph
python scripts/run_benchmark.py --run --legacy

# 对比结果
python scripts/compare_results.py --langgraph results/langgraph.json --legacy results/legacy.json
```

### 6.3 性能测试

```python
import time

async def benchmark():
    graph = build_debate_graph()
    start = time.time()
    
    async for event in graph.astream(initial_state):
        pass
    
    elapsed = time.time() - start
    print(f"LangGraph 执行时间: {elapsed:.2f}s")
```

---

## 7. 里程碑

| 阶段 | 时间 | 交付物 | 负责人 |
|:-----|:-----|:-------|:-------|
| Phase 1 | 第1周 | LangGraph 基础设施 | 架构师 |
| Phase 2 | 第2-3周 | 核心辩论流程迁移 | 核心开发 |
| Phase 3 | 第4周 | 流水线 + 调度器 | 开发 |
| Phase 4 | 第5周 | 自进化闭环 | ML工程师 |
| Phase 5 | 第6周 | 验证 + 清理 | QA |

---

## 8. 代码结构规划

```
langgraph/
├── __init__.py
├── state.py          # 全局状态定义
├── agents.py         # Agent 执行器
├── nodes.py          # 图节点实现
├── graph.py          # 图构建逻辑
├── checkpoint.py     # 持久化配置
└── utils.py          # 工具函数

tests/
└── langgraph/
    ├── test_graph.py
    ├── test_nodes.py
    └── test_state.py

memory/
└── langgraph.db      # SQLite 持久化
```

---

## 9. 后续优化方向

### 9.1 短期（1-2月）

- [ ] 集成 LangSmith 追踪
- [ ] 添加流式输出支持
- [ ] 实现 Agent 工具调用
- [ ] 添加异常重试策略

### 9.2 中期（3-6月）

- [ ] 分布式执行（Ray 集成）
- [ ] 多模型并行辩论
- [ ] 实时数据流集成
- [ ] WebSocket 实时推送

### 9.3 长期（6月+）

- [ ] 动态图重构（运行时调整拓扑）
- [ ] 自适应 Agent 选择
- [ ] 跨模态辩论（文本+图表）
- [ ] 联邦学习集成

---

## 附录

### A. 现有 Agent 到图节点映射

| Agent | 节点 | 角色 |
|:------|:-----|:-----|
| 数技源 | `scan` | 信号扫描 |
| 链证源 | `chain_analysis` | 产业链分析 |
| 闫判官 | `judge_direction`, `verdict` | 方向指定 + 裁决 |
| 观澜 | `research` (并行) | 技术分析 |
| 探源 | `research` (并行) | 基本面分析 |
| 多头分析员 | `debate` (并行) | 多头论据 |
| 空头分析员 | `debate` (并行) | 空头论据 |
| 策执远 | `verdict` | 交易方案 |
| 风控明 | `verdict` | 风控审核 |
| 明鉴秋 | 图调度 | 流程控制 |

### B. 配置迁移映射

| 现有配置 | LangGraph 对应 |
|:---------|:--------------|
| `coordination_config.yaml` | 图定义代码 |
| `config/agents/*.yaml` | Agent 执行器配置 |
| `team_config.json` | 图编译参数 |
| `settings.json` | 全局状态初始值 |

### C. 状态持久化映射

| 现有文件 | LangGraph 对应 |
|:---------|:--------------|
| `memory/debate_journal.json` | `get_state_history()` |
| `memory/execution_followup.json` | 状态字段 |
| `memory/agent_profiles.json` | Agent 配置 |
| `memory/calibration.json` | 状态字段 |

---

*文档结束*