# loop_engine — L2 因子演化循环

> **版本**: v8.9.2 | **状态**: Phase 1 落地 | **基线**: [docs/harness/11-loop-engineering.md](../docs/harness/11-loop-engineering.md)

整合 `agentic-factor-investing` + `factorengine` + Loop Engineering 三层架构的因子演化引擎。

## 模块概览

```
loop_engine/
├── __init__.py              # 包入口
├── contracts.py             # 契约层（TypedDict / 常量）
├── factor_program.py        # 因子程序接口（图灵完备代码 + 安全沙箱）
├── seed_pool.py             # 种子池（12 个内置因子）
├── macro_evolution.py       # 宏观演化（LLM 改逻辑）
├── micro_evolution.py       # 微观演化（optuna 贝叶斯调参）
├── evaluation_chain.py      # agentic 三级评估链
├── experience_chain.py      # 经验链存储
├── verifier.py              # Verifier 协议（锁定评估机制）
├── state.py                 # 演化状态 + trace_id 全链路
└── evolution_loop.py        # 主循环
```

## 快速开始

### 单次运行（CLI）

```bash
cd D:\Programs\FDT
python -m loop_engine.evolution_loop --once --max-generation 5
```

### 编程式调用

```python
import numpy as np
import pandas as pd
from loop_engine import EvolutionLoop

# 准备数据
data = pd.DataFrame({"close": ..., "volume": ..., "open_interest": ...})
forward_returns = np.array([...])

# 运行演化
loop = EvolutionLoop(
    data=data,
    forward_returns=forward_returns,
    elite_dir="memory/knowledge/factors/elite",
    memory_dir="memory/evolution",
)
result = loop.run(max_generation=10)
print(result.to_dict())
```

## 角色边界（HARNESS §角色边界钉死）

| 角色 | 职责 | 禁止 |
|------|------|------|
| `evolution_loop` | 主循环编排 | 直接修改因子代码 |
| `macro_evolution` | LLM 改因子逻辑 | 修改 Verifier、跳过评估 |
| `micro_evolution` | optuna 调参 | 修改因子逻辑代码 |
| `evaluation_chain` | 三级评估 | 接受 override |
| `verifier` | 评估判定 | 修改自身配置 |
| `experience_chain` | 经验链存储 | 干预判定结果 |
| `state` | 状态持久化 | 修改 Verifier 配置 |

## 三层分离原则（factorengine 核心约束）

| 分离 | LLM 负责 | CPU 负责 |
|------|---------|---------|
| 逻辑分离 | 因子逻辑修改 | 参数空间搜索 |
| 资源分离 | API 调用 | 本地 numpy/optuna |
| 时间分离 | 慢决策（每代 1 次） | 快迭代（每代 100 trials） |

## 熔断条件

任一触发立即停止：
1. 单夜 token > 2x 预算（默认 400K）
2. 连续 3 代 IC < 0.01
3. 失败率 > 90%
4. 状态文件 24h 未更新

## Verifier 协议

```python
from loop_engine.verifier import get_global_verifier

verifier = get_global_verifier()  # 锁定配置，不可修改
result = verifier.check(evaluation)
# result["passed"] == True/False
# result["failure_reasons"] == [...]
```

任何尝试修改 Verifier 配置都会抛 `VerifierAlreadyLockedError`。

## 经验链

```
memory/evolution/
├── state.json                # 演化状态
├── success/                  # 成功轨迹
├── failure/                  # 失败轨迹
└── experience_chain.md       # 摘要（LLM 易读）
```

LLM 每次宏观演化必须读取最近 20 条经验链（成功 10 + 失败 10）。

## 集成

### 与 scheduler 集成

`scheduler/tasks.py` 新增 `l2_evolution_loop` 任务，由 `scheduler/triggers.py` 的 20:00 触发器调度。

### 与 multi_factor_strategy.py 集成（Phase 3）

L2 精英因子 → L3 组合构建 → 注入 `multi_factor_strategy.py` 权重配置。

## 测试

```bash
pytest tests/loop_engine/ -v
```

预期 ≥ 60 个测试用例全绿。

## HARNESS 12 项检查清单

详见 [docs/harness/11-loop-engineering.md §11](../docs/harness/11-loop-engineering.md)。

## 版本历史

| 版本 | 日期 | 里程碑 |
|------|------|--------|
| v8.9.2 | 2026-07-18 | Phase 1 L2 Evolution Loop 落地（12 种子 + 三级评估 + 经验链 + Verifier + 熔断） |

---

*loop_engine v8.9.2 — Phase 1 完成*
