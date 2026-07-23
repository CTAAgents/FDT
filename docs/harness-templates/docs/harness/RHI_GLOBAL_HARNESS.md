# 全局 Harness 自进化框架

> **版本**: v9.22.0
> **日期**: 2026-07-23
>
> 本文件定义本机全局 Harness 的自进化架构，整合 **RHI (Recursive Harness Self-Improvement)** +
> **MemoHarness** 两套学术方案，形成统一的 A+B 框架。
>
> - RHI: [arXiv:2607.15524](https://arxiv.org/abs/2607.15524)
> - MemoHarness: [arXiv:2607.14159](https://arxiv.org/abs/2607.14159)

---

## 1. 核心概念

### 1.1 什么是 Harness？

Harness 是将 AI Agent 转化为可执行系统的外部控制层。在全局 Harness 框架中，**每个项目的 `CLAUDE.md` 就是一个 Harness prompt**——它定义了 Agent 的角色、行为约束、工作流规则和验收标准。

### 1.2 为什么需要自进化？

手工维护的 Harness 有两个问题：
- **静态滞后**：项目演进后，CLAUDE.md 中的规则往往落后于实际代码
- **无反馈机制**：无法判断当前 Harness 是否"好"，更不知道如何改进

RHI + MemoHarness 方案解决了这个问题：

| 方案 | 核心思想 | 在本框架中的角色 |
|:-----|:---------|:----------------|
| **A: RHI** | 轨迹局部 pairwise 比较，O(1) 每轮 | **搜索方法**：每次比较当前 Harness 输出 vs 上一版，决定是否改进 |
| **B: MemoHarness** | 六维控制空间 + 双层经验库 | **存储结构**：评分维度 (D1-D6) + 版本历史 (Et/Gt) |

---

## 2. A+B 统一架构

```
┌────────────────────────────────────────────────────────────┐
│                  全局 Harness 自进化                          │
│                                                             │
│  ┌─────────┐   ┌──────────────┐   ┌─────────────────────┐  │
│  │ CLAUDE  │──▶│ 四维评分器    │──▶│ pairwise 比较       │  │
│  │ .md     │   │ (D1-D6子集)  │   │ (current vs prev)   │  │
│  └─────────┘   └──────────────┘   └──────────┬──────────┘  │
│          ▲                                     │            │
│          │                           ┌─────────▼────────┐  │
│          │                           │ 改进率 sⁱ 计算    │  │
│          │                           │ sⁱ < 0.3? 收敛   │  │
│          │                           └─────────┬────────┘  │
│          │                                     │            │
│          │                           ┌─────────▼────────┐  │
│          └─── (人工修改 CLAUDE.md) ──│ 记录到 .rhi/      │  │
│             触发下一轮评估             │ history.json      │  │
│     (A: RHI 轨迹局部比较)            └───────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ B: MemoHarness 评分维度映射                           │   │
│  │                                                      │   │
│  │ D1 Context    → memory_coverage (0.30)               │   │
│  │ D2 Tool       → (项目自定义)                          │   │
│  │ D3 Generation → (项目自定义)                          │   │
│  │ D4 Workflow   → consistency (0.20)                   │   │
│  │ D5 Memory     → memory_coverage (与D1共享)            │   │
│  │ D6 Output     → clarity (0.20) + rule_completeness   │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

### 2.1 评分维度（四维）

当前全局 Harness 使用以下四维评分，覆盖 MemoHarness 六维控制空间的核心维度：

| 维度 | MemoHarness 对应 | 权重 | 度量方式 |
|:-----|:-----------------|:----:|:---------|
| **memory_coverage** | D1 Context + D5 Memory | 0.30 | CLAUDE.md 是否引用了项目记忆和知识库 |
| **rule_completeness** | D6 Output | 0.30 | 检查清单(12项)和反模式(10条)是否齐全 |
| **consistency** | D4 Orchestration | 0.20 | 是否引用了 Harness 文档和 README |
| **clarity** | D6 Output | 0.20 | 文件行数适度(<300最佳，<500可接受) |

> **扩展性**：项目可以在自己的 `rhi_global_setup.py` 中增加更多维度（如 D2 Tool 的工具接入数量、D3 Generation 的 token 预算等），覆盖完整的 MemoHarness 六维空间。

### 2.2 RHI 算法流程

```
Algorithm 1: Recursive Harness Self-Improvement (全局 Harness 适配版)

输入: CLAUDE.md 路径 P, 最大轮次 N=5, 停止阈值 ε=0.3
初始化: 读取 .rhi/history.json
首次执行: 评分当前 CLAUDE.md → 记录首版快照

循环 i = 1..N:
  1. 读取当前 CLAUDE.md 内容
  2. 四维评分 → score_current
  3. 与上一版本评分比较:
     - delta > 0.02 → "improve"
     - delta < -0.02 → "regress"
     - 否则 → "tie"
  4. 计算改进率 sⁱ = (improve 次数) / (总比较次数)
  5. 若 sⁱ < 0.3 且 ≥ 2 次比较 → 收敛，停止
  6. 记录版本快照到 .rhi/history.json
  7. 人工或 LLM 修改 CLAUDE.md → 回到步骤 1

返回: 最优版本号及评分
```

### 2.3 停止条件

| 条件 | 说明 |
|:-----|:------|
| **改进率收敛** | sⁱ < 0.3（连续改进次数不足 30%） |
| **最大轮次** | 达 N=5 轮 |
| **手动终止** | 收敛标记 `converged: true` 后不再触发 |

---

## 3. 目录结构与数据流

### 3.1 文件布局

```
项目根目录/
├── CLAUDE.md                    # Harness prompt — 自优化对象
├── .rhi/                        # RHI 数据目录（自动创建）
│   └── history.json             # 版本历史 + pairwise 偏好
└── scripts/
    ├── rhi_global_setup.py      # RHI 自进化脚本（从 Starter Kit 部署）
    └── pre_commit_harness_check.py  # Harness 检查（已有）
```

### 3.2 history.json 结构

```json
{
  "versions": [
    {
      "version": 0,
      "timestamp": "2026-07-23T12:00:00",
      "score": 0.7000,
      "breakdown": {
        "memory_coverage": 0.0,
        "rule_completeness": 1.0,
        "consistency": 1.0,
        "clarity": 1.0
      },
      "content_length": 1200
    }
  ],
  "preferences": [
    {
      "iteration": 0,
      "preference": "tie",
      "score_current": 0.7000,
      "score_previous": 0.0000,
      "rationale": "首轮基准评分"
    }
  ],
  "improvement_rate": 0.0,
  "best_version": 0,
  "converged": false
}
```

### 3.3 数据流

```
rhi_global_setup.py init
  → 读取 CLAUDE.md
  → 四维评分
  → 写入 .rhi/history.json (version 0)

rhi_global_setup.py step
  → 读取 CLAUDE.md 当前内容
  → 四维评分
  → 读取 .rhi/history.json 上一版本
  → pairwise 比较 → 确定偏好 (improve/regress/tie)
  → 计算改进率 sⁱ
  → 判断是否收敛
  → 写入 .rhi/history.json (追加版本)

rhi_global_setup.py status
  → 读取 .rhi/history.json
  → 显示评分 + 版本数 + 改进率 + 收敛状态
```

---

## 4. 与 Harness 工程规范的关系

### 4.1 整合点

| Harness 规范组件 | RHI 对应 |
|:-----------------|:---------|
| `CLAUDE.md` — 核心入口 | RHI 的自优化对象 |
| `docs/harness/` — 13 份文档 | 评分维度的`consistency`检查目标 |
| `scripts/pre_commit_harness_check.py` | 独立运行，与 RHI 互补（pre-commit 管代码质量，RHI 管 Harness 质量） |
| `harness-rules.yaml` — 12 项检查 + 10 条反模式 | `rule_completeness` 评分维度的检查内容 |

### 4.2 两种进化模式的对比

| 维度 | pre-commit Harness 检查 | RHI 自进化 |
|:-----|:------------------------|:-----------|
| 检查对象 | 本次 commit 的代码变更 | CLAUDE.md 本身的质量 |
| 检查方式 | 规则引擎（YAML → 机读） | 评分函数 + pairwise 比较 |
| 触发时机 | commit 前自动 | 手动 step 或定时触发 |
| 输出 | PASS/FAIL + issue 列表 | 评分 + 偏好 + 改进率 |
| 收敛判断 | 无（每次独立检查） | sⁱ < 0.3 或达最大轮次 |
| 存储 | 无状态 | `.rhi/history.json` |

---

## 5. 使用指南

### 5.1 快速开始

```bash
# 1. 部署 Harness 规范（如果尚未部署）
python D:\HarnessStarterKit\scripts\deploy_harness.py

# 2. 初始化 RHI
python scripts/rhi_global_setup.py init

# 3. 查看状态
python scripts/rhi_global_setup.py status

# 4. 修改 CLAUDE.md（添加项目专属规则）

# 5. 执行自优化
python scripts/rhi_global_setup.py step

# 6. 查看改进效果
python scripts/rhi_global_setup.py status
```

### 5.2 最佳实践

- **每次修改 CLAUDE.md 后运行 `step`**：记录版本快照，追踪 Harness 质量变化
- **评估期运行 3-5 轮**：让改进率 sⁱ 自然收敛到 < 0.3
- **结合 pre-commit 检查**：RHI 优化 CLAUDE.md 结构，pre-commit 检查代码合规，两者互补
- **跨项目复用经验**：`history.json` 可以跨项目对比，找出 Harness 质量最高的项目作为标杆

### 5.3 扩展评分维度

如需覆盖完整的 MemoHarness 六维空间，修改 `rhi_global_setup.py` 中的 `_score_claude()` 函数：

```python
def _score_claude(claude_path):
    content = claude_path.read_text(encoding="utf-8")
    scores = {}

    # D1 Context — 上下文线索完整性
    scores["context_quality"] = ...

    # D2 Tool — 工具声明齐全度
    scores["tool_completeness"] = ...

    # D3 Generation — 解码参数明确度
    scores["decoding_clarity"] = ...

    # D4 Orchestration — 工作流步骤清晰度
    scores["workflow_clarity"] = ...

    # D5 Memory — 记忆/状态持久化规范
    scores["memory_spec"] = ...

    # D6 Output — 输出格式 / 验收标准
    scores["output_standard"] = ...

    weights = {"context_quality": 0.20, "tool_completeness": 0.15, ...}
    total = sum(scores[k] * weights[k] for k in weights)
    return {"score": round(total, 4), "breakdown": scores}
```

---

## 6. 参考

### 6.1 论文

| 论文 | 链接 | 贡献 |
|:-----|:-----|:------|
| Recursive Harness Self-Improvement | [arXiv:2607.15524](https://arxiv.org/abs/2607.15524) | 轨迹局部 O(1) 搜索算法 |
| MemoHarness: Agent Harnesses That Learn from Experience | [arXiv:2607.14159](https://arxiv.org/abs/2607.14159) | 六维控制空间 + 经验库 |

### 6.2 相关文件

| 文件 | 位置 | 说明 |
|:-----|:-----|:------|
| `rhi_global_setup.py` | `D:\HarnessStarterKit\scripts\` | RHI 自进化主脚本 |
| `rhi_global_cli.py` | `D:\Programs\FDT\scripts\` | 增强版 CLI（含改进率计算 import） |
| `CLAUDE.md` | 项目根目录 | Harness prompt，自优化对象 |
| `history.json` | `.rhi/` | RHI 迭代历史 |
| `deploy_harness.py` | `D:\HarnessStarterKit\scripts\` | 一键部署脚本 |

---

> **文档维护**：本文件由 `D:\HarnessStarterKit\` 提供，随全局 Harness 框架版本同步更新。
> 各项目可将其复制到自己的 `docs/` 目录并补充项目专属的自进化策略。
