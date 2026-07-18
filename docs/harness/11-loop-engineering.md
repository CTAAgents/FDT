# 11 — Loop Engineering：自动化量化生产线

> **版本**: v8.10.0（Phase 2+3 落地） | **日期**: 2026-07-18 | **状态**: 实施
>
> **版本历史**:
> - v8.9.2 (2026-07-18): Phase 1 L2 Evolution Loop 落地
> - v8.10.0 (2026-07-18): Phase 2 L1 Meta-Loop 落地
> - v8.10.0 (2026-07-18): Phase 3 L3 Portfolio Loop 落地（信号合成+正交化+组合构建+衰减检验+注入 FDT）
>
> **版本历史**:
> - v8.9.2 (2026-07-18): Phase 1 L2 Evolution Loop 落地
> - v8.10.0 (2026-07-18): Phase 2 L1 Meta-Loop 落地（Bootstrapping Agent 链 + f10 感知 + debate_round 质量反馈）
> **基线文档**: [01-architecture.md](01-architecture.md) | [02-lifecycle.md](02-lifecycle.md) | [08-gap-analysis.md](08-gap-analysis.md)
> **整合蓝图**: [../../LOOP_ENGINEERING_INTEGRATION_PLAN.md](../../LOOP_ENGINEERING_INTEGRATION_PLAN.md)（外部，d:\TRAE）

---

## 1. 概述

FDT 引入 **Loop Engineering** 范式，将 `agentic-factor-investing` + `factorengine` + Loop 三层架构焊死到系统中，形成自动化量化生产线。本文档定义 **L2 因子演化循环**（Phase 1）、**L1 Meta-Loop**（Phase 2）与 **L3 Portfolio Loop**（Phase 3）的架构、契约、流程与运维规范。

### 1.1 四层循环架构

```
L0 人类设定层  → 每周 30 分钟写 program.md（市场环境/预算/风险约束）
L1 Meta-Loop   → 每日 05:00 知识补给（Bootstrapping + f10 web_collector + debate_round 反馈）  ← 本文档 Phase 2 ✅
L2 Evolution Loop → 每日 20:00-06:00 因子演化（宏微协同 + 三级评估 + 经验链）  ← 本文档 Phase 1 ✅
L3 Portfolio Loop → 每周五 15:30 组合构建（信号合成 + 正交化 + 注入 FDT）  ← 本文档 Phase 3 ✅
FDT 消费层     → multi_factor_strategy.py + P4 三步骤辩论 + CTP 信号
```

### 1.2 三框架正交分工

| 框架 | 职责 | L2 中的角色 |
|------|------|------------|
| agentic-factor-investing | **定义**什么是好因子（经济逻辑评估 + 过拟合防护） | L2 三级评估链的判定标准 |
| factorengine | **实现**怎么写和演化因子（程序级因子 + 宏微协同 + Bootstrapping） | L2 演化引擎的算法骨架 |
| Loop Engineering | **协调**怎么自动转起来（Verifier 协议 + 状态文件 + 预算控制） | L2 主循环的运行时框架 |

---

## 2. L2 演化引擎架构

### 2.1 模块拓扑

```
loop_engine/
├── __init__.py
├── contracts.py             # 契约层（TypedDict / Schema / 常量）
├── factor_program.py        # 因子程序接口（图灵完备代码 + 安全沙箱）
├── seed_pool.py             # 种子池（12 个内置因子 + L1 注入）
├── macro_evolution.py       # 宏观演化（LLM 改逻辑）
├── micro_evolution.py       # 微观演化（optuna 贝叶斯调参）
├── evaluation_chain.py      # agentic 三级评估链
├── experience_chain.py      # 经验链存储（成功/失败轨迹）
├── verifier.py              # Verifier 协议（锁定评估机制）
├── state.py                 # 状态文件 + trace_id 全链路
└── evolution_loop.py        # 主循环（宏微协同 + 评估 + 经验链）
```

### 2.2 核心流程

```
seed_pool.fetch()  →  for generation in 1..MAX_GEN:
    ├─ macro_evolution.evolve(factor, experience_chain)  # LLM 改逻辑
    │     ↓
    ├─ micro_evolution.optimize(factor_new)              # optuna 100 trials
    │     ↓
    ├─ evaluation_chain.evaluate(factor_optimized)
    │     ├─ Level 1: 回测验证（IC>0.03 / 夏普>1.5 / 单调性 / 样本外≥30%）
    │     ├─ Level 2: 经济逻辑（四维评分 ≥ 3/4）
    │     └─ Level 3: 多重检验（FDR + Bonferroni）
    │     ↓
    ├─ verifier.check(eval_result)                        # 锁定的 Verifier 不可修改
    │     ↓
    ├─ experience_chain.record(factor, eval_result)       # 成功/失败轨迹
    │     ↓
    └─ state.persist(generation, factor, eval_result)     # 状态文件 + trace_id
                                                                              ↓
                                                       精英因子 → memory/knowledge/factors/elite/
```

### 2.3 三层分离原则（factorengine 核心约束）

| 分离 | LLM 负责 | CPU 负责 |
|------|---------|---------|
| 逻辑分离 | 因子逻辑修改、新因子想法生成 | 参数空间搜索、快速验证 |
| 资源分离 | API 调用（按 token 计费） | 本地 numpy/optuna 计算 |
| 时间分离 | 慢决策（每代 1 次 LLM 调用） | 快迭代（每代 100 次 optuna trials） |

---

## 3. 契约层（contracts.py）

### 3.1 因子程序契约

```python
class FactorProgram(TypedDict, total=False):
    """因子程序 — 图灵完备代码表示"""
    factor_id: str                    # 唯一标识，格式: fct_<8位hash>
    name: str                         # 人类可读名（中文/英文）
    code: str                         # Python 可执行代码（满足安全沙箱约束）
    params: dict[str, Any]            # 可调参数空间（optuna 搜索对象）
    signature: FactorSignature        # 输入/输出契约
    economic_logic: EconomicLogic     # 四维经济逻辑评分
    source: Literal["seed", "macro_evolution", "bootstrapping", "manual"]
    parent_id: Optional[str]          # 演化父因子 ID（用于经验链溯源）
    generation: int                   # 演化代数
    created_at: str                   # ISO 8601
    trace_id: str                     # 全链路 trace_id
```

### 3.2 评估结果契约

```python
class FactorEvaluation(TypedDict, total=False):
    """agentic 三级评估链输出"""
    factor_id: str
    trace_id: str
    level_1_backtest: BacktestMetrics    # IC/夏普/单调性/样本外
    level_2_economic: EconomicScore      # 四维评分
    level_3_multiple: MultipleTestResult # FDR/Bonferroni
    passed: bool                          # 三级全部通过
    failure_reasons: list[str]            # 失败维度（用于经验链）
    evaluated_at: str
```

### 3.3 经验链契约

```python
class ExperienceTrace(TypedDict, total=False):
    """经验链轨迹 — LLM 下一轮参考避免重复踩坑"""
    trace_id: str
    factor_id: str
    parent_id: Optional[str]
    generation: int
    mutation_type: Literal["macro_logic", "micro_param", "combined"]
    mutation_summary: str               # LLM 生成的可读摘要
    evaluation: FactorEvaluation
    success: bool
    lessons: list[str]                  # 失败教训 / 成功要点
    recorded_at: str
```

### 3.4 演化状态契约

```python
class EvolutionState(TypedDict, total=False):
    """演化状态文件 — Loop Engineering 状态原语"""
    run_id: str                         # 本次演化运行的唯一 ID
    started_at: str
    last_generation: int
    total_factors_evaluated: int
    total_factors_promoted: int         # 晋级到 elite 池的因子数
    tokens_consumed: int                # 本次运行的 LLM token 总量
    budget_limit: int                   # 预算上限（熔断）
    status: Literal["running", "paused", "completed", "circuit_broken"]
    last_error: Optional[str]
    experience_chain_ref: list[str]     # 经验链 trace_id 列表
```

---

## 4. 三级评估链规范（agentic 防护）

### 4.1 Level 1 — 回测验证

| 指标 | 阈值 | 计算方式 |
|------|------|---------|
| IC | > 0.03 | Spearman rank IC，截面均值 |
| ICIR | > 0.5 | IC 均值 / IC 标准差 |
| 夏普比率 | > 1.5 | 年化 |
| 最大回撤 | < 20% | 滚动 6 个月 |
| 单调性 | 严格单调 | 十分位组合收益率排序 |
| 样本外比例 | ≥ 30% | 训练/测试分割 |

### 4.2 Level 2 — 经济逻辑（四维评分 ≥ 3/4）

| 维度 | 评分标准 | 阈值 |
|------|---------|------|
| 理论支撑 | 是否与已知风险溢价相关？ | score ≥ 3/5 |
| 行为金融 | 是否捕捉过度反应/反应不足？ | score ≥ 3/5 |
| 市场微观结构 | 是否反映流动性/信息不对称？ | score ≥ 3/5 |
| 机构约束 | 是否可执行（换手率/成本）？ | score ≥ 3/5 |

通过条件：**至少 3/4 维度达标**

### 4.3 Level 3 — 多重检验校正

| 方法 | 应用 | 阈值 |
|------|------|------|
| Bonferroni | 调整显著性水平 | α/n → p < 0.01 |
| FDR | 限制假阳性比例 | q < 0.05 |
| 有效因子数 | 考虑因子相关性 | 调整后 t > 3.0 |

---

## 5. 经验链规范

### 5.1 存储结构

```
memory/evolution/
├── state.json                    # EvolutionState
├── success/                      # 成功轨迹（晋升精英池）
│   └── <trace_id>.json
├── failure/                      # 失败轨迹（LLM 下一轮参考）
│   └── <trace_id>.json
└── experience_chain.md           # 经验链摘要（LLM 易读格式）
```

### 5.2 LLM 读取协议

每次宏观演化时，LLM 必须读取最近 20 条经验链（成功 10 + 失败 10），生成新变异时显式引用至少 1 条历史轨迹。

### 5.3 经验链约束（防过拟合第 6 道防线）

- LLM 每次调用必须读取经验链摘要
- 新因子变异必须显式说明"避免重复踩坑"的依据
- 经验链满 100 条时按时间倒序淘汰最旧的 20 条
- 失败轨迹的 `failure_reasons` 必须结构化（不能为空字符串）

---

## 6. Verifier 协议（锁定评估机制）

### 6.1 不可修改原则

Verifier 是 **Loop Engineering 的核心原语**：评估机制一旦锁定，任何 LLM 调用、参数演化、人类干预都不可修改 Verifier 的判定逻辑。

### 6.2 Verifier 实现

```python
class FactorVerifier:
    """锁定的因子评估 Verifier — 一旦初始化不可修改"""

    def __init__(self, config: VerifierConfig):
        self._locked = True
        self._config = config

    def check(self, evaluation: FactorEvaluation) -> VerifierResult:
        if not self._locked:
            raise RuntimeError("Verifier 未锁定")
        # 严格按配置判定，不接受任何 override
        ...
```

### 6.3 Verifier 配置（v8.9.2 锁定值）

```yaml
# 不可在运行时修改
min_ic: 0.03
min_sharpe: 1.5
min_icir: 0.5
max_drawdown: 0.20
min_economic_score: 3     # 四维中至少 3 维达标
min_t_stat: 3.0
max_fdr: 0.05
```

---

## 7. 预算控制与熔断

### 7.1 Token 预算

| 项 | 单夜上限 | 月度上限 | 熔断触发 |
|----|---------|---------|---------|
| LLM 调用 token | 200,000 | 6,000,000 | 单夜超 400,000 |
| 演化代数 | 50 | — | 连续 3 轮 IC<0.01 |
| 单因子 token | 10,000 | — | 超限即跳过 |

### 7.2 熔断条件（任一触发立即停止）

1. 单夜 token 消耗 > 2x 预算
2. 连续 3 代 IC < 0.01（演化陷入死胡同）
3. L2 失败率 > 90%（LLM 输出全部不通过 Verifier）
4. 状态文件 24 小时未更新（可能进程僵死）

### 7.3 熔断恢复

- 自动暂停 24 小时
- 期间必须人类审查经验链摘要
- 人类手动触发 `loop_engine.resume()` 才能恢复

---

## 8. 与 FDT v8.9.1 的集成映射

| FDT 组件 | L2 改造 | 影响范围 |
|---------|--------|---------|
| `scripts/auto_factor_mining.py` | 保留备份，**功能被 L2 取代** | 不破坏现有接口 |
| `skills/quant-daily/scripts/strategies/multi_factor_strategy.py` | L2 精英因子通过 L3 注入此处 | 本期不改，Phase 3 落地 |
| `memory/knowledge/factors/` | 新增 elite/ decayed/ 子目录 | 仅追加，不修改现有 |
| `memory/evolution/` | 新增（state.json + success/ + failure/） | 全新模块 |
| `scheduler/tasks.py` | 新增 `l2_evolution_loop` 任务 | 追加注册，不修改现有任务 |
| `scheduler/triggers.py` | 新增 20:00 触发器 | 追加，不修改现有触发器 |
| `fdt_langgraph/state.py` | 不动（Phase 2 才接 debate_round） | 0 改动 |

---

## 9. 测试规范

### 9.1 测试覆盖（HARNESS §6 强制）

| 测试文件 | 覆盖范围 | 用例数 |
|---------|---------|-------|
| `tests/loop_engine/test_contracts.py` | TypedDict 实例化 + 字段约束 | ≥ 10 |
| `tests/loop_engine/test_factor_program.py` | 因子程序编译 + 安全沙箱 | ≥ 8 |
| `tests/loop_engine/test_seed_pool.py` | 12 个种子因子加载 | ≥ 6 |
| `tests/loop_engine/test_evaluation_chain.py` | 三级评估链 + 阈值 | ≥ 12 |
| `tests/loop_engine/test_experience_chain.py` | 轨迹存储 + LLM 读取协议 | ≥ 8 |
| `tests/loop_engine/test_verifier.py` | Verifier 锁定 + 防篡改 | ≥ 6 |
| `tests/loop_engine/test_evolution_loop.py` | 主循环 + 状态文件 + 熔断 | ≥ 10 |
| **合计** | — | **≥ 60** |

### 9.2 测试基线

- 所有测试必须使用 mock LLM（不依赖外部 API）
- 因子评估使用合成数据（避免数据窥探）
- Verifier 测试必须覆盖"试图修改 Verifier 应抛 RuntimeError"的场景

---

## 10. 运维 Runbook

### 10.1 启动 L2 演化

```bash
# 手动触发
python -m loop_engine.evolution_loop --once

# 通过 scheduler 调度（每夜 20:00 自动触发）
python scheduler/engine.py daemon
```

### 10.2 状态查询

```bash
# 查看当前演化状态
python -m loop_engine.state --status

# 查看经验链摘要
cat memory/evolution/experience_chain.md

# 查看精英因子池
ls memory/knowledge/factors/elite/
```

### 10.3 故障处理

#### 故障 1：LLM 调用超时

**现象**：`macro_evolution` 节点报超时
**处理**：检查 LLM API 状态；当前因子跳过宏观演化，仅做微观演化；记录失败轨迹。

#### 故障 2：optuna 调参无提升

**现象**：连续 20 次 trials 无改进
**处理**：optuna 自动 early stop；触发宏观演化生成新逻辑。

#### 故障 3：经验链污染

**现象**：LLM 引用失败轨迹生成重复因子
**处理**：手动清理 `memory/evolution/failure/` 下过期轨迹；保留最近 100 条。

#### 故障 4：状态文件损坏

**现象**：`state.json` 解析失败
**处理**：从 `memory/evolution/state.json.backup` 恢复；若无备份则冷启动（generation=0）。

---

## 11. HARNESS 12 项检查清单

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | 数据流/架构变更是否反映？ | ✅ 本文档 §2、§8 |
| 2 | 阶段/文件名/产出物是否反映？ | ✅ §2.1 模块拓扑 |
| 3 | 新配置项是否更新？ | ✅ `03-configuration.md` 追加 L2 配置 |
| 4 | 降级/熔断/超时路径是否更新？ | ✅ §7 预算控制与熔断 |
| 5 | 新指标/日志是否已加？ | ✅ §3.2 评估指标 + `05-observability.md` 追加 |
| 6 | 测试文件和用例数是否更新？ | ✅ §9 测试规范 |
| 7 | 版本号和版本历史是否追加？ | ✅ `07-operations.md` 追加 v8.9.2 |
| 8 | 差距登记/关闭是否更新？ | ✅ `08-gap-analysis.md` 追加 G77（L2 落地） |
| 9 | 晋级里程碑是否更新？ | ✅ `09-advancement-plan.md` 追加 Phase 1 |
| 10 | 流程文档是否同步？ | ✅ `execution_modes_flowchart.md` 追加 L2 节点 |
| 11 | 角色 MD 职责变更是否反映？ | ✅ 新增 `loop_engine/README.md`（角色边界） |
| 12 | README 快速参考是否刷新？ | ✅ `README.md` 追加 Loop Engineering 章节 |

---

## 12. 角色边界钉死

| 角色 | 职责 | 禁止 |
|------|------|------|
| L2 演化引擎 | 因子发现 + 演化 + 评估 + 经验链 | 直接修改 multi_factor_strategy.py（必须经 L3） |
| Verifier | 评估判定 | 接受任何 override / 修改自身配置 |
| LLM（宏观演化） | 因子逻辑变异 | 修改 Verifier、跳过评估链 |
| optuna（微观演化） | 参数空间搜索 | 修改因子逻辑代码 |
| 人类 | 写 program.md、审查经验链、手动恢复熔断 | 直接干预 Verifier 判定 |

---

## 13. 与后续 Phase 的衔接

### 13.1 Phase 2 — L1 Meta-Loop（已落地 v8.10.0）

- ✅ Bootstrapping Agent 链接入 L2 种子池入口（`seed_pool.inject_from_l1()`）
- ✅ `f10/web_collector` 作为 L1 感知层数据源（`MetaLoop._perceive_market()`）
- ✅ `debate_round` 字段作为质量反馈信号（`DebateQualityAnalyzer` 4 种缺口检测）
- ✅ L1 Verifier 锁定 4 维度判定（`L1Verifier`）
- ✅ factor_pool.json 种子池管理（`FactorPoolManager`）
- ✅ scheduler 集成（每日 05:00 TimeTrigger + `l1_meta_loop` 任务）
- ✅ 51 个测试用例全绿（`tests/loop_engine/test_meta_loop.py`）

详见 §15 L1 Meta-Loop 章节。

### 13.2 Phase 3 — L3 Portfolio Loop（已落地 v8.10.0）

- ✅ L2 精英因子池 → L3 信号合成（`synthesize_signals()` 等权/夏普加权）
- ✅ 因子正交化（`orthogonalize_factors()` 剔除相关性 > 0.7）
- ✅ 组合构建（`build_combo()` 权重归一化 + `decay_test()` 6 月滚动窗口）
- ✅ 注入 FDT（combo.json + factor_weights.json + Agent 优化建议）
- ✅ L3 Verifier 锁定 5 维度判定（`L3Verifier`）
- ✅ scheduler 集成（每周五 15:30 TimeTrigger + `l3_portfolio_loop` 任务）
- ✅ 34 个测试用例全绿（`tests/loop_engine/test_portfolio_loop.py`）

详见 §16 L3 Portfolio Loop 章节。

### 13.3 Phase 4 — 人类退场（持续）

- `program.md` 模板解析
- 监控面板 + 熔断告警
- T+1 反馈闭环
- 逐 Agent LLM 配置切换实验

---

## 14. 附录

### 14.1 参考文献

1. 0xCodila. *Loop Engineering: The Karpathy Method*. 2026.
2. Lin et al. *FactorEngine: Program-level Knowledge-Infused Factor Mining*. arXiv:2603.16365, 2026.
3. *Agentic AI Factor Investing Framework*. 2026.
4. FDT v8.9.0/v8.9.1/v8.9.2 版本历史（`07-operations.md §5.2`）

### 14.2 术语表

| 术语 | 定义 |
|------|------|
| Loop Engineering | 把人类敲回车自动化，让 Agent 自动循环运行 |
| 宏微协同演化 | LLM 改逻辑（宏观）+ 贝叶斯调参（微观），资源分离 |
| Verifier 协议 | 锁定评估机制不可修改 |
| 经验链 | 变异轨迹记录，LLM 下一轮参考避免重复踩坑 |
| 三层分离 | 逻辑分离 / 资源分离 / 时间分离（factorengine 核心约束） |

---

*本文档结束 | v8.9.2 Phase 1 L2 Evolution Loop 落地（保留占位，新章节在下方追加）*


---

## 15. L1 Meta-Loop（Phase 2 落地 v8.10.0）

> **新增日期**: 2026-07-18 | **版本**: v8.10.0 | **测试**: 51/51 全绿（`tests/loop_engine/test_meta_loop.py`）

### 15.1 概述

L1 Meta-Loop 是 Loop Engineering Phase 2 的核心实现，承担"知识补给"职责：每日 05:00 由 scheduler 触发，从外部市场感知（f10/web_collector）和辩论质量反馈（debate_round 缺口）中识别因子空白，通过 Bootstrapping Agent 链生成候选因子，经 L1 Verifier 锁定判定后注入 `factor_pool.json`，作为 L2 演化循环的种子补给。

### 15.2 五步流程

```
Step 1: 感知（Perceive）
  │  调用 f10/web_collector.fetch_quote / fetch_kline / search_news / collect_fundamental_web
  │  识别当前市场热点、产业链缺口、新闻事件
  ▼
Step 2: 质量分析（Analyze）
  │  读取 memory/debate_journal.json
  │  DebateQualityAnalyzer 识别 4 种缺口：
  │    - bullish_weak: 多头论据不足（bullish_arguments < bearish_arguments）
  │    - bearish_weak: 空头论据不足
  │    - insufficient_rounds: 辩论轮次 < MAX_DEBATE_ROUNDS
  │    - no_debate: 无辩论记录
  ▼
Step 3: Bootstrapping Agent 链
  │  基于感知+缺口生成候选因子
  │  内置 3 个模板（兜底）：
  │    - bbands_width_reversion: 布林带宽度回归
  │    - oi_price_divergence: 持仓量-价格背离
  │    - news_sentiment_proxy: 新闻情绪代理
  │  LLM 注入接口（生产模式）：generate_factor_with_llm()
  ▼
Step 4: L1 Verifier 判定
  │  4 维度锁定判定（配置不可运行时修改）：
  │    - economic_logic: 经济逻辑评分 >= 2/4 维度达标
  │    - is_executable: factor_program.py 安全沙箱编译通过
  │    - not_duplicate: factor_id 不与现有 factor_pool 重复
  │    - narrative_length: economic_logic.narrative 长度 >= 20 字符
  ▼
Step 5: 注入 factor_pool.json
  │  通过 FactorPoolManager.add_or_update() 写入
  │  状态 pending → L2 演化时 consumed 标记 injected
  │  同时通过 seed_pool.inject_from_l1() 注入 L2 种子池
```

### 15.3 契约层（contracts.py L1 扩展）

```python
# 新增 TypedDict
class SeedCandidate(TypedDict, total=False):
    candidate_id: str          # cand_<8hex>
    name: str
    code: str
    params: dict[str, Any]
    signature: FactorSignature
    economic_logic: EconomicLogic
    source: L1BootstrappingSource  # l1_bootstrapping | l1_web_discovery | l1_debate_gap | l1_manual
    parent_topic: str
    debate_round_ref: Optional[int]
    debate_gap: Optional[str]       # bullish_weak | bearish_weak | insufficient_rounds | no_debate
    web_snapshot_ref: Optional[str]
    is_executable: bool
    is_duplicate: bool
    passed_l1_verifier: bool
    failure_reasons: list[str]
    trace_id: str
    created_at: str
    injected_to_l2: bool
    injected_at: Optional[str]

class L1MetaLoopState(TypedDict, total=False):
    run_id: str
    started_at: str
    last_bootstrap_topic: str
    total_candidates_generated: int
    total_candidates_injected: int
    total_debate_gaps_detected: int
    tokens_consumed: int
    budget_limit: int
    status: MetaLoopStatus  # running | paused | completed | circuit_broken
    last_error: Optional[str]
    candidates_ref: list[str]
    last_updated: str
    version: str

class FactorPoolEntry(TypedDict, total=False):
    factor_id: str
    name: str
    source: FactorSource | L1BootstrappingSource
    parent_topic: Optional[str]
    debate_round_ref: Optional[int]
    debate_gap: Optional[str]
    economic_logic: EconomicLogic
    priority: Literal["high", "medium", "low"]
    status: Literal["pending", "injected", "decayed", "rejected"]
    trace_id: str
    created_at: str
    updated_at: str

class FactorPool(TypedDict, total=False):
    version: str
    updated_at: str
    factors: list[FactorPoolEntry]
    total_count: int
    pending_count: int

class L1VerifierConfig(TypedDict, total=False):
    min_economic_score: int          # 默认 2
    require_executable: bool         # 默认 True
    require_not_duplicate: bool      # 默认 True
    min_narrative_length: int        # 默认 20

class L1BudgetConfig(TypedDict, total=False):
    daily_token_limit: int                        # 50,000
    monthly_token_limit: int                      # 1,500,000
    max_bootstraps_per_run: int                   # 5
    max_tokens_per_candidate: int                 # 5,000
    circuit_breaker_token_ratio: float            # 2.0
    circuit_breaker_failure_rate: float           # 0.95
    circuit_breaker_consecutive_low_quality: int  # 5
```

### 15.4 L1 Verifier 锁定协议

| 维度 | 判定逻辑 | 默认阈值 |
|------|---------|---------|
| economic_logic | 4 维度（理论支撑/行为金融/市场微观结构/机构约束）达标数 >= min_economic_score | 2/4 |
| is_executable | `validate_factor_code(code)` 返回 (True, []) | True |
| not_duplicate | factor_id 不在 factor_pool.json 现有 entries 中 | True |
| narrative_length | `len(economic_logic.narrative)` >= min_narrative_length | 20 字符 |

**锁定原则**：`L1VerifierConfig` 一旦初始化不可运行时修改（与 L2 `FactorVerifier` 一致），任何修改尝试抛 RuntimeError。

### 15.5 熔断机制

| 熔断条件 | 阈值 | 行为 |
|---------|------|------|
| Token 超额 | tokens_consumed > circuit_breaker_token_ratio × daily_token_limit | status = circuit_broken |
| 失败率 | total_failed / total_candidates > circuit_breaker_failure_rate | status = circuit_broken |
| 连续低质量 | consecutive_low_quality > circuit_breaker_consecutive_low_quality | status = circuit_broken |

熔断后状态持久化到 `memory/meta_loop/state.json`，需人类审查后调用 `MetaLoop.resume()` 恢复。

### 15.6 调度集成

| 任务 | 触发器 | 触发条件 | 执行内容 |
|:-----|:-------|:---------|:---------|
| `l1_meta_loop` | TimeTrigger | 每日 05:00 | `python -m loop_engine.meta_loop --once`（1h timeout） |

**环境变量配置**：
- `FDT_L1_MAX_BOOTSTRAPS`：单次运行最大 bootstrapping 候选数（默认 5）
- `FDT_L1_MEMORY_DIR`：L1 状态存储目录（默认 `memory/meta_loop`）
- `FDT_L1_FACTOR_POOL`：factor_pool.json 路径（默认 `memory/meta_loop/factor_pool.json`）
- `FDT_L1_INJECT_DIR`：L2 种子注入目录（默认 `memory/evolution`）

### 15.7 模块拓扑

```
loop_engine/
├── meta_loop.py             # L1 Meta-Loop 主循环（~1159 行）
│   ├── L1Verifier           # 4 维度锁定判定器
│   ├── MetaStateManager     # L1 状态持久化 + backup 恢复
│   ├── FactorPoolManager    # factor_pool.json CRUD
│   ├── DebateQualityAnalyzer  # debate_round 缺口检测
│   ├── BootstrappingChain   # 模板 + LLM 双路径
│   ├── MetaLoop             # 主循环 5 步流程
│   └── main()               # CLI 入口
├── contracts.py             # 追加 L1 契约层（~160 行）
├── seed_pool.py             # 追加 inject_from_l1() / list_injected_l1()
└── __init__.py              # 追加 21 项 L1 API 导出
```

### 15.8 测试覆盖

| 测试类 | 用例数 | 覆盖范围 |
|--------|-------|---------|
| TestL1Verifier | 9 | 锁定机制、4 维度判定、配置不可变 |
| TestMetaStateManager | 10 | 初始化、持久化、backup 恢复、版本检查 |
| TestFactorPoolManager | 5 | 初始化、添加、去重、状态更新、计数 |
| TestDebateQualityAnalyzer | 4 | 无数据、bullish_weak、bearish_weak、insufficient_rounds |
| TestBootstrappingChain | 6 | 模板回退、max_candidates、去重、LLM 注入、代码验证、无效代码 |
| TestMetaLoop | 10 | 完整运行、web_collector、状态持久化、backup、factor_pool 更新、注入、熔断、结果序列化、debate_gaps |
| TestSeedPoolL1Injection | 6 | 注入、缺字段、trace_id、多候选、不污染内置种子 |
| TestMetaLoopEndToEnd | 2 | 完整管道、幂等运行 |
| **合计** | **51** | **全部通过** |

### 15.9 角色边界钉死（L1 扩展）

| 角色 | 职责 | 禁止 |
|------|------|------|
| L1 Meta-Loop | 感知市场 + 识别缺口 + Bootstrapping + L1 Verifier + 注入 factor_pool | 直接修改 multi_factor_strategy.py（必须经 L3） |
| L1 Verifier | 4 维度判定 | 接受任何 override / 修改自身配置 |
| LLM（Bootstrapping） | 候选因子代码生成 | 修改 L1 Verifier、跳过安全沙箱编译 |
| f10/web_collector | 市场数据采集 | 直接生成因子（仅提供 raw 数据） |
| DebateQualityAnalyzer | 辩论缺口识别 | 直接生成因子（仅识别 gap） |
| 人类 | 审查 factor_pool、手动恢复熔断 | 直接干预 L1 Verifier 判定 |

### 15.10 与 L2 的衔接

```
L1 Meta-Loop (05:00)              L2 Evolution Loop (20:00)
       │                                  │
       ├─ factor_pool.json (pending)      │
       │                                  │
       └─ seed_pool.inject_from_l1() ─────┤
                                          ▼
                                    L2 演化主循环
                                    （消费 pending 候选）
                                          │
                                          ▼
                                    精英因子库
                                    memory/knowledge/factors/elite/
```

- L1 产出 `SeedCandidate` → 通过 `seed_pool.inject_from_l1()` 注入 L2 种子池
- L2 演化时优先消费 L1 注入的 pending 候选（标记 `injected_to_l2=True`）
- L1 通过 `debate_round` 质量反馈识别 L2 演化失败模式（形成 L1↔L2 闭环）

---

*本文档结束 | v8.10.0 Phase 2 L1 Meta-Loop 落地*
